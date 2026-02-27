"""Personal notes tool for managing markdown notes in a dedicated directory."""

import os
from pathlib import Path
from typing import Any

from . import Tool, ToolResult


class PersonalNotesTool(Tool):
    """Manage personal notes in a dedicated directory."""

    def __init__(self, notes_dir: str | Path | None = None):
        super().__init__(
            name="notes",
            description="Manage personal notes. Create, read, append to, or search markdown notes in your personal notes folder.",
        )
        
        if notes_dir is None:
            self.notes_dir = Path.home() / "personal_notes"
        else:
            self.notes_dir = Path(notes_dir)
        
        self.notes_dir.mkdir(parents=True, exist_ok=True)

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action: create_note, read_note, append_to_note, search_notes, list_notes",
                    "enum": ["create_note", "read_note", "append_to_note", "search_notes", "list_notes"],
                },
                "filename": {
                    "type": "string",
                    "description": "Filename (without .md extension) for the note",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write or append",
                },
                "query": {
                    "type": "string",
                    "description": "Search query for searching notes",
                },
            },
            "required": ["action"],
        }

    def _get_note_path(self, filename: str) -> Path:
        """Get full path for a note file."""
        # Ensure no directory traversal
        safe_name = os.path.basename(filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        return self.notes_dir / safe_name

    async def execute(self, action: str, filename: str = "", content: str = "", query: str = "", **kwargs) -> ToolResult:
        """Execute notes action."""
        if action == "create_note":
            return await self._create_note(filename, content)
        elif action == "read_note":
            return await self._read_note(filename)
        elif action == "append_to_note":
            return await self._append_to_note(filename, content)
        elif action == "search_notes":
            return await self._search_notes(query)
        elif action == "list_notes":
            return await self._list_notes()
        else:
            return ToolResult(error=f"Unknown action: {action}")

    async def _create_note(self, filename: str, content: str) -> ToolResult:
        """Create a new note."""
        try:
            path = self._get_note_path(filename)
            if path.exists():
                return ToolResult(error=f"Note '{filename}' already exists. Use append_to_note instead.")
            
            path.write_text(content)
            return ToolResult(content=f"Created note: {filename}.md")
        except Exception as e:
            return ToolResult(error=f"Failed to create note: {str(e)}")

    async def _read_note(self, filename: str) -> ToolResult:
        """Read a note."""
        try:
            path = self._get_note_path(filename)
            if not path.exists():
                return ToolResult(error=f"Note '{filename}' not found.")
            
            content = path.read_text()
            return ToolResult(content=f"# {filename}\n\n{content}")
        except Exception as e:
            return ToolResult(error=f"Failed to read note: {str(e)}")

    async def _append_to_note(self, filename: str, content: str) -> ToolResult:
        """Append to a note."""
        try:
            path = self._get_note_path(filename)
            
            # Create with content if doesn't exist
            if not path.exists():
                path.write_text(content)
                return ToolResult(content=f"Created and added to note: {filename}.md")
            
            # Append
            existing = path.read_text()
            new_content = existing + "\n" + content
            path.write_text(new_content)
            return ToolResult(content=f"Appended to note: {filename}.md")
        except Exception as e:
            return ToolResult(error=f"Failed to append: {str(e)}")

    async def _search_notes(self, query: str) -> ToolResult:
        """Search notes for a query."""
        try:
            results = []
            query_lower = query.lower()
            
            for note_file in self.notes_dir.glob("*.md"):
                content = note_file.read_text().lower()
                if query_lower in content:
                    # Show matching snippet
                    lines = content.split("\n")
                    matches = [line for line in lines if query_lower in line]
                    if matches:
                        results.append(f"## {note_file.stem}")
                        for match in matches[:3]:
                            results.append(f"  - {match.strip()}")
                        results.append("")
            
            if not results:
                return ToolResult(content="No notes found matching that query.")
            
            return ToolResult(content="\n".join(results))
        except Exception as e:
            return ToolResult(error=f"Search failed: {str(e)}")

    async def _list_notes(self) -> ToolResult:
        """List all notes."""
        try:
            notes = sorted(self.notes_dir.glob("*.md"))
            if not notes:
                return ToolResult(content="No notes yet. Create one with create_note!")
            
            result = ["Your notes:"]
            for note in notes:
                size = note.stat().st_size
                result.append(f"- {note.stem} ({size} bytes)")
            
            return ToolResult(content="\n".join(result))
        except Exception as e:
            return ToolResult(error=f"Failed to list notes: {str(e)}")
