//! `Chrome DevTools Protocol` transport over `--remote-debugging-pipe`.
//!
//! The pipe protocol frames each message as a 4-byte little-endian
//! length followed by the JSON payload — the same framing the C
//! version's `cdp.c` implemented. A reader task parses stdin into
//! responses (matched by `id`) and ignores events; commands are sent
//! over stdin with a monotonic id.
//!
//! Ownership: `Browser` owns the child and its pipes; `Drop` kills the
//! child's process group (same invariant as `tools::process`).
//!
//! Depends on: `tokio`, `serde_json`, `libc`, crate `error`.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{Value, json};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::process::{Child, ChildStdin, Command};
use tokio::sync::oneshot;

use crate::error::{Error, Result};

/// A `CDP` browser instance.
pub struct Browser {
    child: Child,
    stdin: tokio::sync::Mutex<ChildStdin>,
    pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Value>>>>,
    next_id: AtomicU64,
    #[allow(unused)] // keeps the reader task alive
    reader: tokio::task::JoinHandle<()>,
}

impl Browser {
    /// Launches `binary` with `--remote-debugging-pipe` and the given
    /// extra flags.
    ///
    /// # Errors
    /// `Error::Session` on spawn or pipe-setup failures.
    /// # Panics
    /// Only if a `pending` response lock is poisoned (a panic while
    /// another task held it) {2014} fail fast.
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub fn launch(binary: &str, extra_args: &[&str]) -> Result<Self> {
        let mut command = Command::new(binary);
        command
            .arg("--remote-debugging-pipe")
            .arg("--disable-gpu")
            .arg("--disable-infobars")
            .args(extra_args)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .kill_on_drop(true);
        #[cfg(unix)]
        command.process_group(0);

        let mut child = command.spawn().map_err(|e| Error::Session(e.to_string()))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| Error::Session(String::from("no stdin pipe")))?;
        let mut stdout = child
            .stdout
            .take()
            .ok_or_else(|| Error::Session(String::from("no stdout pipe")))?;

        // The reader task owns the response routing: frames arrive as
        // 4-byte LE length + JSON; responses (messages with an `id`)
        // resolve the matching pending oneshot, events are dropped.
        let pending: Arc<Mutex<HashMap<u64, oneshot::Sender<Value>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let route_pending = Arc::clone(&pending);
        let reader = tokio::spawn(async move {
            let mut buf = Vec::new();
            let mut length = [0u8; 4];
            loop {
                if stdout.read_exact(&mut length).await.is_err() {
                    break; // browser exited
                }
                let len = u32::from_le_bytes(length) as usize;
                buf.resize(len, 0);
                if stdout.read_exact(&mut buf).await.is_err() {
                    break;
                }
                let Ok(msg) = serde_json::from_slice::<Value>(&buf) else {
                    continue;
                };
                let Some(id) = msg.get("id").and_then(Value::as_u64) else {
                    continue; // event, not a response
                };
                // # Panics: poisoned lock = invariant violation (fail fast).
                #[allow(clippy::expect_used)] // poisoned lock = invariant violation
                let sender = route_pending.lock().expect("pending lock").remove(&id);
                if let Some(tx) = sender {
                    let _ = tx.send(msg);
                }
            }
        });

        let browser = Self {
            child,
            stdin: tokio::sync::Mutex::new(stdin),
            pending: Arc::clone(&pending),
            next_id: AtomicU64::new(1),
            reader,
        };
        Ok(browser)
    }

    /// Sends a `CDP` command and waits for its response.
    ///
    /// # Errors
    /// `Error::Session` on protocol failures (transport, response error,
    /// or timeout).
    ///
    /// # Panics
    /// Only if a `pending` lock is poisoned (a panic while another task
    /// held it) — fail fast.
    #[allow(clippy::expect_used)] // poisoned lock = invariant violation
    pub async fn send(&self, method: &str, params: Value) -> Result<Value> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let (tx, rx) = oneshot::channel();
        {
            let mut pending = self.pending.lock().expect("pending lock");
            pending.insert(id, tx);
        }
        let message = json!({ "id": id, "method": method, "params": params });
        let payload = serde_json::to_vec(&message).map_err(|e| Error::Session(e.to_string()))?;
        let mut frame = Vec::with_capacity(4 + payload.len());
        frame.extend_from_slice(
            &u32::try_from(payload.len())
                .unwrap_or(u32::MAX)
                .to_le_bytes(),
        );
        frame.extend_from_slice(&payload);

        let mut stdin = self.stdin.lock().await;
        let mut result = Err(Error::Session(String::from("cdp send timeout")));
        // Write with a hard timeout so a wedged browser cannot hang the
        // agent turn forever.
        if tokio::time::timeout(Duration::from_secs(10), async {
            stdin.write_all(&frame).await?;
            stdin.flush().await
        })
        .await
        .is_err()
        {
            return Err(Error::Session(String::from("cdp write timeout")));
        }

        match tokio::time::timeout(Duration::from_secs(30), rx).await {
            Ok(Ok(msg)) => {
                if let Some(err) = msg.get("error") {
                    return Err(Error::Session(format!("cdp error: {err}")));
                }
                result = Ok(msg.get("result").cloned().unwrap_or(Value::Null));
            }
            Ok(Err(_)) => {
                return Err(Error::Session(String::from("cdp response channel closed")));
            }
            Err(_) => {}
        }
        result
    }

    /// Navigates and waits for the page to reach `complete`.
    ///
    /// # Errors
    /// `Error::Session` on `CDP` failures.
    pub async fn navigate(&self, url: &str, timeout: Duration) -> Result<()> {
        let _ = self.send("Page.navigate", json!({ "url": url })).await?;
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            if tokio::time::Instant::now() >= deadline {
                return Err(Error::Session(format!("page load timeout for {url}")));
            }
            let ready = self
                .send(
                    "Runtime.evaluate",
                    json!({
                        "expression": "document.readyState",
                        "returnByValue": true,
                    }),
                )
                .await?;
            let state = ready
                .get("result")
                .and_then(|r| r.get("value"))
                .and_then(Value::as_str)
                .unwrap_or("");
            if state == "complete" {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }

    /// Evaluates JS and returns the value (must be JSON-serializable).
    ///
    /// # Errors
    /// `Error::Session` on `CDP` failures.
    pub async fn evaluate(&self, expression: &str) -> Result<Value> {
        let resp = self
            .send(
                "Runtime.evaluate",
                json!({
                    "expression": expression,
                    "returnByValue": true,
                }),
            )
            .await?;
        Ok(resp.get("result").cloned().unwrap_or(Value::Null))
    }

    /// Captures a screenshot; returns base64 `PNG`.
    ///
    /// # Errors
    /// `Error::Session` on `CDP` failures.
    pub async fn screenshot(&self) -> Result<String> {
        let resp = self
            .send("Page.captureScreenshot", json!({ "format": "png" }))
            .await?;
        resp.get("data")
            .and_then(Value::as_str)
            .map(String::from)
            .ok_or_else(|| Error::Session(String::from("no screenshot data")))
    }

    /// Injects the webdriver-spoof script on every future navigation.
    ///
    /// # Errors
    /// `Error::Session` on `CDP` failures.
    pub async fn install_stealth(&self) -> Result<()> {
        let _ = self
            .send(
                "Page.addScriptToEvaluateOnNewDocument",
                json!({
                    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                }),
            )
            .await?;
        Ok(())
    }
}

impl Drop for Browser {
    fn drop(&mut self) {
        // The child was spawned with `process_group(0)` (see `launch`),
        // so its pid is its group id; killing the group reaps any
        // renderer it spawned. `killpg` is available on all Unix
        // targets; `ESRCH` is harmless if the browser already exited.
        #[cfg(unix)]
        {
            // SAFETY: pid is the process-group leader's id (spawned with
            // `process_group(0)` in `launch`).
            let _ = unsafe {
                libc::killpg(
                    self.child.id().unwrap_or_default() as libc::pid_t,
                    libc::SIGKILL,
                )
            };
        }
        let _ = self.child.start_kill();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frame_layout_is_length_prefixed_le() {
        let payload = br#"{"id":1,"method":"Page.navigate"}"#;
        let mut frame = Vec::new();
        frame.extend_from_slice(
            &u32::try_from(payload.len())
                .unwrap_or(u32::MAX)
                .to_le_bytes(),
        );
        frame.extend_from_slice(payload);
        assert_eq!(frame.len(), 4 + payload.len());
        let len = u32::from_le_bytes([frame[0], frame[1], frame[2], frame[3]]) as usize;
        assert_eq!(len, payload.len());
    }

    #[test]
    fn id_assignment_is_monotonic() {
        let counter = AtomicU64::new(1);
        let a = counter.fetch_add(1, Ordering::SeqCst);
        let b = counter.fetch_add(1, Ordering::SeqCst);
        assert!(b > a);
    }
}
