//! Modal dialog state machine: password, ask-user, approval, and
//! confirm-quit (the C version's `tui_dialogs.c`, model only).
//!
//! Depends on: `std` only.

use crate::input::LineEditor;

/// The active dialog.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Dialog {
    /// Password prompt (setup/unlock). Input is masked.
    Password {
        /// Prompt title.
        title: String,
    },
    /// A question from the agent (`ask_user` or approval).
    Ask {
        /// Prompt text.
        prompt: String,
        /// `request_id` to answer.
        request_id: String,
        /// Whether this is an approval (answer must be yes/no).
        is_approval: bool,
    },
    /// Confirm quitting.
    ConfirmQuit,
    /// Model picker.
    Pick(String),
}

/// Dialog result sent back to the caller.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DialogResult {
    /// The text entered.
    Text(String),
    /// Confirmed (`yes`/approve).
    Confirmed,
    /// Cancelled.
    Cancelled,
}

/// A dialog in progress.
#[derive(Debug)]
pub struct DialogState {
    /// The dialog kind.
    pub kind: Dialog,
    /// Input editor for free-text dialogs.
    pub editor: LineEditor,
    /// Pending result.
    pub result: Option<DialogResult>,
}

impl DialogState {
    /// Opens a dialog.
    #[must_use]
    pub fn open(kind: Dialog) -> Self {
        Self {
            kind,
            editor: LineEditor::new(),
            result: None,
        }
    }

    /// The prompt title for rendering.
    #[must_use]
    pub fn title(&self) -> &str {
        match &self.kind {
            Dialog::Password { title } => title,
            Dialog::Ask { .. } => "Question",
            Dialog::ConfirmQuit => "Quit",
            Dialog::Pick(_) => "Pick",
        }
    }

    /// The prompt body for rendering.
    #[must_use]
    pub fn body(&self) -> String {
        match &self.kind {
            Dialog::Ask { prompt, .. } => prompt.clone(),
            Dialog::ConfirmQuit => String::from("Discard the current conversation?"),
            _ => String::new(),
        }
    }

    /// Handles a key: `enter` commits, `esc` cancels, `y`/`n` confirm
    /// (approval dialogs), anything else edits.
    #[must_use]
    pub fn handle_key(&mut self, key: &crate::keys::Key) -> Option<DialogResult> {
        match key {
            crate::keys::Key::Named(name) if name == "enter" => Some(self.commit()),
            crate::keys::Key::Named(name) if name == "esc" => {
                self.result = Some(DialogResult::Cancelled);
                Some(DialogResult::Cancelled)
            }
            crate::keys::Key::Char(c) if *c == '\r' || *c == '\n' => Some(self.commit()),
            crate::keys::Key::Char(c) if self.is_approval() && (*c == 'y' || *c == 'Y') => {
                self.result = Some(DialogResult::Confirmed);
                Some(DialogResult::Confirmed)
            }
            crate::keys::Key::Char(c) if self.is_approval() && (*c == 'n' || *c == 'N') => {
                self.result = Some(DialogResult::Cancelled);
                Some(DialogResult::Cancelled)
            }
            crate::keys::Key::Char('\u{7f}') => {
                self.editor.backspace();
                None
            }
            crate::keys::Key::Char(c) => {
                self.editor.insert(&c.to_string());
                None
            }
            crate::keys::Key::Named(_) => None,
        }
    }

    fn is_approval(&self) -> bool {
        matches!(
            &self.kind,
            Dialog::Ask {
                is_approval: true,
                ..
            }
        )
    }

    fn commit(&mut self) -> DialogResult {
        let result = match &self.kind {
            Dialog::Password { .. } | Dialog::Ask { .. } => {
                DialogResult::Text(std::mem::take(&mut self.editor.buffer))
            }
            Dialog::ConfirmQuit | Dialog::Pick(_) => DialogResult::Confirmed,
        };
        self.result = Some(result.clone());
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn password_commits_text() {
        let mut d = DialogState::open(Dialog::Password {
            title: String::from("Unlock"),
        });
        d.editor.insert("secret");
        assert_eq!(
            d.handle_key(&crate::keys::Key::Named(String::from("enter"))),
            Some(DialogResult::Text(String::from("secret")))
        );
    }

    #[test]
    fn approval_accepts_y() {
        let mut d = DialogState::open(Dialog::Ask {
            prompt: String::from("Approve?"),
            request_id: String::from("r1"),
            is_approval: true,
        });
        assert_eq!(
            d.handle_key(&crate::keys::Key::Char('y')),
            Some(DialogResult::Confirmed)
        );
    }

    #[test]
    fn esc_cancels() {
        let mut d = DialogState::open(Dialog::ConfirmQuit);
        assert_eq!(
            d.handle_key(&crate::keys::Key::Named(String::from("esc"))),
            Some(DialogResult::Cancelled)
        );
    }
}
