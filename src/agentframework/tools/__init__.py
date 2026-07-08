"""Tool system for the agent framework."""

from __future__ import annotations

# ruff: noqa: E402
# Imports must be after class definitions to avoid circular import issues

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Type

from pydantic import BaseModel

if TYPE_CHECKING:
    from .bash import BashTool
    from .file import ListDirTool, ReadFileTool, WriteFileTool
    from .git import GitTool
    from .memory import MemoryTool
    from .notes import PersonalNotesTool
    from .search import GlobTool, GrepTool
    from .web import WebFetchTool, WebSearchTool


@dataclass(slots=True)
class ToolResult:
    """Result from a tool execution."""

    content: str = ""
    error: str | None = None
    error_category: str | None = None
    metadata: dict[str, Any] | None = None

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return self.content


class Tool(ABC):
    """Base class for tools."""

    parameters_model: Type[BaseModel] | None = None
    __slots__ = ("name", "description")

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @property
    def schema(self) -> dict[str, Any]:
        """Get the tool schema for LLM tool calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._get_parameters(),
            },
        }

    def _get_parameters(self) -> dict[str, Any]:
        """Get the parameters schema. Override or define parameters_model."""
        if self.parameters_model:
            return self.parameters_model.model_json_schema()
        return {"type": "object", "properties": {}}

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments."""
        pass


from .bash import BashTool
from .file import ListDirTool, ReadFileTool, WriteFileTool
from .git import GitTool
from .memory import MemoryTool
from .notes import PersonalNotesTool
from .search import GlobTool, GrepTool
from .web import WebFetchTool, WebSearchTool
from .python import PythonTool
from .api import RESTAPITool
from .db import SQLiteQueryTool, SQLiteSchemaTool
from .human import AskUserTool
from .rag import SemanticSearchTool, DocumentIngestionTool
from .humanizer import HumanizerTool
from .deep_search import DeepSearchTool


TOOL_REGISTRY: dict[str, Type[Tool]] = {
    "bash": BashTool,
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
    "list_dir": ListDirTool,
    "glob": GlobTool,
    "grep": GrepTool,
    "web_fetch": WebFetchTool,
    "web_search": WebSearchTool,
    "git": GitTool,
    "memory": MemoryTool,
    "notes": PersonalNotesTool,
    "python_execute": PythonTool,
    "rest_api": RESTAPITool,
    "sqlite_query": SQLiteQueryTool,
    "sqlite_schema": SQLiteSchemaTool,
    "ask_user": AskUserTool,
    "semantic_search": SemanticSearchTool,
    "ingest_document": DocumentIngestionTool,
    "humanizer": HumanizerTool,
    "deep_search": DeepSearchTool,
}

TOOL_CONFIG_KEYS: dict[str, dict[str, Any]] = {
    "bash": {"timeout": 60, "allowed_commands": None, "safety_config": None},
    "read_file": {"base_dir": ".", "safety_config": None},
    "write_file": {"base_dir": ".", "safety_config": None},
    "list_dir": {"base_dir": ".", "safety_config": None},
    "glob": {"base_dir": ".", "safety_config": None},
    "grep": {"base_dir": ".", "safety_config": None},
    "web_fetch": {"safety_config": None, "limits": None},
    "web_search": {"safety_config": None, "provider": "brave", "limits": None},
    "git": {"base_dir": ".", "safety_config": None},
    "memory": {"db_path": None, "safety_config": None},
    "notes": {"notes_dir": None},
    "deep_search": {"safety_config": None, "limits": None},
    "python_execute": {"safety_config": None, "execution_timeout": 30},
    "rest_api": {"safety_config": None},
    "sqlite_query": {"safety_config": None, "session_db_path": None},
    "sqlite_schema": {"safety_config": None},
    "ask_user": {},
    "semantic_search": {"vector_store": None},
    "ingest_document": {"vector_store": None},
    "humanizer": {"llm_provider": None},
}


def get_tool_config_schema(tool_name: str) -> dict[str, Any]:
    """Get the configuration schema for a tool."""
    return TOOL_CONFIG_KEYS.get(tool_name, {})
