"""Constants used throughout the agent framework."""

import os
from pathlib import Path

import httpx

ECHO_DATA_DIR = Path(os.environ.get("ECHO_DATA_DIR", str(Path.home() / ".echo-ai")))

# Provider base URLs
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LM_STUDIO_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234")

# Output truncation limits
BASH_OUTPUT_MAX_CHARS = int(os.environ.get("BASH_OUTPUT_MAX_CHARS", "100000"))
GIT_OUTPUT_MAX_CHARS = int(os.environ.get("GIT_OUTPUT_MAX_CHARS", "50000"))
MESSAGE_CONTENT_MAX_CHARS = int(os.environ.get("MESSAGE_CONTENT_MAX_CHARS", "20000"))

# Execution timeouts (seconds)
PYTHON_EXEC_TIMEOUT = int(os.environ.get("PYTHON_EXEC_TIMEOUT", "10"))
GIT_COMMAND_TIMEOUT = int(os.environ.get("GIT_COMMAND_TIMEOUT", "30"))
WEB_SEARCH_TIMEOUT = int(os.environ.get("WEB_SEARCH_TIMEOUT", "30"))
WEB_CRAWL_TIMEOUT = int(os.environ.get("WEB_CRAWL_TIMEOUT", "60"))
DEEP_SEARCH_TIMEOUT = int(os.environ.get("DEEP_SEARCH_TIMEOUT", "30"))

# Workflow
WORKFLOW_MAX_ITERATIONS = int(os.environ.get("WORKFLOW_MAX_ITERATIONS", "100"))

# CORS default ports
CORS_FRONTEND_PORT = 3000
CORS_ALT_FRONTEND_PORT = 3001
CORS_STREAMLIT_PORT = 8501

THINKING_START = "__THINKING__"
THINKING_END = "__THINKING_END__"

DEFAULT_MODEL = "qwen3:4b-instruct"

MESSAGE_ROLE_USER = "user"
MESSAGE_ROLE_ASSISTANT = "assistant"
MESSAGE_ROLE_SYSTEM = "system"
MESSAGE_ROLE_TOOL = "tool"

TOOL_RESULT_SUCCESS = "success"
TOOL_RESULT_ERROR = "error"

DEFAULT_HTTP_TIMEOUT = httpx.Timeout(60.0, connect=30.0)
DEFAULT_STREAM_TIMEOUT = httpx.Timeout(300.0, connect=30.0)

DEFAULT_MAX_TOKENS = 4096

MEMORY_MAX_MESSAGES = 20
MEMORY_KEEP_RECENT = 6

MODELS_CACHE_TTL = 60.0

RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 1
RETRY_MAX_WAIT = 10

ERROR_NETWORK_BLOCKED = "Network access is blocked by safety configuration"
ERROR_APPROVAL_REQUIRED = "Operation requires user approval"
ERROR_INVALID_URL = "Invalid URL: {detail}"
ERROR_WORKSPACE_VIOLATION = "Operation violates workspace boundaries"
ERROR_TIMEOUT = "Request timed out"
