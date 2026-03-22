"""Theme and styling for NiceGUI implementation."""

from nicegui import ui

DARK_THEME_COLORS = {
    "primary": "#58a6ff",
    "secondary": "#238636",
    "accent": "#da3633",
    "dark": "#0e1117",
    "dark-page": "#161b22",
    "positive": "#238636",
    "negative": "#da3633",
    "info": "#58a6ff",
    "warning": "#d29922",
}

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

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
}

.app-container {
    display: flex;
    height: 100vh;
    width: 100vw;
    overflow: hidden;
}

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

.sidebar-section {
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
}

.sidebar-section.flex-grow {
    flex: 1;
    overflow-y: auto;
}

.sidebar-footer {
    margin-top: auto;
    padding: 1rem;
    border-top: 1px solid var(--border-color);
}

.main-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    background: var(--bg-primary);
}

.chat-header {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 0.875rem;
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

.chat-input-row {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}

.message {
    padding: 1rem;
    border-radius: 8px;
    margin-bottom: 1rem;
    animation: fadeIn 0.3s ease-in-out;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.message.user {
    background: var(--bg-tertiary);
    margin-left: 2rem;
}

.message.assistant {
    background: var(--bg-secondary);
    margin-right: 2rem;
}

.message-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
}

.message-content {
    line-height: 1.6;
}

.message-content p {
    margin-bottom: 0.5rem;
}

.message-content code {
    background: var(--code-bg);
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
    font-family: 'Monaco', 'Menlo', monospace;
    font-size: 0.875rem;
}

.message-content pre {
    background: var(--code-bg);
    padding: 1rem;
    border-radius: 8px;
    overflow-x: auto;
    margin: 0.5rem 0;
}

.code-block {
    background: var(--code-bg);
    padding: 1rem;
    border-radius: 8px;
    overflow-x: auto;
    margin: 0.5rem 0;
}

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

.quick-actions {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: center;
    margin-top: 1rem;
}

.session-list {
    flex: 1;
    overflow-y: auto;
    padding: 0.5rem;
}

.session-item {
    padding: 0.5rem;
    border-radius: 6px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    transition: background 0.2s;
}

.session-item:hover {
    background: var(--bg-tertiary);
}

.session-item.active {
    background: var(--bg-tertiary);
    border-left: 3px solid var(--accent-blue);
}

.session-item .title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.875rem;
}

.session-item .btn-delete {
    opacity: 0;
    padding: 0 4px;
    background: none;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
}

.session-item:hover .btn-delete {
    opacity: 1;
}

.session-item .btn-delete:hover {
    color: var(--accent-red);
}

.tool-calls {
    margin-top: 0.5rem;
}

.tool-call {
    background: var(--bg-tertiary);
    padding: 0.5rem;
    border-radius: 4px;
    margin-bottom: 0.5rem;
}

.thinking-section {
    margin-top: 0.5rem;
}

.loading-spinner {
    display: inline-block;
    width: 20px;
    height: 20px;
    border: 2px solid var(--border-color);
    border-radius: 50%;
    border-top-color: var(--accent-blue);
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Scrollbar styling */
::-webkit-scrollbar {
    width: 8px;
}

::-webkit-scrollbar-track {
    background: var(--bg-primary);
}

::-webkit-scrollbar-thumb {
    background: var(--border-color);
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--text-secondary);
}

/* Mobile responsive */
@media (max-width: 768px) {
    .app-container {
        flex-direction: column;
    }
    .sidebar {
        width: 100%;
        height: auto;
        max-height: 40vh;
    }
    .message.user {
        margin-left: 1rem;
    }
    .message.assistant {
        margin-right: 1rem;
    }
}
"""


def setup_theme(dark_mode: bool = True) -> None:
    """Setup the theme and custom CSS."""
    ui.colors(**DARK_THEME_COLORS)
    ui.add_css(CUSTOM_CSS)
    if dark_mode:
        ui.dark_mode().enable()
