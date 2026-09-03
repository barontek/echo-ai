//! JSON-lines logging to stderr, leveled and thread-safe.
//!
//! Each line is a single JSON object built before the write, so
//! concurrent loggers never interleave. The C project logged the same
//! way; the format is kept so existing log scrapers keep working.
//!
//! Depends on: `std` only.

use std::sync::atomic::{AtomicU8, Ordering};

use super::string_utils;

/// Log severity, ordered so `>=` comparisons filter.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[repr(u8)]
pub enum Level {
    /// Verbose diagnostics, hidden unless debug is on.
    Debug = 0,
    /// Normal operational events.
    Info = 1,
    /// Recoverable problems.
    Warn = 2,
    /// Failures that need attention.
    Error = 3,
}

static LEVEL: AtomicU8 = AtomicU8::new(Level::Info as u8);

/// Sets the minimum emitted level.
pub fn set_level(level: Level) {
    LEVEL.store(level as u8, Ordering::Relaxed);
}

/// Current minimum emitted level.
pub fn current_level() -> Level {
    match LEVEL.load(Ordering::Relaxed) {
        0 => Level::Debug,
        1 => Level::Info,
        2 => Level::Warn,
        _ => Level::Error,
    }
}

/// Emits a leveled JSON-lines record.
///
/// `kv` pairs are attached verbatim (values are JSON-string-escaped).
pub fn log(level: Level, msg: &str, kv: &[(&str, &str)]) {
    if level < current_level() {
        return;
    }
    let mut line = String::from(r#"{"ts":"#);
    line.push_str(&epoch_millis().to_string());
    line.push_str(r#","level":"#);
    line.push_str(match level {
        Level::Debug => r#""debug""#,
        Level::Info => r#""info""#,
        Level::Warn => r#""warn""#,
        Level::Error => r#""error""#,
    });
    line.push_str(r#","msg":"#);
    line.push_str(&string_utils::json_escape(msg));
    for (k, v) in kv {
        line.push(',');
        line.push_str(&string_utils::json_escape(k));
        line.push(':');
        line.push_str(&string_utils::json_escape(v));
    }
    line.push('}');
    eprintln!("{line}");
}

fn epoch_millis() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => i64::try_from(d.as_millis()).unwrap_or(i64::MAX),
        Err(_) => 0,
    }
}

/// Logs at [`Level::Debug`].
pub fn log_debug(msg: &str, kv: &[(&str, &str)]) {
    log(Level::Debug, msg, kv);
}

/// Logs at [`Level::Info`].
pub fn log_info(msg: &str, kv: &[(&str, &str)]) {
    log(Level::Info, msg, kv);
}

/// Logs at [`Level::Warn`].
pub fn log_warn(msg: &str, kv: &[(&str, &str)]) {
    log(Level::Warn, msg, kv);
}

/// Logs at [`Level::Error`].
pub fn log_error(msg: &str, kv: &[(&str, &str)]) {
    log(Level::Error, msg, kv);
}

/// Convenience: `log_info!("msg", "k" => "v", "k2" => v2)`.
#[macro_export]
macro_rules! log_info {
    ($msg:expr $(, $k:expr => $v:expr)*) => {
        $crate::utils::logging::log_info($msg, &[$(($k, $v)),*])
    };
}

/// Convenience: `log_error!("msg", "k" => "v")`.
#[macro_export]
macro_rules! log_error {
    ($msg:expr $(, $k:expr => $v:expr)*) => {
        $crate::utils::logging::log_error($msg, &[$(($k, $v)),*])
    };
}

/// Convenience: `log_debug!("msg", "k" => "v")`.
#[macro_export]
macro_rules! log_debug {
    ($msg:expr $(, $k:expr => $v:expr)*) => {
        $crate::utils::logging::log_debug($msg, &[$(($k, $v)),*])
    };
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn level_filtering_skips_below_minimum() {
        set_level(Level::Warn);
        assert!(!matches!(current_level(), Level::Debug));
        // Emitted at Info with a Warn minimum: no output, no panic.
        log(Level::Info, "filtered", &[]);
        set_level(Level::Debug);
        assert_eq!(current_level(), Level::Debug);
    }

    #[test]
    fn json_line_escapes_quotes_and_backslashes() {
        let line = format!(
            r#"{{"level":"info","msg":{},"path":"a\"b"}}"#,
            string_utils::json_escape("say \"hi\" \\ bye")
        );
        assert!(
            line.contains(r#""say \"hi\" \\ bye""#),
            "unexpected: {line}"
        );
    }
}
