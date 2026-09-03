//! File undo/redo: a fixed-capacity snapshot stack (64 entries, one per
//! edited file), captured *before* writes so `undo` can restore them.
//!
//! The risky path is `undo`/`redo`: the snapshot is popped before the
//! file write, so a failed write must push it back (nothing lost). That
//! rollback is fault-injection tested. `track` uses `try_reserve` and
//! returns `Err` without mutating the stack on allocation failure —
//! with the capacity cap at 64 this is defense in depth, not a hot path.
//!
//! Depends on: crate `error`.

use std::path::PathBuf;

use crate::error::{Error, Result};

/// Maximum undo/redo entries (the C version's `CT_MAX_STACK`).
pub const MAX_STACK: usize = 64;

/// A captured file state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileSnapshot {
    /// Absolute or workspace-relative path of the file.
    pub path: PathBuf,
    /// Exact bytes captured before the write.
    pub contents: Vec<u8>,
}

impl FileSnapshot {
    /// Captures the current on-disk state of `path`.
    ///
    /// # Errors
    /// `Error::Io` when the file cannot be read.
    pub fn capture(path: impl Into<PathBuf>) -> Result<Self> {
        let path = path.into();
        let contents = std::fs::read(&path).map_err(|e| Error::Io {
            path: path.clone(),
            source: e,
        })?;
        Ok(Self { path, contents })
    }
}

/// The undo/redo stacks.
#[derive(Debug, Default)]
pub struct ChangeTracker {
    undo: Vec<FileSnapshot>,
    redo: Vec<FileSnapshot>,
}

impl ChangeTracker {
    /// An empty tracker.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Records a snapshot as the latest undo point, dropping the oldest
    /// entry when the stack is at capacity. Any redo history is cleared
    /// (a new edit invalidates it).
    ///
    /// # Errors
    /// `Error::Invalid` when the allocation for the new entry fails
    /// (the stack is left unmodified — nothing is lost).
    pub fn track(&mut self, snapshot: FileSnapshot) -> Result<()> {
        self.redo.clear();
        self.undo
            .try_reserve(1)
            .map_err(|_| Error::Invalid(String::from("undo stack allocation failed")))?;
        self.undo.push(snapshot);
        if self.undo.len() > MAX_STACK {
            self.undo.remove(0);
        }
        Ok(())
    }

    /// Restores the most recent snapshot. On success the pre-undo state
    /// becomes the redo point. On write failure the snapshot is pushed
    /// back onto the undo stack (nothing is lost).
    ///
    /// # Errors
    /// `Error::Io` when the restore write fails; `Error::Invalid` when
    /// there is nothing to undo.
    pub fn undo(&mut self) -> Result<FileSnapshot> {
        let (undo, redo) = (&mut self.undo, &mut self.redo);
        Self::pop_and_restore(undo, redo)
    }

    /// Re-applies the most recently undone state (mirror of `undo`).
    ///
    /// # Errors
    /// `Error::Io` on write failure; `Error::Invalid` when there is
    /// nothing to redo.
    pub fn redo(&mut self) -> Result<FileSnapshot> {
        let (undo, redo) = (&mut self.redo, &mut self.undo);
        Self::pop_and_restore(undo, redo)
    }

    /// Whether an undo is available.
    #[must_use]
    pub fn can_undo(&self) -> bool {
        !self.undo.is_empty()
    }

    /// Whether a redo is available.
    #[must_use]
    pub fn can_redo(&self) -> bool {
        !self.redo.is_empty()
    }

    /// Number of undo entries (test/diagnostic use).
    #[must_use]
    pub fn undo_len(&self) -> usize {
        self.undo.len()
    }

    /// Number of redo entries (test/diagnostic use).
    #[must_use]
    pub fn redo_len(&self) -> usize {
        self.redo.len()
    }

    fn pop_and_restore(
        from: &mut Vec<FileSnapshot>,
        to: &mut Vec<FileSnapshot>,
    ) -> Result<FileSnapshot> {
        let snapshot = from
            .pop()
            .ok_or_else(|| Error::Invalid(String::from("nothing to restore")))?;
        let current = FileSnapshot::capture(&snapshot.path);
        match std::fs::write(&snapshot.path, &snapshot.contents) {
            Ok(()) => {
                if let Ok(current) = current {
                    to.push(current);
                }
                Ok(snapshot)
            }
            Err(e) => {
                // Roll the popped entry back: a failed restore must not
                // consume the undo point.
                from.push(snapshot);
                let path = from.last().map_or_else(PathBuf::new, |s| s.path.clone());
                Err(Error::Io { path, source: e })
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_file(tag: &str, contents: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!("echo-ct-{tag}-{}.txt", std::process::id()));
        std::fs::write(&path, contents).expect("write fixture");
        path
    }

    #[test]
    fn track_undo_redo_roundtrip() {
        let path = temp_file("roundtrip", "v1");
        let mut ct = ChangeTracker::new();
        ct.track(FileSnapshot::capture(&path).expect("capture"))
            .expect("track");
        std::fs::write(&path, "v2").expect("modify");

        let undone = ct.undo().expect("undo");
        assert_eq!(undone.contents, b"v1");
        assert_eq!(std::fs::read_to_string(&path).expect("read"), "v1");
        assert!(ct.can_redo());

        let redone = ct.redo().expect("redo");
        assert_eq!(redone.contents, b"v2");
        assert_eq!(std::fs::read_to_string(&path).expect("read"), "v2");
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn new_track_clears_redo_history() {
        let path = temp_file("clearredo", "v1");
        let mut ct = ChangeTracker::new();
        ct.track(FileSnapshot::capture(&path).expect("capture"))
            .expect("track");
        std::fs::write(&path, "v2").expect("modify");
        ct.undo().expect("undo");
        assert!(ct.can_redo());
        // A new edit after undo invalidates the redo history.
        ct.track(FileSnapshot::capture(&path).expect("capture"))
            .expect("track");
        assert!(!ct.can_redo());
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn capacity_keeps_newest_64() {
        let path = temp_file("cap", "x");
        let mut ct = ChangeTracker::new();
        for i in 0..(MAX_STACK + 5) {
            std::fs::write(&path, format!("v{i}")).expect("write");
            ct.track(FileSnapshot::capture(&path).expect("capture"))
                .expect("track");
        }
        assert_eq!(ct.undo_len(), MAX_STACK);
        // The oldest five entries were dropped.
        std::fs::write(&path, "final").expect("write");
        let newest = ct.undo().expect("undo");
        assert_eq!(
            newest.contents, b"v68",
            "oldest entries dropped, newest kept"
        );
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn failed_restore_rolls_back_the_undo_stack() {
        // Capture a real file, then make its path unwritable by
        // replacing it with a directory.
        let dir = std::env::temp_dir().join(format!("echo-ct-fail-{}", std::process::id()));
        let path = dir.join("file.txt");
        std::fs::create_dir_all(&dir).expect("dir");
        std::fs::write(&path, "v1").expect("write");
        let mut ct = ChangeTracker::new();
        ct.track(FileSnapshot::capture(&path).expect("capture"))
            .expect("track");
        std::fs::write(&path, "v2").expect("modify");
        std::fs::remove_file(&path).expect("remove");
        std::fs::create_dir(&path).expect("replace file with dir");

        let err = ct.undo().expect_err("write to a directory must fail");
        assert!(matches!(err, Error::Io { .. }));
        // The undo point must survive the failed restore.
        assert!(ct.can_undo());
        assert_eq!(ct.undo_len(), 1);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn empty_stacks_error_cleanly() {
        let mut ct = ChangeTracker::new();
        assert!(ct.undo().is_err());
        assert!(ct.redo().is_err());
    }
}
