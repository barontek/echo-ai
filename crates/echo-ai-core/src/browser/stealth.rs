//! Browser stealth: launch flags and `CDP` scripts that make the
//! automation less fingerprintable (.
//!
//! the original implementation's stealth header logic reduces to two pieces here: a
//! curated flag set and one `Page.addScriptToEvaluateOnNewDocument`
//! script that neutralizes the `navigator.webdriver` signal. `CDP`
//! itself is not detectable from page JS (it is a protocol, not a
//! page-visible artifact), so the rest of the C list is dropped by
//! design.
//!
//! Depends on: `std` only.

/// A user-agent for the browser (Chrome-compatible, desktop).
#[must_use]
pub fn default_user_agent() -> String {
    String::from(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) \
         Chrome/126.0.0.0 Safari/537.36",
    )
}

/// Extra launch flags beyond the `CDP`-required ones.
#[must_use]
pub fn stealth_flags() -> Vec<String> {
    vec![
        String::from("--disable-blink-features=AutomationControlled"),
        String::from("--disable-background-networking"),
        String::from("--no-first-run"),
        String::from("--no-default-browser-check"),
        String::from("--window-size=1280,900"),
        String::from("--start-maximized"),
    ]
}

/// The webdriver-spoof script installed for every new document.
#[must_use]
pub fn webdriver_spoof() -> String {
    String::from(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); \
         window.chrome = window.chrome || { runtime: {} };",
    )
}

/// A desktop-chrome request `User-Agent` for plain fetches (used by
/// `stealth_fetch`).
#[must_use]
pub fn fetch_user_agent() -> String {
    default_user_agent()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stealth_flags_are_stable_and_ordered() {
        let flags = stealth_flags();
        assert!(flags.contains(&String::from(
            "--disable-blink-features=AutomationControlled"
        )));
        // No duplicates.
        let mut sorted = flags.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), flags.len());
    }

    #[test]
    fn webdriver_spoof_is_valid_js() {
        let script = webdriver_spoof();
        assert!(script.contains("navigator"));
        assert!(script.contains("webdriver"));
    }

    #[test]
    fn user_agent_is_chrome_shaped() {
        let ua = default_user_agent();
        assert!(ua.contains("Chrome/"));
        assert!(ua.contains("Safari/"));
    }
}
