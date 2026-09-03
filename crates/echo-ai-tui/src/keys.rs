//! Keymap model: key-string parsing and the leader-chord engine (the C
//! version's `tui_keys.c`).
//!
//! Keys are encoded as strings like `"ctrl+n"`, `"alt+x"`, `"enter"`,
//! `"char:q"` — parses to a normalized key, then matched against
//! bindings with optional leader prefixes.
//!
//! Depends on: `std` only.

/// A normalized key.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum Key {
    /// A character.
    Char(char),
    /// A named key (`enter`, `esc`, `tab`, `up`, ...).
    Named(String),
}

/// Parses a key-string (`"ctrl+n"`, `"alt+x"`, `"enter"`).
#[must_use]
pub fn parse_key(s: &str) -> Key {
    if let Some(name) = s.strip_prefix("char:") {
        return name
            .chars()
            .next()
            .map_or_else(|| Key::Named(String::from("none")), Key::Char);
    }
    let lower = s.to_ascii_lowercase();
    if lower.starts_with("ctrl+") {
        return lower
            .strip_prefix("ctrl+")
            .and_then(|c| c.chars().next())
            .map_or_else(
                || Key::Named(String::from("none")),
                |c| Key::Char(ctrl_char(c)),
            );
    }
    if lower.starts_with("alt+") {
        return lower
            .strip_prefix("alt+")
            .and_then(|c| c.chars().next())
            .map_or_else(
                || Key::Named(String::from("none")),
                |c| Key::Char(alt_char(c)),
            );
    }
    Key::Named(lower)
}

/// Maps a key to its crossterm-compatible control code (a-z become
/// control bytes).
fn ctrl_char(c: char) -> char {
    let c = c.to_ascii_lowercase();
    if c.is_ascii_lowercase() {
        ((c as u8) - b'a' + 1) as char
    } else {
        c
    }
}

/// Alt-modified keys are reported as the char with `\u{1b}` semantics;
/// in the model they map back to the bare char.
fn alt_char(c: char) -> char {
    c
}

/// The leader-chord engine.
#[derive(Debug, Default)]
pub struct Keymap {
    /// Bindings: key-string -> action.
    bindings: Vec<(Key, String)>,
    /// Leader key strings (e.g. `"ctrl+space"`).
    leaders: Vec<Key>,
    /// Whether we are mid-chord (waiting for the second key).
    pub in_chord: bool,
    /// The leader that started the chord.
    chord_leader: Option<Key>,
}

impl Keymap {
    /// A fresh keymap.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Binds a key-string to an action.
    pub fn bind(&mut self, key_str: &str, action: &str) {
        let key = parse_key(key_str);
        if action == "leader" {
            self.leaders.push(key);
        } else {
            self.bindings.push((key, String::from(action)));
        }
    }

    /// Feeds a raw key; returns the resolved action, or `None` when the
    /// key starts (or continues) a chord.
    #[must_use]
    pub fn feed(&mut self, key: &Key) -> Option<String> {
        if self.in_chord {
            self.in_chord = false;
            let leader = self.chord_leader.take();
            if leader.is_some() {
                return self
                    .bindings
                    .iter()
                    .find_map(|(k, a)| if *k == *key { Some(a.clone()) } else { None });
            }
            return None;
        }
        if self.leaders.contains(key) {
            self.in_chord = true;
            self.chord_leader = Some(key.clone());
            return None;
        }
        self.bindings
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, a)| a.clone())
    }

    /// Cancels a pending chord.
    pub fn cancel_chord(&mut self) {
        self.in_chord = false;
        self.chord_leader = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_common_key_strings() {
        assert_eq!(parse_key("enter"), Key::Named(String::from("enter")));
        assert_eq!(parse_key("ctrl+n"), Key::Char('\x0e'));
        assert_eq!(parse_key("char:q"), Key::Char('q'));
        assert_eq!(parse_key("CTRL+X"), Key::Char('\x18'));
    }

    #[test]
    fn leader_chord_resolves_second_key() {
        let mut km = Keymap::new();
        km.bind("ctrl+space", "leader");
        km.bind("ctrl+space", "open_palette");
        km.bind("n", "new_chat");
        // First leader press: chord starts.
        assert_eq!(km.feed(&parse_key("ctrl+space")), None);
        assert!(km.in_chord);
        // Second key resolves against the full binding table.
        assert_eq!(km.feed(&parse_key("n")), Some(String::from("new_chat")));
    }

    #[test]
    fn direct_bindings_resolve_without_chord() {
        let mut km = Keymap::new();
        km.bind("enter", "send");
        assert_eq!(km.feed(&parse_key("enter")), Some(String::from("send")));
    }

    #[test]
    fn cancel_chord_resets() {
        let mut km = Keymap::new();
        km.bind("ctrl+space", "leader");
        let _ = km.feed(&parse_key("ctrl+space"));
        km.cancel_chord();
        assert!(!km.in_chord);
        assert_eq!(km.feed(&Key::Char('n')), None);
    }
}
