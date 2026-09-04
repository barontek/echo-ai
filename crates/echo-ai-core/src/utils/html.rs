//! HTML-to-text extraction: readable text from raw HTML with
//! boilerplate skipping, entity decoding, and truncation.
//!
//! A deliberately compact single-module design (the original implementation split
//! this into seven files for length discipline; a tokenizer + writer
//! pair keeps the same behaviors without the file sprawl). The
//! tokenizer is a best-effort HTML scanner, not a spec-compliant parser
//! — enough for article-style pages, which is the tool's job.
//!
//! Depends on: `std` only.

use std::collections::HashMap;

/// Tags whose entire subtree is skipped (scripts, styles, chrome).
const SKIP_TAGS: &[&str] = &[
    "script", "style", "noscript", "template", "svg", "math", "iframe", "nav", "header", "footer",
    "form", "button", "select", "option", "dialog",
];

/// Tags that are invisible but affect block flow.
const BLOCK_TAGS: &[&str] = &[
    "p",
    "div",
    "section",
    "article",
    "main",
    "aside",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ul",
    "ol",
    "table",
    "tr",
    "blockquote",
    "pre",
    "br",
    "hr",
    "figure",
    "figcaption",
];

/// Named entities decoded by the extractor (common subset).
fn named_entities() -> HashMap<&'static str, &'static str> {
    let mut m = HashMap::new();
    for (name, ch) in [
        ("amp", "&"),
        ("lt", "<"),
        ("gt", ">"),
        ("quot", "\""),
        ("apos", "'"),
        ("nbsp", " "),
        ("copy", "©"),
        ("reg", "®"),
        ("trade", "™"),
        ("mdash", "—"),
        ("ndash", "–"),
        ("hellip", "…"),
        ("lsquo", "'"),
        ("rsquo", "'"),
        ("ldquo", "\""),
        ("rdquo", "\""),
        ("bull", "•"),
        ("middot", "·"),
        ("sect", "§"),
        ("para", "¶"),
        ("laquo", "«"),
        ("raquo", "»"),
        ("eacute", "é"),
        ("egrave", "è"),
        ("agrave", "à"),
        ("aacute", "á"),
        ("ccedil", "ç"),
        ("uuml", "ü"),
        ("ouml", "ö"),
        ("auml", "ä"),
    ] {
        m.insert(name, ch);
    }
    m
}

/// Extracts readable text from HTML.
///
/// * `html` — raw page bytes (lossy-decoded).
/// * `max_chars` — output cap; the result is cut at a word boundary.
#[must_use]
pub fn extract_text(html: &str, max_chars: usize) -> String {
    let entities = named_entities();
    let mut out = String::new();
    let mut skip_depth = 0usize;
    let mut pending_space = false;
    let mut truncated = false;
    let mut chars = html.char_indices().peekable();

    while let Some((idx, c)) = chars.next() {
        if c == '<' {
            // Determine if this is a tag (or a comment / doctype).
            if html[idx..].starts_with("<!--") {
                skip_until(&mut chars, "-->");
                continue;
            }
            if html[idx..].starts_with("<!") || html[idx..].starts_with("<?") {
                skip_until(&mut chars, ">");
                continue;
            }
            let (tag, closing, end) = parse_tag(html, idx);
            // Consume the whole tag from the main iterator so its
            // characters are not emitted as text.
            while let Some((next_idx, _)) = chars.peek() {
                if *next_idx < end {
                    chars.next();
                } else {
                    break;
                }
            }
            let name = tag.to_ascii_lowercase();
            if closing {
                if let Some(pos) = SKIP_TAGS.iter().position(|s| *s == name) {
                    skip_depth = skip_depth.saturating_sub(1);
                    let _ = pos;
                }
                continue;
            }
            if SKIP_TAGS.contains(&name.as_str()) {
                skip_depth += 1;
                continue;
            }
            if BLOCK_TAGS.contains(&name.as_str()) {
                pending_space = true;
            }
            continue;
        }
        if skip_depth > 0 {
            continue;
        }
        if c.is_whitespace() {
            pending_space = true;
            continue;
        }
        if pending_space && !out.is_empty() && !out.ends_with('\n') {
            out.push(' ');
        }
        pending_space = false;
        if c == '&'
            && let Some(decoded) = decode_entity(html, idx, &entities)
        {
            out.push_str(&decoded);
            // Advance past the entity.
            let end = idx + 1 + entity_len(html, idx);
            while let Some((next_idx, _)) = chars.peek() {
                if *next_idx < end {
                    chars.next();
                } else {
                    break;
                }
            }
            continue;
        }
        out.push(c);
        if out.len() >= max_chars {
            truncated = true;
            break;
        }
    }

    clean_whitespace(&mut out);
    if truncated || out.len() > max_chars {
        truncate(&mut out, max_chars);
        out.push_str("\n...[truncated]");
    }
    out
}

/// Skips input until `marker` appears (consuming it).
fn skip_until<I>(chars: &mut std::iter::Peekable<I>, marker: &str)
where
    I: Iterator<Item = (usize, char)>,
{
    // Re-accumulate the tail text and scan for the marker.
    let mut tail = String::new();
    let mut prefix = String::new();
    for (_, c) in chars.by_ref() {
        tail.push(c);
        prefix.push(c);
        if prefix.len() > marker.len() {
            prefix.remove(0);
        }
        if prefix == marker {
            return;
        }
        if tail.len() > 4096 {
            return; // runaway "comment": bail defensively
        }
    }
}

/// Parses a tag starting at `<`; returns (name, `is_closing`, end index
/// of the tag's `>`).
fn parse_tag(html: &str, idx: usize) -> (String, bool, usize) {
    let rest = &html[idx + 1..];
    let mut name = String::new();
    let mut closing = false;
    let mut consumed = 0usize;
    for (offset, c) in rest.char_indices() {
        match c {
            '/' if name.is_empty() => closing = true,
            c if c.is_ascii_alphanumeric() => name.push(c),
            '>' => {
                consumed = offset + 1;
                break;
            }
            _ => break,
        }
    }
    let end = if consumed > 0 {
        idx + 1 + consumed
    } else {
        // Unclosed tag: consume everything up to the next `<`.
        rest.find('<').map_or(html.len(), |p| idx + 1 + p)
    };
    (name, closing, end)
}

/// Decodes one entity at `&`.
fn decode_entity(html: &str, idx: usize, entities: &HashMap<&str, &str>) -> Option<String> {
    let rest = &html[idx + 1..];
    if let Some(tail) = rest.strip_prefix('#') {
        let digits: String = tail
            .chars()
            .take_while(|c| c.is_ascii_digit() || *c == 'x' || *c == 'X')
            .collect();
        let hex = digits.starts_with('x') || digits.starts_with('X');
        let num_part = if hex { &digits[1..] } else { &digits[..] };
        if num_part.is_empty() {
            return None;
        }
        let code = if hex {
            u32::from_str_radix(num_part, 16).ok()?
        } else {
            num_part.parse::<u32>().ok()?
        };
        return char::from_u32(code).map(|c| c.to_string());
    }
    let name: String = rest
        .chars()
        .take_while(char::is_ascii_alphanumeric)
        .collect();
    entities.get(name.as_str()).copied().map(String::from)
}

/// Length of the entity at `&` (name + `;`), for cursor advancing.
fn entity_len(html: &str, idx: usize) -> usize {
    let rest = &html[idx + 1..];
    if let Some(semi) = rest.find(';') {
        return semi + 1;
    }
    rest.len()
}

/// Collapses runs of whitespace and trims trailing blanks per line.
fn clean_whitespace(out: &mut String) {
    let mut cleaned = String::with_capacity(out.len());
    let mut prev_space = false;
    for c in out.chars() {
        if c == '\n' {
            if !cleaned.ends_with('\n') {
                cleaned.push('\n');
            }
            prev_space = false;
        } else if c.is_whitespace() {
            if !prev_space && !cleaned.ends_with('\n') {
                cleaned.push(' ');
            }
            prev_space = true;
        } else {
            cleaned.push(c);
            prev_space = false;
        }
    }
    *out = cleaned;
}

/// Cuts at a word boundary at or before `max`.
fn truncate(out: &mut String, max: usize) {
    if out.len() <= max {
        return;
    }
    let mut cut = max;
    let bytes = out.as_bytes();
    while cut > 0 && !bytes[cut - 1].is_ascii_whitespace() {
        cut -= 1;
    }
    if cut == 0 {
        cut = max;
    }
    out.truncate(cut);
    out.push_str("\n...[truncated]");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_paragraph_text() {
        let html = "<html><body><h1>Title</h1><p>Hello <b>world</b>!</p></body></html>";
        let text = extract_text(html, 10_000);
        assert!(text.contains("Title"));
        assert!(text.contains("Hello world!"));
    }

    #[test]
    fn skips_scripts_and_styles() {
        let html = "<p>visible</p><script>var x = 'hidden';</script><style>.x{}</style><p>also visible</p>";
        let text = extract_text(html, 10_000);
        assert!(text.contains("visible"));
        assert!(!text.contains("hidden"));
        assert!(!text.contains("var x"));
    }

    #[test]
    fn decodes_entities() {
        let html = "<p>a &amp; b &lt; c &copy; d &#65; &#x42;</p>";
        let text = extract_text(html, 10_000);
        assert!(text.contains("a & b < c © d A B"), "got: {text}");
    }

    #[test]
    fn comments_and_doctypes_are_skipped() {
        let html = "<!DOCTYPE html><!-- comment --><p>text</p>";
        let text = extract_text(html, 10_000);
        assert!(!text.contains("DOCTYPE"));
        assert!(!text.contains("comment"));
        assert!(text.contains("text"));
    }

    #[test]
    fn truncates_at_word_boundary() {
        let html = "<p>one two three four five</p>";
        let text = extract_text(html, 10);
        assert!(text.contains("..."));
    }

    #[test]
    fn whitespace_is_collapsed() {
        let html = "<p>a\n   \n  b</p><p>c</p>";
        let text = extract_text(html, 10_000);
        let normalized = text.split_whitespace().collect::<Vec<_>>().join(" ");
        assert_eq!(normalized, "a b c");
    }
}
