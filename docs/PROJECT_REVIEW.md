# Echo AI - Full Project Review

**Date:** 2026-03-19
**Reviewer:** Claude Code
**Overall Score:** 7/10 (Good)

---

## Executive Summary

The project has a solid architecture, good test coverage (83%), and passes linting/type checking. However, there are areas for improvement in code quality, maintainability, and production readiness.

**Verdict:** Good working condition for personal/development use. With suggested improvements, could be production-ready for small-to-medium deployments.

---

## 1. Code Quality Issues

### Critical Issues

#### 1.1 Failing Tests (HIGH PRIORITY)
```
FAILED tests/test_message_filtering.py::test_filter_messages_for_ui
FAILED tests/test_message_filtering.py::test_filter_messages_as_objects
```
These are related to recent tool_calls fixes. The `filter_messages_for_ui` function has subtle bugs with pending tool_calls state.

**Location:** `src/agentframework/web_api.py:57-176`

**Fix:** Review the pending_tool_calls state management logic and ensure it correctly attaches tool_calls to the next assistant message with content.

#### 1.2 Global State in web_api.py (HIGH PRIORITY)
```python
# web_api.py:51-54
agent: Agent | None = None
current_session_id: str | None = None
message_history: list[dict[str, Any]] = []
```

**Problems:**
- Testing requires mocking
- Multiple concurrent WebSocket connections share state
- Not serverless-friendly
- Session data leakage between connections possible

**Fix:** Use FastAPI's dependency injection or application state (`request.app.state`).

#### 1.3 Debug Logging to Files (MEDIUM)
```python
# ollama.py:227-231
with open("/tmp/ollama_debug_payload.log", "a") as f:
    f.write("\n--- STREAMING CHAT REQUEST ---\n")
    f.write(f"Messages: {json.dumps(messages, indent=2)}\n")
```
Debug logs should use the logging framework, not file writes.

**Fix:** Replace with `logger.debug()` calls.

#### 1.4 CORS Wildcard (MEDIUM)
```python
# web_api.py:43-49
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Security risk
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Fix:** Make CORS origins configurable via environment variable or config.yaml.

### Code Smells

#### 1.5 Duplicated Logic
`_run_loop` and `_run_loop_streaming` in `agent.py` are ~95% identical (lines 233-446).

**Fix:** Extract common logic to a shared helper method.

#### 1.6 Magic Strings
```python
# Multiple locations
"__THINKING__"
"__THINKING_END__"
"qwen3:4b-instruct"
```

**Fix:** Move to constants in a `constants.py` file.

#### 1.7 Inconsistent Error Handling
Some places return `ToolResult(error=...)`, others raise exceptions.

**Fix:** Establish a unified error handling strategy.

---

## 2. Architecture Recommendations

### Quick Wins

| Issue | Impact | Effort | Priority |
|-------|--------|--------|----------|
| Fix failing tests | Reliability | Low | HIGH |
| Remove global state | Scalability | Medium | HIGH |
| Add DI container | Testability | Medium | MEDIUM |
| Centralize constants | Maintainability | Low | MEDIUM |
| Unified error handling | Reliability | Medium | MEDIUM |

### Long-term Architecture

#### 2.1 Dependency Injection
**Current:**
```python
agent = _create_runtime_agent(...)
```

**Recommended:** Use FastAPI's dependency injection or a factory pattern for better testability.

#### 2.2 Provider Abstraction Leak
The Ollama provider has ~1000 lines handling edge cases.

**Consider:**
- Base class for streaming logic
- Provider-specific plugins/strategies

---

## 3. Security Considerations

### Current Strengths
- Comprehensive dangerous pattern detection (`safety.py`)
- Workspace confinement
- Command allowlisting
- Audit logging capability

### Areas to Harden

#### 3.1 Tool Injection Prevention
```python
# bash.py:60 - command passed directly
proc = await asyncio.create_subprocess_shell(command)
```

**Consider:** Command parameterization or sandboxed execution (docker/namespace).

#### 3.2 File Operation Atomicity
File writes are not atomic - partial writes could corrupt files.

**Consider:** Temp-file-then-rename pattern.

#### 3.3 Rate Limiting
No rate limiting on API endpoints.

**Add:**
- Per-IP rate limits
- Per-session token limits
- Tool execution quotas

#### 3.4 Input Sanitization
Many places accept arbitrary content without sanitization.

**Consider:** Content sanitization before tool execution.

---

## 4. Frontend Improvements

### Current State: Functional but Basic

**Strengths:**
- Vanilla JS (no framework dependency)
- Responsive design
- Streaming support
- Theme switching

### Recommended Improvements

| Area | Issue | Recommendation |
|------|-------|----------------|
| Error Handling | Generic error messages | User-friendly error states |
| Loading States | No skeleton screens | Add loading indicators |
| Accessibility | Limited ARIA | Full keyboard nav, screen reader support |
| Code Blocks | Basic styling | Syntax highlighting with Prism/Shiki |
| Long Content | No virtual scrolling | Use virtual list for 100+ messages |
| Mobile | Basic responsive | Improved touch targets |

### JavaScript Improvements

```javascript
// Current: Class with no error boundaries
class EchoAI { ... }

// Better: Error boundaries, retry logic, graceful degradation
```

---

## 5. Performance Optimizations

### Identified Bottlenecks

#### 5.1 Token Counting - Called on Every Message
```python
# conversation.py:37-45
def estimate_tokens(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")  # Re-created each call!
```

**Fix:** Cache the encoder instance at module level.

#### 5.2 Message Filtering - Regex Recompilation
```python
# web_api.py:125-129
is_internal = any(
    re.search(pattern, content) for pattern in internal_patterns  # Recompiled each time
)
```

**Fix:** Pre-compile patterns at module level.

#### 5.3 SQLite Sessions - Full Table Scans
```python
# session.py:154
db.query(DBSessionModel).order_by(DBSessionModel.created_at.desc()).all()
```

**Fix:** Add indexes on `created_at` and add pagination for large session lists.

#### 5.4 Frontend Rendering - No Virtualization
```javascript
// app.js:716
this.messages.slice(start).forEach((msg) => this.renderMessage(msg));
```

**Fix:** Implement virtual scrolling for 50+ messages.

---

## 6. Testing Gaps

### Current Coverage: 83%

**Missing Test Areas:**

1. **Integration Tests**
   - End-to-end WebSocket flows
   - Multi-turn conversations with tool calls
   - Session persistence across restarts

2. **Security Tests**
   - Path traversal attempts - ✅ Covered in `safety.py`
   - Command injection attempts - ✅ Covered in tool validators
   - Rate limiting behavior - needs explicit tests

3. **Concurrency Tests**
   - Multiple simultaneous WebSocket connections
   - Parallel tool execution
   - Session conflict handling

4. **Edge Cases**
   - Empty responses
   - Malformed tool calls
   - Token limit boundaries

### Testing Utilities Missing
```python
# Need: fixtures for common scenarios
@pytest.fixture
def agent_with_tools():
    ...

@pytest.fixture
def session_with_messages():
    ...
```

---

## 7. Deployment & Operations

### Missing Production Features

| Feature | Status | Recommendation |
|---------|--------|----------------|
| Health checks | ✅ Implemented | `/health` endpoint exists |
| Metrics | Not implemented | Add Prometheus metrics |
| Structured logging | ✅ Implemented | JSON logging with correlation IDs |
| Graceful shutdown | ✅ Implemented | Via lifespan handlers |
| Container hardening | Not implemented | Non-root user, read-only filesystem |

### Security

| Feature | Status |
|---------|--------|
| Path traversal protection | ✅ Implemented in `safety.py` |
| Command injection protection | ✅ Implemented in tools |
| Rate limiting | ✅ Implemented (60 req/min) |

### Docker Improvements
```dockerfile
# Current: Basic multi-stage
# Missing:
# - Health checks
# - Signal handling
# - Resource limits
# - Non-root user
```

---

## 8. Documentation Gaps

### What's Good:
- README is clear
- Config options documented
- Architecture diagram in README

### What's Implemented:
- OpenAPI/Swagger docs - ✅ Available at `/docs` and `/redoc`
- README is clear ✅
- Config options documented ✅
- Architecture diagram in README ✅
- Contribution guidelines ✅ - `CONTRIBUTING.md`
- Runbook for common issues ✅ - `docs/RUNBOOK.md`
- Security policy ✅ - `docs/SECURITY.md`
- Performance tuning guide ✅ - `docs/PERFORMANCE.md`

### What's Done:
- README is clear ✅
- Config options documented ✅
- Architecture diagram in README ✅

---

## 9. Troubleshooting Guide

### "Tools Used" appearing as separate message

**Symptom:** When a model uses tools, "Tools Used: web_search" or the tool name appears as a separate message block instead of inline with the response.

**Root Cause:** The model outputs tool names as plain text (e.g., `web_search{"query": "..."}`) before the actual response content. This results in:
1. An assistant message with `content=''` and `tool_calls=[...]`
2. A separate assistant message with the actual response

**Solution (3-part fix):**

1. **Backend - Extract tool calls from content** (`src/agentframework/providers/ollama.py`):
   - Added `COMMON_TOOL_NAMES` constant with known tool names
   - Updated `_extract_tool_calls_from_content()` to handle `tool_name{"args"}` format
   - Tool names are now detected as "technical" content and extracted

2. **Frontend - Merge tool messages** (`static/js/main.js`):
   - Added `mergeToolMessages()` function in EchoAI class
   - Merges empty assistant messages with tool_calls into the next assistant message with content
   - Called during `renderMessages()` for session loading

3. **Frontend - Extract from content** (`static/js/components/ui.js`):
   - Added `extractToolUsageFromContent()` function
   - Extracts tool names from the START of content
   - Tools render as collapsible inline section (like Sources)

**Files changed:**
- `src/agentframework/providers/ollama.py`
- `static/js/main.js`
- `static/js/components/ui.js`

**Test cases added:**
- `tests/test_ollama_provider_extended.py`: `test_extract_tool_calls_name_followed_by_json`

---

## 9. Quick Wins (Can Implement Today)

1. **Fix the 2 failing tests** - 30 minutes
2. **Remove debug file writes** - 10 minutes
3. **Pre-compile regex patterns** - 15 minutes
4. **Add health endpoint** - 20 minutes
5. **Cache tiktoken encoder** - 10 minutes
6. **Remove global state** - 2 hours
7. **Add CORS configuration** - 15 minutes

---

## 10. Recommended Priority Order

### Phase 1 (This Week) - COMPLETED 2026-03-19
- [x] Fix failing tests
- [x] Remove debug code
- [x] Add health endpoint
- [x] Pre-compile regex patterns
- [x] Cache tiktoken encoder

### Phase 2 (This Month) - COMPLETED 2026-03-19
- [x] Remove global state (AppState + DI)
- [x] Add structured logging with correlation IDs
- [x] Improve error messages

### Phase 3 (Next Quarter) - COMPLETED 2026-03-19
- [x] Syntax highlighting - Added Prism.js with Python, Bash, JavaScript, JSON, YAML, Markdown support
- [x] Rate limiting - Added 60 requests/minute per IP with rate limit headers
- [x] Virtual scrolling for chats - Window-based limiting (120 messages) with content-visibility: auto
- [x] Event sourcing for sessions - Added SessionEvent class and event log for audit/replay
- [x] Full accessibility audit - Skip links, ARIA labels, focus management, reduced motion, screen reader announcements

---

## File Reference

### Core Files
- `src/agentframework/agent.py` - Main agent logic (677 lines)
- `src/agentframework/web_api.py` - Web backend (740 lines)
- `src/agentframework/session.py` - Session management (261 lines)
- `src/agentframework/safety.py` - Security validation (307 lines)
- `src/agentframework/providers/ollama.py` - Ollama provider (436 lines)

### Frontend
- `static/js/app.js` - Frontend JavaScript (840 lines)
- `static/css/style.css` - Styles (490 lines)
- `static/index.html` - Main HTML

### Config
- `config.yaml` - Main configuration
- `requirements.txt` - Dependencies (555 lines)

### Tests
- `tests/` - 48 test files
- Current status: 348 passed, 0 failed (as of 2026-03-19)

---

## Changelog of This Review

| Date | Changes |
|------|---------|
| 2026-03-19 | Initial review created |
| 2026-03-19 | Phase 1 completed: Fixed tests, removed debug code, added health endpoint, pre-compiled regex patterns, cached tiktoken encoder |
| 2026-03-19 | Phase 2 (partial): Removed global state - created AppState class, refactored REST endpoints to use dependency injection via `get_state()`, WebSocket now uses `_state` directly, updated all tests to use state properly |
| 2026-03-19 | Cleanup: Fixed 16 type errors across 7 test files (test_bash_tool_extended, test_complex_tools, test_config, test_file_extended, test_utils_extended, test_web_api, test_web_tools_extended). All tests now pass with 0 pyright errors. |
| 2026-03-19 | Phase 2 completed: Added structured logging with correlation IDs via `CorrelationIdFilter` and `JsonFormatter`, improved error messages in web_api.py, updated WebSocket error handling, updated test for new error message |
| 2026-03-19 | Phase 3: Added Prism.js syntax highlighting (Python, Bash, JS, JSON, YAML, Markdown), added rate limiting (60 req/min per IP), enhanced code block styling in CSS |
| 2026-03-19 | Frontend modularization: Refactored monolithic app.js into ES modules (state.js, services/api.js, services/websocket.js, components/ui.js, main.js) with all original features preserved |
| 2026-03-19 | Code quality fixes: Made CORS origins configurable via config.yaml, replaced debug file logging with proper logger.debug() calls, created constants.py for magic strings (THINKING_START, THINKING_END), refactored duplicated _run_loop methods into shared _call_llm helper, upgraded pyopenssl to fix CVEs |
| 2026-03-19 | Phase 3 completed: Virtual scrolling via content-visibility:auto and 120-message window, event sourcing with SessionEvent class for audit/replay, full accessibility audit with skip links, ARIA, focus management, reduced motion support, screen reader announcements |
| 2026-03-19 | Fixed "Tools Used" appearing as separate message: When model outputs tool names as plain text (e.g., `web_search{"query": "..."}`), backend now extracts tool calls from content in ollama.py. Frontend merges empty tool messages with next assistant message via `mergeToolMessages()` in main.js. Tool names are extracted from content start via `extractToolUsageFromContent()` in ui.js and rendered as collapsible inline section (like sources). |

(End of file - total 392 lines)
