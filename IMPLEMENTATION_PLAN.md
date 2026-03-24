# Implementation Plan: Echo AI Improvements

**Based on**: CODEBASE_REVIEW.md
**Created**: March 28, 2026
**Total Items**: 27 tasks across 4 phases

---

## Phase 1: Security Hardening (CRITICAL)

### 1.1 Remove Dangerous Commands from Allowlist
**Priority**: CRITICAL | **Effort**: 5 min | **Risk**: Low

```
config.yaml
├── Remove: curl, wget from allowed_commands
└── Add: comment explaining why file downloads require approval
```

**Files to modify**:
- `config.yaml` - Remove `curl`, `wget` from allowed_commands
- `docs/security.md` - Document the change and rationale

**Verification**: Run `grep -r "curl\|wget" tests/` to ensure no tests depend on these

---

### 1.2 Expand Blocked Extensions
**Priority**: HIGH | **Effort**: 10 min | **Risk**: Low

**Files to modify**:
- `src/agentframework/safety.py`

**Change**:
```python
BLOCKED_EXTENSIONS = [
    '*.key', '*.pem', '*.pub', '*.secret', '*.token',
    '*.env', '*.password', '*.credential', '*.api_key',
    '*.aws', '*.gcp', '*.azure', 'id_rsa', 'id_ed25519',
    # NEW
    '*.crt', '*.cer', '*.p12', '*.pfx',
    '*_key', '*_secret', '*_token', '*_credential',
]
```

**Verification**: Add test cases for new patterns in `tests/unit/test_safety.py`

---

### 1.3 Enable SQLite WAL Mode
**Priority**: HIGH | **Effort**: 10 min | **Risk**: Low

**Files to modify**:
- `src/agentframework/session.py`

**Add after connection creation**:
```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")  # Good balance of safety/speed
```

**Verification**: Add test that queries `PRAGMA journal_mode` after session init

---

### 1.4 Fix Global State in API
**Priority**: HIGH | **Effort**: 2 hours | **Risk**: Medium

**Files to modify**:
- `src/agentframework/api.py`
- `src/agentframework/dependencies.py` (create)

**Implementation**:
```python
# dependencies.py
from dataclasses import dataclass
from typing import Dict
from fastapi import Depends

@dataclass
class AgentRegistry:
    agents: Dict[str, Agent]

_agent_registry = AgentRegistry(agents={})

def get_agent_registry() -> AgentRegistry:
    return _agent_registry

# api.py - replace global agents with dependency
@router.post("/chat")
async def chat(
    request: ChatRequest,
    registry: AgentRegistry = Depends(get_agent_registry)
):
    agent = registry.agents.get(request.session_id)
    ...
```

**Verification**: Run existing API tests, test multi-instance scenarios

---

### 1.5 Add Connection Timeouts to httpx
**Priority**: HIGH | **Effort**: 30 min | **Risk**: Low

**Files to modify**:
- `src/agentframework/providers/anthropic.py`
- `src/agentframework/providers/openai.py`
- `src/agentframework/providers/ollama.py`
- `src/agentframework/tools/web.py`
- `src/agentframework/tools/api.py`

**Add to AsyncClient initialization**:
```python
httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
```

**Verification**: Test with slow/unresponsive endpoints

---

## Phase 2: Performance & Reliability

### 2.1 Add Pagination to list_sessions
**Priority**: MEDIUM | **Effort**: 2 hours | **Risk**: Low

**Files to modify**:
- `src/agentframework/session.py`
- `src/agentframework/api.py`
- `src/agentframework/ui_nicegui/` (update calls)

**Implementation**:
```python
def list_sessions(
    self,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None
) -> tuple[list[Session], int]:
    """Returns (sessions, total_count)"""
    query = db.query(DBSessionModel)
    if search:
        query = query.filter(DBSessionModel.title.ilike(f"%{search}%"))
    total = query.count()
    sessions = query.order_by(...).offset(offset).limit(limit).all()
    return [Session.from_db(s) for s in sessions], total
```

**Verification**: Test with 100+ sessions, verify pagination works

---

### 2.2 Add Rate Limiting to web_api.py
**Priority**: MEDIUM | **Effort**: 1 hour | **Risk**: Low

**Files to modify**:
- `src/agentframework/tools/api.py`

**Add dependency**:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/search")
@limiter.limit("10/minute")
async def web_search(...):
    ...
```

**Verification**: Load test with concurrent requests

---

### 2.3 Add Input Sanitization for Search
**Priority**: MEDIUM | **Effort**: 30 min | **Risk**: Low

**Files to modify**:
- `src/agentframework/tools/search.py`

**Add**:
```python
def sanitize_search_query(query: str) -> str:
    dangerous = ['<script', 'javascript:', 'data:', 'onerror=', 'onclick=']
    for pattern in dangerous:
        query = query.replace(pattern, '')
    return query.strip()[:500]  # Max length
```

**Verification**: Add XSS test cases

---

### 2.4 Add HTTPS Enforcement for WebSocket
**Priority**: MEDIUM | **Effort**: 1 hour | **Risk**: Medium

**Files to modify**:
- `src/agentframework/api.py`
- `config.yaml`

**Add to WebSocket endpoint**:
```python
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Check for wss://
    if websocket.scope.get("scheme") == "http":
        await websocket.close(code=4001, reason="HTTPS required")
        return
    ...
```

**Verification**: Test WebSocket over HTTP fails

---

### 2.5 Async File I/O in Web Tools
**Priority**: MEDIUM | **Effort**: 2 hours | **Risk**: Low

**Files to modify**:
- `src/agentframework/tools/web.py`

**Replace synchronous httpx fallback with aiofiles**:
```python
import aiofiles

async def fetch_with_fallback(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.text()
    except:
        # Fallback - but make it async
        async with aiofiles.tempfile.NamedTemporaryFile() as f:
            subprocess.run(['curl', '-s', url], stdout=f)
            return await f.read()
```

**Verification**: Benchmark async vs sync paths

---

## Phase 3: Code Quality

### 3.1 Replace Magic Numbers with Config
**Priority**: MEDIUM | **Effort**: 3 hours | **Risk**: Low

**Files to modify**:
- `config.yaml` - Add limits section
- `src/agentframework/config.py` - Load limits
- `src/agentframework/conversation.py`
- `src/agentframework/tools/web.py`

**config.yaml additions**:
```yaml
limits:
  max_file_read_kb: 1024
  max_search_content_chars: 8000
  max_messages_before_summary: 120
  max_content_length: 15000
  token_reserve_ratio: 0.7
```

**Verification**: Verify all existing behavior with config values

---

### 3.2 Replace Any Types in Critical Paths
**Priority**: MEDIUM | **Effort**: 4 hours | **Risk**: Medium

**Files to audit**:
- `src/agentframework/agent.py`
- `src/agentframework/tool_runtime.py`
- `src/agentframework/providers/`

**Approach**: Run pyright with strict mode, fix errors incrementally

**Verification**: `pyright --strict` passes

---

### 3.3 Add Protocol Classes for Providers
**Priority**: MEDIUM | **Effort**: 2 hours | **Risk**: Low

**Files to create/modify**:
- `src/agentframework/providers/base.py` (create)

**Implementation**:
```python
from typing import Protocol, AsyncIterator
from dataclasses import dataclass

@dataclass
class Message:
    role: str
    content: str

class LLMProvider(Protocol):
    def complete(self, messages: list[Message]) -> str: ...
    def complete_stream(self, messages: list[Message]) -> AsyncIterator[str]: ...
    def count_tokens(self, text: str) -> int: ...
```

**Verification**: Type check all providers against protocol

---

### 3.4 Consolidate UI Frameworks
**Priority**: MEDIUM | **Effort**: 8 hours | **Risk**: High

**Decision required**: Choose which UI to keep:
- **Option A**: Keep `ui_nicegui/` (more full-featured)
- **Option B**: Keep `ui/` (simpler)
- **Option C**: Keep both but document when to use each

**If consolidating**: Remove one directory, update imports

**Verification**: Both UIs work or remaining UI works

---

### 3.5 Add __slots__ to Frequent Classes
**Priority**: LOW | **Effort**: 1 hour | **Risk**: Low

**Files to modify**:
- `src/agentframework/conversation.py` (Message)
- `src/agentframework/tool_runtime.py` (ToolResult)

**Implementation**:
```python
@dataclass
class Message:
    role: str
    content: str
    __slots__ = ('role', 'content')
```

**Verification**: Memory profiling before/after

---

### 3.6 Add Logging Improvements
**Priority**: LOW | **Effort**: 1 hour | **Risk**: Low

**Files to modify**: Multiple files

**Changes**:
1. Standardize to f-strings
2. Replace `logger.debug` with `logger.warning` for approval-required messages
3. Add structured logging context

---

## Phase 4: Testing & Documentation

### 4.1 Add Integration Tests
**Priority**: MEDIUM | **Effort**: 4 hours | **Risk**: Low

**Files to create**:
- `tests/integration/test_agent_loop.py`
- `tests/integration/test_provider_mock.py`

**Implementation**:
```python
@pytest.mark.asyncio
async def test_agent_loop_with_mock_provider():
    """Test full agent loop with mocked LLM responses."""
    from unittest.mock import AsyncMock

    mock_provider = AsyncMock(spec=LLMProvider)
    mock_provider.complete.return_value = "Final response"

    agent = Agent(provider=mock_provider, tools=[])
    result = await agent.run("Hello")
    assert result == "Final response"
```

**Verification**: All integration tests pass

---

### 4.2 Add Concurrency Stress Tests
**Priority**: LOW | **Effort**: 2 hours | **Risk**: Low

**Files to create**:
- `tests/stress/test_concurrent_sessions.py`

**Test scenarios**:
- 100 concurrent session queries
- 50 concurrent WebSocket connections
- Rapid start/stop of agents

**Verification**: Tests complete without deadlocks

---

### 4.3 Update Security Documentation
**Priority**: MEDIUM | **Effort**: 1 hour | **Risk**: Low

**Files to modify**:
- `docs/security.md`
- `docs/runbook.md`

**Document**:
- Why curl/wget removed from defaults
- New blocked extensions
- Best practices for allowed_commands

---

### 4.4 Add Observability (Prometheus Metrics)
**Priority**: LOW | **Effort**: 4 hours | **Risk**: Low

**Files to create/modify**:
- `src/agentframework/metrics.py` (create)
- `src/agentframework/api.py`

**Metrics to export**:
- `agent_requests_total`
- `agent_request_duration_seconds`
- `tool_execution_duration_seconds`
- `token_usage_total`

---

## Implementation Order

```
Week 1: Security (1.1-1.5)
├── 1.1 Remove curl/wget (5 min)
├── 1.2 Expand blocked extensions (10 min)
├── 1.3 Enable SQLite WAL (10 min)
├── 1.5 Add httpx timeouts (30 min)
└── 1.4 Fix global state (2 hrs)

Week 2: Performance (2.1-2.5)
├── 2.1 Pagination (2 hrs)
├── 2.3 Sanitization (30 min)
├── 2.2 Rate limiting (1 hr)
├── 2.4 HTTPS enforcement (1 hr)
└── 2.5 Async file I/O (2 hrs)

Week 3-4: Code Quality (3.1-3.6)
├── 3.1 Magic numbers config (3 hrs)
├── 3.2 Type fixes (4 hrs)
├── 3.3 Protocol classes (2 hrs)
├── 3.4 UI consolidation (8 hrs) - OR defer
├── 3.5 __slots__ (1 hr)
└── 3.6 Logging (1 hr)

Week 5: Testing & Docs (4.1-4.4)
├── 4.1 Integration tests (4 hrs)
├── 4.3 Update docs (1 hr)
├── 4.2 Concurrency tests (2 hrs)
└── 4.4 Prometheus (4 hrs) - if time permits
```

---

## Success Criteria

- [ ] All HIGH priority items completed
- [ ] pyright strict mode passes
- [ ] pytest coverage >= 80%
- [ ] No security vulnerabilities in bandit's output
- [ ] All integration tests pass
- [ ] Performance benchmarks show improvement (WAL mode)

---

## Rollback Plan

For each change:
1. Create git branch before modification
2. Add test that fails without the change
3. Document rollback steps in PR description
4. Monitor error rates after deployment
