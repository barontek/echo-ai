//! String helpers that aren't in `std` but show up everywhere in this
//! codebase: JSON escaping, ellipsis truncation, and a few guarded
//! splitting utilities. The C project's `string_utils.c` carried more,
//! but `std` covers trimming/splitting/prefix checks natively.
//!
//! Depends on: `std` only.

/// Escapes a string for embedding in a JSON string literal.
#[must_use]
pub fn json_escape(s: &str) -> String {
    use std::fmt::Write as _;
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

/// Truncates `s` to at most `max` chars, appending an ellipsis when it
/// was cut. `max` includes the ellipsis; `max < 4` returns the raw
/// prefix (the ellipsis cannot fit).
#[must_use]
pub fn ellipsize(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return String::from(s);
    }
    if max < 4 {
        return s.chars().take(max).collect();
    }
    let cut = max - 3;
    let mut out: String = s.chars().take(cut).collect();
    out.push_str("...");
    out
}

/// Case-insensitive containment check.
#[must_use]
pub fn contains_ignore_case(haystack: &str, needle: &str) -> bool {
    let h = haystack.to_lowercase();
    let n = needle.to_lowercase();
    h.contains(&n)
}

/// Splits on the *last* occurrence of `sep`, returning the two halves.
/// `None` when `sep` is absent (or empty, to stay unambiguous).
#[must_use]
pub fn rsplit_once(s: &str, sep: char) -> Option<(&str, &str)> {
    if sep == '\0' {
        return None;
    }
    let idx = s.rfind(sep)?;
    Some((&s[..idx], &s[idx + sep.len_utf8()..]))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn json_escape_handles_control_characters() {
        assert_eq!(json_escape("a\"b"), r#""a\"b""#);
        assert_eq!(json_escape("a\nb"), r#""a\nb""#);
        assert_eq!(json_escape("a\u{01}b"), r#""a\u0001b""#);
    }

    #[test]
    fn ellipsize_shortens_and_marks() {
        assert_eq!(ellipsize("hello", 10), "hello");
        assert_eq!(ellipsize("hello world", 8), "hello...");
        assert_eq!(ellipsize("hello world", 3), "hel");
    }

    #[test]
    fn rsplit_once_takes_the_last_separator() {
        assert_eq!(rsplit_once("a/b/c", '/'), Some(("a/b", "c")));
        assert_eq!(rsplit_once("abc", '/'), None);
        assert_eq!(rsplit_once("abc", '\0'), None);
    }
}
