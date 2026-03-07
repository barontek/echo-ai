"""Agent Framework - A standalone AI agent framework."""

__version__ = "0.1.0"

from .agent import Agent, AgentConfig, create_agent, SubAgentConfig
from .session import SessionManager, Session, ChangeTracker
from .router import SemanticRouter
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
    "SessionManager",
    "Session",
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
]
