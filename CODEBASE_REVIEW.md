# Echo AI Codebase Review

**Date**: March 29, 2026
**Reviewer**: AI Analysis

---

## Project Overview

Echo AI is a standalone AI agent framework with tool-calling capabilities. After previous improvements, the codebase is in good shape with proper error handling, timeouts, and input validation.

---

## Previously Addressed Issues (Fixed)

1. ✅ curl/wget in allowed_commands - Already secure
2. ✅ SQLite WAL mode - Already enabled
3. ✅ Global state - Using AgentRegistry pattern
4. ✅ Config schema validation - Added Pydantic models
5. ✅ Async approval callback - Added async_approval_callback
6. ✅ Circuit breaker - Implemented circuit_breaker.py
7. ✅ Optional dependencies - Added extras_require groups
8. ✅ Mock fixtures - Added in conftest.py
9. ✅ Protocol classes - Already exist
10. ✅ BLOCKED_EXTENSIONS - Already complete
11. ✅ __slots__ - Added to key dataclasses
12. ✅ Exception handling - Added logging to exception handlers
13. ✅ HTTP timeouts - Added to all providers
14. ✅ Magic numbers extracted - Added to constants.py
15. ✅ Workflow hardcoded sleep - Made configurable

---

## NEW Issues Found

### 1. Duplicate Re-export Wrappers (MEDIUM)

The codebase has many wrapper modules that just re-export from `core/`:

| Wrapper | Target | Lines |
|---------|--------|-------|
| `agent.py` | `core/agent.py` | 48 (just re-exports) |
| `memory.py` | `core/memory.py` | 8 (just re-exports) |
| `session_runtime.py` | `core/session_runtime.py` | 13 (just re-exports) |
| `tool_runtime.py` | `core/tool_runtime.py` | 22 (just re-exports) |

**Recommendation**: Remove these wrapper files and update all imports to use direct paths, or keep them but add clear deprecation warnings.

---

### 2. Duplicate Code in Providers (LOW)

Each provider has similar but not identical patterns. Could benefit from a base class:

- `anthropic.py:38-45` - Extracts system message manually
- `openai.py` - Passes messages directly (no system extraction)
- `ollama.py` - Has custom thinking extraction

The response parsing logic is duplicated across providers.

**Recommendation**: Consider a shared `BaseProvider` class with common logic.

---

### 3. Hardcoded max_tokens (LOW)

Multiple hardcoded values:

| File | Line | Value |
|------|------|-------|
| `anthropic.py` | 49, 107, 173 | `max_tokens=4096` |
| `constants.py` | - | Has DEFAULT_MAX_TOKENS but not used |

**Recommendation**: Use `constants.DEFAULT_MAX_TOKENS` instead of hardcoding 4096.

---

### 4. Inconsistent Timeout Configuration (LOW)

- `anthropic.py` - Uses `DEFAULT_TIMEOUT` constant ✅
- `openai.py` - Uses inline `httpx.Timeout(60.0, connect=30.0)` ❌
- `ollama.py` - Uses `httpx.Timeout(300.0, connect=30.0)` (different!)

**Recommendation**: Use constants from `constants.py` consistently.

---

### 5. Missing Error Handling in Tool Validation (LOW)

Tools that parse user input could fail silently:

- `tools/search.py` - `sanitize_search_query` returns empty string on error
- `tools/web.py` - URL validation exists but could be bypassed

**Recommendation**: Add logging when sanitization/validation produces unexpected results.

---

### 6. No Connection Pooling for External Tools (LOW)

Each tool execution may create new HTTP clients:

- `tools/web.py` - Creates new `AsyncWebCrawler` or `httpx.AsyncClient` per request
- `tools/api.py` - Creates new client per request

**Recommendation**: Consider sharing a cached client for better performance.

---

### 7. Global State for Tiktoken Encoder (LOW)

`conversation.py:25` uses global mutable state:
```python
global _TIKTOKEN_ENCODER
```

While cached, this could cause issues in multi-threaded environments.

**Recommendation**: Use `lru_cache` or threading-safe singleton pattern.

---

### 8. No Rate Limiting at Tool Level (LOW)

Rate limiting exists at web server level but not at the agent/tool execution level. A malicious user could spam tool calls.

**Recommendation**: Add per-user rate limiting for tool executions.

---

### 9. Missing Pydantic Models for Tool Parameters (LOW)

Some tools use `**kwargs` instead of typed parameters:

- `tools/web.py:142` - `execute(self, url: str, **kwargs)`
- Multiple tools pass kwargs without validation

**Recommendation**: Ensure all tools use their `parameters_model` for validation.

---

### 10. Inconsistent Error Messages (LOW)

Error messages vary across the codebase:
- Some return `ToolResult(error=...)`
- Some return `LLMResponse(content=f"Error: ...")`
- Some raise exceptions

**Recommendation**: Standardize error handling approach.

---

### 11. Workspace Path in Config (MEDIUM)

`config.yaml:50` has hardcoded path:
```yaml
workspace: "/home/barontek"
```

This should be relative or configurable via environment.

**Recommendation**: Use `~` or environment variable for workspace.

---

### 12. No Request ID Propagation (LOW)

Logs don't consistently include request/trace IDs for correlation across services.

**Recommendation**: Ensure all log statements include correlation IDs.

---

## Summary

| Category | Priority | Count |
|----------|----------|-------|
| Duplicate Wrappers | MEDIUM | 1 |
| Hardcoded Values | LOW | 3 |
| Inconsistency | LOW | 3 |
| Missing Features | LOW | 4 |
| Configuration | MEDIUM | 1 |

**Overall**: The codebase is well-structured after previous fixes. Remaining issues are minor and don't affect functionality. Focus on cleanup (remove duplicate wrappers) and consistency improvements.
