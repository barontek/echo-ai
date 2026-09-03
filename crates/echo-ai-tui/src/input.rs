//! Line editor model: byte-based cursor with codepoint-atomic deletion
//! and history (the C version's `tui_input.c`).
//!
//! Pure and terminal-independent — tests drive it directly.
//!
//! Depends on: `std` only.

/// The line editor state.
#[derive(Debug, Clone, Default)]
pub struct LineEditor {
    /// Current buffer.
    pub buffer: String,
    /// Byte offset of the cursor (always on a char boundary).
    pub cursor: usize,
    /// History of committed lines (most recent last).
    history: Vec<String>,
    /// Index into `history` during recall (`None` = editing fresh).
    history_idx: Option<usize>,
}

impl LineEditor {
    /// A fresh editor.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Inserts text at the cursor.
    pub fn insert(&mut self, text: &str) {
        if self.buffer.is_char_boundary(self.cursor) {
            self.buffer.insert_str(self.cursor, text);
            self.cursor += text.len();
        } else {
            self.buffer.push_str(text);
            self.cursor = self.buffer.len();
        }
    }

    /// Deletes the codepoint before the cursor (atomic: never leaves a
    /// broken `char`).
    pub fn backspace(&mut self) {
        if self.cursor == 0 {
            return;
        }
        // Walk back one full codepoint from the cursor: the byte before
        // the cursor may be a continuation byte, so step until a char
        // boundary is found.
        let mut start = self.cursor - 1;
        while !self.buffer.is_char_boundary(start) {
            start -= 1;
        }
        self.buffer.replace_range(start..self.cursor, "");
        self.cursor = start;
    }

    /// Deletes the codepoint at the cursor.
    pub fn delete(&mut self) {
        if self.cursor >= self.buffer.len() {
            return;
        }
        let mut end = self.cursor + 1;
        while end < self.buffer.len() && !self.buffer.is_char_boundary(end) {
            end += 1;
        }
        self.buffer.replace_range(self.cursor..end, "");
    }

    /// Moves the cursor left/right by one codepoint.
    pub fn move_cursor(&mut self, delta: isize) {
        let pos = if delta < 0 {
            self.previous_boundary()
        } else {
            self.next_boundary()
        };
        self.cursor = pos;
    }

    /// Moves to the start/end.
    pub fn home(&mut self) {
        self.cursor = 0;
    }

    /// Moves to the end.
    pub fn end(&mut self) {
        self.cursor = self.buffer.len();
    }

    /// Commits the current line to history and clears the buffer.
    pub fn commit(&mut self) {
        if !self.buffer.is_empty() {
            self.history.push(self.buffer.clone());
        }
        self.buffer.clear();
        self.cursor = 0;
        self.history_idx = None;
    }

    /// Recalls history (older or newer); `-1` = older.
    pub fn recall(&mut self, dir: isize) {
        if self.history.is_empty() {
            return;
        }
        let idx = match self.history_idx {
            Some(i) => {
                if dir < 0 {
                    i.saturating_sub(1)
                } else {
                    (i + 1).min(self.history.len() - 1)
                }
            }
            None => {
                if dir < 0 {
                    self.history.len() - 1
                } else {
                    0
                }
            }
        };
        self.buffer = self.history[idx].clone();
        self.cursor = self.buffer.len();
        self.history_idx = Some(idx);
    }

    /// Whether the buffer is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.buffer.is_empty()
    }

    fn previous_boundary(&self) -> usize {
        let mut pos = self.cursor;
        while pos > 0 && !self.buffer.is_char_boundary(pos) {
            pos -= 1;
        }
        if pos > 0 { pos - 1 } else { 0 }
    }

    fn next_boundary(&self) -> usize {
        let len = self.buffer.len();
        if self.cursor >= len {
            return len;
        }
        let mut pos = self.cursor + 1;
        while pos < len && !self.buffer.is_char_boundary(pos) {
            pos += 1;
        }
        pos
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn insert_and_backspace_are_codepoint_safe() {
        let mut ed = LineEditor::new();
        ed.insert("héllo");
        assert_eq!(ed.buffer, "héllo");
        assert_eq!(ed.cursor, 6, "é is 2 bytes");
        ed.backspace();
        assert_eq!(ed.buffer, "héll");
        assert!(ed.buffer.is_char_boundary(ed.cursor));
    }

    #[test]
    fn delete_removes_char_at_cursor() {
        let mut ed = LineEditor::new();
        ed.insert("abc");
        ed.move_cursor(-1);
        // Cursor is now on 'c' (index 2); delete removes it.
        ed.delete();
        assert_eq!(ed.buffer, "ab");
        assert_eq!(ed.cursor, 2);
    }

    #[test]
    fn cursor_stays_in_bounds() {
        let mut ed = LineEditor::new();
        ed.insert("abc");
        ed.home();
        ed.move_cursor(-5);
        assert_eq!(ed.cursor, 0);
        ed.end();
        ed.move_cursor(5);
        assert_eq!(ed.cursor, 3);
    }

    #[test]
    fn commit_and_recall_history() {
        let mut ed = LineEditor::new();
        ed.insert("first");
        ed.commit();
        ed.insert("second");
        ed.commit();
        ed.recall(-1);
        assert_eq!(ed.buffer, "second");
        ed.recall(-1);
        assert_eq!(ed.buffer, "first");
        ed.recall(1);
        assert_eq!(ed.buffer, "second");
        // Recall keeps the buffer editable.
        ed.insert("!");
        assert_eq!(ed.buffer, "second!");
    }
}
