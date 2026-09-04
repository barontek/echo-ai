//! Persistent user-memory key/value store (`user_memory` table),
//! injected into the agent's system prompt.
//!
//! the original implementation's known gap was `memory_get_dup`: a failed allocation
//! was indistinguishable from "not found". Rust's ownership model
//! removes the seam entirely — `memory_get` returns `Ok(None)` for a
//! missing key and `Err` only for real store failures, and the table is
//! owned by `rusqlite`'s `Connection`, so there is no manual allocation
//! to forget. The contract below still documents the distinction
//! explicitly (AGENTS.md "Nullability / absence").
//!
//! Depends on: `rusqlite`, crate `error`.

use rusqlite::Connection;

use crate::error::{Error, Result};

/// Sanity cap on a single fact's size (the original implementation had a similar
/// bound; facts are prompt material, not documents).
pub const MAX_FACT_SIZE: usize = 4096;

/// Returns the value for `key`. `Ok(None)` means the key is absent —
/// distinct from `Err`, which is a real store failure.
///
/// # Errors
/// `Error::Sqlite` on query failures.
pub fn memory_get(conn: &Connection, key: &str) -> Result<Option<String>> {
    let value: rusqlite::Result<String> = conn.query_row(
        "SELECT value FROM user_memory WHERE key = ?1",
        rusqlite::params![key],
        |row| row.get(0),
    );
    match value {
        Ok(v) => Ok(Some(v)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(Error::Sqlite(e.to_string())),
    }
}

/// Upserts a fact. Empty values are rejected (delete is the explicit
/// way to remove a fact).
///
/// # Errors
/// `Error::Invalid` for empty/oversized values; `Error::Sqlite` on
/// query failures.
pub fn memory_set(conn: &Connection, key: &str, value: &str) -> Result<()> {
    if key.is_empty() {
        return Err(Error::Invalid(String::from("memory key must not be empty")));
    }
    if value.is_empty() {
        return Err(Error::Invalid(String::from(
            "memory value must not be empty (use delete to remove)",
        )));
    }
    if value.len() > MAX_FACT_SIZE {
        return Err(Error::Invalid(format!(
            "memory value exceeds {MAX_FACT_SIZE} bytes"
        )));
    }
    conn.execute(
        "INSERT INTO user_memory (key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                        updated_at = CURRENT_TIMESTAMP",
        rusqlite::params![key, value],
    )
    .map_err(|e| Error::Sqlite(e.to_string()))?;
    Ok(())
}

/// Deletes a fact. Returns `true` when a row was removed.
///
/// # Errors
/// `Error::Sqlite` on query failures.
pub fn memory_delete(conn: &Connection, key: &str) -> Result<bool> {
    let n = conn
        .execute(
            "DELETE FROM user_memory WHERE key = ?1",
            rusqlite::params![key],
        )
        .map_err(|e| Error::Sqlite(e.to_string()))?;
    Ok(n > 0)
}

/// Lists all facts (`(key, value)` pairs).
///
/// # Errors
/// `Error::Sqlite` on query failures.
pub fn memory_list(conn: &Connection) -> Result<Vec<(String, String)>> {
    let mut stmt = conn
        .prepare("SELECT key, value FROM user_memory ORDER BY key")
        .map_err(|e| Error::Sqlite(e.to_string()))?;
    let rows = stmt
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
        .map_err(|e| Error::Sqlite(e.to_string()))?;
    rows.collect::<rusqlite::Result<Vec<_>>>()
        .map_err(|e| Error::Sqlite(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::db;
    use std::sync::atomic::{AtomicUsize, Ordering};

    static COUNTER: AtomicUsize = AtomicUsize::new(0);

    /// Fresh DB per test: tests run in parallel within one process, and
    /// a shared DB would leak keys between tests (order-dependent
    /// failures — the very thing AGENTS.md forbids).
    fn test_conn() -> Connection {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!("echo-mem-{}-{n}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("dir");
        db::open_db(&dir.join("t.db")).expect("open")
    }

    #[test]
    fn get_distinguishes_absent_from_error() {
        let conn = test_conn();
        assert_eq!(memory_get(&conn, "nope").expect("query"), None);
        memory_set(&conn, "k", "v").expect("set");
        assert_eq!(memory_get(&conn, "k").expect("query").as_deref(), Some("v"));
    }

    #[test]
    fn set_overwrites_and_delete_removes() {
        let conn = test_conn();
        memory_set(&conn, "k", "v1").expect("set");
        memory_set(&conn, "k", "v2").expect("overwrite");
        assert_eq!(
            memory_get(&conn, "k").expect("query").as_deref(),
            Some("v2")
        );
        assert!(memory_delete(&conn, "k").expect("delete"));
        assert!(!memory_delete(&conn, "k").expect("delete again"));
    }

    #[test]
    fn empty_and_oversized_values_rejected() {
        let conn = test_conn();
        assert!(memory_set(&conn, "k", "").is_err());
        let big = "x".repeat(MAX_FACT_SIZE + 1);
        assert!(memory_set(&conn, "k", &big).is_err());
        assert!(memory_set(&conn, "", "v").is_err());
    }

    #[test]
    fn list_returns_sorted_facts() {
        let conn = test_conn();
        memory_set(&conn, "b", "2").expect("set");
        memory_set(&conn, "a", "1").expect("set");
        let facts = memory_list(&conn).expect("list");
        assert_eq!(
            facts,
            vec![
                (String::from("a"), String::from("1")),
                (String::from("b"), String::from("2")),
            ]
        );
    }
}
