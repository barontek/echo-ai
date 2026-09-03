//! SQLite schema and data-directory plumbing for the session store.
//!
//! The schema is byte-compatible with the C project's `session_db.c`:
//! the same tables, columns, and durability pragmas, so a database
//! created by either version opens in the other. The data dir is
//! created mode 0700 (it holds key material).
//!
//! Depends on: `rusqlite`, crate `error`, crate `utils::logging`.

use std::path::Path;

use rusqlite::Connection;

use crate::error::{Error, Result};
use crate::log_error;

/// Creates `dir` with mode 0700, component by component (umask
/// independent — key material lives here).
///
/// # Errors
/// `Error::Io` when the directory cannot be created.
pub fn ensure_data_dir(dir: &Path) -> Result<()> {
    if dir.exists() {
        return Ok(());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        let mut builder = std::fs::DirBuilder::new();
        builder.recursive(true).mode(0o700);
        builder.create(dir).map_err(|e| Error::Io {
            path: dir.to_path_buf(),
            source: e,
        })
    }
    #[cfg(not(unix))]
    {
        std::fs::create_dir_all(dir).map_err(|e| Error::Io {
            path: dir.to_path_buf(),
            source: e,
        })
    }
}

/// Opens the session database, creating tables and applying the
/// durability pragmas (`journal_mode=DELETE`, `synchronous=FULL` — the
/// crash-durability contract the password migration relies on).
///
/// # Errors
/// `Error::Sqlite` on open, schema, or pragma failures.
pub fn open_db(path: &Path) -> Result<Connection> {
    let conn = Connection::open(path).map_err(|e| Error::Sqlite(e.to_string()))?;
    conn.pragma_update(None, "journal_mode", "DELETE")
        .map_err(|e| Error::Sqlite(format!("journal_mode: {e}")))?;
    conn.pragma_update(None, "synchronous", "FULL")
        .map_err(|e| Error::Sqlite(format!("synchronous: {e}")))?;

    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS agent_sessions (
             id TEXT PRIMARY KEY,
             title_encrypted BLOB,
             title_generation_attempted INTEGER DEFAULT 0,
             created_at TEXT,
             messages_encrypted BLOB,
             metadata_encrypted BLOB,
             events_encrypted BLOB
         );
         CREATE TABLE IF NOT EXISTS provider_oauth (
             provider TEXT PRIMARY KEY,
             data_encrypted BLOB NOT NULL
         );
         CREATE TABLE IF NOT EXISTS user_memory (
             key TEXT PRIMARY KEY,
             value TEXT NOT NULL,
             updated_at TEXT DEFAULT CURRENT_TIMESTAMP
         );",
    )
    .map_err(|e| Error::Sqlite(format!("schema: {e}")))?;

    Ok(conn)
}

/// Runs `PRAGMA` diagnostics at open (best-effort; failures are logged,
/// not fatal — the pragmas themselves are enforced on `open_db`).
pub fn log_durability_status(conn: &Connection) {
    let journal: rusqlite::Result<String> =
        conn.pragma_query_value(None, "journal_mode", |row| row.get(0));
    match journal {
        Ok(mode) => log_error!("journal_mode", "mode" => &mode),
        Err(e) => log_error!("journal_mode query failed", "err" => &e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schema_creates_all_tables() {
        let dir = std::env::temp_dir().join(format!("echo-db-{}", std::process::id()));
        ensure_data_dir(&dir).expect("data dir");
        let conn = open_db(&dir.join("echo-ai.db")).expect("open");
        let tables: Vec<String> = conn
            .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            .expect("prepare")
            .query_map([], |row| row.get(0))
            .expect("query")
            .collect::<rusqlite::Result<_>>()
            .expect("collect");
        assert!(
            tables.contains(&String::from("agent_sessions")),
            "missing agent_sessions: {tables:?}"
        );
        assert!(
            tables.contains(&String::from("provider_oauth")),
            "missing provider_oauth: {tables:?}"
        );
        assert!(
            tables.contains(&String::from("user_memory")),
            "missing user_memory: {tables:?}"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn data_dir_is_created_0700() {
        let dir = std::env::temp_dir().join(format!("echo-db-mode-{}", std::process::id()));
        ensure_data_dir(&dir).expect("data dir");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&dir).expect("meta").permissions().mode() & 0o777;
            assert_eq!(mode, 0o700, "data dir must be 0700");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
