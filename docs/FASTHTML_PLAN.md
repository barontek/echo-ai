# FastHTML Implementation Plan for Echo AI

## Overview

Replace the static HTML/JS frontend with FastHTML for a pure-Python web UI.

**Benefits:**
- No JavaScript needed (except optional for complex interactions)
- No npm, no build tools
- All UI logic in Python
- Easier to maintain, test, and extend

**Key Challenge:**
The current UI uses WebSockets for streaming. FastHTML supports WebSockets but differently - we'll need to adapt.

---

## Current State Analysis

### Frontend Files (to be replaced)
```
static/
├── index.html          (87 lines - HTML structure)
├── css/style.css       (604 lines - styling)
└── js/
    ├── main.js         (663 lines - app logic)
    ├── state.js       (state management)
    ├── app.js         (entry point)
    ├── components/
    │   └── ui.js      (449 lines - rendering)
    └── services/
        ├── api.js      (REST calls)
        └── websocket.js (WebSocket client)
```

### Key Features
| Feature | Current Implementation |
|---------|------------------------|
| Model selection | JS + API call |
| Session list | JS + API call |
| Chat input | JS event handler |
| Message streaming | WebSocket |
| Thinking display | JS parsing |
| Markdown rendering | marked.js + DOMPurify |
| Code highlighting | Prism.js |
| Theme toggle | JS + CSS variables |
| Accessibility | ARIA, skip links |

---

## FastHTML Architecture

### New Structure
```
src/agentframework/
├── web_api.py          (existing - keep API endpoints)
├── ui/
│   ├── __init__.py
│   ├── app.py          (FastHTML app setup)
│   ├── pages.py        (page components)
│   ├── components.py   (reusable UI components)
│   └── ws.py           (WebSocket handling)
├── static/             (keep for assets if needed)
└── templates/          (minimal - mostly Python-generated)
```

### Components to Build

| Component | FastHTML Equivalent |
|-----------|-------------------|
| Page layout | `Div`, `Header`, `Main`, `Aside` |
| Chat message | `Card` or custom `Div` with classes |
| Input form | `Form`, `Input`, `Button` |
| Session list | `Ul`, `Li` with `onclick` handlers |
| Model select | `Select`, `Option` |
| Theme toggle | `Input(type='checkbox')` with hx-trigger |

---

## Implementation Phases

### Phase 1: Setup & Basic App
**Goal:** Get FastHTML serving a basic page

1. Add `python-fasthtml` to dependencies
2. Create `src/agentframework/ui/` module
3. Build minimal FastHTML app that renders the main page
4. Test serving at `/ui` route

**Deliverable:** `http://localhost:8000/ui` shows basic chat UI

### Phase 2: Core Components
**Goal:** Build all UI components in FastHTML

1. `Header` - logo, model badge, metrics
2. `Sidebar` - model select, session list, controls
3. `ChatContainer` - message display area
4. `ChatInput` - message input form
5. `MessageBubble` - individual messages with markdown

**Deliverable:** Static UI renders correctly

### Phase 3: Interactivity (HTMX)
**Goal:** Make UI work without WebSockets

1. HTMX for form submissions (send message)
2. HTMX for session management (new, delete, rename)
3. HTMX for model switching
4. Server-Sent Events (SSE) for streaming responses

**Key Decision:** Use SSE instead of WebSocket for streaming
- SSE is simpler with HTMX
- Built into FastHTML
- No client-side JS needed

**Deliverable:** Chat works via HTMX + SSE

### Phase 4: Advanced Features
**Goal:** Match all current functionality

1. Markdown rendering (use `markdown` Python library, render server-side)
2. Code highlighting (use `rich` or `pygments` for HTML output)
3. Theme toggle (CSS variables + HTMX swap)
4. Thinking display (extract and render server-side)
5. Session search/filter

**Deliverable:** Feature parity with current UI

### Phase 5: Polish
**Goal:** Match UX quality

1. Accessibility (ensure keyboard nav works)
2. Mobile responsive (CSS media queries)
3. Loading states (HTMX indicators)
4. Error handling (user-friendly messages)
5. Animation/transitions (CSS)

### Phase 6: Migration
**Goal:** Clean transition

1. Make `/ui` the default route (`/`)
2. Keep old `/static` for any remaining assets
3. Deprecate old WebSocket endpoint
4. Update documentation

---

## Technical Decisions

### Streaming: Keep WebSockets (Updated)

**Decision: Keep WebSockets**
FastHTML has first-class WebSocket support and HTMX's `hx-ext="ws"` extension.

```python
@app.ws('/chat-ws')
async def ws(ws):
    async for msg in ws:
        # Yield FastHTML components directly - HTMX swaps into DOM
        yield Div(P("Streaming response..."), id="msg-1")
```

**Benefits:**
- Maps directly to existing `web_api.py` WebSocket logic
- No bidirectional protocol change needed
- HTMX handles DOM updates automatically
- Less work than rewriting for SSE

**Markdown Streaming Strategy:**
1. Accumulate tokens on server
2. Render full Markdown → HTML
3. Send complete HTML via WebSocket
4. HTMX swaps into DOM

**Note:** Partial HTML tags (streaming `<strong>`) breaks DOM. Solution: accumulate + render + send full message bubble.

### Markdown Rendering

**Option A: Server-side**
```python
import markdown
html = markdown.markdown(content, extensions=['fenced_code', 'codehilite'])
```
- No client JS needed
- Render once, cache possible

**Option B: Client-side (keep marked.js)**
- CDN loaded
- Current approach
- Works but adds JS dependency

**Recommendation:** Server-side with Python `markdown`

### Code Highlighting

**Option A: Pygments HTML output**
```python
from pygments import highlight
from pygments.formatters import HtmlFormatter
html = highlight(code, lexer, HtmlFormatter())
```
- Pure Python
- Can pre-render

**Option B: Prism.js (CDN)**
- Current approach
- Need JS on client

**Recommendation:** Pygments server-side

---

## Migration Path

### Parallel Deployment
1. Build FastHTML UI at `/ui`
2. Keep existing UI at `/` (static files)
3. Test both
4. Switch default when stable

### FastAPI + FastHTML Integration

**Cannot mix decorators** - FastHTML `@rt()` and FastAPI `@app.get()` are separate.

**Solution: Mount FastHTML into FastAPI**
```python
# web_api.py
from fastapi import FastAPI
from fasthtml.common import *

# Create FastHTML app separately
fasthtml_app, rt = fast_app()

# Mount into FastAPI
app.mount("/ui", fasthtml_app)
```

**Result:**
- `/api/*` → FastAPI JSON endpoints (unchanged)
- `/ui/*` → FastHTML HTML UI (new)
- `/` → Static files (current UI)

### Data Flow Changes

**Before:**
```
Client JS -> WebSocket -> Agent -> LLM -> WebSocket -> Client JS -> DOM
```

**After (Phase 3+):**
```
Client (HTMX + FastHTML) -> WebSocket -> Agent -> LLM -> WebSocket -> HTMX -> DOM
```

---

## Effort Estimate

| Phase | Effort | Risk |
|-------|--------|------|
| Phase 1: Setup | Low | Low |
| Phase 2: Core Components | Medium | Medium |
| Phase 3: Interactivity | Medium | High (SSE learning) |
| Phase 4: Advanced Features | Medium | Low |
| Phase 5: Polish | Low | Low |
| Phase 6: Migration | Low | Low |

**Total:** ~3-5 days of work

---

## Files to Create/Modify

### New Files
```
src/agentframework/ui/
├── __init__.py
├── app.py              # FastHTML app setup
├── pages.py            # Page routes and layouts
├── components.py       # UI components (Message, Sidebar, etc.)
└── ws.py               # WebSocket/SSE handlers
```

### Modified Files
```
src/agentframework/web_api.py    # Add FastHTML mount or route
pyproject.toml                   # Add python-fasthtml dependency
docs/IMPLEMENTATION.md           # Document new architecture
```

### Deleted Files (after migration)
```
static/index.html
static/js/
static/css/style.css
```

---

## Rollback Plan

If FastHTML doesn't work out:
1. Keep old `/static` files
2. Point `/` back to static files
3. Delete `ui/` module
4. No data loss, minimal risk

---

## Testing Strategy

1. **Unit tests:** Test component rendering
2. **Integration tests:** Test full page loads
3. **Manual testing:** Chat flow, session management
4. **Compare output:** Ensure same HTML structure as current

---

## Decisions (Resolved)

| Decision | Answer | Rationale |
|----------|--------|-----------|
| SSE or WebSocket? | **WebSocket** | FastHTML has first-class WS + HTMX support, maps to existing code |
| Keep any client JS? | **No JS goal** | Start pure Python, add only if absolutely needed (e.g., copy button) |
| URL structure? | `/ui` during dev, `/` after | Parallel deployment at `/ui`, migrate to root when stable |
| Deprecation timeline? | Keep both indefinitely | Mounting doesn't break API, can run side-by-side forever |

## Key Insights from Review

1. **FastHTML WS yields components directly** - HTMX swaps into DOM automatically
2. **Markdown must accumulate** - Can't stream partial HTML tags; accumulate full message before rendering
3. **Mount, don't replace** - FastHTML mounts into FastAPI, existing API stays untouched
4. **Parallel deployment is safe** - Both UIs can run indefinitely with no conflicts
