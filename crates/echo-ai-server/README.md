# echo-ai-server

`HTTPS`/`HTTP` + `WebSocket` frontend over axum, replacing the C
project's libuv server. Includes built-in `TLS` (axum-server + rustls,
local CA + localhost cert generated on first run), unlock-token
middleware, per-IP rate limiting, `SSE`, and static serving of the
vendored frontend build.

## Module map

| Module | Responsibility |
|---|---|
| `server` | axum app assembly, `TLS` setup, lifecycle |
| `tls` | rcgen local CA + cert generation, `PEM` loading, 0600 key handling |
| `routes` | all REST endpoints, `SSE`, `/ws/chat` protocol (frames 1:1 with C) |
| `middleware` | constant-time token compare, unlock gating, rate limit, `CORS` |

## Testing

Route-table parity tests against the C endpoint list, `WS` protocol frame
tests, cert-lifecycle tests, middleware auth tests in `tests/`.