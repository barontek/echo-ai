# Codebase Cleanup Plan

Generated: 2026-04-07

## HIGH PRIORITY

### 1. Version Inconsistency
- **Issue:** "0.1.0" hardcoded in multiple places
- **Files:** `__init__.py`, `web_api.py` (lines 123, 723, 770), `cli.py` (line 157), `sentry.py` (line 53)
- **Fix:** Create `src/agentframework/_version.py` as single source

### 2. Duplicate Router
- **Issue:** `router.py` wraps `core/router.py`
- **Fix:** Update imports to use `core.router` directly, deprecate wrapper

### 3. Type Ignore Comments
- **Issue:** SQLAlchemy type ignores in `session.py` (lines 233-238, 309-314)
- **Fix:** Address typing issues properly

## MEDIUM PRIORITY

### 4. Provider Code Duplication
- **Issue:** Anthropic, OpenAI, Ollama share similar patterns
- **Fix:** Extract common logic to base `LLMProvider` class

### 5. Missing Docstrings
- **Files:** `logging_utils.py`, `metrics.py`, `chat_runtime.py`, `chat_render.py`, `chat_commands.py`
- **Fix:** Add module and function docstrings

### 6. Large web_api.py Functions
- **Issue:** `chat_completion` (~300 lines), `_handle_websocket_chat` (~200 lines)
- **Fix:** Split into smaller functions/modules

## LOW PRIORITY

### 7. Chat Module Consolidation
- **Issue:** Split across `chat_runtime.py`, `chat_render.py`, `chat_commands.py`
- **Fix:** Create `chat/` package

### 8. Broad Exception Catching
- **Issue:** 95 instances of `except Exception`
- **Fix:** Use more specific exception types

### 9. Frontend Test Coverage
- **Issue:** Only 3 test files
- **Fix:** Add tests for contexts, edge cases, error states

### 10. Hardcoded Config Values
- **Issue:** `DEFAULT_WEB_PORT`, `DEFAULT_PROVIDER`, `DEFAULT_MODEL` duplicate config
- **Fix:** Use config module consistently
