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
    Pre,
    Code,
    Style,
    Script,
    Title,
)  # noqa: F401, F403

import json

from .markdown import format_message_content

CSS = """
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

[data-theme="light"] {
    --bg-primary: #ffffff;
    --bg-secondary: #f6f8fa;
    --bg-tertiary: #eaeef2;
    --border-color: #d0d7de;
    --text-primary: #1f2328;
    --text-secondary: #656d76;
    --accent-blue: #0969da;
    --accent-green: #1a7f37;
    --accent-red: #cf222e;
    --code-bg: #f6f8fa;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
}
.app { display: flex; height: 100vh; }

/* Sidebar */
.sidebar {
    width: 280px;
    background: var(--bg-secondary);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}
.sidebar-header {
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.sidebar-header h1 {
    font-size: 1.25rem;
    color: var(--accent-blue);
}
.theme-toggle {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    color: var(--text-primary);
    border-radius: 4px;
    padding: 0.25rem 0.5rem;
    cursor: pointer;
    font-size: 1rem;
}
.theme-toggle:hover {
    background: var(--border-color);
}
.sidebar-section {
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
}
.sidebar-section label {
    display: block;
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-bottom: 0.25rem;
    text-transform: uppercase;
}
.sidebar-section select {
    width: 100%;
    padding: 0.5rem;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-primary);
    color: var(--text-primary);
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
    border-top: 1px solid var(--border-color);
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
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 0.875rem;
}
.chat-header .badge {
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    background: var(--bg-tertiary);
}
.chat-container {
    flex: 1;
    overflow-y: auto;
    padding: 1rem;
}
.chat-input-container {
    padding: 1rem;
    border-top: 1px solid var(--border-color);
    background: var(--bg-secondary);
}
.chat-form {
    display: grid !important;
    grid-template-columns: 1fr auto !important;
    gap: 0.5rem;
    width: 100%;
}
.chat-input {
    width: 100% !important;
    padding: 0.75rem 1rem;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 1rem;
    min-height: 44px;
    box-sizing: border-box;
}
.chat-input:focus {
    outline: none;
    border-color: var(--accent-blue);
}

/* Buttons */
.btn {
    padding: 0.5rem 1rem;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    cursor: pointer;
    font-size: 0.875rem;
    font-weight: 500;
    background: var(--bg-tertiary);
    color: var(--text-primary);
    transition: background 0.15s;
}
.btn:hover { background: var(--border-color); }
.btn-primary {
    background: var(--accent-green);
    color: white;
    border-color: var(--accent-green);
}
.btn-primary:hover { background: #2ea043; }
.btn-danger {
    background: var(--accent-red);
    color: white;
    border-color: var(--accent-red);
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
    background: var(--accent-green);
    margin-left: auto;
}
.message.assistant {
    background: var(--bg-tertiary);
    margin-right: auto;
}
.message .role {
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 0.25rem;
    text-transform: uppercase;
}
.message.user .role { color: #3fb950; }
.message.assistant .role { color: var(--accent-blue); }
.message .content {
    line-height: 1.6;
    word-wrap: break-word;
    overflow-wrap: break-word;
    max-width: 100%;
}
.message .content code {
    background: var(--code-bg);
    padding: 0.125rem 0.375rem;
    border-radius: 4px;
    font-family: 'Consolas', monospace;
    font-size: 0.875em;
}
.message .content pre {
    background: var(--code-bg);
    padding: 1rem;
    border-radius: 6px;
    overflow-x: auto;
    margin: 0.5rem 0;
}
.message .content pre code {
    background: none;
    padding: 0;
}
.message .content ul, .message .content ol {
    margin: 0.5rem 0;
    padding-left: 1.5rem;
}
.message .content li {
    margin-bottom: 0.25rem;
}

/* Thinking */
.thinking {
    background: var(--code-bg);
    border-left: 3px solid #f0a500;
    padding: 0.75rem;
    margin: 0.5rem 0;
    border-radius: 0 6px 6px 0;
    font-size: 0.875rem;
    color: var(--text-secondary);
}

/* Tool calls */
.tool-calls {
    margin-top: 0.5rem;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    overflow: hidden;
}
.tool-call-header {
    background: var(--bg-tertiary);
    padding: 0.5rem 0.75rem;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--accent-blue);
    text-transform: uppercase;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.tool-call-header:hover {
    background: var(--border-color);
}
.tool-call-content {
    background: var(--code-bg);
    padding: 0.75rem;
    font-size: 0.875rem;
    overflow-x: auto;
}
.tool-call-content pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
}
.tool-call-arguments {
    color: var(--text-secondary);
}
.tool-call-name {
    color: var(--accent-blue);
    font-family: 'Consolas', monospace;
}
.tool-call-item {
    border-bottom: 1px solid var(--border-color);
}
.tool-call-item:last-child {
    border-bottom: none;
}
.tool-call-item .tool-call-content {
    display: none;
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
.session-item:hover { background: var(--bg-tertiary); }
.session-item.active {
    background: var(--border-color);
    border-left: 2px solid var(--accent-blue);
}
.session-item .title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* Loading indicator */
.loading {
    display: inline-block;
    width: 1rem;
    height: 1rem;
    border: 2px solid var(--border-color);
    border-top-color: var(--accent-blue);
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

/* Code highlighting (Pygments) */
.codehilite {
    background: var(--code-bg);
    padding: 1rem;
    border-radius: 6px;
    overflow-x: auto;
    margin: 0.5rem 0;
}
.codehilite pre {
    margin: 0;
    background: transparent;
}
.codehilite code {
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 0.875rem;
    line-height: 1.5;
}

/* Pygments theme (dark) */
.codehilite .hll { background-color: #2d2d2d; }
.codehilite .c { color: #6a9955; } /* Comment */
.codehilite .k { color: #569cd6; } /* Keyword */
.codehilite .o { color: #d4d4d4; } /* Operator */
.codehilite .cm { color: #6a9955; } /* Comment.Multiline */
.codehilite .cp { color: #d7ba7d; } /* Comment.Preproc */
.codehilite .c1 { color: #6a9955; } /* Comment.Single */
.codehilite .cs { color: #6a9955; } /* Comment.Special */
.codehilite .err { color: #f44747; border: 1px solid #f44747; } /* Error */
.codehilite .m { color: #b5cea8; } /* Number */
.codehilite .n { color: #d4d4d4; } /* Name */
.codehilite .p { color: #d4d4d4; } /* Punctuation */
.codehilite .s { color: #ce9178; } /* String */
.codehilite .w { color: #d4d4d4; } /* Whitespace */

/* Light theme Pygments overrides */
[data-theme="light"] .codehilite .hll { background-color: #ffff00; }
[data-theme="light"] .codehilite .c { color: #008000; }
[data-theme="light"] .codehilite .k { color: #0000ff; }
[data-theme="light"] .codehilite .o { color: #333333; }
[data-theme="light"] .codehilite .cm { color: #008000; }
[data-theme="light"] .codehilite .cp { color: #bc7a00; }
[data-theme="light"] .codehilite .c1 { color: #008000; }
[data-theme="light"] .codehilite .cs { color: #008000; }
[data-theme="light"] .codehilite .err { color: #a61717; }
[data-theme="light"] .codehilite .m { color: #008000; }
[data-theme="light"] .codehilite .n { color: #333333; }
[data-theme="light"] .codehilite .p { color: #333333; }
[data-theme="light"] .codehilite .s { color: #ba2121; }
[data-theme="light"] .codehilite .w { color: #bbbbbb; }

/* Session search */
.session-search {
    padding: 0.5rem 0;
    margin-bottom: 0.5rem;
}
.session-search input {
    width: 100%;
    padding: 0.5rem;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-primary);
    color: var(--text-primary);
    font-size: 0.875rem;
}
.session-search input:focus {
    outline: none;
    border-color: var(--accent-blue);
}
.session-search input::placeholder {
    color: var(--text-secondary);
}

/* Error state */
.error-message {
    background: var(--accent-red);
    color: white;
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin: 0.5rem 0;
    font-size: 0.875rem;
}
.error-state {
    text-align: center;
    padding: 2rem;
    color: var(--accent-red);
}

/* Transitions */
.message {
    animation: fadeIn 0.3s ease-out;
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

/* Scrollbar styling */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}
::-webkit-scrollbar-track {
    background: var(--bg-secondary);
}
::-webkit-scrollbar-thumb {
    background: var(--border-color);
    border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--text-secondary);
}

/* Accessibility - focus visible */
:focus-visible {
    outline: 2px solid var(--accent-blue);
    outline-offset: 2px;
}
button:focus-visible,
input:focus-visible,
select:focus-visible {
    outline: 2px solid var(--accent-blue);
    outline-offset: 2px;
}

/* Skip link for accessibility */
.skip-link {
    position: absolute;
    top: -40px;
    left: 0;
    background: var(--accent-blue);
    color: white;
    padding: 8px 16px;
    z-index: 100;
    transition: top 0.2s;
}
.skip-link:focus {
    top: 0;
}

/* Empty state and quick actions */
.empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 2rem;
    color: var(--text-secondary);
}
.empty-state.chat-container {
    flex: 1;
    min-height: 0;
}
.empty-state h2 {
    font-size: 1.5rem;
    margin-bottom: 1rem;
    color: var(--text-primary);
}
.quick-actions {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: center;
    margin-top: 1rem;
}
.quick-actions .btn {
    font-size: 0.875rem;
}

/* Session actions grid */
.session-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
    margin: 0.5rem 0;
}

/* Mobile responsive */
@media (max-width: 768px) {
    .app {
        flex-direction: column;
    }
    .sidebar {
        width: 100%;
        height: auto;
        max-height: 40vh;
        border-right: none;
        border-bottom: 1px solid var(--border-color);
    }
    .sidebar-header {
        padding: 0.75rem;
    }
    .sidebar-section {
        padding: 0.75rem;
    }
    .session-list {
        max-height: 15vh;
    }
    .main {
        flex: 1;
        min-height: 0;
    }
    .chat-header {
        padding: 0.5rem 0.75rem;
    }
    .chat-container {
        padding: 0.75rem;
    }
    .message {
        max-width: 95%;
    }
    .chat-input-container {
        padding: 0.75rem;
    }
}

/* Loading indicator enhancement */
.sending-indicator {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-secondary);
    font-size: 0.875rem;
}
.htmx-indicator {
    display: none;
}
.htmx-request .htmx-indicator {
    display: inline-block;
}
.htmx-request.htmx-indicator {
    display: inline-block;
}
"""

SCRIPT = """
(function() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    document.body.classList.add('htmx-loaded');
})();

function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
}

function filterSessions(query) {
    const items = document.querySelectorAll('#session-list .session-item');
    const lowerQuery = query.toLowerCase();
    items.forEach(item => {
        const title = item.querySelector('.title');
        if (title) {
            const text = title.textContent.toLowerCase();
            item.style.display = text.includes(lowerQuery) ? '' : 'none';
        }
    });
}

function toggleToolCall(header) {
    const toolCallItem = header.closest('.tool-call-item');
    const content = toolCallItem.querySelector('.tool-call-content');
    const isHidden = content.style.display === 'none' || content.style.display === '';
    if (isHidden) {
        content.style.display = 'block';
        header.querySelector('span:last-child').textContent = '▾';
    } else {
        content.style.display = 'none';
        header.querySelector('span:last-child').textContent = '▸';
    }
}
"""


def model_select(models: list[str], current: str = "") -> Div:
    """Model selection dropdown."""
    options = [Option(m, value=m, selected=(m == current)) for m in models]
    select = Select(
        *options,
        id="model-select",
        name="model",
        hx_post="/ui/models",
        hx_target="#model-select",
        hx_swap="outerHTML",
        hx_trigger="change",
    )
    label = Label("Model")
    return Div(label, select, cls="sidebar-section")


def session_item(session: dict, active: bool = False) -> Div:
    """A single session list item."""
    title = session.get("title") or "New Chat"
    session_id = session.get("id", "")
    cls = "session-item active" if active else "session-item"
    icon = Span("💬", cls="session-icon")
    title_span = Span(title, cls="title")
    delete_btn = Button(
        "×",
        cls="btn-delete",
        style="padding: 0 4px; background: none; border: none; color: #8b949e; cursor: pointer;",
        hx_delete=f"/ui/sessions/delete/{session_id}",
        hx_target=f"#session-{session_id}",
        hx_swap="delete",
        hx_confirm="Delete this session?",
    )
    return Div(
        icon,
        title_span,
        delete_btn,
        id=f"session-{session_id}",
        cls=cls,
        hx_get=f"/ui/sessions/{session_id}",
        hx_target="#chat-container",
        hx_swap="outerHTML",
        hx_on__after_request="""
            if(event.detail.successful) {
                document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
                this.classList.add('active');
            }
        """,
    )


def session_list(sessions: list[dict], active_id: str = "") -> Div:
    """Session list with all items."""
    items: list[Div] = []
    for s in sessions:
        items.append(session_item(s, s.get("id") == active_id))

    if not items:
        return Div(
            P(
                "No sessions yet",
                cls="empty-state",
                style="padding: 0.5rem; font-size: 0.875rem;",
            ),
            id="session-list",
            cls="session-list",
        )

    return Div(*items, id="session-list", cls="session-list")


def session_search_input() -> Div:
    """Session search input with client-side filtering."""
    search_input = Input(
        type="text",
        id="session-search",
        name="search",
        placeholder="Search sessions...",
        cls="session-search-input",
        onkeyup="filterSessions(this.value)",
    )
    return Div(search_input, cls="session-search")


def session_actions() -> Div:
    """Session action buttons (rename, delete, purge)."""
    rename_btn = Button(
        "Rename",
        cls="btn",
        onclick="renameCurrentSession()",
    )
    delete_btn = Button(
        "Delete",
        cls="btn btn-danger",
        hx_delete="/ui/sessions/delete/current",
        hx_confirm="Delete this session?",
    )
    return Div(rename_btn, delete_btn, cls="session-actions")


def purge_sessions_button() -> Button:
    """Button to purge all session history."""
    return Button(
        "Purge History",
        cls="btn btn-danger btn-small",
        style="margin-top: 0.5rem; width: 100%;",
        hx_delete="/ui/sessions/purge",
        hx_confirm="Are you sure you want to purge ALL session history? This cannot be undone.",
        hx_swap="none",
    )


def sidebar(models: list[str], sessions: list[dict], current_model: str = "") -> Div:
    """Full sidebar component."""
    theme_toggle = Button(
        "☀",
        cls="theme-toggle",
        title="Toggle theme",
        onclick="toggleTheme()",
    )
    header = Div(
        H1("Echo AI"),
        theme_toggle,
        cls="sidebar-header",
    )
    model_sel = model_select(models, current_model)

    new_btn = Button(
        "+ New",
        cls="btn btn-primary btn-small",
        hx_post="/ui/sessions/new",
        hx_target="#session-list",
        hx_swap="outerHTML",
    )
    session_title = H2("Sessions", style="font-size: 0.875rem; margin-bottom: 0.5rem;")
    search_input = session_search_input()
    sessions_section = session_list(sessions)

    sessions_container = Div(
        session_title,
        search_input,
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


def message_bubble(
    role: str, content: str, thinking: str = "", tool_calls: list = None
) -> Div:
    """A single message bubble."""
    cls = "message user" if role == "user" else "message assistant"
    role_label = "You" if role == "user" else "Assistant"

    formatted_content = format_message_content(content)
    content_div = (
        Div(formatted_content, cls="content", role="region") if content else None
    )
    thinking_div = Div(thinking, cls="thinking") if thinking else None

    tool_calls_div = None
    if tool_calls:
        tool_items = []
        for i, tc in enumerate(tool_calls):
            name = tc.get("name", "unknown")
            args = tc.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    pass
            args_str = (
                json.dumps(args, indent=2) if isinstance(args, dict) else str(args)
            )

            header = Div(
                Span(f"🔧 {name}"),
                Span("▾", style="margin-left: auto;"),
                cls="tool-call-header",
                onclick="toggleToolCall(this)",
            )
            content_wrapper = Div(
                Pre(Code(args_str), cls="tool-call-arguments"),
                cls="tool-call-content",
            )
            tool_items.append(Div(header, content_wrapper, cls="tool-call-item"))

        tool_calls_div = Div(
            Span(
                "Tool Calls",
                style="font-size: 0.7rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 0.25rem;",
            ),
            *tool_items,
            cls="tool-calls",
        )

    parts: list = [Div(role_label, cls="role")]
    if content_div:
        parts.append(content_div)
    if thinking_div:
        parts.append(thinking_div)
    if tool_calls_div:
        parts.append(tool_calls_div)

    return Div(*parts, cls=cls)


def quick_actions() -> Div:
    """Quick action buttons for empty state."""
    actions = [
        (
            "Search AI News",
            "Search the web for the latest news on Artificial Intelligence",
        ),
        (
            "Write Python Server",
            "Write a python script that implements a simple FastAPI server",
        ),
        (
            "Extract Data",
            "Help me extract structured entity data from a messy block of text",
        ),
    ]
    btns = []
    for label, prompt in actions:
        btns.append(
            Button(
                label,
                cls="btn",
                type="button",
                onclick=f"document.getElementById('chat-input').value='{prompt}'; document.getElementById('chat-form').requestSubmit();",
            )
        )
    return Div(*btns, cls="quick-actions")


def chat_container(messages: list[dict]) -> Div:
    """Chat message container."""
    if not messages:
        return Div(
            H2("How can I help you today?"),
            quick_actions(),
            cls="empty-state chat-container",
            id="chat-container",
        )

    bubbles: list[Div] = []
    pending_tool_calls = []
    for msg in messages:
        role = msg.get("role", "")
        tool_name = msg.get("tool_name", "")
        tool_arguments = msg.get("tool_arguments", {})
        tool_call_id = msg.get("tool_call_id", "")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")

        if role == "tool" or tool_name or tool_call_id:
            if tool_name:
                pending_tool_calls.append(
                    {"name": tool_name, "arguments": tool_arguments}
                )
            continue

        if role == "assistant" and tool_calls and not content.strip():
            pending_tool_calls.extend(tool_calls)
            continue

        if not tool_calls and pending_tool_calls:
            tool_calls = pending_tool_calls
            pending_tool_calls = []

        bubbles.append(
            message_bubble(
                role=role,
                content=content,
                thinking=msg.get("thinking", ""),
                tool_calls=tool_calls,
            )
        )
        pending_tool_calls = []

    return Div(*bubbles, id="chat-container", cls="chat-container")


def chat_input(model: str = "qwen3:4b-instruct") -> Div:
    """Chat input form using HTMX WebSockets."""
    input_field = Input(
        type="text",
        id="chat-input",
        name="message",
        placeholder="Type your message... (Enter to send)",
        cls="chat-input",
        style="flex: 1; min-width: 0;",
        autofocus=True,
    )

    send_btn = Button(
        "Send",
        id="send-btn",
        cls="btn btn-primary",
        type="submit",
        style="flex: 0 0 auto; white-space: nowrap;",
    )

    hidden_model = Hidden(name="model", value=model)

    form = Form(
        input_field,
        send_btn,
        hidden_model,
        cls="chat-form",
        style="display: flex; gap: 0.5rem; width: 100%;",
        hx_ext="ws",
        ws_connect="/ui/ws/chat",
        ws_send=True,
        hx_target="#chat-container",
        hx_swap="beforeend",
        hx_on__ws_after_send="this.reset()",
    )

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
