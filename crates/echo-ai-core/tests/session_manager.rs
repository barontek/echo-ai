//! Integration tests for `SessionManager` (AGENTS.md test convention: `tests/session_manager.rs`).
//!
//! Exercises the full lifecycle of a session vault as an external consumer:
//! creation, password verification, session CRUD, persistence roundtrips,
//! user memory, OAuth storage, and password migration.

use echo_ai_core::agent::message::Message;
use echo_ai_core::session::SessionManager;
use std::path::PathBuf;

fn temp_data_dir(tag: &str) -> PathBuf {
    // SAFETY: Initializing test environment variable for cheap scrypt in test runs
    unsafe {
        std::env::set_var("ECHO_AI_TEST_FAST_SCRYPT", "1");
    }
    let dir = std::env::temp_dir().join(format!(
        "echo-test-sm-{tag}-{}-{}",
        std::process::id(),
        rand::random::<u32>()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("create test data dir");
    dir
}

#[test]
fn session_lifecycle_full_integration() {
    let dir = temp_data_dir("lifecycle");
    let password = "integration-password-123";

    // 1. Initial creation
    let sm = SessionManager::open(&dir, password).expect("open fresh vault");
    assert_eq!(sm.data_dir(), dir.as_path());

    // 2. Create, populate, and save a session
    let mut session = sm.create_session();
    let session_id = session.id.clone();
    session.title = Some(String::from("Test Conversation"));
    session.messages.push(Message::user("Hello agent"));
    session
        .messages
        .push(Message::assistant("Hello user, how can I help?"));
    sm.save_session(&session).expect("save session");

    // 3. List sessions
    let list = sm.list_sessions().expect("list sessions");
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].id, session_id);
    assert_eq!(list[0].title.as_deref(), Some("Test Conversation"));

    // 4. Load session back
    let loaded = sm
        .load_session(&session_id)
        .expect("load session")
        .expect("session exists");
    assert_eq!(loaded.id, session_id);
    assert_eq!(loaded.title.as_deref(), Some("Test Conversation"));
    assert_eq!(loaded.messages.len(), 2);
    assert_eq!(loaded.messages[0].content, "Hello agent");
    assert_eq!(loaded.messages[1].content, "Hello user, how can I help?");

    // 5. Rename session
    let renamed = sm
        .rename_session(&session_id, "Renamed Conversation")
        .expect("rename");
    assert!(renamed);
    let reloaded = sm
        .load_session(&session_id)
        .expect("reload")
        .expect("exists");
    assert_eq!(reloaded.title.as_deref(), Some("Renamed Conversation"));

    // 6. User memory facts
    assert!(sm.memory_get("user_name").expect("get").is_none());
    sm.memory_set("user_name", "Baron").expect("set");
    sm.memory_set("editor", "Antigravity").expect("set");
    assert_eq!(
        sm.memory_get("user_name").expect("get").as_deref(),
        Some("Baron")
    );

    let facts = sm.memory_list().expect("list facts");
    assert_eq!(facts.len(), 2);
    assert_eq!(
        facts[0],
        (String::from("editor"), String::from("Antigravity"))
    );
    assert_eq!(facts[1], (String::from("user_name"), String::from("Baron")));

    assert!(sm.memory_delete("user_name").expect("delete"));
    assert!(sm.memory_get("user_name").expect("get").is_none());

    // 7. OAuth tokens
    assert!(sm.oauth_get("openai").expect("get oauth").is_none());
    sm.oauth_set("openai", "sk-secret-token-value")
        .expect("set oauth");
    assert_eq!(
        sm.oauth_get("openai").expect("get oauth").as_deref(),
        Some("sk-secret-token-value")
    );
    assert!(sm.oauth_delete("openai").expect("delete oauth"));
    assert!(sm.oauth_get("openai").expect("get oauth").is_none());

    // 8. Delete session
    assert!(sm.delete_session(&session_id).expect("delete session"));
    assert!(sm.load_session(&session_id).expect("load").is_none());

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn wrong_password_rejected_and_reopen_succeeds() {
    let dir = temp_data_dir("auth");
    let password = "correct-password";

    // Setup vault
    {
        let sm = SessionManager::open(&dir, password).expect("setup");
        let session = sm.create_session();
        sm.save_session(&session).expect("save");
    }

    // Attempt open with incorrect password
    let failed = SessionManager::open(&dir, "incorrect-password");
    assert!(failed.is_err(), "wrong password must be rejected");

    // Re-open with correct password
    let reopened = SessionManager::open(&dir, password).expect("reopen with correct password");
    let list = reopened.list_sessions().expect("list");
    assert_eq!(list.len(), 1);

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn password_change_migration_integration() {
    let dir = temp_data_dir("change-pw");
    let old_pw = "initial-vault-password";
    let new_pw = "updated-vault-password";

    let session_id = {
        let sm = SessionManager::open(&dir, old_pw).expect("setup");
        let mut session = sm.create_session();
        session.title = Some(String::from("Migration Test"));
        session.messages.push(Message::user("Before migration"));
        sm.save_session(&session).expect("save");
        let id = session.id.clone();

        // Migrate to new password
        sm.change_password(new_pw).expect("migrate password");
        id
    };

    // Old password must now fail
    assert!(
        SessionManager::open(&dir, old_pw).is_err(),
        "old password must fail"
    );

    // New password must succeed and session data must be intact
    let sm = SessionManager::open(&dir, new_pw).expect("open with new password");
    let loaded = sm
        .load_session(&session_id)
        .expect("load")
        .expect("session found");
    assert_eq!(loaded.title.as_deref(), Some("Migration Test"));
    assert_eq!(loaded.messages.len(), 1);
    assert_eq!(loaded.messages[0].content, "Before migration");

    let _ = std::fs::remove_dir_all(&dir);
}
