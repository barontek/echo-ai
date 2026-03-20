# Echo AI - Project Changelog

## Changelog

| Date | Changes |
|------|---------|
| 2026-03-20 | Review fixes: pyopenssl updated, ResourceWarnings fixed, web_ui.py removed |
| 2026-03-19 | Database indexes added for sessions and memories |
| 2026-03-19 | Docker: non-root user, resource limits, docker-compose |
| 2026-03-19 | Rate limiting: skip localhost, tests added |
| 2026-03-19 | Testing: rate limiting (10 tests), concurrency (8 tests) |
| 2026-03-19 | Documentation: CONTRIBUTING, RUNBOOK, SECURITY, PERFORMANCE |
| 2026-03-19 | OpenAPI docs at `/docs` |
| 2026-03-19 | Phase 3: Syntax highlighting, rate limiting, modularity, a11y, event sourcing |
| 2026-03-19 | Phase 2: AppState+DI, structured logging, correlation IDs |
| 2026-03-19 | Phase 1: Tests, debug removal, health endpoint, regex, tiktoken |

---

## Review 2026-03-20

### Current State
- 369 tests, 84% coverage
- 0 ruff errors, 0 pyright errors
- Production-ready

### Fixed This Session
- [x] CVEs: pyopenssl updated to 26.0.0 (nltk/diskcache already latest)
- [x] ResourceWarnings: Fixed SQLite connection cleanup in session migrations
- [x] Removed web_ui.py stub

### Skipped (Low Priority)
- ESLint for JavaScript (npm complexity not worth it)
- SQL LIKE query fix (was already parameterized - review was wrong)
- Duplicate thinking extraction refactor (medium effort, low benefit)

### What's Working Well
- Test suite (369 tests)
- Safety layer (path traversal, command injection protection)
- Modularity, type safety, documentation
- WebSocket implementation
- Session management with migrations

---

## Ideas for Future

<!-- Add improvement ideas here -->
