//! Project-wide error conventions (AGENTS.md "Error handling").
//!
//! Each module defines its own `thiserror`-derived enum for domain
//! failures; this crate-level error is the common currency at module
//! boundaries, and `anyhow` is used at application boundaries (the bin
//! crate, server routes) where context stacking matters more than exact
//! variants. Every failure path carries the operation context in the
//! variant message — no bare downstream errors.

use std::path::PathBuf;

/// Common error for core-crate operations.
#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// Configuration could not be loaded or is invalid.
    #[error("config error: {0}")]
    Config(String),

    /// An operation was rejected by safety policy.
    #[error("safety: {0}")]
    Safety(String),

    /// Session store failure, wrapping the underlying cause.
    #[error("session store: {0}")]
    Session(String),

    /// A cryptographic operation failed (bad key, bad token, KDF failure).
    #[error("crypto: {0}")]
    Crypto(String),

    /// Path or file access failure.
    #[error("io on {path}: {source}")]
    Io {
        /// The path the operation was acting on.
        path: PathBuf,
        /// The underlying I/O error.
        #[source]
        source: std::io::Error,
    },

    /// SQLite failure with the SQL that failed, when known.
    #[error("sqlite: {0}")]
    Sqlite(String),

    /// A value failed validation (out of range, malformed, duplicate).
    #[error("invalid value: {0}")]
    Invalid(String),

    /// Unsupported or unknown variant (provider, tool, mode, ...).
    #[error("unknown {what}: {value}")]
    Unknown {
        /// What kind of thing was looked up.
        what: String,
        /// The value that was not found.
        value: String,
    },
}

/// Convenience alias used across the core crate (defaults to the
/// crate-wide error; modules may override the error type).
pub type Result<T, E = Error> = std::result::Result<T, E>;

/// Builds an [`Error::Io`] from an operation on `path`.
pub fn io_error(path: impl Into<PathBuf>, source: std::io::Error) -> Error {
    Error::Io {
        path: path.into(),
        source,
    }
}
