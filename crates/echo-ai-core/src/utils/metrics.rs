//! Prometheus-text metrics registry: counters and histograms.
//!
//! the original implementation had a fault-injection-tested registry that silently
//! dropped updates when full or on OOM; Rust's `try_reserve`-driven
//! growth keeps the "never let metrics break the app" property without
//! the injection seams — updates return `bool` and callers may ignore
//! it. Registry is lock-guarded; individual counters use atomics.
//!
//! Depends on: `std` only.

use std::collections::BTreeMap;
use std::sync::Mutex;
use std::sync::atomic::{AtomicU64, Ordering};

/// Monotonic histogram bucket bounds (seconds), wide enough for LLM and
/// tool latencies.
pub const DEFAULT_BUCKETS: &[f64] = &[
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    f64::INFINITY,
];

#[derive(Debug)]
struct Counter {
    help: &'static str,
    value: AtomicU64,
}

#[derive(Debug)]
struct Histogram {
    help: &'static str,
    buckets: Vec<f64>,
    counts: Vec<AtomicU64>,
    sum_micros: AtomicU64,
}

/// Thread-safe metrics registry.
#[derive(Debug, Default)]
pub struct Metrics {
    counters: Mutex<BTreeMap<String, Counter>>,
    histograms: Mutex<BTreeMap<String, Histogram>>,
}

impl Metrics {
    /// Creates an empty registry.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Registers a counter (no-op when the name is already registered).
    ///
    /// # Panics
    /// Only if the registry lock is poisoned (a panic while another
    /// thread held it) — a fatal invariant violation; metrics must never
    /// silently misbehave, and the app should fail fast.
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn register_counter(&self, name: &str, help: &'static str) {
        let mut counters = self.counters.lock().expect("metrics counter lock poisoned");
        counters.entry(String::from(name)).or_insert(Counter {
            help,
            value: AtomicU64::new(0),
        });
    }

    /// Increments a counter by `n`. Returns `false` when the counter was
    /// never registered (updates to unknown names are dropped silently).
    #[must_use]
    pub fn inc_by(&self, name: &str, n: u64) -> bool {
        match self.counters.lock() {
            Ok(counters) => match counters.get(name) {
                Some(c) => {
                    c.value.fetch_add(n, Ordering::Relaxed);
                    true
                }
                None => false,
            },
            Err(_) => false,
        }
    }

    /// Increments a counter by one.
    #[must_use]
    pub fn inc(&self, name: &str) -> bool {
        self.inc_by(name, 1)
    }

    /// Registers a histogram with the default bucket bounds.
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::register_counter`].
    pub fn register_histogram(&self, name: &str, help: &'static str) {
        self.register_histogram_with_buckets(name, help, DEFAULT_BUCKETS);
    }

    /// Registers a histogram with explicit bucket bounds (must be sorted
    /// ascending and end with `f64::INFINITY`).
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::register_counter`].
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn register_histogram_with_buckets(&self, name: &str, help: &'static str, buckets: &[f64]) {
        let mut histograms = self
            .histograms
            .lock()
            .expect("metrics histogram lock poisoned");
        histograms
            .entry(String::from(name))
            .or_insert_with(|| Histogram {
                help,
                buckets: buckets.to_vec(),
                counts: (0..buckets.len()).map(|_| AtomicU64::new(0)).collect(),
                sum_micros: AtomicU64::new(0),
            });
    }

    /// Records an observation (seconds). Returns `false` when the
    /// histogram was never registered.
    #[must_use]
    pub fn observe(&self, name: &str, secs: f64) -> bool {
        // Clamp before the cast: any real latency is far below
        // `u64::MAX` microseconds, so the bounds check makes the cast
        // sound (negative/NaN/infinite inputs collapse to 0). The
        // `u64::MAX as f64` bound is exact at this scale (~1.8e19).
        #[allow(
            clippy::cast_precision_loss,
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss
        )]
        let micros = {
            let m = (secs * 1_000_000.0).round();
            if m.is_finite() && (0.0..=(u64::MAX as f64)).contains(&m) {
                m as u64
            } else {
                0
            }
        };
        let Ok(histograms) = self.histograms.lock() else {
            return false;
        };
        let Some(hist) = histograms.get(name) else {
            return false;
        };
        let mut bucket_idx = 0;
        for (i, bound) in hist.buckets.iter().enumerate() {
            if secs <= *bound {
                bucket_idx = i;
                break;
            }
        }
        hist.counts[bucket_idx].fetch_add(1, Ordering::Relaxed);
        hist.sum_micros.fetch_add(micros, Ordering::Relaxed);
        true
    }

    /// Renders the whole registry in Prometheus text format (each metric
    /// with its `# HELP`/`# TYPE` lines).
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::register_counter`].
    #[must_use]
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn render(&self) -> String {
        use std::fmt::Write as _;
        let mut out = String::new();
        {
            let counters = self.counters.lock().expect("metrics counter lock poisoned");
            for (name, c) in counters.iter() {
                let _ = writeln!(out, "# HELP {name} {}", c.help);
                let _ = writeln!(out, "# TYPE {name} counter");
                let _ = writeln!(out, "{name} {}", c.value.load(Ordering::Relaxed));
            }
        }
        {
            let histograms = self
                .histograms
                .lock()
                .expect("metrics histogram lock poisoned");
            for (name, h) in histograms.iter() {
                let _ = writeln!(out, "# HELP {name} {}", h.help);
                let _ = writeln!(out, "# TYPE {name} histogram");
                let mut cumulative = 0u64;
                for (i, bound) in h.buckets.iter().enumerate() {
                    cumulative += h.counts[i].load(Ordering::Relaxed);
                    let bound_str = if bound.is_infinite() {
                        String::from("+Inf")
                    } else {
                        bound.to_string()
                    };
                    let _ = writeln!(out, "{name}_bucket{{le=\"{bound_str}\"}} {cumulative}");
                }
                let _ = writeln!(out, "{name}_sum {}", h.sum_micros.load(Ordering::Relaxed));
                let _ = writeln!(out, "{name}_count {cumulative}");
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counter_renders_prometheus_text() {
        let m = Metrics::new();
        m.register_counter("http_requests_total", "HTTP requests served.");
        assert!(m.inc("http_requests_total"));
        assert!(m.inc_by("http_requests_total", 2));
        let text = m.render();
        assert!(text.contains("# HELP http_requests_total HTTP requests served."));
        assert!(text.contains("# TYPE http_requests_total counter"));
        assert!(text.contains("http_requests_total 3"));
    }

    #[test]
    fn unregistered_updates_are_silently_dropped() {
        let m = Metrics::new();
        assert!(!m.inc("never_registered"));
        assert!(!m.observe("never_registered", 1.0));
    }

    #[test]
    fn histogram_buckets_accumulate() {
        let m = Metrics::new();
        m.register_histogram("llm_latency_seconds", "LLM round-trip latency.");
        assert!(m.observe("llm_latency_seconds", 0.05));
        assert!(m.observe("llm_latency_seconds", 10.0));
        assert!(m.observe("llm_latency_seconds", 0.05));
        let text = m.render();
        assert!(
            text.contains("llm_latency_seconds_bucket{le=\"0.05\"} 2"),
            "{text}"
        );
        assert!(
            text.contains("llm_latency_seconds_bucket{le=\"10\"} 3"),
            "{text}"
        );
        assert!(
            text.contains("llm_latency_seconds_bucket{le=\"+Inf\"} 3"),
            "{text}"
        );
        assert!(text.contains("llm_latency_seconds_count 3"), "{text}");
    }
}
