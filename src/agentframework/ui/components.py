"""UI components for FastHTML chat interface."""

from fasthtml.common import (
    Div,
    Span,
    H1,
    H2,
    Label,
    Select,
    Option,
    Button,
    Input,
    Form,
    Hidden,
    P,
    Style,
    Script,
    Title,
)  # noqa: F401, F403

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0e1117;
    color: #ececf1;
    min-height: 100vh;
}
.app { display: flex; height: 100vh; }

/* Sidebar */
.sidebar {
    width: 280px;
    background: #161b22;
    border-right: 1px solid #30363d;
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}
.sidebar-header {
    padding: 1rem;
    border-bottom: 1px solid #30363d;
}
.sidebar-header h1 {
    font-size: 1.25rem;
    color: #58a6ff;
}
.sidebar-section {
    padding: 1rem;
    border-bottom: 1px solid #30363d;
}
.sidebar-section label {
    display: block;
    font-size: 0.75rem;
    color: #8b949e;
    margin-bottom: 0.25rem;
    text-transform: uppercase;
}
.sidebar-section select {
    width: 100%;
    padding: 0.5rem;
    border-radius: 6px;
    border: 1px solid #30363d;
    background: #0d1117;
    color: #ececf1;
    font-size: 0.875rem;
}
.sidebar-actions {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.5rem;
}
.sidebar-footer {
    margin-top: auto;
    padding: 1rem;
    border-top: 1px solid #30363d;
}

/* Main content */
.main {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
}
.chat-header {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #30363d;
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 0.875rem;
}
.chat-header .badge {
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    background: #21262d;
}
.chat-container {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
}
.chat-input-container {
    padding: 1rem;
    border-top: 1px solid #30363d;
}
.chat-form {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}
.chat-input {
    flex: 1;
    padding: 0.75rem 1rem;
    border-radius: 8px;
    border: 1px solid #30363d;
    background: #161b22;
    color: #ececf1;
    font-size: 1rem;
}
.chat-input:focus {
    outline: none;
    border-color: #58a6ff;
}

/* Buttons */
.btn {
    padding: 0.5rem 1rem;
    border-radius: 6px;
    border: 1px solid #30363d;
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    background: #21262d;
    color: #ececf1;
    transition: background 0.15s;
}
.btn:hover { background: #30363d; }
.btn-primary {
    background: #238636;
    color: white;
    border-color: #238636;
}
.btn-primary:hover { background: #2ea043; }
.btn-danger {
    background: #da3633;
    color: white;
    border-color: #da3633;
}
.btn-danger:hover { background: #f85149; }
.btn-small {
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
}

/* Messages */
.message {
    margin-bottom: 1rem;
    padding: 1rem;
    border-radius: 8px;
    max-width: 80%;
}
.message.user {
    background: #238636;
    margin-left: auto;
}
.message.assistant {
    background: #21262d;
    margin-right: auto;
}
.message .role {
    font-size: 0.75rem;
    font-weight: 600;
    color: #8b949e;
    margin-bottom: 0.25rem;
    text-transform: uppercase;
}
.message.user .role { color: #3fb950; }
.message.assistant .role { color: #58a6ff; }
.message .content {
    line-height: 1.6;
}
.message .content code {
    background: #161b22;
    padding: 0.125rem 0.375rem;
    border-radius: 4px;
    font-family: 'Consolas', monospace;
    font-size: 0.875em;
}
.message .content pre {
    background: #161b22;
    padding: 1rem;
    border-radius: 6px;
    overflow-x: auto;
    margin: 0.5rem 0;
}
.message .content pre code {
    background: none;
    padding: 0;
}

/* Thinking */
.thinking {
    background: #1a1a2e;
    border-left: 3px solid #f0a500;
    padding: 0.75rem;
    margin: 0.5rem 0;
    border-radius: 0 6px 6px 0;
    font-size: 0.875rem;
    color: #a0a0a0;
}

/* Session list */
.session-list {
    flex: 1;
    overflow-y: auto;
    margin: 0.5rem 0;
}
.session-item {
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.875rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.session-item:hover { background: #21262d; }
.session-item.active {
    background: #30363d;
    border-left: 2px solid #58a6ff;
}
.session-item .title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* Empty state */
.empty-state {
    text-align: center;
    padding: 2rem;
    color: #8b949e;
}

/* Loading indicator */
.loading {
    display: inline-block;
    width: 1rem;
    height: 1rem;
    border: 2px solid #30363d;
    border-top-color: #58a6ff;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}
@keyframes spin {
    to { transform: rotate(360deg); }
}

/* HTMX indicators */
.htmx-indicator { display: none; }
.htmx-request .htmx-indicator { display: inline-block; }
.htmx-request.htmx-indicator { display: inline-block; }
"""

SCRIPT = """
document.body.classList.add('htmx-loaded');
"""


def model_select(models: list[str], current: str = "") -> Div:
    """Model selection dropdown."""
    options = [Option(m, value=m, selected=(m == current)) for m in models]
    select = Select(*options, id="model-select", name="model")
    label = Label("Model")
    return Div(label, select, cls="sidebar-section")


def session_item(session: dict, active: bool = False) -> Div:
    """A single session list item."""
    title = session.get("title") or "New Chat"
    session_id = session.get("id", "")
    cls = "session-item active" if active else "session-item"
    icon = Span("💬", cls="session-icon")
    title_span = Span(title, cls="title")
    return Div(
        icon,
        title_span,
        id=f"session-{session_id}",
        cls=cls,
        hx_get=f"/ui/sessions/{session_id}",
        hx_target="#chat-container",
        hx_swap="innerHTML",
        hx_on__after_request="if(event.detail.successful) this.classList.add('active')",
    )


def session_list(sessions: list[dict], active_id: str = "") -> Div:
    """Session list with all items."""
    items: list[Div] = []
    for s in sessions:
        items.append(session_item(s, s.get("id") == active_id))

    if not items:
        items.append(
            Div(
                P(
                    "No sessions yet",
                    cls="empty-state",
                    style="padding: 0.5rem; font-size: 0.875rem;",
                ),
                cls="session-list",
            )
        )
        return items[0]

    return Div(*items, id="session-list", cls="session-list")


def sidebar(models: list[str], sessions: list[dict], current_model: str = "") -> Div:
    """Full sidebar component."""
    header = Div(H1("Echo AI"), cls="sidebar-header")
    model_sel = model_select(models, current_model)

    new_btn = Button(
        "+ New",
        cls="btn btn-primary btn-small",
        hx_post="/ui/sessions/new",
        hx_target="#session-list",
        hx_swap="innerHTML",
    )
    session_title = H2("Sessions", style="font-size: 0.875rem; margin-bottom: 0.5rem;")
    sessions_section = session_list(sessions)

    sessions_container = Div(
        session_title,
        new_btn,
        sessions_section,
        cls="sidebar-section",
        style="flex: 1; display: flex; flex-direction: column; overflow: hidden;",
    )

    footer = Div(
        P(f"{len(sessions)} sessions", style="font-size: 0.75rem; color: #8b949e;"),
        cls="sidebar-footer",
    )

    return Div(header, model_sel, sessions_container, footer, cls="sidebar")


def chat_header(model: str, message_count: int) -> Div:
    """Chat header with model badge and metrics."""
    badge1 = Span(f"Model: {model}", cls="badge")
    badge2 = Span(f"Messages: {message_count}", cls="badge")
    return Div(badge1, badge2, cls="chat-header")


def message_bubble(role: str, content: str, thinking: str = "") -> Div:
    """A single message bubble."""
    cls = "message user" if role == "user" else "message assistant"
    role_label = "You" if role == "user" else "Assistant"

    content_div = Div(P(content), cls="content") if content else None
    thinking_div = Div(thinking, cls="thinking") if thinking else None

    parts: list = [Div(role_label, cls="role")]
    if content_div:
        parts.append(content_div)
    if thinking_div:
        parts.append(thinking_div)

    return Div(*parts, cls=cls)


def chat_container(messages: list[dict]) -> Div:
    """Chat message container."""
    if not messages:
        return Div(
            P("Start a conversation by typing below.", cls="empty-state"),
            id="chat-container",
            cls="chat-container",
        )

    bubbles: list[Div] = []
    for msg in messages:
        bubbles.append(
            message_bubble(
                role=msg.get("role", "assistant"),
                content=msg.get("content", ""),
                thinking=msg.get("thinking", ""),
            )
        )

    return Div(*bubbles, id="chat-container", cls="chat-container")


def chat_input(model: str = "qwen3:4b-instruct") -> Div:
    """Chat input form with SSE streaming."""
    input_field = Input(
        type="text",
        id="chat-input",
        name="message",
        placeholder="Type your message... (Enter to send)",
        cls="chat-input",
        autofocus=True,
        hx_post=f"/ui/chat/stream?model={model}",
        hx_ext="sse",
        sse_swap="message:#chat-container",
        hx_on__before_request="document.getElementById('send-btn').disabled=true",
        hx_on__after_request="this.reset(); document.getElementById('send-btn').disabled=false",
    )

    send_btn = Button(
        Span("Send", id="send-btn"),
        cls="btn btn-primary",
        type="submit",
    )

    hidden_model = Hidden(name="model", value=model)

    form = Form(input_field, send_btn, hidden_model, cls="chat-form")

    return Div(form, cls="chat-input-container")


def main_page(
    models: list[str],
    sessions: list[dict],
    messages: list[dict],
    current_model: str = "",
    active_session: str = "",
) -> tuple:
    """Full main page layout."""
    return (
        Title("Echo AI"),
        Style(CSS),
        Script(SCRIPT),
        Div(
            sidebar(models, sessions, current_model),
            Div(
                chat_header(current_model or "qwen3:4b-instruct", len(messages)),
                chat_container(messages),
                chat_input(),
                cls="main",
            ),
            cls="app",
        ),
    )
