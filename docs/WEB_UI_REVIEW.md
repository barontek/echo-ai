# Web UI Review (Performance-Conscious)

## Scope Reviewed

- `static/index.html` (Vanilla JS chat shell)
- `static/js/app.js` (frontend behavior, rendering, websocket lifecycle)
- `static/css/style.css` (theme system and component styles)
- `src/agentframework/web_api.py` (FastAPI + websocket streaming)
- `src/agentframework/web_ui.py` (Streamlit UI path)

## What is already strong

1. **Simple architecture with low runtime overhead**
   - The static UI is framework-free and has a very small client footprint.
   - This is a good baseline for responsiveness and startup speed.

2. **Progressive streaming experience exists**
   - The websocket path sends incremental `thinking` and `content` updates.
   - The frontend updates incrementally rather than waiting for full responses.

3. **Reasonable visual hierarchy and theming**
   - Dark/light theme variables are centralized in CSS custom properties.
   - Chat layout and CTA hierarchy are clear for first-time users.

4. **Session concepts are present**
   - APIs and sidebar UI support session listing, loading, and creating new chat.

## High-priority issues to address first (P0/P1)

### P0 — Websocket handler appears duplicated (correctness + performance risk)

In `web_api.py`, the websocket loop includes **two streaming pipelines in sequence** for each incoming prompt. This can cause duplicate events, extra compute, and unpredictable UX.

**Why it matters for robustness/performance:**
- Potential duplicate emissions to clients.
- Additional queue/task setup per message.
- Higher CPU and latency under load due to repeated work.

**Recommendation:**
- Refactor to one streaming path only (prefer the cancellation-aware variant).
- Keep a single sender queue/task lifecycle per prompt.
- Add a regression test verifying one `done` event per prompt.

### P1 — Frontend does unthrottled per-chunk DOM writes

`updateContent` and `updateThinking` apply DOM updates and auto-scroll on every chunk. For high token-rate streams this can produce frequent reflow/repaint work.

**Why it matters:**
- Choppy scrolling and increased main-thread time on slower devices.
- Unnecessary battery/CPU use with long responses.

**Recommendation:**
- Buffer chunks and flush UI with `requestAnimationFrame` (or ~30–60ms throttle).
- Only auto-scroll if user is near bottom.
- Use text-only updates when possible to avoid repeated `innerHTML` parsing.

### P1 — Inline HTML event handlers and repeated template strings

Thinking expanders are generated with inline `onclick` handlers and repeated string templates.

**Why it matters:**
- Harder maintenance and testing.
- Harder to enforce CSP later.
- More parsing overhead and duplicated logic.

**Recommendation:**
- Move to delegated event listeners (`container.addEventListener('click', ...)`).
- Create small helper render functions for thinking blocks and metadata.

## UX improvements that preserve performance

1. **Virtualized or windowed message rendering for large histories**
   - Keep full history in memory, render only last N messages + sentinel region.
   - Preserve fast scroll by lazy-loading older messages on demand.

2. **Session search + rename + delete with optimistic UI**
   - Current session list is functional; add ergonomics for many sessions.
   - Keep interactions local-first, sync in background to maintain snappiness.

3. **Improved empty/loading/error states**
   - Add explicit websocket reconnect banner and retry countdown.
   - Show model availability/loading placeholders while `/api/models` resolves.

4. **Token/latency instrumentation in header (lightweight)**
   - Show TTFB, total response time, and message count.
   - This helps users trust speed and helps detect regressions quickly.

5. **Accessibility pass (low-cost, high-value)**
   - Add ARIA labels for controls.
   - Ensure focus-visible styles and keyboard navigation for session items.
   - Improve contrast for some light-theme combinations.

## Technical recommendations by layer

### Frontend (`static/js/app.js`, `static/index.html`, `static/css/style.css`)

- Introduce a tiny rendering scheduler:
  - queue latest `thinking` and `content`
  - flush once per animation frame
- Split `formatContent` into safer stages:
  - parse markdown via a vetted renderer with sanitizer (or keep limited formatting but avoid complex regex chains for giant texts)
- Replace string-built HTML where possible with DOM APIs for better safety and incremental updates.
- Make message container use `content-visibility: auto;` for long logs to reduce off-screen layout cost.
- Add CSS `prefers-reduced-motion` support to reduce animation cost/accessibility issues.

### Backend websocket (`src/agentframework/web_api.py`)

- Remove duplicated streaming section.
- Introduce structured message schema validation (Pydantic models) for websocket payloads.
- Add per-connection state isolation (avoid mutable global `stop_flag` shared across clients).
- Add bounded queue or backpressure handling to prevent memory spikes under slow clients.
- Add ping/pong keepalive and stale connection cleanup strategy.

### Streamlit path (`src/agentframework/web_ui.py`)

- Minimize rerun pressure in `process_chat` where possible.
- Avoid event loop churn per message (creating new loop each prompt).
- Consider one UI path strategy long term:
  - either keep Streamlit for admin/workflows and static UI for chat
  - or standardize around one interface to reduce duplicate maintenance.

## Suggested roadmap (performance-safe sequence)

1. **Stability first**
   - Fix duplicated websocket pipeline.
   - Add websocket regression tests.

2. **Render performance**
   - Add chunk coalescing + smart autoscroll heuristic.
   - Profile with 1k+ line responses.

3. **Scalability UX**
   - Session management improvements (search/rename/delete).
   - Message windowing for very long chats.

4. **Quality and trust**
   - Accessibility pass.
   - Lightweight metrics in UI.

## Metrics to guard robustness after changes

Track before/after on same machine:

- Median/95p first token time.
- Median/95p full response time.
- Main-thread long tasks during streaming.
- Memory growth after 100-message session.
- Reconnect success rate after websocket interruption.

## Nice additions (optional)

- **Command palette** (`⌘/Ctrl + K`) for model switch, new session, session jump.
- **Message actions** (copy, regenerate, export markdown/json).
- **Pinned system prompts/profiles** for recurring tasks.
- **Compact mode** for dense chat logs.

## Bottom line

The current UI has a good lightweight foundation. The highest-leverage step is fixing websocket duplication and introducing render throttling; both directly improve reliability and perceived speed while preserving the minimal footprint.
