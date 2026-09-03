//! Circuit breaker: `CLOSED` → `OPEN` → `HALF_OPEN` fail-fast state
//! machine, driven by the monotonic clock (`std::time::Instant`).
//!
//! Ports the C version's semantics: failures trip the breaker after a
//! threshold; the breaker stays `OPEN` for a cooldown; `HALF_OPEN`
//! admits one probe call; a success resets to `CLOSED`, a failure
//! re-`OPEN`s it.
//!
//! Depends on: `std` only.

use std::sync::Mutex;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum State {
    Closed { failures: u32 },
    Open { until: Instant },
    HalfOpen,
}

/// A fail-fast breaker around a fallible operation.
#[derive(Debug)]
pub struct CircuitBreaker {
    threshold: u32,
    cooldown: Duration,
    state: Mutex<State>,
}

impl CircuitBreaker {
    /// Creates a breaker that trips after `threshold` consecutive
    /// failures and stays `OPEN` for `cooldown`.
    #[must_use]
    pub fn new(threshold: u32, cooldown: Duration) -> Self {
        Self {
            threshold: threshold.max(1),
            cooldown,
            state: Mutex::new(State::Closed { failures: 0 }),
        }
    }

    /// Whether calls should be rejected right now.
    ///
    /// `OPEN` state expires on its own: once the cooldown elapses the
    /// breaker reports `HALF_OPEN` (admit the next call as a probe).
    #[must_use]
    pub fn is_open(&self) -> bool {
        matches!(self.state(), State::Open { .. })
    }

    /// Whether the breaker allows a call through (`CLOSED` or expired
    /// `OPEN`). `check` is the primitive callers use before invoking.
    #[must_use]
    pub fn allow(&self) -> bool {
        !self.is_open()
    }

    /// Records a successful call: resets failures (`CLOSED`) or closes a
    /// `HALF_OPEN` probe.
    ///
    /// # Panics
    /// Panics only if the internal lock is poisoned (a panic while
    /// another thread held it), which is a fatal invariant violation —
    /// fail fast rather than continue with unknown breaker state.
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn record_success(&self) {
        let mut state = self.state.lock().expect("circuit breaker lock poisoned");
        *state = State::Closed { failures: 0 };
    }

    /// Records a failed call: increments toward the threshold, re-`OPEN`s
    /// from `HALF_OPEN`.
    ///
    /// # Panics
    /// Same poisoned-lock fail-fast policy as [`Self::record_success`].
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn record_failure(&self) {
        let mut state = self.state.lock().expect("circuit breaker lock poisoned");
        let next = match *state {
            State::Closed { failures } => {
                if failures + 1 >= self.threshold {
                    State::Open {
                        until: Instant::now() + self.cooldown,
                    }
                } else {
                    State::Closed {
                        failures: failures + 1,
                    }
                }
            }
            State::Open { .. } | State::HalfOpen => State::Open {
                until: Instant::now() + self.cooldown,
            },
        };
        *state = next;
    }

    /// Reads the current state, promoting an expired `OPEN` to
    /// `HALF_OPEN` in place.
    ///
    /// # Panics
    /// Same poisoned-lock fail-fast policy as [`Self::record_success`].
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    fn state(&self) -> State {
        let mut state = self.state.lock().expect("circuit breaker lock poisoned");
        if let State::Open { until } = *state
            && Instant::now() >= until
        {
            *state = State::HalfOpen;
        }
        *state
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trips_after_threshold_and_stays_open_during_cooldown() {
        let cb = CircuitBreaker::new(3, Duration::from_millis(50));
        assert!(cb.allow());
        cb.record_failure();
        cb.record_failure();
        assert!(cb.allow(), "below threshold");
        cb.record_failure();
        assert!(!cb.allow(), "tripped");
        assert!(!cb.allow(), "still open during cooldown");
    }

    #[test]
    fn opens_then_half_opens_and_closes_on_probe_success() {
        let cb = CircuitBreaker::new(1, Duration::from_millis(30));
        cb.record_failure();
        assert!(!cb.allow());
        std::thread::sleep(Duration::from_millis(40));
        assert!(cb.allow(), "cooldown expired -> half open probe");
        cb.record_success();
        assert!(cb.allow(), "probe success closes the breaker");
    }

    #[test]
    fn half_open_failure_reopens() {
        let cb = CircuitBreaker::new(2, Duration::from_millis(20));
        cb.record_failure();
        cb.record_failure();
        assert!(!cb.allow());
        std::thread::sleep(Duration::from_millis(30));
        assert!(cb.allow());
        cb.record_failure();
        assert!(!cb.allow(), "probe failure re-opens immediately");
    }

    #[test]
    fn success_resets_failure_count() {
        let cb = CircuitBreaker::new(3, Duration::from_millis(100));
        cb.record_failure();
        cb.record_failure();
        cb.record_success();
        cb.record_failure();
        assert!(cb.allow(), "success reset the counter");
        cb.record_failure();
        cb.record_failure();
        assert!(!cb.allow(), "now tripped");
    }
}
