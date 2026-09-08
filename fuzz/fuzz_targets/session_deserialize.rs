#![no_main]

use echo_ai_core::agent::message::Message;
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| {
    let _ = serde_json::from_slice::<Vec<Message>>(data);
    let _ = serde_json::from_slice::<serde_json::Value>(data);
    if let Ok(s) = std::str::from_utf8(data) {
        let _ = serde_json::from_str::<Message>(s);
    }
});
