#![no_main]

use echo_ai_core::session::encryption::EncryptionKey;
use libfuzzer_sys::fuzz_target;
use std::sync::OnceLock;

static KEY: OnceLock<EncryptionKey> = OnceLock::new();

fn get_key() -> &'static EncryptionKey {
    KEY.get_or_init(|| {
        // SAFETY: Setting environment variable for fast scrypt in fuzz target
        unsafe {
            std::env::set_var("ECHO_AI_TEST_FAST_SCRYPT", "1");
        }
        let salt = [0x55u8; 16];
        let pepper = [0xAAu8; 32];
        EncryptionKey::derive("fuzz-password", &salt, &pepper).expect("derive fuzz key")
    })
}

fuzz_target!(|data: &[u8]| {
    let key = get_key();
    let _ = key.decrypt(data);
});
