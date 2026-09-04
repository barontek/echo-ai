//! Built-in `TLS`: a local CA + localhost certificate generated on
//! first run (rcgen), stored in the data dir with 0600 key files.
//!
//! The trust story mirrors the original implementation's Caddy setup without the
//! extra process: the CA is generated once and the user imports it into
//! their browser trust store; subsequent runs reuse the same CA, so
//! re-imports are never needed. Custom certificates (`[server]
//! tls_cert`/`tls_key`) override the generated ones.
//!
//! Depends on: `rcgen`, `axum-server` (rustls).

use std::net::SocketAddr;
use std::path::{Path, PathBuf};

use axum_server::tls_rustls::RustlsConfig;
use rcgen::{
    BasicConstraints, CertificateParams, DistinguishedName, DnType, IsCa, KeyPair, KeyUsagePurpose,
};
use serde::Deserialize;

use echo_ai_core::config;
use echo_ai_core::error::{Error, Result};

const CA_KEY: &str = "tls/ca-key.pem";
const CA_CERT: &str = "tls/ca-cert.pem";
const LEAF_KEY: &str = "tls/key.pem";
const LEAF_CERT: &str = "tls/cert.pem";

/// Resolved TLS settings.
#[derive(Debug, Clone, Deserialize)]
pub struct TlsSettings {
    /// Serve `HTTPS`.
    pub enabled: bool,
    /// Optional custom cert path (overrides the generated leaf).
    pub cert: String,
    /// Optional custom key path.
    pub key: String,
}

impl From<&config::Server> for TlsSettings {
    fn from(cfg: &config::Server) -> Self {
        Self {
            enabled: cfg.tls,
            cert: cfg.tls_cert.clone(),
            key: cfg.tls_key.clone(),
        }
    }
}

/// Generates (or loads) the CA + leaf, and builds the rustls config.
///
/// # Errors
/// `Error::Io` on key-material writes; `Error::Crypto` on generation or
/// parsing failures.
pub async fn rustls_config(data_dir: &Path, settings: &TlsSettings) -> Result<RustlsConfig> {
    let (cert_path, key_path) = if !settings.cert.is_empty() && !settings.key.is_empty() {
        (PathBuf::from(&settings.cert), PathBuf::from(&settings.key))
    } else {
        let dir = data_dir.join("tls");
        ensure_leaf(&dir)?;
        (dir.join(LEAF_CERT), dir.join(LEAF_KEY))
    };
    RustlsConfig::from_pem_file(cert_path, key_path)
        .await
        .map_err(|e| Error::Crypto(format!("rustls config: {e}")))
}

/// Binds and serves the router over `TLS`.
///
/// # Errors
/// Propagates bind failures.
pub async fn serve_tls(addr: SocketAddr, tls: RustlsConfig, app: axum::Router) -> Result<()> {
    axum_server::bind_rustls(addr, tls)
        .serve(app.into_make_service())
        .await
        .map_err(|e| Error::Session(format!("server error: {e}")))
}

/// Binds and serves plain `HTTP`.
///
/// # Errors
/// Propagates bind failures.
pub async fn serve_plain(addr: SocketAddr, app: axum::Router) -> Result<()> {
    axum_server::bind(addr)
        .serve(app.into_make_service())
        .await
        .map_err(|e| Error::Session(format!("server error: {e}")))
}

/// Ensures the CA + leaf exist under `dir`, generating them on first
/// use. The key files are written with mode 0600.
///
/// # Errors
/// `Error::Io`/`Error::Crypto` on generation or write failures.
fn ensure_leaf(dir: &Path) -> Result<()> {
    std::fs::create_dir_all(dir.join("tls")).map_err(|e| Error::Io {
        path: dir.to_path_buf(),
        source: e,
    })?;
    let ca_key_path = dir.join(CA_KEY);
    let ca_cert_path = dir.join(CA_CERT);
    let leaf_key_path = dir.join(LEAF_KEY);
    let leaf_cert_path = dir.join(LEAF_CERT);

    if !leaf_cert_path.exists() {
        // Load the CA if present, otherwise generate + persist it.
        let (ca_key, ca_cert) = if ca_cert_path.exists() {
            let key = KeyPair::from_pem(&read_string(&ca_key_path)?)
                .map_err(|e| Error::Crypto(e.to_string()))?;
            let params = CertificateParams::from_ca_cert_pem(&read_string(&ca_cert_path)?)
                .map_err(|e| Error::Crypto(e.to_string()))?;
            // `self_signed` on the loaded params reproduces the same
            // certificate (rcgen derives it deterministically from
            // params + key), giving us a `Certificate` to sign with.
            let cert = params
                .self_signed(&key)
                .map_err(|e| Error::Crypto(e.to_string()))?;
            (key, cert)
        } else {
            let key = KeyPair::generate().map_err(|e| Error::Crypto(e.to_string()))?;
            let cert = ca_params()
                .self_signed(&key)
                .map_err(|e| Error::Crypto(e.to_string()))?;
            write_0600(&ca_key_path, key.serialize_pem().as_bytes())?;
            write_0600(&ca_cert_path, cert.pem().as_bytes())?;
            (key, cert)
        };

        let leaf_key = KeyPair::generate().map_err(|e| Error::Crypto(e.to_string()))?;
        let leaf = leaf_params()
            .signed_by(&leaf_key, &ca_cert, &ca_key)
            .map_err(|e| Error::Crypto(e.to_string()))?;
        write_0600(&leaf_key_path, leaf_key.serialize_pem().as_bytes())?;
        write_0600(&leaf_cert_path, leaf.pem().as_bytes())?;
    }
    Ok(())
}

/// CA certificate parameters (infallible — empty subject lists are
/// always accepted).
fn ca_params() -> CertificateParams {
    #[allow(clippy::expect_used)] // invariant: empty SAN list is always valid
    let mut params = CertificateParams::new(vec![]).expect("ca params");
    params.is_ca = IsCa::Ca(BasicConstraints::Unconstrained);
    params.key_usages = vec![KeyUsagePurpose::KeyCertSign, KeyUsagePurpose::CrlSign];
    let mut dn = DistinguishedName::new();
    dn.push(DnType::CommonName, "Echo AI Local CA");
    params.distinguished_name = dn;
    params
}

/// Leaf certificate parameters (infallible — valid SANs).
fn leaf_params() -> CertificateParams {
    #[allow(clippy::expect_used)] // invariant: valid SAN list
    let mut params =
        CertificateParams::new(vec![String::from("localhost"), String::from("127.0.0.1")])
            .expect("leaf params");
    params.is_ca = IsCa::NoCa;
    let mut dn = DistinguishedName::new();
    dn.push(DnType::CommonName, "localhost");
    params.distinguished_name = dn;
    params
}

/// Writes a key file with mode 0600 (umask independent).
fn write_0600(path: &Path, bytes: &[u8]) -> Result<()> {
    use std::io::Write;
    use std::os::unix::fs::OpenOptionsExt;
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(path)
        .map_err(|e| Error::Io {
            path: path.to_path_buf(),
            source: e,
        })?;
    file.write_all(bytes)
        .and_then(|()| file.flush())
        .map_err(|e| Error::Io {
            path: path.to_path_buf(),
            source: e,
        })
}

fn read_string(path: &Path) -> Result<String> {
    std::fs::read_to_string(path).map_err(|e| Error::Io {
        path: path.to_path_buf(),
        source: e,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tls_settings_from_config() {
        let cfg = config::Server::default();
        let tls = TlsSettings::from(&cfg);
        assert!(tls.enabled);
    }

    #[test]
    fn cert_generation_roundtrip() {
        let dir = std::env::temp_dir().join(format!("echo-tls-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        ensure_leaf(&dir).expect("generate");
        assert!(dir.join(LEAF_CERT).exists());
        assert!(dir.join(LEAF_KEY).exists());
        // Idempotent: second run reuses the CA (no regeneration).
        ensure_leaf(&dir).expect("reuse");
        let ca1 = read_string(&dir.join(CA_CERT)).expect("ca");
        ensure_leaf(&dir).expect("reuse2");
        let ca2 = read_string(&dir.join(CA_CERT)).expect("ca");
        assert_eq!(ca1, ca2, "CA must be stable across runs");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(dir.join(LEAF_KEY))
                .expect("meta")
                .permissions()
                .mode()
                & 0o777;
            assert_eq!(mode, 0o600, "key file must be 0600");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
