//! Field-level encryption for session records: scrypt key derivation,
//! Fernet-format tokens (AES-128-CBC + HMAC-SHA256), and the
//! salt/pepper/verifier key-material files.
//!
//! The on-disk format is byte-compatible with the original implementation's
//! `encryption.c` — a vault created by either version must open in the
//! other. Token layout: `0x80 | 8-byte big-endian timestamp | 16-byte IV
//! | AES-128-CBC ciphertext (PKCS7) | 32-byte HMAC-SHA256`. Key:
//! `scrypt(password, salt || pepper, N=262144, r=8, p=1)`; bytes
//! `0..16` sign, bytes `16..32` encrypt.
//!
//! Key-material files are created exclusively with mode 0600 (umask
//! independent) and unlinked on any partial write, so no half-written
//! key file can survive a crash.
//!
//! Depends on: `aes`, `cbc`, `hmac`, `sha2`, `scrypt`, `rand`, `subtle`
//! (via `digest::constant_time_eq`), crate `utils::logging`.

use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use aes::Aes128;
use cbc::cipher::{BlockDecryptMut, BlockEncryptMut, KeyIvInit, block_padding::Pkcs7};
use cbc::{Decryptor, Encryptor};
use hmac::{Hmac, Mac};
use rand::RngCore;
use scrypt::Params as ScryptParams;
use sha2::Sha256;
use subtle::ConstantTimeEq;

use crate::error::{Error, Result};
use crate::log_error;

type Aes128CbcEnc = Encryptor<Aes128>;
type Aes128CbcDec = Decryptor<Aes128>;
type HmacSha256 = Hmac<Sha256>;

/// Scrypt cost parameters (locked to the original implementation's values — changing
/// them would make existing vaults unreadable).
#[cfg(not(test))]
const SCRYPT_LOG_N: u8 = 18; // N = 2^18 = 262144
/// Test-only cheap cost (N = 2^10, ~1 MB): the suite exercises logic —
/// roundtrips, tamper rejection, partial-commit rollback — not KDF
/// strength, and no test pins real-parameter output bytes. Debug scrypt
/// at N=2^18 takes ~50 s per derivation, which dominated the session
/// tests (~21 min for 21 tests).
#[cfg(test)]
const SCRYPT_LOG_N: u8 = 10;
const SCRYPT_R: u32 = 8;
const SCRYPT_P: u32 = 1;

/// Salt size generated at first run.
pub const SALT_SIZE: usize = 16;
/// Pepper size generated at first run.
pub const PEPPER_SIZE: usize = 32;
/// Max accepted length for loaded salt/pepper files.
pub const SALT_PEPPER_MAX: usize = 64;

/// Fernet token version byte.
const FERNET_VERSION: u8 = 0x80;
/// AES-CBC IV size.
const IV_SIZE: usize = 16;
/// HMAC-SHA256 output size.
const HMAC_SIZE: usize = 32;
/// Fernet freshness rule: reject tokens timestamped more than 60s in
/// the future. Past timestamps are always accepted (no TTL semantics).
const CLOCK_SKEW_TOLERANCE_SECS: i64 = 60;

/// Verifier plaintext, encrypted into the verifier file.
const VERIFIER_PLAINTEXT: &[u8] = b"echo-ai-ok";

/// Derived 32-byte key: `[0..16]` HMAC signing, `[16..32]` AES.
#[derive(Debug, Clone)]
pub struct EncryptionKey {
    key: [u8; 32],
}

/// Key-material file names inside the data dir (compat with the C
/// version's vault layout).
/// Salt file name.
pub const SALT_FILE: &str = "salt";
/// Pepper file name.
pub const PEPPER_FILE: &str = ".pepper";
/// Verifier file name.
pub const VERIFIER_FILE: &str = ".verifier";
/// Migration staging verifier file name.
pub const VERIFIER_NEW_FILE: &str = ".verifier.new";
/// Password-migration in-flight marker file name.
pub const MIGRATION_MARKER: &str = ".changing_pwd";
/// Session database file name.
pub const DB_FILE: &str = "echo-ai.db";

impl EncryptionKey {
    /// Derives the key from a password, salt, and pepper.
    ///
    /// # Errors
    /// `Error::Crypto` when the KDF parameters are invalid or the
    /// derivation fails.
    pub fn derive(password: &str, salt: &[u8], pepper: &[u8]) -> Result<Self> {
        if salt.is_empty() || salt.len() > SALT_PEPPER_MAX {
            return Err(Error::Crypto(String::from("salt must be 1..=64 bytes")));
        }
        if pepper.len() > SALT_PEPPER_MAX {
            return Err(Error::Crypto(String::from(
                "pepper must be at most 64 bytes",
            )));
        }
        let params = ScryptParams::new(SCRYPT_LOG_N, SCRYPT_R, SCRYPT_P, 32)
            .map_err(|e| Error::Crypto(format!("invalid scrypt params: {e}")))?;
        let mut combined = Vec::with_capacity(salt.len() + pepper.len());
        combined.extend_from_slice(salt);
        combined.extend_from_slice(pepper);
        let mut key = [0u8; 32];
        scrypt::scrypt(password.as_bytes(), &combined, &params, &mut key)
            .map_err(|e| Error::Crypto(format!("scrypt failed: {e}")))?;
        Ok(Self { key })
    }

    /// Encrypts `plaintext` into a Fernet token.
    ///
    /// # Panics
    /// Cannot panic in practice: the signing key is a fixed 16-byte
    /// slice of a `[u8; 32]` key, and `Hmac<Sha256>` accepts any key
    /// length — `new_from_slice` only fails on lengths it forbids.
    #[must_use]
    #[allow(clippy::missing_panics_doc)] // invariant: HMAC accepts 16-byte keys
    pub fn encrypt(&self, plaintext: &[u8]) -> Vec<u8> {
        let mut iv = [0u8; IV_SIZE];
        rand::thread_rng().fill_bytes(&mut iv);

        let ciphertext = Aes128CbcEnc::new(self.key[16..32].into(), iv.as_slice().into())
            .encrypt_padded_vec_mut::<Pkcs7>(plaintext);

        let timestamp = now_epoch_secs().max(1); // Fernet spec: 0 invalid
        let mut token = Vec::with_capacity(1 + 8 + IV_SIZE + ciphertext.len() + HMAC_SIZE);
        token.push(FERNET_VERSION);
        token.extend_from_slice(&timestamp.to_be_bytes());
        token.extend_from_slice(&iv);
        token.extend_from_slice(&ciphertext);

        // Same invariant as the doc above: a 16-byte slice is always a
        // valid `Hmac` key, so this branch is unreachable.
        #[allow(clippy::expect_used)]
        let mut mac =
            HmacSha256::new_from_slice(&self.key[0..16]).expect("HMAC accepts any key length");
        mac.update(&token);
        token.extend_from_slice(&mac.finalize().into_bytes());

        token
    }

    /// Decrypts a Fernet token. `None` on any structural failure, bad
    /// HMAC, bad padding, or a clock-skewed timestamp.
    ///
    /// # Panics
    /// Cannot panic in practice: same fixed-16-byte `Hmac` key invariant
    /// as [`Self::encrypt`].
    #[must_use]
    #[allow(clippy::missing_panics_doc)] // invariant: HMAC accepts 16-byte keys
    pub fn decrypt(&self, token: &[u8]) -> Option<Vec<u8>> {
        if token.len() < 1 + 8 + IV_SIZE + 1 + HMAC_SIZE || token[0] != FERNET_VERSION {
            return None;
        }
        let timestamp = i64::from_be_bytes(token[1..9].try_into().ok()?);
        if timestamp != 0 && timestamp > now_epoch_secs() + CLOCK_SKEW_TOLERANCE_SECS {
            return None;
        }
        let iv = &token[9..9 + IV_SIZE];
        let ciphertext_end = token.len() - HMAC_SIZE;
        let stored_hmac = &token[ciphertext_end..];

        #[allow(clippy::expect_used)]
        let mut mac =
            HmacSha256::new_from_slice(&self.key[0..16]).expect("HMAC accepts any key length");
        mac.update(&token[..ciphertext_end]);
        let mac = mac.finalize().into_bytes();
        if !bool::from(mac.ct_eq(stored_hmac)) {
            return None;
        }

        // The ciphertext starts *after* the IV — the naive `9..end` slice
        // would feed the IV in as the first plaintext block (garbage).
        let plaintext = Aes128CbcDec::new(self.key[16..32].into(), iv.into())
            .decrypt_padded_vec_mut::<Pkcs7>(&token[9 + IV_SIZE..ciphertext_end])
            .ok()?;
        Some(plaintext)
    }
}

/// First-run detection: the salt file's presence marks an initialized
/// vault (the original implementation's rule).
#[must_use]
/// Whether a vault exists, keyed on the verifier file — the C
/// server's authoritative check (`routes_auth.c` uses
/// `verifier_exists`). A dir with key material but no verifier is
/// in the setup state, exactly like the original implementation.
pub fn vault_initialized(data_dir: &Path) -> bool {
    data_dir.join(VERIFIER_FILE).exists()
}

/// Generates `n` random bytes.
fn random_bytes(n: usize) -> Vec<u8> {
    let mut buf = vec![0u8; n];
    rand::thread_rng().fill_bytes(&mut buf);
    buf
}

/// Creates a key-material file with exclusive creation and mode 0600,
/// writing all `bytes`; unlinks on any failure so no partial file
/// survives.
fn write_secure_exclusive(path: &Path, bytes: &[u8]) -> Result<()> {
    use std::os::unix::fs::OpenOptionsExt;
    let mut file = match std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
    {
        Ok(f) => f,
        Err(e) => {
            return Err(Error::Io {
                path: path.to_path_buf(),
                source: e,
            });
        }
    };
    let write_result = file.write_all(bytes).and_then(|()| file.flush());
    if let Err(e) = write_result {
        log_error!(
            "failed to write key material, removing partial file",
            "path" => &path.to_string_lossy()
        );
        let _ = std::fs::remove_file(path);
        return Err(Error::Io {
            path: path.to_path_buf(),
            source: e,
        });
    }
    Ok(())
}

/// Creates the salt file.
///
/// # Errors
/// `Error::Io` when the exclusive-create or write fails.
pub fn create_salt(data_dir: &Path) -> Result<()> {
    write_secure_exclusive(&data_dir.join(SALT_FILE), &random_bytes(SALT_SIZE))
}

/// Creates the pepper file.
///
/// # Errors
/// `Error::Io` when the exclusive-create or write fails.
pub fn create_pepper(data_dir: &Path) -> Result<()> {
    write_secure_exclusive(&data_dir.join(PEPPER_FILE), &random_bytes(PEPPER_SIZE))
}

/// Loads a key-material file (salt or pepper), enforcing the 1..=64
/// byte size bound.
///
/// # Errors
/// `Error::Io` on read failure; `Error::Crypto` on absurd sizes.
pub fn load_key_material(path: &Path) -> Result<Vec<u8>> {
    let data = std::fs::read(path).map_err(|e| Error::Io {
        path: path.to_path_buf(),
        source: e,
    })?;
    if data.is_empty() || data.len() > SALT_PEPPER_MAX {
        return Err(Error::Crypto(format!(
            "key material file {} has invalid size {}",
            path.display(),
            data.len()
        )));
    }
    Ok(data)
}

/// Writes the verifier file (encrypted `"echo-ai-ok"`).
///
/// # Errors
/// `Error::Io` when the exclusive-create or write fails.
pub fn create_verifier(key: &EncryptionKey, data_dir: &Path) -> Result<()> {
    let token = key.encrypt(VERIFIER_PLAINTEXT);
    write_secure_exclusive(&data_dir.join(VERIFIER_FILE), &token)
}

#[must_use]
/// Whether a Fernet token decrypts to the verifier plaintext (used for
/// both the live verifier and the migration.s `.verifier.new`).
pub fn verifier_token_matches(key: &EncryptionKey, token: &[u8]) -> bool {
    key.decrypt(token).as_deref() == Some(VERIFIER_PLAINTEXT)
}

/// Verifies the password by decrypting the verifier file.
///
/// # Errors
/// `Error::Crypto` when the verifier is missing/malformed or does not
/// decrypt to the known plaintext (i.e. wrong password).
pub fn check_verifier(key: &EncryptionKey, data_dir: &Path) -> Result<()> {
    let path = data_dir.join(VERIFIER_FILE);
    let token = std::fs::read(&path).map_err(|e| Error::Io {
        path: path.clone(),
        source: e,
    })?;
    if token.is_empty() || token.len() > 4096 {
        return Err(Error::Crypto(format!(
            "verifier file has invalid size {}",
            token.len()
        )));
    }
    if verifier_token_matches(key, &token) {
        Ok(())
    } else {
        Err(Error::Crypto(String::from(
            "verifier check failed: wrong password or corrupt vault",
        )))
    }
}

/// Boolean form of the verifier check (migration recovery uses it
/// without needing the error detail).
#[must_use]
pub fn verifier_file_matches(key: &EncryptionKey, path: &Path) -> bool {
    matches!(std::fs::read(path), Ok(token) if verifier_token_matches(key, &token))
}

/// Full first-run vault setup: salt, pepper, key, verifier.
///
/// # Errors
/// Propagates key-material or verifier write failures.
pub fn initialize_vault(data_dir: &Path, password: &str) -> Result<EncryptionKey> {
    // A complete vault (verifier present) must go through the verify
    // path — never silently re-derive with a new password.
    if data_dir.join(VERIFIER_FILE).exists() {
        let key = EncryptionKey::derive(
            password,
            &load_key_material(&data_dir.join(SALT_FILE))?,
            &load_key_material(&data_dir.join(PEPPER_FILE))?,
        )?;
        check_verifier(&key, data_dir)?;
        return Ok(key);
    }
    // Idempotent key-material creation: reuse existing files (the C
    // setup flow can run against a dir holding a leftover `.pepper`
    // from a partial vault) — only create what is missing.
    if !data_dir.join(SALT_FILE).exists() {
        create_salt(data_dir)?;
    }
    if !data_dir.join(PEPPER_FILE).exists() {
        create_pepper(data_dir)?;
    }
    let key = EncryptionKey::derive(
        password,
        &load_key_material(&data_dir.join(SALT_FILE))?,
        &load_key_material(&data_dir.join(PEPPER_FILE))?,
    )?;
    create_verifier(&key, data_dir)?;
    Ok(key)
}

/// Loads the key for an existing vault (salt + pepper + password).
///
/// # Errors
/// `Error::Crypto` when key material is missing or the password is
/// wrong (verifier check).
pub fn load_key(data_dir: &Path, password: &str) -> Result<EncryptionKey> {
    let salt = load_key_material(&data_dir.join(SALT_FILE))?;
    let pepper = load_key_material(&data_dir.join(PEPPER_FILE))?;
    let key = EncryptionKey::derive(password, &salt, &pepper)?;
    check_verifier(&key, data_dir)?;
    Ok(key)
}

/// Unix epoch seconds (the token's timestamp field).
#[must_use]
fn now_epoch_secs() -> i64 {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(d) => i64::try_from(d.as_secs()).unwrap_or(i64::MAX),
        Err(_) => 0,
    }
}

/// Joins a data-dir file name onto the dir (helper for callers that
/// want explicit `PathBuf` construction without string concatenation).
#[must_use]
pub fn data_file(data_dir: &Path, name: &str) -> PathBuf {
    data_dir.join(name)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("echo-vault-{tag}-{}", std::process::id()));
        std::fs::create_dir_all(&dir).expect("create vault dir");
        dir
    }

    #[test]
    fn encrypt_decrypt_roundtrip() {
        let key = EncryptionKey::derive("pw", &[1u8; 16], &[2u8; 32]).expect("derive");
        let plain = b"hello session world";
        let token = key.encrypt(plain);
        assert_eq!(token[0], FERNET_VERSION);
        assert_eq!(key.decrypt(&token).expect("decrypt"), plain);
    }

    #[test]
    fn token_layout_matches_c_spec() {
        let key = EncryptionKey::derive("pw", &[1u8; 16], &[2u8; 32]).expect("derive");
        let token = key.encrypt(b"abc");
        // 1 version + 8 ts + 16 iv + padded ct (3 -> one 16-byte block) + 32 hmac
        assert_eq!(token.len(), 1 + 8 + 16 + 16 + 32);
        let ts = i64::from_be_bytes(token[1..9].try_into().expect("ts"));
        assert!(ts > 0);
        let now = now_epoch_secs();
        assert!(now - ts <= 2, "timestamp fresh");
    }

    #[test]
    fn wrong_password_derives_wrong_key() {
        let key = EncryptionKey::derive("right", &[1u8; 16], &[2u8; 32]).expect("derive");
        let wrong = EncryptionKey::derive("wrong", &[1u8; 16], &[2u8; 32]).expect("derive");
        let token = key.encrypt(b"secret");
        assert!(wrong.decrypt(&token).is_none());
    }

    #[test]
    fn tampered_token_rejected() {
        let key = EncryptionKey::derive("pw", &[1u8; 16], &[2u8; 32]).expect("derive");
        let mut token = key.encrypt(b"secret");
        let last = token.len() - 1;
        token[last] ^= 0x01;
        assert!(key.decrypt(&token).is_none());
    }

    #[test]
    fn truncated_token_rejected() {
        let key = EncryptionKey::derive("pw", &[1u8; 16], &[2u8; 32]).expect("derive");
        let token = key.encrypt(b"secret");
        assert!(key.decrypt(&token[..token.len() - 5]).is_none());
    }

    #[test]
    fn wrong_version_rejected() {
        let key = EncryptionKey::derive("pw", &[1u8; 16], &[2u8; 32]).expect("derive");
        let mut token = key.encrypt(b"secret");
        token[0] = 0x81;
        assert!(key.decrypt(&token).is_none());
    }

    #[test]
    fn future_timestamp_rejected() {
        let key = EncryptionKey::derive("pw", &[1u8; 16], &[2u8; 32]).expect("derive");
        let mut token = key.encrypt(b"secret");
        let future = now_epoch_secs() + 10_000;
        token[1..9].copy_from_slice(&future.to_be_bytes());
        assert!(key.decrypt(&token).is_none());
    }

    #[test]
    fn vault_files_are_created_0600_and_exclusive() {
        let dir = temp_dir("files");
        initialize_vault(&dir, "pw").expect("init");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            for name in [SALT_FILE, PEPPER_FILE, VERIFIER_FILE] {
                let meta = std::fs::metadata(dir.join(name)).expect("meta");
                assert_eq!(meta.permissions().mode() & 0o777, 0o600, "{name} mode");
            }
        }
        // Initialization is idempotent (reuses existing key material —
        // the C setup flow can run against a partially-created vault),
        // but a different password is rejected by the verifier.
        let err = initialize_vault(&dir, "pw2").expect_err("wrong pw");
        assert!(matches!(err, Error::Crypto(_)));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn verifier_check_distinguishes_passwords() {
        let dir = temp_dir("verifier");
        initialize_vault(&dir, "good").expect("init");
        assert!(load_key(&dir, "good").is_ok());
        let err = load_key(&dir, "bad").expect_err("wrong password");
        assert!(matches!(err, Error::Crypto(_)));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn empty_salt_rejected() {
        let err = EncryptionKey::derive("pw", &[], &[2u8; 32]).expect_err("empty salt");
        assert!(matches!(err, Error::Crypto(_)));
    }
}
