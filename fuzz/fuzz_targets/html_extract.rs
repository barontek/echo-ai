#![no_main]

use echo_ai_core::utils::html::extract_text;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    if let Ok(s) = std::str::from_utf8(data) {
        let _ = extract_text(s, 1000);
    }
});
