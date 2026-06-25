"""Agent Framework - A standalone AI agent framework."""

import asyncio
import inspect
import sys

# Python 3.14+ deprecated asyncio.iscoroutinefunction in favor of
# inspect.iscoroutinefunction.  chromadb still uses the asyncio variant
# at runtime (chromadb 1.5.9), so we patch it preemptively to silence
# the DeprecationWarning.
if sys.version_info >= (3, 14):
    asyncio.iscoroutinefunction = inspect.iscoroutinefunction

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
    "__version__",
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

    "validate_tool_args",
    "format_tool_failure",
    "ToolError",
    "undo_change",
    "redo_change",
    "serialize_messages",
    "deserialize_messages",
]
