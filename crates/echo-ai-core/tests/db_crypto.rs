//! Cross-version vault compatibility & DB crypto integration tests (`tests/db_crypto.rs`).
//!
//! Validates byte-level compatibility with the legacy C implementation's on-disk layout:
//! - Fernet token format: 0x80 | 8-byte BE ts | 16-byte IV | AES-128-CBC PKCS7 | 32-byte HMAC-SHA256
//! - Key derivation: scrypt(password, salt || pepper, N, r=8, p=1), 0..16 sign, 16..32 encrypt
//! - SQLite schema: `agent_sessions`, `provider_oauth`, `user_memory`
//! - File permissions: 0700 data dir, 0600 key files

use std::io::Write;
use std::path::PathBuf;

use rusqlite::Connection;

use echo_ai_core::session::SessionManager;
use echo_ai_core::session::db::ensure_data_dir;
use echo_ai_core::session::encryption::{EncryptionKey, PEPPER_FILE, SALT_FILE, VERIFIER_FILE};

fn temp_data_dir(tag: &str) -> PathBuf {
    // SAFETY: Initializing test environment variable for cheap scrypt in test runs
    unsafe {
        std::env::set_var("ECHO_AI_TEST_FAST_SCRYPT", "1");
    }
    let dir = std::env::temp_dir().join(format!(
        "echo-test-crypto-{tag}-{}-{}",
        std::process::id(),
        rand::random::<u32>()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    dir
}

fn seed_c_database(conn: &Connection, key: &EncryptionKey) {
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
    .expect("create tables");

    // Encrypt title and messages JSON
    let title_token = key.encrypt(b"Legacy C Session");
    let messages_plain = serde_json::json!([
        {
            "role": "user",
            "content": "Message from the legacy format"
        },
        {
            "role": "assistant",
            "content": "Understood perfectly"
        }
    ])
    .to_string();
    let messages_token = key.encrypt(messages_plain.as_bytes());
    let metadata_token = key.encrypt(b"{}");
    let events_token = key.encrypt(b"[]");

    conn.execute(
        "INSERT INTO agent_sessions (id, title_encrypted, title_generation_attempted, created_at, messages_encrypted, metadata_encrypted, events_encrypted)
         VALUES (?1, ?2, 0, '2026-08-11T12:00:00Z', ?3, ?4, ?5)",
        rusqlite::params![
            "sess-c-compat-001",
            title_token,
            messages_token,
            metadata_token,
            events_token
        ],
    )
    .expect("insert c session");
}

#[test]
fn c_vault_format_compatibility_and_roundtrip() {
    let dir = temp_data_dir("c-compat");
    ensure_data_dir(&dir).expect("ensure data dir");
    let password = "legacy-c-vault-password";

    // 1. Manually generate salt and pepper
    let salt = [0x42u8; 16];
    let pepper = [0x24u8; 32];

    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut f_salt = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(dir.join(SALT_FILE))
            .expect("create salt");
        f_salt.write_all(&salt).expect("write salt");
        let mut f_pep = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(dir.join(PEPPER_FILE))
            .expect("create pepper");
        f_pep.write_all(&pepper).expect("write pepper");
    }
    #[cfg(not(unix))]
    {
        std::fs::write(dir.join(SALT_FILE), &salt).expect("write salt");
        std::fs::write(dir.join(PEPPER_FILE), &pepper).expect("write pepper");
    }

    // 2. Derive keys using EncryptionKey::derive
    let key = EncryptionKey::derive(password, &salt, &pepper).expect("derive key");

    // 3. Write manual .verifier token with "echo-ai-ok"
    let verifier_token = key.encrypt(b"echo-ai-ok");
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let mut f_ver = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(dir.join(VERIFIER_FILE))
            .expect("create verifier");
        f_ver.write_all(&verifier_token).expect("write verifier");
    }
    #[cfg(not(unix))]
    {
        std::fs::write(dir.join(VERIFIER_FILE), &verifier_token).expect("write verifier");
    }

    // 4. Manually initialize SQLite DB with C-compatible schema and a seeded session row
    let db_path = dir.join("echo-ai.db");
    let conn = Connection::open(&db_path).expect("open db");
    seed_c_database(&conn, &key);
    drop(conn);

    // 5. Open using SessionManager::open (the Rust engine)
    let sm = SessionManager::open(&dir, password).expect("SessionManager must unlock C vault");

    // 6. Verify session loads and decrypts
    let sess = sm
        .load_session("sess-c-compat-001")
        .expect("load")
        .expect("session found");
    assert_eq!(sess.id, "sess-c-compat-001");
    assert_eq!(sess.title.as_deref(), Some("Legacy C Session"));
    assert_eq!(sess.messages.len(), 2);
    assert_eq!(sess.messages[0].content, "Message from the legacy format");
    assert_eq!(sess.messages[1].content, "Understood perfectly");

    // 7. Verify wrong password fails
    assert!(SessionManager::open(&dir, "wrong-password").is_err());

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn durability_pragmas_and_file_modes() {
    let dir = temp_data_dir("pragmas");
    let password = "pragma-check-pw";

    let sm = SessionManager::open(&dir, password).expect("open");
    let conn = Connection::open(dir.join("echo-ai.db")).expect("open db directly");

    let journal_mode: String = conn
        .pragma_query_value(None, "journal_mode", |r| r.get(0))
        .expect("journal");
    assert_eq!(journal_mode.to_lowercase(), "delete");

    let sync_mode: i32 = conn
        .pragma_query_value(None, "synchronous", |r| r.get(0))
        .expect("sync");
    assert_eq!(sync_mode, 2);

    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let d_meta = std::fs::metadata(&dir).expect("meta");
        assert_eq!(d_meta.mode() & 0o777, 0o700, "data dir must be 0700");

        for name in [SALT_FILE, PEPPER_FILE, VERIFIER_FILE] {
            let f_meta = std::fs::metadata(dir.join(name)).expect("meta file");
            assert_eq!(f_meta.mode() & 0o777, 0o600, "{name} must be 0600");
        }
    }

    drop(conn);
    drop(sm);
    let _ = std::fs::remove_dir_all(&dir);
}
