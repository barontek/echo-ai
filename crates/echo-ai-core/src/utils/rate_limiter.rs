//! In-memory rate limiter: per-IP fixed-window request throttling plus a
//! rolling window on unlock attempts.
//!
//! The C version persisted buckets to SQLite (`rate_limits.db`); this
//! port keeps the same policy surface in memory — a single-process
//! server loses nothing, and restart resets windows, which is the
//! fail-open behavior anyway. Stale buckets are swept on access, so the
//! map stays bounded.
//!
//! Depends on: `std` only.

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

const DEFAULT_WINDOW: Duration = Duration::from_secs(60);
const DEFAULT_MAX_REQUESTS: u32 = 120;
const UNLOCK_WINDOW: Duration = Duration::from_secs(60);
const UNLOCK_MAX_ATTEMPTS: usize = 5;

#[derive(Debug)]
struct Bucket {
    window_start: Instant,
    count: u32,
}

/// Per-IP throttling with a fixed window.
#[derive(Debug)]
pub struct RateLimiter {
    window: Duration,
    max_requests: u32,
    buckets: Mutex<HashMap<String, Bucket>>,
    unlock_attempts: Mutex<HashMap<String, Vec<Instant>>>,
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::new(DEFAULT_WINDOW, DEFAULT_MAX_REQUESTS)
    }
}

impl RateLimiter {
    /// Creates a limiter with a fixed `window` and `max_requests` per IP.
    #[must_use]
    pub fn new(window: Duration, max_requests: u32) -> Self {
        Self {
            window,
            max_requests: max_requests.max(1),
            buckets: Mutex::new(HashMap::new()),
            unlock_attempts: Mutex::new(HashMap::new()),
        }
    }

    /// Whether `ip` may proceed. A fresh window always allows the first
    /// request; returning `true` consumes one slot.
    ///
    /// # Panics
    /// Only if an internal lock is poisoned (a panic while another
    /// thread held it) — fail fast, the limiter must never be silently
    /// bypassed.
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn check(&self, ip: &str) -> bool {
        let mut buckets = self
            .buckets
            .lock()
            .expect("rate limiter bucket lock poisoned");
        let now = Instant::now();
        let entry = buckets.entry(String::from(ip)).or_insert(Bucket {
            window_start: now,
            count: 0,
        });
        if now.duration_since(entry.window_start) >= self.window {
            entry.window_start = now;
            entry.count = 0;
        }
        if entry.count >= self.max_requests {
            return false;
        }
        entry.count += 1;
        true
    }

    /// Whether an unlock attempt from `ip` is allowed within the rolling
    /// 60s window (max 5 attempts). Prunes stale attempts on access.
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::check`].
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn allow_unlock_attempt(&self, ip: &str) -> bool {
        let mut attempts = self
            .unlock_attempts
            .lock()
            .expect("rate limiter unlock lock poisoned");
        let now = Instant::now();
        let list = attempts.entry(String::from(ip)).or_default();
        list.retain(|t| now.duration_since(*t) < UNLOCK_WINDOW);
        if list.len() >= UNLOCK_MAX_ATTEMPTS {
            return false;
        }
        list.push(now);
        true
    }

    /// Number of live buckets (test/diagnostic use).
    ///
    /// # Panics
    /// Same poisoned-lock policy as [`Self::check`].
    #[must_use]
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn bucket_count(&self) -> usize {
        self.buckets
            .lock()
            .expect("rate limiter bucket lock poisoned")
            .len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn window_resets_allowance() {
        let limiter = RateLimiter::new(Duration::from_millis(50), 2);
        assert!(limiter.check("1.2.3.4"));
        assert!(limiter.check("1.2.3.4"));
        assert!(!limiter.check("1.2.3.4"), "limit reached");
        std::thread::sleep(Duration::from_millis(60));
        assert!(limiter.check("1.2.3.4"), "new window");
        assert!(limiter.check("1.2.3.4"));
        assert!(!limiter.check("1.2.3.4"));
    }

    #[test]
    fn ips_are_isolated() {
        let limiter = RateLimiter::new(Duration::from_secs(60), 1);
        assert!(limiter.check("a"));
        assert!(!limiter.check("a"));
        assert!(limiter.check("b"));
    }

    #[test]
    fn unlock_throttle_rolls_over_sixty_seconds() {
        let limiter = RateLimiter::default();
        for _ in 0..5 {
            assert!(limiter.allow_unlock_attempt("9.9.9.9"));
        }
        assert!(!limiter.allow_unlock_attempt("9.9.9.9"), "throttled");
        assert!(
            limiter.allow_unlock_attempt("1.1.1.1"),
            "other ip unaffected"
        );
    }
}
