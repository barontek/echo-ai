# Codebase Concerns

**Analysis Date:** 2026-03-08

## Tech Debt

**Complex Tool Implementations:**
- Issue: Memory tool (`src/agentframework/tools/memory.py`) is 413 lines with complex SQLite FTS5 setup and triggers
- Files: `src/agentframework/tools/memory.py`
- Impact: Hard to maintain, difficult to add features, potential for DB corruption bugs
- Fix approach: Split into separate modules (storage, search, memory management)

**Ollama Provider Complexity:**
- Issue: Ollama provider has 392 lines with complex tool call extraction logic (multiple regex patterns, streaming edge cases)
- Files: `src/agentframework/providers/ollama.py`
- Impact: Hard to debug tool call extraction issues, streaming and non-streaming paths have divergent behavior
- Fix approach: Extract tool call parsing into separate utility functions, add comprehensive tests

**Duplicate Streaming Logic:**
- Issue: CLI (`cli.py`) duplicates the thinking marker handling that exists in agent.py streaming
- Files: `src/agentframework/cli.py`, `src/agentframework/agent.py`
- Impact: Inconsistent behavior between CLI and programmatic usage
- Fix approach: Extract streaming handling to shared utility

**Backward Compatibility API in Agent:**
- Issue: `_execute_tool_calls` has confusing overload pattern for backward compatibility
- Files: `src/agentframework/agent.py` (lines 262-338)
- Impact: Hard to understand API contract, potential for bugs when mixing old/new usage
- Fix approach: Deprecate old API, standardize on single return type

## Known Bugs

**Vector Store Silently Fails:**
- Symptoms: RAG tools fail with unclear errors if ChromaDB initialization fails
- Files: `src/agentframework/vector.py`
- Trigger: Any issue with ChromaDB (disk space, permissions, corrupted data)
- Workaround: Check logs for initialization errors, manually delete `.agent_vector_db` directory

**SQLite Query Row Limit:**
- Symptoms: Large query results truncated at 100 rows with no warning
- Files: `src/agentframework/tools/db.py` (line 66)
- Trigger: Queries returning more than 100 rows
- Workaround: None - users cannot adjust this limit

**DDGS Search Output Capture:**
- Symptoms: Web search captures and suppresses stdout/stderr from ddgs library
- Files: `src/agentframework/tools/web.py` (lines 170-179)
- Trigger: Web search operations
- Workaround: None identified

## Security Considerations

**Incomplete Python Sandbox:**
- Risk: Python tool executes arbitrary code in the same Python environment (just subprocess)
- Files: `src/agentframework/tools/python.py`
- Current mitigation: Only passes PATH and PYTHONUNBUFFERED env vars, uses timeout
- Recommendations: Add resource limits (memory, CPU), consider gVisor or firecracker microVM for true isolation

**No SSRF Protection on Web Fetch:**
- Risk: Agent can be tricked into making requests to internal services (localhost, 169.254.169.254)
- Files: `src/agentframework/tools/web.py`
- Current mitigation: Only has domain allowlist option (not enforced by default)
- Recommendations: Block localhost/internal IP ranges by default, add cloud metadata endpoint blocking

**SQLite Query Injection Risk:**
- Risk: String matching for query validation can potentially be bypassed
- Files: `src/agentframework/tools/db.py` (lines 52-55)
- Current mitigation: String check for forbidden keywords
- Recommendations: Use SQL statement parsing instead of string matching

**Bash Tool Command Injection:**
- Risk: Commands are passed to shell even with safety checks
- Files: `src/agentframework/tools/bash.py`
- Current mitigation: Pattern matching for dangerous commands, approval workflow
- Recommendations: Use `shlex` for proper escaping, consider allowlist-only mode

**REST API Tool Exposes Network:**
- Risk: Arbitrary HTTP requests can be made to any allowed domain
- Files: `src/agentframework/tools/api.py`
- Current mitigation: Domain allowlist (not enabled by default)
- Recommendations: Enable strict allowlist by default, add rate limiting

## Performance Bottlenecks

**Synchronous SQLite in Async Context:**
- Problem: Memory tool and session manager use synchronous sqlite3
- Files: `src/agentframework/tools/memory.py`, `src/agentframework/session.py`
- Cause: sqlite3 library is synchronous, not using thread pool
- Improvement path: Use `aiosqlite` for async operations, or run in executor

**Large Output Truncation:**
- Problem: Bash (100k chars), Python (20k chars), API (20k chars) all truncate without warning
- Files: `src/agentframework/tools/bash.py`, `src/agentframework/tools/python.py`, `src/agentframework/tools/api.py`
- Cause: Context window protection
- Improvement path: Add explicit truncation messages with original size

**No Connection Pooling:**
- Problem: Each tool creates its own HTTP client
- Files: `src/agentframework/tools/web.py`, `src/agentframework/tools/api.py`
- Cause: Tools instantiate own httpx.AsyncClient
- Improvement path: Share HTTP client across tools

**Token Estimation Fallback:**
- Problem: Falls back to `len(text) / 4` when tiktoken fails
- Files: `src/agentframework/conversation.py` (line 40)
- Cause: Silent failure
- Improvement path: Log warning when using fallback estimation

## Fragile Areas

**Context Window Management:**
- Files: `src/agentframework/conversation.py`
- Why fragile: Complex logic with multiple conditions (message count, char count, summarization trigger)
- Safe modification: Add unit tests for each edge case before changing
- Test coverage: Limited - only tested indirectly through agent tests

**Tool Call Extraction (Ollama):**
- Files: `src/agentframework/providers/ollama.py`
- Why fragile: Multiple regex patterns and edge cases for different model outputs
- Safe modification: Add test cases for each model type before changing extraction
- Test coverage: Basic - uses mocked responses

**Session Deserialization:**
- Files: `src/agentframework/session_runtime.py`
- Why fragile: Message reconstruction from dict could fail on schema changes
- Safe modification: Add version field to serialized messages
- Test coverage: None for backward compatibility

## Scaling Limits

**Memory Tool FTS5:**
- Current capacity: Unlimited theoretically, but FTS5 can degrade with millions of entries
- Limit: Performance degrades around 10M+ entries
- Scaling path: Implement pagination, add index optimization

**Session Storage:**
- Current capacity: Single SQLite file, grows indefinitely
- Limit: File system space, SQLite performance degradation >10GB
- Scaling path: Implement session rotation/archival, consider time-series DB

**Concurrent Tool Execution:**
- Current capacity: Parallel execution supported but limited by tool timeouts
- Limit: Default 60s bash timeout, 10s Python timeout
- Scaling path: Add configurable per-tool timeouts, implement queue for rate limiting

## Dependencies at Risk

**ddgs Package:**
- Risk: DuckDuckGo search API can change without notice, library may become outdated
- Impact: Web search tool stops working
- Migration plan: Add alternative search provider (SerpAPI, Bing, or Tavily)

**chromadb:**
- Risk: Heavy dependency, can fail silently on initialization errors
- Impact: RAG tools fail completely
- Migration plan: Add fallback to simple text search or in-memory vector store

**instructor Library:**
- Risk: Used for structured extraction, API can change
- Impact: `extract_data` method breaks
- Migration plan: Implement native structured extraction per provider

## Missing Critical Features

**Retry Logic:**
- Problem: No automatic retry for transient failures (network timeouts, rate limits)
- Blocks: Reliable production usage
- Priority: High

**Circuit Breaker:**
- Problem: No way to stop calling failing services
- Blocks: Resilience to downstream failures
- Priority: High

**Observability:**
- Problem: No metrics, traces, or health checks
- Blocks: Production monitoring
- Priority: Medium

**Rate Limiting:**
- Problem: No protection against API rate limits
- Blocks: Reliable API usage
- Priority: Medium

## Test Coverage Gaps

**CLI Configuration:**
- What's not tested: Config file loading, error handling for missing configs
- Files: `src/agentframework/config.py`, `src/agentframework/bootstrap.py`
- Risk: Misconfiguration goes unnoticed
- Priority: Medium

**Integration Tests:**
- What's not tested: Full agent workflows with real LLM calls
- Files: End-to-end scenarios
- Risk: Real-world issues not caught
- Priority: High

**Security Tests:**
- What's not tested: Path traversal bypasses, command injection patterns
- Files: `src/agentframework/safety.py`, tool implementations
- Risk: Security vulnerabilities go undetected
- Priority: High

**Error Recovery:**
- What's not tested: Agent recovery from tool failures mid-conversation
- Files: `src/agentframework/agent.py`
- Risk: Cascading failures
- Priority: Medium

---

*Concerns audit: 2026-03-08*
