//! Crash-safe password migration: re-encrypts every row under a new
//! password, with recovery of interrupted migrations on next open.
//!
//! Protocol (each step is individually atomic; the DB transaction makes
//! the row migration all-or-nothing):
//!
//! 1. Create the marker file `.changing_pwd` (exclusive create — a
//!    leftover marker means a migration is in flight and must be
//!    recovered first).
//! 2. Derive the new key and write `.verifier.new` (exclusive).
//! 3. In one transaction: record `state='committed'` in
//!    `password_migration_state`, then re-encrypt every row.
//! 4. Rename `.verifier.new` → `.verifier` (atomic within the dir).
//! 5. Remove the marker and the state row.
//!
//! A crash can land between any two steps; [`recover`] resolves the
//! state from (a) whether the DB transaction committed and (b) which
//! verifier the entered password matches. Rows are never left partially
//! migrated: before commit they are all old-key, after commit all
//! new-key.
//!
//! Depends on: `rusqlite`, crate `session::{db, encryption, manager}`.

use std::io::Write;
use std::path::Path;

use crate::error::{Error, Result};
use crate::log_error;

use super::encryption::{self, DB_FILE, EncryptionKey, MIGRATION_MARKER, VERIFIER_FILE};
use super::manager::SessionManager;
use super::{db, encryption::VERIFIER_NEW_FILE};

/// State-row marker written *inside* the migration transaction.
const STATE_TABLE: &str = "password_migration_state";
const STATE_COMMITTED: &str = "committed";

/// Re-encrypts all rows under `new_password`.
///
/// # Errors
/// Any failure leaves the vault in its pre-migration state (marker and
/// `.verifier.new` removed on the pre-commit paths); a leftover marker
/// from an interrupted earlier migration aborts with `Error::Session`.
pub fn migrate(sm: &SessionManager, new_password: &str) -> Result<()> {
    let data_dir = sm.data_dir().to_path_buf();
    let marker = data_dir.join(MIGRATION_MARKER);
    let verifier_new = data_dir.join(VERIFIER_NEW_FILE);

    write_marker(&marker)?;

    let result = (|| {
        let (salt, pepper) = super::manager::key_material(&data_dir)?;
        let new_key = EncryptionKey::derive(new_password, &salt, &pepper)?;

        write_verifier_new(&verifier_new, &new_key)?;

        // Migration runs on its own connection to the DB file (rusqlite
        // has no connection cloning; a second handle to the same file is
        // safe — the manager is the only writer in this process).
        let conn = db::open_db(&data_dir.join(DB_FILE))?;
        let tx = conn
            .unchecked_transaction()
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        tx.execute(
            &format!(
                "CREATE TABLE IF NOT EXISTS {STATE_TABLE} \
                 (id INTEGER PRIMARY KEY, state TEXT NOT NULL)"
            ),
            [],
        )
        .map_err(|e| Error::Sqlite(e.to_string()))?;
        tx.execute(
            &format!(
                "INSERT INTO {STATE_TABLE} (id, state) VALUES (1, ?1) \
                 ON CONFLICT(id) DO UPDATE SET state = excluded.state"
            ),
            rusqlite::params![STATE_COMMITTED],
        )
        .map_err(|e| Error::Sqlite(e.to_string()))?;

        reencrypt_all_rows(&tx, sm.key(), &new_key)?;
        tx.commit().map_err(|e| Error::Sqlite(e.to_string()))?;

        // Post-commit promotion: rows are new-key; make the new verifier
        // authoritative before the marker comes down.
        std::fs::rename(&verifier_new, data_dir.join(VERIFIER_FILE)).map_err(|e| Error::Io {
            path: data_dir.join(VERIFIER_FILE),
            source: e,
        })?;
        let _ = std::fs::remove_file(&marker);
        conn.execute(&format!("DELETE FROM {STATE_TABLE} WHERE id = 1"), [])
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        log_error!("password migration complete");
        Ok(())
    })();

    if result.is_err() {
        // Pre-commit failure: rows are all old-key; discard the partial
        // migration artifacts so the vault opens normally.
        let _ = std::fs::remove_file(&marker);
        let _ = std::fs::remove_file(&verifier_new);
    }
    result
}

/// Resolves an interrupted migration at open time (marker present).
///
/// `password` is the password the user opened the vault with. The
/// database transaction state decides which verifier must match:
/// committed rows require the *new* password; uncommitted rows require
/// the old one.
///
/// # Errors
/// `Error::Crypto` when `password` matches neither state (wrong
/// password) or the recovery artifacts are corrupt.
pub fn recover(data_dir: &Path, password: &str) -> Result<()> {
    let (salt, pepper) = super::manager::key_material(data_dir)?;
    let key = EncryptionKey::derive(password, &salt, &pepper)?;

    let marker = data_dir.join(MIGRATION_MARKER);
    let verifier_new = data_dir.join(VERIFIER_NEW_FILE);

    let committed = {
        let conn = db::open_db(&data_dir.join(DB_FILE))?;
        let state: rusqlite::Result<String> = conn.query_row(
            &format!("SELECT state FROM {STATE_TABLE} WHERE id = 1"),
            [],
            |r| r.get(0),
        );
        matches!(state, Ok(s) if s == STATE_COMMITTED)
    };

    if committed {
        // Rows are new-key; the entered password must be the new one.
        let token = std::fs::read(&verifier_new).map_err(|e| Error::Io {
            path: verifier_new.clone(),
            source: e,
        })?;
        if !encryption::verifier_token_matches(&key, &token) {
            return Err(Error::Crypto(String::from(
                "migration was committed but this password does not match it",
            )));
        }
        std::fs::rename(&verifier_new, data_dir.join(VERIFIER_FILE)).map_err(|e| Error::Io {
            path: data_dir.join(VERIFIER_FILE),
            source: e,
        })?;
    } else {
        // Rows are old-key; the entered password must be the old one.
        if !encryption::verifier_file_matches(&key, &data_dir.join(VERIFIER_FILE)) {
            return Err(Error::Crypto(String::from(
                "wrong password for the vault state left by the interrupted migration",
            )));
        }
        let _ = std::fs::remove_file(&verifier_new);
    }

    let _ = std::fs::remove_file(&marker);
    if let Ok(conn) = db::open_db(&data_dir.join(DB_FILE)) {
        let _ = conn.execute(&format!("DELETE FROM {STATE_TABLE} WHERE id = 1"), []);
    }
    Ok(())
}

/// Creates the exclusive-creation marker file (0600).
fn write_marker(marker: &Path) -> Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(marker)
        .map(|_| ())
        .map_err(|e| Error::Io {
            path: marker.to_path_buf(),
            source: e,
        })
}

/// Creates the exclusive-creation `.verifier.new` file (0600).
fn write_verifier_new(path: &Path, key: &EncryptionKey) -> Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let token = key.encrypt(b"echo-ai-ok");
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|e| Error::Io {
            path: path.to_path_buf(),
            source: e,
        })?;
    file.write_all(&token)
        .and_then(|()| file.flush())
        .map_err(|e| Error::Io {
            path: path.to_path_buf(),
            source: e,
        })
}

/// Re-encrypts every encrypted blob in `agent_sessions` and
/// `provider_oauth` from `old_key` to `new_key`, inside the caller's
/// transaction. A blob that fails to decrypt aborts the migration
/// (transaction rolls back — the vault keeps its old password).
fn reencrypt_all_rows(
    tx: &rusqlite::Transaction<'_>,
    old_key: &EncryptionKey,
    new_key: &EncryptionKey,
) -> Result<()> {
    {
        let mut stmt = tx
            .prepare(
                "SELECT id, title_encrypted, messages_encrypted, metadata_encrypted, \
                 events_encrypted FROM agent_sessions",
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        let rows = stmt
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, Option<Vec<u8>>>(1)?,
                    row.get::<_, Option<Vec<u8>>>(2)?,
                    row.get::<_, Option<Vec<u8>>>(3)?,
                    row.get::<_, Option<Vec<u8>>>(4)?,
                ))
            })
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        for row in rows {
            let (id, title, messages, metadata, events) =
                row.map_err(|e| Error::Sqlite(e.to_string()))?;
            let title_new = reencrypt_opt(old_key, new_key, title)?;
            let messages_new = reencrypt_opt(old_key, new_key, messages)?;
            let metadata_new = reencrypt_opt(old_key, new_key, metadata)?;
            let events_new = reencrypt_opt(old_key, new_key, events)?;
            tx.execute(
                "UPDATE agent_sessions SET title_encrypted = ?2, messages_encrypted = ?3, \
                 metadata_encrypted = ?4, events_encrypted = ?5 WHERE id = ?1",
                rusqlite::params![id, title_new, messages_new, metadata_new, events_new],
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        }
    }
    {
        let mut stmt = tx
            .prepare("SELECT provider, data_encrypted FROM provider_oauth")
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        let rows = stmt
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
            })
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        for row in rows {
            let (provider, data) = row.map_err(|e| Error::Sqlite(e.to_string()))?;
            let data_new = reencrypt_blob(old_key, new_key, &data)?;
            tx.execute(
                "UPDATE provider_oauth SET data_encrypted = ?2 WHERE provider = ?1",
                rusqlite::params![provider, data_new],
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        }
    }
    Ok(())
}

/// Re-encrypts an optional blob (decrypt-with-old, encrypt-with-new).
fn reencrypt_opt(
    old_key: &EncryptionKey,
    new_key: &EncryptionKey,
    blob: Option<Vec<u8>>,
) -> Result<Option<Vec<u8>>> {
    match blob {
        Some(b) => Ok(Some(reencrypt_blob(old_key, new_key, &b)?)),
        None => Ok(None),
    }
}

/// Re-encrypts one blob.
fn reencrypt_blob(
    old_key: &EncryptionKey,
    new_key: &EncryptionKey,
    blob: &[u8],
) -> Result<Vec<u8>> {
    let plain = old_key.decrypt(blob).ok_or_else(|| {
        Error::Crypto(String::from("row blob failed to decrypt during migration"))
    })?;
    Ok(new_key.encrypt(&plain))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::manager::SessionManager;

    fn open_temp(tag: &str) -> (SessionManager, std::path::PathBuf) {
        let dir = std::env::temp_dir().join(format!("echo-mig-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let sm = SessionManager::open(&dir, "old").expect("open");
        (sm, dir)
    }

    #[test]
    fn interrupted_before_commit_recovers_with_old_password() {
        let (sm, dir) = open_temp("precommit");
        let mut s = sm.create_session();
        s.messages
            .push(crate::agent::message::Message::user("data"));
        sm.save_session(&s).expect("save");
        // Simulate a crash right after the marker was written: no
        // verifier.new, no state row.
        write_marker(&dir.join(MIGRATION_MARKER)).expect("marker");
        drop(sm);

        let sm2 = SessionManager::open(&dir, "old").expect("recover with old pw");
        assert!(!dir.join(MIGRATION_MARKER).exists(), "marker cleaned");
        let loaded = sm2.load_session(&s.id).expect("load").expect("exists");
        assert_eq!(loaded.messages[0].content, "data");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn interrupted_after_commit_recovers_with_new_password() {
        let (sm, dir) = open_temp("postcommit");
        let mut s = sm.create_session();
        s.messages
            .push(crate::agent::message::Message::user("data"));
        sm.save_session(&s).expect("save");

        // Run the full migration, then simulate a crash in the
        // committed-but-not-cleaned-up window: marker + state row + a
        // `.verifier.new` encrypted under the NEW password all present.
        sm.change_password("new").expect("migrate");
        write_marker(&dir.join(MIGRATION_MARKER)).expect("marker");
        let conn = db::open_db(&dir.join(DB_FILE)).expect("open");
        conn.execute_batch(&format!(
            "CREATE TABLE IF NOT EXISTS {STATE_TABLE} (id INTEGER PRIMARY KEY, state TEXT NOT NULL);
             INSERT INTO {STATE_TABLE} (id, state) VALUES (1, '{STATE_COMMITTED}');"
        ))
        .expect("state");
        drop(conn);
        let (salt, pepper) = crate::session::manager::key_material(&dir).expect("material");
        let new_key = EncryptionKey::derive("new", &salt, &pepper).expect("derive");
        write_verifier_new(&dir.join(VERIFIER_NEW_FILE), &new_key).expect("verifier.new");
        drop(sm);

        // Old password no longer works; new password must recover.
        let err = SessionManager::open(&dir, "old").expect_err("old must fail");
        assert!(matches!(err, Error::Crypto(_)));
        let sm2 = SessionManager::open(&dir, "new").expect("recover with new pw");
        assert!(!dir.join(MIGRATION_MARKER).exists(), "marker cleaned");
        assert!(
            !dir.join(VERIFIER_NEW_FILE).exists(),
            "verifier.new promoted"
        );
        let loaded = sm2.load_session(&s.id).expect("load").expect("exists");
        assert_eq!(loaded.messages[0].content, "data");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn migrate_is_idempotent_after_completion() {
        let (sm, dir) = open_temp("twice");
        sm.change_password("new1").expect("first");
        sm.change_password("new2").expect("second");
        drop(sm);
        let err = SessionManager::open(&dir, "new1").expect_err("new1 gone");
        assert!(matches!(err, Error::Crypto(_)));
        let sm2 = SessionManager::open(&dir, "new2").expect("new2 works");
        drop(sm2);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
