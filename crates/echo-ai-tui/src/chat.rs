//! Scrollback model: greedy word-wrapped chat lines with block-append
//! commit .
//!
//! Pure and terminal-independent.
//!
//! Depends on: `std` only.

/// One chat block (a message or a tool line).
#[derive(Debug, Clone, Default)]
pub struct Block {
    /// Sender role for coloring.
    pub role: String,
    /// Raw text (unwrapped).
    pub text: String,
}

/// The scrollback buffer.
#[derive(Debug, Clone, Default)]
pub struct ChatBuffer {
    /// Blocks in order.
    pub blocks: Vec<Block>,
}

impl ChatBuffer {
    /// A fresh buffer.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Appends a block (a single atomic commit).
    pub fn push(&mut self, block: Block) {
        self.blocks.push(block);
    }

    /// Appends text to the last block of `role` (streaming).
    pub fn append_to_last(&mut self, role: &str, text: &str) {
        if let Some(last) = self.blocks.last_mut()
            && last.role == role
        {
            last.text.push_str(text);
            return;
        }
        self.push(Block {
            role: String::from(role),
            text: String::from(text),
        });
    }

    /// Truncates the buffer to `keep` blocks (undo/regenerate support).
    pub fn truncate(&mut self, keep: usize) {
        self.blocks.truncate(keep);
    }

    /// Removes the last block (regenerate drops the assistant answer).
    pub fn pop_last(&mut self) {
        self.blocks.pop();
    }

    /// Number of blocks.
    #[must_use]
    pub fn len(&self) -> usize {
        self.blocks.len()
    }

    /// Whether the buffer is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.blocks.is_empty()
    }

    /// Lays out the buffer into viewport-width wrapped display lines.
    /// Returns `(lines, scroll_offset)` where the offset is the index
    /// into `lines` to keep the bottom anchored.
    #[must_use]
    pub fn layout(&self, width: usize, height: usize) -> (Vec<String>, usize) {
        let mut lines: Vec<String> = Vec::new();
        for block in &self.blocks {
            for paragraph in block.text.split('\n') {
                wrap_into(&mut lines, paragraph, width.max(1));
            }
        }
        let total = lines.len();
        let offset = total.saturating_sub(height.max(1));
        (lines, offset)
    }
}

/// Greedy word wrap of a single paragraph into `out`.
fn wrap_into(out: &mut Vec<String>, paragraph: &str, width: usize) {
    if paragraph.is_empty() {
        out.push(String::new());
        return;
    }
    let mut line = String::new();
    for word in paragraph.split_whitespace() {
        if word.len() > width {
            // Oversized word: flush the line, then hard-split.
            if !line.is_empty() {
                out.push(std::mem::take(&mut line));
            }
            let mut rest = word;
            while rest.len() > width {
                let (head, tail) = rest.split_at(width);
                out.push(String::from(head));
                rest = tail;
            }
            line.push_str(rest);
            continue;
        }
        if line.len() + 1 + word.len() > width && !line.is_empty() {
            out.push(std::mem::take(&mut line));
        }
        if !line.is_empty() {
            line.push(' ');
        }
        line.push_str(word);
    }
    out.push(line);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn greedy_wrap_breaks_at_width() {
        let mut lines = Vec::new();
        wrap_into(&mut lines, "one two three four", 8);
        assert_eq!(lines, vec!["one two", "three", "four"]);
    }

    #[test]
    fn oversized_word_hard_splits() {
        let mut lines = Vec::new();
        wrap_into(&mut lines, "supercalifragilistic", 5);
        assert_eq!(lines, vec!["super", "calif", "ragil", "istic"]);
    }

    #[test]
    fn streaming_append_joins_same_role() {
        let mut buf = ChatBuffer::new();
        buf.append_to_last("assistant", "hel");
        buf.append_to_last("assistant", "lo");
        buf.append_to_last("tool", "done");
        assert_eq!(buf.len(), 2);
        assert_eq!(buf.blocks[0].text, "hello");
    }

    #[test]
    fn layout_anchors_bottom() {
        let mut buf = ChatBuffer::new();
        for i in 0..10 {
            buf.push(Block {
                role: String::from("user"),
                text: format!("line {i}"),
            });
        }
        let (lines, offset) = buf.layout(40, 5);
        assert_eq!(lines.len(), 10);
        assert_eq!(offset, 5, "show the last 5 lines");
    }
}
