//! Session store facade: CRUD over the encrypted SQLite database.
//!
//! All DB access goes through one `Mutex<Connection>` (the C version's
//! mutex-protected facade, translated to Rust ownership). Every fallible
//! step is checked; writes are transactional, so a failed save never
//! leaves a partially-updated row.
//!
//! # Thread-safety
//! `SessionManager` is `Send + Sync` (mutex-guarded connection, `Copy`
//! key) and safe to share across tasks. No claim is made about
//! cross-process access — two processes opening the same data dir are
//! unsupported, same as the C version.
//!
//! Depends on: `rusqlite`, crate `session::{db,encryption,migration}`.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use rusqlite::Connection;

use crate::error::{Error, Result};
use crate::log_error;

use super::encryption::{
    self, DB_FILE, EncryptionKey, MIGRATION_MARKER, data_file, load_key_material,
};
use super::migration;
use super::{Session, db};

/// A row in the session list (titles decrypted; decryption failures
/// surface as `None`, matching the C version's lenient listing).
#[derive(Debug, Clone)]
pub struct SessionSummary {
    /// Session id.
    pub id: String,
    /// Decrypted title, when the row carries one.
    pub title: Option<String>,
    /// Whether a title-generation attempt was made.
    pub title_generation_attempted: bool,
    /// Creation timestamp text as stored.
    pub created_at: String,
}

/// The encrypted session store.
#[derive(Debug)]
pub struct SessionManager {
    data_dir: PathBuf,
    conn: Mutex<Connection>,
    key: EncryptionKey,
}

impl SessionManager {
    /// Opens (or, on first run, initializes) the vault at `data_dir`.
    ///
    /// First run: creates salt/pepper/verifier and the DB. Subsequent
    /// runs: recovers any interrupted password migration, then verifies
    /// the password via the verifier file.
    ///
    /// # Errors
    /// `Error::Crypto` on wrong password or corrupt key material;
    /// `Error::Sqlite`/`Error::Io` on storage failures.
    pub fn open(data_dir: &Path, password: &str) -> Result<Self> {
        db::ensure_data_dir(data_dir)?;

        if !encryption::vault_initialized(data_dir) {
            let key = encryption::initialize_vault(data_dir, password)?;
            let conn = db::open_db(&data_file(data_dir, DB_FILE))?;
            return Ok(Self {
                data_dir: data_dir.to_path_buf(),
                conn: Mutex::new(conn),
                key,
            });
        }

        // Existing vault: finish any interrupted password migration
        // before the verifier check (the migration may have promoted a
        // new verifier that `password` must now match).
        if data_dir.join(MIGRATION_MARKER).exists() {
            log_error!("password migration marker found, recovering");
            migration::recover(data_dir, password)?;
        }

        let key = encryption::load_key(data_dir, password)?;
        let conn = db::open_db(&data_file(data_dir, DB_FILE))?;
        Ok(Self {
            data_dir: data_dir.to_path_buf(),
            conn: Mutex::new(conn),
            key,
        })
    }

    /// The vault directory.
    pub fn data_dir(&self) -> &Path {
        &self.data_dir
    }

    /// The guarded connection. A poisoned lock means a panic happened
    /// mid-operation; the connection state is unknowable and continuing
    /// could corrupt the vault — fail fast rather than recover.
    #[allow(clippy::expect_used)] // poison = invariant violation, fail fast
    fn conn(&self) -> std::sync::MutexGuard<'_, Connection> {
        self.conn.lock().expect("session conn lock poisoned")
    }

    /// Creates an empty, unsaved session with a fresh random id.
    pub fn create_session(&self) -> Session {
        Session::new(random_hex_id())
    }

    /// Persists a session (upsert). All encrypted parts are serialized
    /// before any SQL runs; the upsert is a single transaction, so a
    /// failure cannot leave a partially-written row.
    ///
    /// # Errors
    /// `Error::Session` on serialization or DB failures.
    pub fn save_session(&self, session: &Session) -> Result<()> {
        let messages = session
            .messages_json()
            .map_err(|e| Error::Session(format!("serialize messages: {e}")))?;
        let metadata = serde_json::to_string(&session.metadata)
            .map_err(|e| Error::Session(format!("serialize metadata: {e}")))?;
        let events = serde_json::to_string(&session.events)
            .map_err(|e| Error::Session(format!("serialize events: {e}")))?;

        let title_enc = session
            .title
            .as_deref()
            .map(|t| self.key.encrypt(t.as_bytes()));
        let messages_enc = self.key.encrypt(messages.as_bytes());
        let metadata_enc = self.key.encrypt(metadata.as_bytes());
        let events_enc = self.key.encrypt(events.as_bytes());

        let conn = self.conn();
        let tx = conn
            .unchecked_transaction()
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        tx.execute(
            "INSERT INTO agent_sessions
                 (id, title_encrypted, title_generation_attempted, created_at,
                  messages_encrypted, metadata_encrypted, events_encrypted)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
             ON CONFLICT(id) DO UPDATE SET
                 title_encrypted = excluded.title_encrypted,
                 title_generation_attempted = excluded.title_generation_attempted,
                 created_at = excluded.created_at,
                 messages_encrypted = excluded.messages_encrypted,
                 metadata_encrypted = excluded.metadata_encrypted,
                 events_encrypted = excluded.events_encrypted",
            rusqlite::params![
                session.id,
                title_enc,
                i64::from(session.title_generation_attempted),
                session.created_at,
                messages_enc,
                metadata_enc,
                events_enc,
            ],
        )
        .map_err(|e| Error::Sqlite(e.to_string()))?;
        tx.commit().map_err(|e| Error::Sqlite(e.to_string()))
    }

    /// Loads a session by id.
    ///
    /// # Errors
    /// `Error::Session` on decrypt or deserialize failures (a row that
    /// does not decrypt cleanly is reported, not silently emptied).
    pub fn load_session(&self, id: &str) -> Result<Option<Session>> {
        let conn = self.conn();
        let mut stmt = conn
            .prepare(
                "SELECT title_encrypted, title_generation_attempted, created_at,
                        messages_encrypted, metadata_encrypted, events_encrypted
                 FROM agent_sessions WHERE id = ?1",
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        let row = stmt
            .query_row(rusqlite::params![id], |row| {
                Ok((
                    row.get::<_, Option<Vec<u8>>>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, Option<Vec<u8>>>(3)?,
                    row.get::<_, Option<Vec<u8>>>(4)?,
                    row.get::<_, Option<Vec<u8>>>(5)?,
                ))
            })
            .map_err(|e| match e {
                rusqlite::Error::QueryReturnedNoRows => rusqlite::Error::QueryReturnedNoRows,
                other => other,
            });

        let (title_enc, title_gen, created_at, messages_enc, metadata_enc, events_enc) = match row {
            Ok(v) => v,
            Err(rusqlite::Error::QueryReturnedNoRows) => return Ok(None),
            Err(e) => return Err(Error::Sqlite(e.to_string())),
        };

        let title = match title_enc {
            Some(bytes) => Some(decrypt_str(&self.key, &bytes, "title")?),
            None => None,
        };
        let messages = decrypt_str(
            &self.key,
            &messages_enc
                .ok_or_else(|| Error::Session(format!("session {id} has no messages blob")))?,
            "messages",
        )?;
        let metadata = decrypt_str(
            &self.key,
            &metadata_enc
                .ok_or_else(|| Error::Session(format!("session {id} has no metadata blob")))?,
            "metadata",
        )?;
        let events = decrypt_str(
            &self.key,
            &events_enc
                .ok_or_else(|| Error::Session(format!("session {id} has no events blob")))?,
            "events",
        )?;

        Ok(Some(Session {
            id: String::from(id),
            title,
            title_generation_attempted: title_gen != 0,
            created_at,
            messages: Session::messages_from_json(&messages)
                .map_err(|e| Error::Session(format!("deserialize messages: {e}")))?,
            metadata: serde_json::from_str(&metadata)
                .map_err(|e| Error::Session(format!("deserialize metadata: {e}")))?,
            events: serde_json::from_str(&events)
                .map_err(|e| Error::Session(format!("deserialize events: {e}")))?,
        }))
    }

    /// Lists all sessions, newest first, with decrypted titles.
    ///
    /// # Errors
    /// `Error::Sqlite` on query failures. Per-row title decryption
    /// failures are logged and yield `title: None` (lenient, as in C).
    pub fn list_sessions(&self) -> Result<Vec<SessionSummary>> {
        let conn = self.conn();
        let mut stmt = conn
            .prepare(
                "SELECT id, title_encrypted, title_generation_attempted, created_at
                 FROM agent_sessions ORDER BY created_at DESC",
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        let rows = stmt
            .query_map([], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, Option<Vec<u8>>>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, String>(3)?,
                ))
            })
            .map_err(|e| Error::Sqlite(e.to_string()))?;

        let mut out = Vec::new();
        for row in rows {
            let (id, title_enc, title_gen, created_at) =
                row.map_err(|e| Error::Sqlite(e.to_string()))?;
            let title = match title_enc {
                Some(bytes) => match decrypt_str(&self.key, &bytes, "title") {
                    Ok(t) => Some(t),
                    Err(e) => {
                        log_error!("list: title decrypt failed", "id" => &id, "err" => &e.to_string());
                        None
                    }
                },
                None => None,
            };
            out.push(SessionSummary {
                id,
                title,
                title_generation_attempted: title_gen != 0,
                created_at,
            });
        }
        Ok(out)
    }

    /// Deletes a session by id. Returns `true` when a row was removed.
    ///
    /// # Errors
    /// `Error::Sqlite` on query failures.
    pub fn delete_session(&self, id: &str) -> Result<bool> {
        let conn = self.conn();
        let n = conn
            .execute(
                "DELETE FROM agent_sessions WHERE id = ?1",
                rusqlite::params![id],
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        Ok(n > 0)
    }

    /// Deletes sessions older than `older_than_secs`, returning how many
    /// were removed.
    ///
    /// # Errors
    /// `Error::Sqlite` on query failures.
    pub fn purge_older_than(&self, older_than_secs: i64) -> Result<usize> {
        let cutoff = now_epoch_secs() - older_than_secs;
        let conn = self.conn();
        let n = conn
            .execute(
                "DELETE FROM agent_sessions WHERE CAST(created_at AS INTEGER) < ?1",
                rusqlite::params![cutoff],
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        Ok(n)
    }

    /// Renames a session. Returns `false` when the session does not
    /// exist.
    ///
    /// # Errors
    /// `Error::Session`/`Error::Sqlite` on failures.
    pub fn rename_session(&self, id: &str, title: &str) -> Result<bool> {
        let Some(mut session) = self.load_session(id)? else {
            return Ok(false);
        };
        session.title = Some(String::from(title));
        self.save_session(&session)?;
        Ok(true)
    }

    /// Appends an event to a session's event log (load-modify-save).
    ///
    /// # Errors
    /// `Error::Session` when the session does not exist.
    pub fn record_event(&self, id: &str, event: serde_json::Value) -> Result<()> {
        let Some(mut session) = self.load_session(id)? else {
            return Err(Error::Session(format!("record_event: no session {id}")));
        };
        session.events.push(event);
        self.save_session(&session)
    }

    /// Stores OAuth provider state (encrypted JSON string).
    ///
    /// # Errors
    /// `Error::Sqlite` on query failures.
    pub fn oauth_set(&self, provider: &str, data: &str) -> Result<()> {
        let enc = self.key.encrypt(data.as_bytes());
        let conn = self.conn();
        conn.execute(
            "INSERT INTO provider_oauth (provider, data_encrypted) VALUES (?1, ?2)
             ON CONFLICT(provider) DO UPDATE SET data_encrypted = excluded.data_encrypted",
            rusqlite::params![provider, enc],
        )
        .map_err(|e| Error::Sqlite(e.to_string()))?;
        Ok(())
    }

    /// Loads stored OAuth provider state, if any.
    ///
    /// # Errors
    /// `Error::Sqlite`/`Error::Crypto` on failures.
    pub fn oauth_get(&self, provider: &str) -> Result<Option<String>> {
        let conn = self.conn();
        let enc: Option<Vec<u8>> = match conn.query_row(
            "SELECT data_encrypted FROM provider_oauth WHERE provider = ?1",
            rusqlite::params![provider],
            |row| row.get(0),
        ) {
            Ok(v) => v,
            Err(rusqlite::Error::QueryReturnedNoRows) => None,
            Err(e) => return Err(Error::Sqlite(e.to_string())),
        };
        match enc {
            Some(bytes) => Ok(Some(decrypt_str(&self.key, &bytes, "oauth")?)),
            None => Ok(None),
        }
    }

    /// Removes stored OAuth provider state. Returns `true` when a row
    /// was removed.
    ///
    /// # Errors
    /// `Error::Sqlite` on query failures.
    pub fn oauth_delete(&self, provider: &str) -> Result<bool> {
        let conn = self.conn();
        let n = conn
            .execute(
                "DELETE FROM provider_oauth WHERE provider = ?1",
                rusqlite::params![provider],
            )
            .map_err(|e| Error::Sqlite(e.to_string()))?;
        Ok(n > 0)
    }

    /// Re-encrypts every row under a new password (crash-safe
    /// migration; see `session::migration` for the protocol).
    ///
    /// # Errors
    /// `Error::Crypto`/`Error::Sqlite`/`Error::Io` on failures; the
    /// vault is left in its pre-migration state on any error.
    pub fn change_password(&self, new_password: &str) -> Result<()> {
        migration::migrate(self, new_password)
    }

    /// Test-only access to the raw connection (fault-injection tests
    /// tamper with the schema to force DB failures).
    #[cfg(test)]
    pub(crate) fn with_raw_conn<R>(&self, f: impl FnOnce(&Connection) -> R) -> R {
        let conn = self.conn();
        f(&conn)
    }

    /// The current encryption key (migration re-encrypts with it).
    pub(crate) fn key(&self) -> &EncryptionKey {
        &self.key
    }
}

/// Decrypts and UTF-8-validates a stored blob.
fn decrypt_str(key: &EncryptionKey, bytes: &[u8], what: &str) -> Result<String> {
    let plain = key
        .decrypt(bytes)
        .ok_or_else(|| Error::Crypto(format!("{what} blob failed to decrypt")))?;
    String::from_utf8(plain).map_err(|_| Error::Crypto(format!("{what} blob is not UTF-8")))
}

/// Random 32-hex-char session id.
fn random_hex_id() -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut bytes = [0u8; 16];
    rand::RngCore::fill_bytes(&mut rand::thread_rng(), &mut bytes);
    let mut out = String::with_capacity(32);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

fn now_epoch_secs() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => i64::try_from(d.as_secs()).unwrap_or(i64::MAX),
        Err(_) => 0,
    }
}

/// Re-exports used by the migration module.
pub(crate) fn key_material(data_dir: &Path) -> Result<(Vec<u8>, Vec<u8>)> {
    let salt = load_key_material(&data_dir.join(encryption::SALT_FILE))?;
    let pepper = load_key_material(&data_dir.join(encryption::PEPPER_FILE))?;
    Ok((salt, pepper))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn open_temp_manager(tag: &str) -> (SessionManager, PathBuf) {
        let dir = std::env::temp_dir().join(format!("echo-sm-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let sm = SessionManager::open(&dir, "pw").expect("open");
        (sm, dir)
    }

    #[test]
    fn save_and_load_roundtrip() {
        let (sm, dir) = open_temp_manager("rt");
        let mut s = sm.create_session();
        s.messages
            .push(crate::agent::message::Message::user("hello"));
        s.title = Some(String::from("Test session"));
        sm.save_session(&s).expect("save");

        let loaded = sm.load_session(&s.id).expect("load").expect("exists");
        assert_eq!(loaded.id, s.id);
        assert_eq!(loaded.title.as_deref(), Some("Test session"));
        assert_eq!(loaded.messages.len(), 1);
        assert_eq!(loaded.messages[0].content, "hello");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn missing_session_loads_none() {
        let (sm, dir) = open_temp_manager("none");
        assert!(sm.load_session("nope").expect("query").is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn list_returns_decrypted_titles() {
        let (sm, dir) = open_temp_manager("list");
        let mut a = sm.create_session();
        a.title = Some(String::from("Alpha"));
        sm.save_session(&a).expect("save a");
        let b = sm.create_session();
        sm.save_session(&b).expect("save b");

        let list = sm.list_sessions().expect("list");
        assert_eq!(list.len(), 2);
        let titles: Vec<Option<String>> = list.iter().map(|s| s.title.clone()).collect();
        assert!(titles.contains(&Some(String::from("Alpha"))));
        assert!(titles.contains(&None));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn delete_and_rename() {
        let (sm, dir) = open_temp_manager("dr");
        let s = sm.create_session();
        sm.save_session(&s).expect("save");
        assert!(sm.rename_session(&s.id, "New title").expect("rename"));
        assert_eq!(
            sm.load_session(&s.id)
                .expect("load")
                .expect("exists")
                .title
                .as_deref(),
            Some("New title")
        );
        assert!(sm.delete_session(&s.id).expect("delete"));
        assert!(!sm.delete_session(&s.id).expect("delete again"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn wrong_password_rejected() {
        let dir = std::env::temp_dir().join(format!("echo-sm-wp-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        SessionManager::open(&dir, "right").expect("first open");
        let err = SessionManager::open(&dir, "wrong").expect_err("wrong password");
        assert!(matches!(err, Error::Crypto(_)));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn oauth_store_roundtrip() {
        let (sm, dir) = open_temp_manager("oauth");
        assert!(sm.oauth_get("openai").expect("get").is_none());
        sm.oauth_set("openai", r#"{"token":"t"}"#).expect("set");
        assert_eq!(
            sm.oauth_get("openai").expect("get").as_deref(),
            Some(r#"{"token":"t"}"#)
        );
        assert!(sm.oauth_delete("openai").expect("delete"));
        assert!(sm.oauth_get("openai").expect("get").is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn change_password_reencrypts_and_rejects_old() {
        let (sm, dir) = open_temp_manager("cp");
        let mut s = sm.create_session();
        s.messages
            .push(crate::agent::message::Message::user("secret"));
        sm.save_session(&s).expect("save");

        sm.change_password("new-pw").expect("migrate");
        drop(sm);

        let err = SessionManager::open(&dir, "old-pw").expect_err("old password gone");
        assert!(matches!(err, Error::Crypto(_)));
        let sm2 = SessionManager::open(&dir, "new-pw").expect("new password");
        let loaded = sm2.load_session(&s.id).expect("load").expect("exists");
        assert_eq!(loaded.messages[0].content, "secret");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn save_failure_leaves_original_row_intact() {
        let (sm, dir) = open_temp_manager("rollback");
        let mut s = sm.create_session();
        s.title = Some(String::from("original"));
        sm.save_session(&s).expect("save");

        // Force the upsert to fail with a trigger that aborts every
        // INSERT — the row must stay exactly as it was.
        sm.with_raw_conn(|conn| {
            conn.execute_batch(
                "CREATE TRIGGER fail_save BEFORE INSERT ON agent_sessions
                 BEGIN SELECT RAISE(ABORT, 'injected failure'); END;",
            )
            .expect("trigger");
        });
        let mut tampered = s.clone();
        tampered.title = Some(String::from("should not persist"));
        assert!(sm.save_session(&tampered).is_err(), "upsert must fail");

        sm.with_raw_conn(|conn| {
            conn.execute_batch("DROP TRIGGER fail_save")
                .expect("drop trigger");
        });
        let loaded = sm.load_session(&s.id).expect("load").expect("exists");
        assert_eq!(
            loaded.title.as_deref(),
            Some("original"),
            "failed save must leave the committed row untouched"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn purge_removes_old_sessions_only() {
        let (sm, dir) = open_temp_manager("purge");
        let old = sm.create_session();
        let fresh = sm.create_session();
        sm.save_session(&old).expect("save old");
        sm.save_session(&fresh).expect("save fresh");
        // Backdate the old session's created_at.
        sm.with_raw_conn(|conn| {
            conn.execute(
                "UPDATE agent_sessions SET created_at = '1' WHERE id = ?1",
                rusqlite::params![old.id],
            )
            .expect("backdate");
        });
        let removed = sm.purge_older_than(3600).expect("purge");
        assert_eq!(removed, 1);
        assert!(sm.load_session(&old.id).expect("load").is_none());
        assert!(sm.load_session(&fresh.id).expect("load").is_some());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
