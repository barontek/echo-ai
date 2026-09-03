//! Browser tools: navigate, click, type, scroll, read, screenshot, and
//! script execution against the shared `CDP` browser instance.
//!
//! The browser is process-wide (one `Arc<BrowserManager>` shared by the
//! registry): the first tool call launches the browser, later calls
//! reuse it. Interactivity is implemented with `Runtime.evaluate`
//! (JS `.click()` / value + input events), which is both simpler and
//! more robust than `Input` protocol emulation.
//!
//! Depends on: `tokio`, crate `browser::{cdp, stealth}`, `tools::tool`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::sync::Arc;
use std::time::Duration;

use super::cdp::Browser;
use super::stealth;

use crate::tools::tool::{
    Tool, ToolContext, ToolError, ToolOutput, arg_optional_string, arg_optional_u64, arg_string,
};

/// Shared browser instance (lazily launched).
#[derive(Default)]
pub struct BrowserManager {
    inner: tokio::sync::Mutex<Option<Arc<Browser>>>,
}

impl BrowserManager {
    /// A manager with no browser yet.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Returns the shared browser, launching it on first use.
    ///
    /// # Errors
    /// `ToolError::Execution` when the browser cannot be launched.
    pub async fn get(&self) -> Result<Arc<Browser>, ToolError> {
        let mut guard = self.inner.lock().await;
        if let Some(browser) = &*guard {
            return Ok(Arc::clone(browser));
        }
        let binary = std::env::var("ECHO_AI_BROWSER").unwrap_or_else(|_| String::from("chromium"));
        let mut flags = stealth::stealth_flags();
        flags.push(format!("--user-agent={}", stealth::default_user_agent()));
        let flag_refs: Vec<&str> = flags.iter().map(String::as_str).collect();
        let browser = Browser::launch(&binary, &flag_refs)
            .map_err(|e| ToolError::Execution(e.to_string()))?;
        browser
            .install_stealth()
            .await
            .map_err(|e| ToolError::Execution(e.to_string()))?;
        let browser = Arc::new(browser);
        *guard = Some(Arc::clone(&browser));
        Ok(browser)
    }

    /// Whether a browser is already running.
    #[must_use]
    pub async fn is_running(&self) -> bool {
        self.inner.lock().await.is_some()
    }

    /// Kills the browser (frees the pipes).
    pub async fn close(&self) {
        *self.inner.lock().await = None;
    }
}

fn js_string_literal(s: &str) -> String {
    let escaped = s.replace('\\', "\\\\").replace('\'', "\\'");
    format!("'{escaped}'")
}

/// `browser_navigate`: load a URL and wait for the page.
pub struct BrowserNavigate {
    manager: Arc<BrowserManager>,
}

impl BrowserNavigate {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserNavigate {
    fn name(&self) -> &'static str {
        "browser_navigate"
    }

    fn description(&self) -> &'static str {
        "Open a URL in the browser and wait for the page to finish loading."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let url = arg_string(&args, "url")?;
            let browser = manager.get().await?;
            browser
                .navigate(&url, Duration::from_secs(30))
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            Ok(ToolOutput::text(format!("navigated to {url}")))
        })
    }
}

/// `browser_get_content`: visible text of the current page.
pub struct BrowserGetContent {
    manager: Arc<BrowserManager>,
}

impl BrowserGetContent {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserGetContent {
    fn name(&self) -> &'static str {
        "browser_get_content"
    }

    fn description(&self) -> &'static str {
        "Return the visible text of the current browser page (capped)."
    }

    fn parameters(&self) -> Value {
        json!({"type": "object", "properties": {}})
    }

    fn execute<'a>(
        &self,
        _args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let browser = manager.get().await?;
            let value = browser
                .evaluate("JSON.stringify(document.body.innerText || '')")
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let text = value
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let text = crate::utils::string_utils::ellipsize(&text, 8000);
            Ok(ToolOutput::text(text))
        })
    }
}

/// `browser_click`: click an element by CSS selector (or index).
pub struct BrowserClick {
    manager: Arc<BrowserManager>,
}

impl BrowserClick {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserClick {
    fn name(&self) -> &'static str {
        "browser_click"
    }

    fn description(&self) -> &'static str {
        "Click an element matching a CSS selector (uses JS .click())."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "selector": {"type": "string"}
            },
            "required": ["selector"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let selector = arg_string(&args, "selector")?;
            let browser = manager.get().await?;
            let script = format!(
                "(() => {{ const el = document.querySelector({sel}); \
                 if (!el) return 'no element'; el.click(); return 'clicked'; }})()",
                sel = js_string_literal(&selector)
            );
            let value = browser
                .evaluate(&script)
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let status = value
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or("?")
                .to_string();
            Ok(ToolOutput::text(format!("browser_click: {status}")))
        })
    }
}

/// `browser_type`: set an input's value (with input events).
pub struct BrowserType {
    manager: Arc<BrowserManager>,
}

impl BrowserType {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserType {
    fn name(&self) -> &'static str {
        "browser_type"
    }

    fn description(&self) -> &'static str {
        "Type text into an input matched by CSS selector."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"}
            },
            "required": ["selector", "text"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let selector = arg_string(&args, "selector")?;
            let text = arg_string(&args, "text")?;
            let browser = manager.get().await?;
            let script = format!(
                "(() => {{ const el = document.querySelector({sel}); \
                 if (!el) return 'no element'; \
                 el.value = {val}; \
                 el.dispatchEvent(new Event('input', {{bubbles:true}})); \
                 el.dispatchEvent(new Event('change', {{bubbles:true}})); \
                 return 'typed'; }})()",
                sel = js_string_literal(&selector),
                val = js_string_literal(&text)
            );
            let value = browser
                .evaluate(&script)
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let status = value
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or("?")
                .to_string();
            Ok(ToolOutput::text(format!("browser_type: {status}")))
        })
    }
}

/// `browser_scroll`: scroll by pixels or to a selector.
pub struct BrowserScroll {
    manager: Arc<BrowserManager>,
}

impl BrowserScroll {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserScroll {
    fn name(&self) -> &'static str {
        "browser_scroll"
    }

    fn description(&self) -> &'static str {
        "Scroll the page: pass 'down'/'up' (one viewport), a pixel amount, or a selector to scroll to."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "amount": {"type": "string"}
            },
            "required": ["amount"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let amount = arg_string(&args, "amount")?;
            let browser = manager.get().await?;
            let script = match amount.as_str() {
                "down" => String::from("window.scrollBy(0, window.innerHeight); 'scrolled'"),
                "up" => String::from("window.scrollBy(0, -window.innerHeight); 'scrolled'"),
                _ if amount.parse::<i64>().is_ok() => {
                    format!("window.scrollBy(0, {amount}); 'scrolled'")
                }
                _ => format!(
                    "(() => {{ const el = document.querySelector({sel}); \
                     if (!el) return 'no element'; el.scrollIntoView(); return 'scrolled'; }})()",
                    sel = js_string_literal(&amount)
                ),
            };
            let value = browser
                .evaluate(&script)
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let status = value
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or("?")
                .to_string();
            Ok(ToolOutput::text(format!("browser_scroll: {status}")))
        })
    }
}

/// `browser_wait_for_selector`: poll until an element exists.
pub struct BrowserWait {
    manager: Arc<BrowserManager>,
}

impl BrowserWait {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserWait {
    fn name(&self) -> &'static str {
        "browser_wait_for_selector"
    }

    fn description(&self) -> &'static str {
        "Wait until an element matching a CSS selector exists (up to 30s)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "selector": {"type": "string"}
            },
            "required": ["selector"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let selector = arg_string(&args, "selector")?;
            let browser = manager.get().await?;
            let deadline = tokio::time::Instant::now() + Duration::from_secs(30);
            loop {
                if tokio::time::Instant::now() >= deadline {
                    return Err(ToolError::Timeout(Duration::from_secs(30)));
                }
                let script = format!(
                    "Boolean(document.querySelector({sel}))",
                    sel = js_string_literal(&selector)
                );
                let value = browser
                    .evaluate(&script)
                    .await
                    .map_err(|e| ToolError::Execution(e.to_string()))?;
                if value.get("value").and_then(Value::as_bool).unwrap_or(false) {
                    return Ok(ToolOutput::text(format!("selector '{selector}' found")));
                }
                tokio::time::sleep(Duration::from_millis(200)).await;
            }
        })
    }
}

/// `browser_screenshot`: capture the page as a PNG (saved to the
/// workspace when `path` is given, base64-capped otherwise).
pub struct BrowserScreenshot {
    manager: Arc<BrowserManager>,
}

impl BrowserScreenshot {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserScreenshot {
    fn name(&self) -> &'static str {
        "browser_screenshot"
    }

    fn description(&self) -> &'static str {
        "Take a screenshot of the current page (PNG). With a path, saves it to the workspace."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Optional workspace path to save the PNG"}
            }
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let browser = manager.get().await?;
            let png = browser
                .screenshot()
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            if let Some(path) = arg_optional_string(&args, "path") {
                let resolved = ctx
                    .safety
                    .check_write(std::path::Path::new(&path))
                    .map_err(|e| ToolError::Safety(e.to_string()))?;
                let bytes = decode_png(&png)?;
                std::fs::write(&resolved, &bytes).map_err(|e| ToolError::Io {
                    path: resolved.clone(),
                    source: e,
                })?;
                Ok(ToolOutput::text(format!(
                    "screenshot saved to {} ({} bytes)",
                    resolved.display(),
                    bytes.len()
                )))
            } else {
                Ok(ToolOutput::text(format!(
                    "screenshot (base64, capped): {}",
                    crate::utils::string_utils::ellipsize(&png, 4000)
                )))
            }
        })
    }
}

/// `browser_run_script`: execute JS on the page.
pub struct BrowserRunScript {
    manager: Arc<BrowserManager>,
}

impl BrowserRunScript {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for BrowserRunScript {
    fn name(&self) -> &'static str {
        "browser_run_script"
    }

    fn description(&self) -> &'static str {
        "Run JavaScript on the current page and return the JSON result."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "script": {"type": "string"}
            },
            "required": ["script"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let script = arg_string(&args, "script")?;
            let browser = manager.get().await?;
            let value = browser
                .evaluate(&format!("JSON.stringify((() => {{{script}}})())"))
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let text = value
                .get("value")
                .and_then(Value::as_str)
                .unwrap_or("null")
                .to_string();
            Ok(ToolOutput::text(crate::utils::string_utils::ellipsize(
                &text, 8000,
            )))
        })
    }
}

/// `stealth_fetch`: fetch with desktop-chrome headers.
pub struct StealthFetch;

impl Tool for StealthFetch {
    fn name(&self) -> &'static str {
        "stealth_fetch"
    }

    fn description(&self) -> &'static str {
        "Fetch a URL with a desktop-chrome user agent (useful when a site blocks plain fetches)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            if !ctx.safety.allow_network {
                return Err(ToolError::Safety(String::from("network access disabled")));
            }
            let url = arg_string(&args, "url")?;
            let resp = reqwest::Client::new()
                .get(&url)
                .header("User-Agent", stealth::fetch_user_agent())
                .header(
                    "Accept",
                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                )
                .header("Accept-Language", "en-US,en;q=0.9")
                .send()
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let status = resp.status().as_u16();
            let text = resp
                .text()
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            Ok(ToolOutput::text(format!(
                "HTTP {status}\n{}",
                crate::utils::html::extract_text(&text, 8000)
            )))
        })
    }
}

/// `open_in_browser`: launch the browser at a URL (headless by default
/// unless `visible` is set).
pub struct OpenInBrowser {
    manager: Arc<BrowserManager>,
}

impl OpenInBrowser {
    /// Wraps the shared manager.
    pub fn new(manager: Arc<BrowserManager>) -> Self {
        Self { manager }
    }
}

impl Tool for OpenInBrowser {
    fn name(&self) -> &'static str {
        "open_in_browser"
    }

    fn description(&self) -> &'static str {
        "Open a URL in the browser (and navigate to it)."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        let manager = Arc::clone(&self.manager);
        Box::pin(async move {
            let url = arg_string(&args, "url")?;
            let browser = manager.get().await?;
            browser
                .navigate(&url, Duration::from_secs(30))
                .await
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            Ok(ToolOutput::text(format!("opened {url}")))
        })
    }
}

/// Re-export for the registry.
#[allow(unused)]
fn _arg_optional_u64_unused(_: &Value, _: &str) -> Option<u64> {
    arg_optional_u64(&Value::Null, "")
}

/// Decodes a base64 `PNG` payload.
fn decode_png(png: &str) -> std::result::Result<Vec<u8>, ToolError> {
    use base64::Engine as _;
    base64::engine::general_purpose::STANDARD
        .decode(png)
        .map_err(|e| ToolError::Execution(e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn js_string_literal_escapes_quotes() {
        assert_eq!(js_string_literal("a'b"), "'a\\'b'");
        assert_eq!(js_string_literal("plain"), "'plain'");
    }

    #[test]
    fn manager_starts_stopped() {
        let rt = tokio::runtime::Runtime::new().expect("rt");
        let manager = BrowserManager::new();
        rt.block_on(async {
            assert!(!manager.is_running().await);
            // close on a non-running manager is a no-op.
            manager.close().await;
        });
    }
}
