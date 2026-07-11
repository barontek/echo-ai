# Security Remediation Plan — Echo AI Database Encryption

**Date**: 2026-07-11
**Scope**: 10 vulnerabilities in the database encryption system

## Priority Order

| # | Vulnerability | Priority | Effort | Dependencies |
|---|--------------|----------|--------|--------------|
| V1 | Module-level Fernet singleton | Critical | Large | — |
| V2 | SQLite WAL mode + file permissions | Critical | Medium | — |
| V3 | Scrypt N below modern standard | Critical | Small | — |
| V4 | Process-level unlock no logout | High | Medium | — |
| V5 | Environment variable leak | High | Small | — |
| V6 | Rate limiting bypassable | High | Small | — |
| V7 | Plaintext metadata (titles) | Medium | Medium | V1 (EncryptedJSON refactor) |
| V8 | TOCTOU in _is_session_db guard | Medium | Small | — |
| V9 | WAL artifact exposure | Medium | Small | V2 overlap |
| V10 | No mutual auth on API | Low | Small | — |

## Execution Order

1. V3 — Scrypt N (single constant change)
2. V2 — WAL mode + file permissions (PRAGMA + chmod)
3. V1 — Module-level Fernet singleton (heavy refactor)
4. V8 — TOCTOU guard fix (tools/db.py)
5. V5 — Env var scrubbing (db_crypto.py)
6. V6 — Global rate limit + exponential backoff (unlock.py + rate_limit.py)
7. V4 — Token-based unlock (unlock.py + web_models.py + client.ts + web_api.py)
8. V7 — Encrypt titles (session.py + sessions.py)
9. V9 — WAL checkpoint on close (session.py — overlaps V2)
10. V10 — API key hardening + TLS warning (web_api.py)
