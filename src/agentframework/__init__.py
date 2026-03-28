"""Agent Framework - A standalone AI agent framework."""

__version__ = "0.1.0"

from .core import (
    Agent,
    AgentConfig,
    SubAgentConfig,
    create_agent,
    CallbackManager,
    AgentCallback,
    MemoryManager,
    SemanticRouter,
    execute_single_tool,
    execute_tool_calls,
    create_tool_result_notice,
    validate_tool_args,
    format_tool_failure,
    ToolError,
    undo_change,
    redo_change,
    serialize_messages,
    deserialize_messages,
)
from .session import SessionManager, Session, ChangeTracker
from .conversation import Message
from .tools import Tool, ToolResult
from .tools.bash import BashTool
from .tools.file import ReadFileTool, WriteFileTool, ListDirTool
from .tools.search import GlobTool, GrepTool
from .tools.web import WebFetchTool, WebSearchTool
from .tools.git import GitTool

__all__ = [
    "Agent",
    "AgentConfig",
    "SubAgentConfig",
    "create_agent",
    "CallbackManager",
    "AgentCallback",
    "MemoryManager",
    "SessionManager",
    "Session",
    "Message",
    "ChangeTracker",
    "SemanticRouter",
    "Tool",
    "ToolResult",
    "BashTool",
    "ReadFileTool",
    "WriteFileTool",
    "ListDirTool",
    "GlobTool",
    "GrepTool",
    "WebFetchTool",
    "WebSearchTool",
    "GitTool",
    "execute_single_tool",
    "execute_tool_calls",
    "create_tool_result_notice",
    "validate_tool_args",
    "format_tool_failure",
    "ToolError",
    "undo_change",
    "redo_change",
    "serialize_messages",
    "deserialize_messages",
]
