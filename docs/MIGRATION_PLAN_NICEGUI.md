# Migration Plan: FastHTML to NiceGUI

## Executive Summary

This document outlines a comprehensive plan to migrate the Echo AI web UI from FastHTML to NiceGUI. The migration is driven by persistent issues with FastHTML's HTMX integration, particularly around OOB (out-of-band) swaps and dynamic content replacement.

## Current State Analysis

### FastHTML Implementation (Working Directory: `/home/barontek/echo-ai/src/agentframework/ui/`)

| File | Purpose | Lines |
|------|---------|-------|
| `__init__.py` | Module exports | 5 |
| `app.py` | Routes, WebSocket handler, state management | 265 |
| `components.py` | UI components, CSS, JavaScript | 1008 |
| `markdown.py` | Markdown rendering with syntax highlighting | 50 |

### Key Features Used
1. **HTMX** - Dynamic partial page updates
2. **WebSockets** - Real-time streaming responses
3. **Component Functions** - Return FastHTML elements
4. **Inline CSS/JS** - Custom styling and interactions
5. **Async Streaming** - Agent response streaming

### Persistent Issues (Root Cause: FastHTML/HTMX)
- OOB swaps causing nested element issues
- Content replacement not working correctly for chat container
- Browser-specific rendering inconsistencies

---

## Why NiceGUI?

### Advantages
1. **True Python-First** - No HTML/HTMX knowledge required
2. **Native WebSocket Support** - Built-in real-time updates
3. **Component-Based Architecture** - `@ui.page`, `@ui.component` decorators
4. **Vue/Quasar Backend** - Modern, reliable frontend
5. **Live Reload** - Automatic UI refresh during development
6. **Better State Management** - Native Python state handling
7. **Active Development** - v3.0 released Oct 2025 with major improvements

### NiceGUI Stack
- **Backend**: FastAPI
- **Frontend**: Vue.js + Quasar Framework
- **Styling**: Tailwind CSS (built-in)
- **Real-time**: WebSockets for live updates

---

## Migration Strategy

### Phase 1: Project Setup (Day 1)
**Goal**: Set up NiceGUI alongside existing FastAPI backend

#### Tasks
1. Add NiceGUI to dependencies
   ```toml
   # pyproject.toml
   nicegui>=3.0.0
   ```

2. Create new directory structure
   ```
   src/agentframework/
   ├── ui/                    # Keep FastHTML for fallback
   │   ├── __init__.py
   │   ├── app.py
   │   ├── components.py
   │   └── markdown.py
   └── ui_nicegui/            # New NiceGUI implementation
       ├── __init__.py
       ├── app.py             # Main NiceGUI app
       ├── pages/
       │   ├── __init__.py
       │   ├── chat.py        # Main chat page
       │   └── sessions.py     # Session management
       ├── components/
       │   ├── __init__.py
       │   ├── sidebar.py
       │   ├── message.py
       │   ├── chat_input.py
       │   └── markdown.py
       └── theme.py           # Shared styling
   ```

3. Update `web_api.py` mount point
   ```python
   # Option A: Replace FastHTML with NiceGUI
   from src.agentframework.ui_nicegui.app import ui as nicegui_app
   app.mount("/ui", nicegui_app)

   # Option B: Route-based (keep both)
   @app.get("/ui")
   async def redirect_to_nicegui():
       return RedirectResponse("/nicegui/")
   ```

#### Deliverables
- [ ] NiceGUI installed and running
- [ ] Basic page rendering without errors
- [ ] Backend integration verified

---

### Phase 2: Core Layout (Day 1-2)
**Goal**: Implement main page layout matching current design

#### Tasks

2.1 **Theme & Styling Setup**
```python
# theme.py
from nicegui import ui

# Color palette matching current design
DARK_THEME = {
    'primary': '#58a6ff',
    'secondary': '#238636',
    'accent': '#da3633',
    'dark': '#0e1117',
    'dark-page': '#161b22',
    'positive': '#238636',
    'negative': '#da3633',
    'info': '#58a6ff',
    'warning': '#d29922',
}

def setup_theme():
    ui.dark_mode().enable()
    ui.colors(**DARK_THEME)
```

2.2 **Main Layout Structure**
```python
# pages/chat.py
@ui.page('/nicegui/')
async def chat_page(client: ui.Client):
    # Sidebar
    with ui.column().classes('sidebar'):
        with ui.column().classes('sidebar-header'):
            ui.label('Echo AI').classes('text-h5 text-primary')
            theme_toggle()

        with ui.column().classes('sidebar-section'):
            model_selector()

        with ui.column().classes('sidebar-section').style('flex: 1; overflow-y: auto'):
            session_list()

        with ui.column().classes('sidebar-footer'):
            new_chat_button()

    # Main content area
    with ui.column().classes('main'):
        chat_header()
        chat_container()  # This will need reactive updates
        chat_input()
```

2.3 **CSS Customization**
```python
# Add custom CSS via ui.add_css()
CUSTOM_CSS = """
:root {
    --bg-primary: #0e1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --border-color: #30363d;
    --text-primary: #ececf1;
    --text-secondary: #8b949e;
    --accent-blue: #58a6ff;
    --accent-green: #238636;
    --accent-red: #da3633;
    --code-bg: #161b22;
}

.app {
    display: flex;
    height: 100vh;
    background: var(--bg-primary);
}

.sidebar {
    width: 280px;
    background: var(--bg-secondary);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
}
"""

ui.add_css(CUSTOM_CSS)
```

#### Deliverables
- [ ] Main layout matches current design
- [ ] Sidebar with sessions list
- [ ] Theme toggle working
- [ ] Responsive design verified

---

### Phase 3: Components - Static (Day 2-3)
**Goal**: Implement all UI components without interactivity

#### 3.1 Message Bubble Component
```python
# components/message.py
from nicegui import ui

def message_bubble(role: str, content: str, thinking: str = "", tool_calls: list = None):
    """Render a chat message bubble."""
    bubble_classes = 'message user' if role == 'user' else 'message assistant'

    with ui.column().classes(bubble_classes).style('width: 100%'):
        # Avatar/Role indicator
        with ui.row().classes('message-header'):
            avatar = '👤' if role == 'user' else '🤖'
            ui.label(avatar).classes('text-sm')
            ui.label('You' if role == 'user' else 'Assistant').classes('text-xs text-secondary')

        # Content
        content_html = render_markdown(content)
        ui.html(f'<div class="message-content">{content_html}</div>')

        # Tool calls (if any)
        if tool_calls:
            tool_call_section(tool_calls)

        # Thinking indicator (if any)
        if thinking:
            thinking_section(thinking)

def tool_call_section(tool_calls: list):
    """Collapsible tool call display."""
    with ui.expansion('Tool Calls', icon='build').classes('tool-calls'):
        for tool in tool_calls:
            with ui.card().classes('tool-call'):
                ui.label(f'🔧 {tool.get("name", "Unknown")}').classes('font-bold')
                ui.code(json.dumps(tool.get('arguments', {}), indent=2))

def thinking_section(thinking: str):
    """Display thinking process."""
    with ui.expansion('Thinking', icon='psychology').classes('thinking-section'):
        ui.html(render_markdown(thinking))
```

#### 3.2 Chat Container Component
```python
# components/chat_container.py
from nicegui import ui

class ChatContainer:
    def __init__(self):
        self.messages = []
        self.container = None

    def create(self):
        with ui.column().classes('chat-container').style('flex: 1; overflow-y: auto; padding: 1rem;') as self.container:
            self._render_messages()
        return self.container

    def _render_messages(self):
        if not self.messages:
            empty_state()
        else:
            for msg in self.messages:
                message_bubble(
                    role=msg.get('role'),
                    content=msg.get('content', ''),
                    thinking=msg.get('thinking', ''),
                    tool_calls=msg.get('tool_calls', [])
                )

    def update(self, messages: list):
        """Update container with new messages."""
        self.messages = messages
        self.container.clear()
        with self.container:
            self._render_messages()

def empty_state():
    """Render empty chat state."""
    with ui.column().classes('empty-state').style('flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;'):
        ui.label('How can I help you today?').classes('text-h4')
        quick_actions()

def quick_actions():
    """Quick action buttons."""
    actions = [
        ('Search AI News', 'Search the web for the latest news on Artificial Intelligence'),
        ('Write Python Server', 'Write a python script that implements a simple FastAPI server'),
        ('Extract Data', 'Help me extract structured entity data from a messy block of text'),
    ]

    with ui.row().classes('quick-actions').style('gap: 0.5rem; flex-wrap: wrap; margin-top: 1rem;'):
        for label, query in actions:
            ui.button(label, on_click=lambda q=query: send_message(q)).classes('btn')
```

#### 3.3 Chat Input Component
```python
# components/chat_input.py
from nicegui import ui

class ChatInput:
    def __init__(self, on_submit: callable):
        self.on_submit = on_submit
        self.input_field = None
        self.model_select = None

    def create(self):
        with ui.row().classes('chat-input-container').style('padding: 1rem; border-top: 1px solid var(--border-color); background: var(--bg-secondary);'):
            # Model selector
            self.model_select = ui.select(
                options=['qwen3:4b-instruct', 'llama3.2:3b'],
                value='qwen3:4b-instruct'
            ).props('dense outlined').style('width: 150px;')

            # Text input
            self.input_field = ui.input(
                placeholder='Type your message... (Enter to send)'
            ).props('outlined dense').style('flex: 1;').on('keydown.enter', self._handle_submit)

            # Send button
            ui.button('Send', icon='send', on_click=self._handle_submit).props('flat color=primary')

    def _handle_submit(self):
        message = self.input_field.value.strip()
        if message:
            model = self.model_select.value
            self.input_field.value = ''
            self.on_submit(message, model)
```

#### 3.4 Session List Component
```python
# components/sidebar.py
from nicegui import ui

class SessionList:
    def __init__(self, sessions: list, active_id: str = '', on_select: callable = None):
        self.sessions = sessions
        self.active_id = active_id
        self.on_select = on_select

    def create(self):
        with ui.column().classes('session-list').style('flex: 1; overflow-y: auto;'):
            # Search
            ui.input(
                placeholder='Search sessions...',
                on_change=lambda e: self._filter_sessions(e.value)
            ).props('dense outlined').classes('session-search-input')

            # Session items
            for session in self.sessions:
                session_item(session, is_active=session['id'] == self.active_id)

            if not self.sessions:
                ui.label('No sessions yet').classes('text-secondary text-center q-pa-md')

def session_item(session: dict, is_active: bool = False):
    """Render a single session item."""
    item_classes = 'session-item active' if is_active else 'session-item'

    with ui.row().classes(item_classes).style('padding: 0.5rem; cursor: pointer;').on('click', lambda: load_session(session['id'])):
        ui.label('💬').classes('session-icon')
        ui.label(session.get('title', 'New Chat')).classes('title')

        # Delete button
        ui.button('×', on_click=lambda e, s=session: delete_session(e, s)).props('flat round size=sm').classes('btn-delete')

def delete_session(e, session):
    """Handle session deletion."""
    e.stop_propagation()
    # Call backend to delete
    from src.agentframework.web_api import delete_session_data, get_state
    delete_session_data(session['id'], get_state())
    # Refresh session list
    ui.notify(f"Deleted: {session.get('title', 'session')}")
    refresh_session_list()
```

#### 3.5 Markdown Renderer
```python
# components/markdown.py
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
import re

CODE_BLOCK_PATTERN = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)

def render_markdown(text: str) -> str:
    """Render markdown with syntax highlighting."""

    def replace_code(match):
        lang = match.group(1) or 'text'
        code = match.group(2)

        try:
            lexer = get_lexer_by_name(lang)
        except:
            lexer = guess_lexer(code) if code else None

        if lexer:
            highlighted = highlight(code, lexer, HtmlFormatter())
            return f'<div class="code-block">{highlighted}</div>'
        return f'<pre><code>{code}</code></pre>'

    text = CODE_BLOCK_PATTERN.sub(replace_code, text)

    html = markdown.markdown(
        text,
        extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists']
    )

    return html
```

#### Deliverables
- [ ] All components implemented
- [ ] Layout matches current design
- [ ] CSS styling applied
- [ ] No JavaScript errors

---

### Phase 4: Dynamic Interactivity (Day 3-4)
**Goal**: Add all interactive features

#### 4.1 State Management
```python
# app.py
from nicegui import app, ui
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ChatState:
    current_session_id: Optional[str] = None
    messages: list = field(default_factory=list)
    model: str = 'qwen3:4b-instruct'
    is_streaming: bool = False

# Global state (per-user in production)
user_states = {}

def get_user_state(client_id: str) -> ChatState:
    if client_id not in user_states:
        user_states[client_id] = ChatState()
    return user_states[client_id]
```

#### 4.2 Session Management
```python
@ui.page('/nicegui/sessions/new')
async def new_session():
    """Create a new session."""
    from src.agentframework.web_api import create_session_data, get_state

    state = get_state()
    data = create_session_data(state)

    if data.get('session_id'):
        # Update global state
        chat_state = get_user_state(str(id(ui.context.client)))
        chat_state.current_session_id = data['session_id']
        chat_state.messages = []

        # Update UI - navigate to new session
        ui.navigate.to(f'/nicegui/sessions/{data["session_id"]}')
    else:
        ui.notify('Failed to create session', type='negative')
```

#### 4.3 Loading a Session
```python
@ui.page('/nicegui/sessions/{session_id}')
async def load_session_page(session_id: str):
    """Load a specific session."""
    from src.agentframework.web_api import load_session_data, get_state

    state = get_state()
    data = load_session_data(session_id, state)

    if error := data.get('error'):
        ui.notify(error, type='negative')
        ui.navigate.to('/nicegui/')
        return

    messages = data.get('messages', [])

    # Update state
    chat_state = get_user_state(str(id(ui.context.client)))
    chat_state.current_session_id = session_id
    chat_state.messages = messages

    # Re-render chat container
    await render_full_page(chat_state)
```

#### 4.4 Chat Submission & Streaming
```python
async def send_message(message: str, model: str):
    """Handle sending a message and streaming response."""
    chat_state = get_user_state(str(id(ui.context.client)))

    # Add user message
    user_msg = {
        'role': 'user',
        'content': message,
        'timestamp': datetime.now().isoformat()
    }
    chat_state.messages.append(user_msg)
    append_message_to_ui(user_msg)

    # Create placeholder for assistant response
    assistant_msg = {
        'role': 'assistant',
        'content': '',
        'thinking': '',
        'timestamp': datetime.now().isoformat()
    }
    chat_state.messages.append(assistant_msg)
    placeholder = append_message_to_ui(assistant_msg, placeholder=True)

    # Stream response
    chat_state.is_streaming = True

    async def on_chunk(chunk: str):
        # Parse thinking markers
        if '__THINKING__' in chunk:
            in_thinking = True
            chunk = chunk.replace('__THINKING__', '')
        if '__THINKING_END__' in chunk:
            in_thinking = False
            chunk = chunk.replace('__THINKING_END__', '')

        assistant_msg['content'] += chunk
        update_placeholder(placeholder, assistant_msg)

    # Run streaming
    from src.agentframework.agent import Agent
    agent = create_agent(model)
    await agent.run_streaming(message, on_chunk=on_chunk)

    chat_state.is_streaming = False
    ui.notify('Response complete')
```

#### 4.5 Real-time Updates
```python
# NiceGUI's reactive system handles updates automatically
# No need for HTMX OOB swaps!

# Instead of HTMX, use NiceGUI's async updates:
async def update_chat_container():
    chat_container.clear()
    with chat_container:
        for msg in chat_state.messages:
            message_bubble(msg)
```

#### Deliverables
- [ ] Session creation works
- [ ] Session loading works
- [ ] Message streaming works
- [ ] Real-time UI updates without page reload

---

### Phase 5: Integration & Polish (Day 4-5)
**Goal**: Final integration and bug fixes

#### 5.1 Backend Integration
```python
# Ensure all backend functions work with NiceGUI
# Most should work unchanged, but verify:

# src/agentframework/web_api.py
# Functions used:
- create_session_data(state)
- load_session_data(session_id, state)
- delete_session_data(session_id, state)
- get_sessions_data(state)
- get_models_sync()
- _create_runtime_agent(config)
```

#### 5.2 WebSocket for Streaming
```python
# NiceGUI handles WebSocket automatically
# No custom WebSocket code needed!

@ui.page('/nicegui/')
async def main_page(client: ui.Client):
    # NiceGUI creates WebSocket automatically
    # State is per-client
    pass
```

#### 5.3 Error Handling
```python
# Global error handler
app.exceptions['all'].handle(my_error_handler)

async def my_error_handler(e: Exception):
    ui.notify(f'Error: {str(e)}', type='negative', timeout=0)
    logging.error(f'Unhandled error: {e}', exc_info=True)
```

#### 5.4 Testing
```python
# tests/test_ui_nicegui.py
import pytest
from nicegui.testing import User

@pytest.fixture
def client():
    with ui.test_client() as client:
        yield client

async def test_main_page(client: User):
    await client.open('/nicegui/')
    assert client.find('Echo AI')  # Title visible
    assert client.find('How can I help you today?')  # Empty state

async def test_send_message(client: User):
    await client.open('/nicegui/')
    client.type('chat-input', 'Hello')
    client.click('Send')

    # Wait for response
    await client.wait_for('assistant')
    assert client.find('.message.assistant')
```

#### 5.5 Performance Optimizations
```python
# Virtual scrolling for long message lists
with ui.scroll_area().props('virtual-scroll'):
    for msg in chat_state.messages:
        message_bubble(msg)

# Debounce input
from nicegui import ui
debounced_search = ui.debounce(search_sessions, 300)
```

#### 5.6 Mobile Responsiveness
```python
# Use Tailwind classes for responsiveness
with ui.column().classes('md:flex-row'):
    # Sidebar hides on mobile
    with ui.column().classes('hidden md:block'):
        sidebar()
    # Main content always visible
    main_content()
```

#### Deliverables
- [ ] All features working
- [ ] Tests passing
- [ ] Performance acceptable
- [ ] Mobile responsive

---

### Phase 6: Deployment (Day 5)
**Goal**: Production-ready deployment

#### 6.1 Configuration
```python
# Run configuration
ui.run(
    title='Echo AI',
    port=8000,
    reload=True,  # Only in development
    storage_secret='your-secret-key',  # For session storage
    uvicorn_log_level='info',
)
```

#### 6.2 Docker
```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY uv.lock pyproject.toml ./
RUN pip install uv && uv sync
COPY . .
EXPOSE 8000
CMD ["uv", "run", "python", "-m", "src.agentframework.ui_nicegui.app"]
```

#### 6.3 Update Main Entry Point
```python
# src/agentframework/__main__.py or run.py
from src.agentframework.ui_nicegui.app import ui
ui.run()
```

#### 6.4 Nginx/Caddy Reverse Proxy
```nginx
# For production behind reverse proxy
location /nicegui/ {
    proxy_pass http://localhost:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

---

## Component Mapping

| FastHTML | NiceGUI Equivalent |
|----------|-------------------|
| `Div(cls='sidebar')` | `ui.column().classes('sidebar')` |
| `Button('Click', hx_post='/url')` | `ui.button('Click').on('click', handler)` |
| `Form(hx_post='/chat', hx_ext='ws')` | `ui.input().on('enter', send_handler)` |
| `Div(id='chat-container')` | `ui.column().props('id=chat-container')` |
| `H2('Title')` | `ui.label('Title').classes('text-h4')` |
| `Style(CSS)` | `ui.add_css(CSS)` |
| `Script(JS)` | Inline Python callbacks |
| `Safe(html)` | `ui.html(html)` |
| `markdown()` | `render_markdown()` |

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Learning curve | Medium | NiceGUI docs are excellent; similar to Streamlit |
| Performance at scale | Low | NiceGUI uses efficient Vue.js rendering |
| Real-time updates | Low | Native WebSocket support |
| Browser compatibility | Low | Vue.js/Quasar handles this |
| Streaming complexity | Medium | Need to test agent streaming integration |

---

## Rollback Plan

1. Keep FastHTML implementation in `ui/` directory
2. Use environment variable to switch:
   ```python
   USE_NICEGUI = os.getenv('USE_NICEGUI', 'false').lower() == 'true'

   if USE_NICEGUI:
       app.mount("/ui", nicegui_app)
   else:
       app.mount("/ui", fasthtml_app)
   ```
3. Deploy NiceGUI to staging first
4. Monitor for issues before production switch

---

## Success Criteria

- [ ] All current features work in NiceGUI
- [ ] Streaming responses display correctly
- [ ] Session management works seamlessly
- [ ] Theme toggle functions properly
- [ ] Mobile experience is acceptable
- [ ] No significant performance regression
- [ ] Tests cover critical paths

---

## Time Estimate

| Phase | Duration | Notes |
|-------|----------|-------|
| Phase 1: Setup | 1 day | Dependencies, structure |
| Phase 2: Layout | 1-2 days | Core layout, styling |
| Phase 3: Components | 2-3 days | Static components |
| Phase 4: Interactivity | 2-3 days | State, streaming |
| Phase 5: Polish | 1-2 days | Integration, testing |
| Phase 6: Deploy | 1 day | Production readiness |
| **Total** | **8-12 days** | |

---

## References

- NiceGUI Documentation: https://nicegui.io/documentation
- NiceGUI GitHub: https://github.com/zauberzeug/nicegui
- Talk Python Episode: https://talkpython.fm/episodes/show/525/nicegui-goes-3-0
- Quasar Components: https://quasar.dev/
- Tailwind CSS: https://tailwindcss.com/
