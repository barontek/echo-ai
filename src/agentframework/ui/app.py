"""FastHTML app for Echo AI chat UI.

Minimal implementation for Phase 1 - just serves a basic page.
"""

from fasthtml.common import *  # noqa: F403, F405, E501

app, rt = fast_app()

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { 
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0e1117; 
    color: #ececf1; 
    min-height: 100vh;
}
.app { display: flex; height: 100vh; }
.sidebar { 
    width: 280px; 
    background: #161b22; 
    border-right: 1px solid #30363d;
    padding: 1rem;
    display: flex;
    flex-direction: column;
}
.sidebar h1 { font-size: 1.5rem; margin-bottom: 1rem; color: #58a6ff; }
.main { flex: 1; display: flex; flex-direction: column; }
.chat-header { 
    padding: 0.75rem 1rem; 
    border-bottom: 1px solid #30363d;
    display: flex;
    align-items: center;
    gap: 1rem;
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
.chat-form { display: flex; gap: 0.5rem; }
.chat-input { 
    flex: 1; 
    padding: 0.75rem; 
    border-radius: 6px;
    border: 1px solid #30363d;
    background: #0d1117;
    color: #ececf1;
}
.btn { 
    padding: 0.75rem 1rem; 
    border-radius: 6px; 
    border: none;
    cursor: pointer;
    font-weight: 500;
}
.btn-primary { background: #238636; color: white; }
.btn-primary:hover { background: #2ea043; }
.session-list { flex: 1; overflow-y: auto; margin: 1rem 0; }
.session-item { 
    padding: 0.5rem; 
    border-radius: 4px; 
    cursor: pointer;
    margin-bottom: 0.25rem;
}
.session-item:hover { background: #21262d; }
.message { margin-bottom: 1rem; padding: 1rem; border-radius: 8px; }
.message.user { background: #238636; margin-left: 2rem; }
.message.assistant { background: #21262d; margin-right: 2rem; }
"""

SCRIPT = """
// Minimal JS for theme toggle - rest is pure Python/HTMX
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
        toggle.addEventListener('change', () => {
            document.body.classList.toggle('light-theme');
        });
    }
});
"""


@rt("/")
def get():
    """Main chat page."""
    return (
        Title("Echo AI"),
        Style(CSS),
        Div(
            Div(
                Div(H1("Echo AI"), cls="sidebar-header"),
                Div(
                    Label("Model"),
                    Select(
                        Option("qwen3:4b-instruct", value="qwen3:4b-instruct"),
                        id="model-select",
                        name="model",
                    ),
                    cls="sidebar-section",
                ),
                Div(
                    H2("Sessions"),
                    Button(
                        "+ New Chat",
                        cls="btn",
                        hx_post="/ui/new-session",
                        hx_target="#session-list",
                    ),
                    Div(id="session-list", cls="session-list"),
                    cls="sidebar-section",
                ),
                cls="sidebar",
            ),
            Div(
                Div(
                    Span("Model: qwen3:4b-instruct", id="model-badge"),
                    cls="header-info",
                ),
                cls="chat-header",
            ),
            Div(
                Div(
                    P(
                        "Welcome to Echo AI. Start a conversation by typing below.",
                        cls="empty-state",
                    ),
                    id="chat-container",
                    cls="chat-container",
                ),
                cls="main",
            ),
            Div(
                Form(
                    Input(
                        type="text",
                        id="chat-input",
                        name="message",
                        placeholder="Type your message...",
                        cls="chat-input",
                        hx_post="/ui/chat",
                        hx_trigger="keyup[key=='Enter']",
                        hx_target="#chat-container",
                        hx_swap="beforeend",
                    ),
                    Button("Send", cls="btn btn-primary", type="submit"),
                    id="chat-form",
                    cls="chat-form",
                ),
                cls="chat-input-container",
            ),
            Script(SCRIPT),
            cls="app",
        ),
    )


@rt("/new-session")
def new_session():
    """Create a new session."""
    return Div(P("New session created"), cls="session-item")


@rt("/chat")
def chat_post(message: str = ""):
    """Handle chat submission."""
    if not message.strip():
        return ""
    return Div(
        Div(message, cls="message user"),
        Div(P(f"Echo: You said '{message}'"), cls="message assistant"),
        id="chat-container",
    )


@rt("/sessions")
def list_sessions():
    """Return session list."""
    return Div(
        Div("Session 1", cls="session-item"),
        Div("Session 2", cls="session-item"),
        cls="session-list",
    )
