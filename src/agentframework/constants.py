"""Constants used throughout the agent framework."""

import httpx

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
