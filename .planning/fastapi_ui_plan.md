# FastAPI + Vanilla JS Web UI Plan

## Overview
Replace Streamlit with FastAPI backend + vanilla JS frontend for maximum performance and real-time streaming.

## Architecture

```
                    ┌─────────────────┐
                    │   Browser       │
                    │  (Vanilla JS)   │
                    └────────┬────────┘
                             │ WebSocket
                             │ HTTP
                             ▼
                    ┌─────────────────┐
                    │   FastAPI       │
                    │   Backend       │
                    └────────┬────────┘
                             │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────────┐  ┌──────────┐
        │  Agent   │   │   Sessions   │  │  Ollama  │
        │  Logic   │   │   Storage    │  │   API    │
        └──────────┘   └──────────────┘  └──────────┘
```

## Features to Preserve

### Current Features
- [x] Chat interface with streaming
- [x] Theme toggle (dark/light)
- [x] Message timestamps
- [x] Session management (save/load)
- [x] Provider/model selection
- [x] Thinking process display
- [x] Session history list

### New Features (Enabled by FastAPI)
- [x] True real-time streaming (WebSocket)
- [x] Better state management
- [x] No page reloads
- [x] Keyboard shortcuts

## API Endpoints

### HTTP Endpoints
```
GET  /                  - Serve index.html
GET  /static/js/main.js - Serve JS
GET  /static/css/style.css - Serve CSS
GET  /api/models       - List available models
POST /api/chat         - Send chat message (non-streaming)
GET  /api/sessions     - List sessions
POST /api/sessions     - Create new session
GET  /api/sessions/{id} - Load session
DELETE /api/sessions/{id} - Delete session
POST /api/config       - Update agent config
```

### WebSocket Endpoint
```
WS   /ws/chat         - Real-time streaming chat
```

## Frontend Structure (Vanilla JS)

```
static/
├── index.html    - Main HTML
├── css/
│   └── style.css - All styles
├── js/
│   └── app.js   - Main application
```

## UI Layout

```
┌─────────────────────────────────────────────────┐
│  Header: Logo | Model Selector | Theme Toggle  │
├──────────────┬──────────────────────────────────┤
│              │                                  │
│   Sidebar    │         Main Chat Area           │
│              │                                  │
│  - Sessions  │   ┌─────────────────────────┐   │
│  - New Chat  │   │ User message            │   │
│  - Session   │   │                         │   │
│    List      │   ├─────────────────────────┤   │
│              │   │ AI Response             │   │
│              │   │ [Thinking] (collapsible)│   │
│              │   │                         │   │
│              │   └─────────────────────────┘   │
│              │                                  │
│              │   ┌─────────────────────────┐   │
│              │   │ Input field             │   │
│              │   └─────────────────────────┘   │
└──────────────┴──────────────────────────────────┘
```

## Implementation Steps

### Phase 1: Backend
1. Create FastAPI app in `src/agentframework/web_api.py`
2. Implement WebSocket chat endpoint
3. Add session management endpoints
4. Add model listing endpoint
5. Create static file serving

### Phase 2: Frontend
1. Create HTML structure
2. Implement CSS (dark/light themes)
3. Build JS app with WebSocket client
4. Add chat UI logic
5. Add session management UI
6. Add keyboard shortcuts

### Phase 3: Integration
1. Replace streamlit entry point
2. Update Makefile/CLI
3. Test all features

## File Changes

### New Files
- `src/agentframework/web_api.py` - FastAPI application
- `static/index.html` - HTML template
- `static/css/style.css` - Styles
- `static/js/app.js` - Frontend JS

### Modified Files
- `scripts/run_web.py` - Point to new API
- `Makefile` - Update commands

### Removed Files
- `src/agentframework/web_ui.py` - Streamlit UI (keep for reference)
