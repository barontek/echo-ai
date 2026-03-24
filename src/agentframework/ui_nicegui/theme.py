"""Theme and styling for NiceGUI premium implementation."""

from nicegui import ui

# Premium Zinc-dark palette with Cyan/Blue gradient accents
DARK_THEME_COLORS = {
    "primary": "#0ea5e9",      # Cyan-500
    "secondary": "#3b82f6",    # Blue-500
    "accent": "#6366f1",       # Indigo-500
    "dark": "#09090b",         # Zinc-950 (True dark background)
    "dark-page": "#09090b",    # Zinc-950
    "positive": "#10b981",     # Emerald-500
    "negative": "#ef4444",     # Red-500
    "info": "#3b82f6",         # Blue-500
    "warning": "#f59e0b",      # Amber-500
}

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

:root {
    --bg-base: #09090b;       /* Zinc-950 */
    --bg-surface: #18181b;    /* Zinc-900 */
    --bg-elevated: #27272a;   /* Zinc-800 */
    --border-subtle: #27272a; /* Zinc-800 */
    --border-strong: #3f3f46; /* Zinc-700 */

    --text-primary: #fafafa;  /* Zinc-50 */
    --text-secondary: #a1a1aa;/* Zinc-400 */
    --text-muted: #71717a;    /* Zinc-500 */

    --brand-primary: #0ea5e9;
    --brand-secondary: #3b82f6;
    --brand-gradient: linear-gradient(135deg, var(--brand-primary), var(--brand-secondary));

    --glass-bg: rgba(24, 24, 27, 0.7);
    --glass-border: rgba(255, 255, 255, 0.08);
    --glass-blur: blur(12px);

    --code-bg: #09090b;
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-pill: 9999px;
}

html, body, #q-app {
    background: var(--bg-base) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--text-primary);
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    margin: 0 !important;
    padding: 0 !important;
    width: 100%;
    height: 100%;
    overflow: hidden !important;
    box-shadow: none !important;
}

.q-page {
    padding: 0 !important;
    min-height: 100vh !important;
    height: 100vh !important;
    overflow: hidden !important;
    display: flex;
    flex-direction: column;
}

.nicegui-content {
    padding: 0 !important;
    margin: 0 !important;
    flex: 1;
    display: flex;
    flex-direction: column;
    height: 100%;
    width: 100%;
    min-height: 0;
}

/* Layout */
.app-container {
    display: flex;
    height: 100%;
    width: 100%;
    overflow: hidden;
    background: var(--bg-base);
}

.sidebar {
    width: 280px;
    height: 100%;
    background: var(--glass-bg);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border-right: 1px solid var(--border-subtle);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    z-index: 10;
    overflow: hidden;
    box-sizing: border-box;
}

.sidebar-header {
    padding: 1rem 1.25rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-sizing: border-box;
}

.brand-text {
    font-size: 1.25rem;
    font-weight: 700;
    background: var(--brand-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    letter-spacing: -0.025em;
}

.sidebar-section {
    padding: 0.5rem 1.25rem;
    box-sizing: border-box;
}

.sidebar-section.flex-grow {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
}

.sidebar-footer {
    margin-top: auto;
    padding: 1.25rem;
    border-top: 1px solid var(--border-subtle);
}

.main-content {
    flex: 1;
    position: relative;
    height: 100%;
    min-width: 0;
    background: transparent;
    overflow: hidden;
}

.chat-header {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 70px;
    padding: 0 1.5rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    border-bottom: 1px solid var(--glass-border);
    background: var(--glass-bg);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    z-index: 30;
}

.chat-container {
    position: absolute;
    top: 70px;
    bottom: 0;
    left: 0;
    right: 0;
    overflow-y: auto;
    padding: 1.5rem;
    scroll-behavior: smooth;
    z-index: 10;
}

.chat-container::after {
    content: "";
    display: block;
    height: 100px;
    width: 100%;
    flex-shrink: 0;
}

/* Chat Input */
.chat-input-wrapper {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 1.5rem;
    background: linear-gradient(to top, var(--bg-base) 50%, transparent);
    z-index: 40;
}

.chat-input-pill {
    max-width: 800px;
    margin: 0 auto;
    background: var(--bg-surface);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-pill);
    padding: 0.5rem 0.5rem 0.5rem 1.25rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.chat-input-pill:focus-within {
    border-color: var(--brand-secondary);
    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25), 0 4px 20px rgba(0, 0, 0, 0.5);
    transform: translateY(-2px);
}

.chat-input-field textarea, .chat-input-field input {
    background: transparent !important;
    border: none !important;
    color: var(--text-primary) !important;
    font-family: inherit;
    font-size: 1rem;
    outline: none !important;
    box-shadow: none !important;
}

.btn-send {
    background: var(--brand-gradient) !important;
    color: white !important;
    border-radius: var(--radius-pill) !important;
    width: 40px !important;
    height: 40px !important;
    min-height: 40px !important;
    padding: 0 !important;
    transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s !important;
}

.btn-send:hover {
    transform: scale(1.05) !important;
    box-shadow: 0 0 15px rgba(14, 165, 233, 0.5) !important;
}

.btn-send:active {
    transform: scale(0.95) !important;
}

/* Messages */
.message {
    max-width: 80%;
    margin-bottom: 1.5rem;
    animation: springSlideUp 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
    opacity: 0;
    transform: translateY(20px);
}

@keyframes springSlideUp {
    to { opacity: 1; transform: translateY(0); }
}

.message.user {
    margin-left: auto;
}

.message.assistant {
    margin-right: auto;
}

.message-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.375rem;
    padding: 0 0.5rem;
}

.message-bubble {
    padding: 1rem 1.25rem;
    line-height: 1.6;
    font-size: 0.95rem;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
}

.message.user .message-bubble {
    background: var(--bg-elevated);
    border-radius: 20px 20px 4px 20px;
    border: 1px solid var(--glass-border);
}

.message.assistant .message-bubble {
    background: rgba(39, 39, 42, 0.4);
    backdrop-filter: var(--glass-blur);
    -webkit-backdrop-filter: var(--glass-blur);
    border: 1px solid var(--glass-border);
    border-radius: 4px 20px 20px 20px;
    padding: 1rem 1.25rem;
    box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
}

.message-content p { margin-top: 0; margin-bottom: 0.75rem; }
.message-content p:last-child { margin-bottom: 0; }

.message-content code {
    background: var(--code-bg);
    padding: 0.2rem 0.4rem;
    border-radius: 6px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.85em;
    border: 1px solid var(--border-subtle);
}

.code-block {
    background: var(--code-bg);
    padding: 1rem;
    border-radius: var(--radius-md);
    overflow-x: auto;
    margin: 0.75rem 0;
    border: 1px solid var(--border-strong);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.85em;
    box-shadow: inset 0 2px 8px rgba(0,0,0,0.5);
}

/* Sessions */
.session-list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 0;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
}

.session-item {
    padding: 0.625rem 0.875rem;
    border-radius: var(--radius-sm);
    box-sizing: border-box;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    transition: all 0.2s ease;
    color: var(--text-secondary);
    border: 1px solid transparent;
    flex-wrap: nowrap;
    min-width: 0;
}

.session-item:hover {
    background: rgba(255, 255, 255, 0.03);
    transform: translateX(4px);
    color: var(--text-primary);
}

.session-item.active {
    background: var(--bg-elevated);
    color: var(--text-primary);
    border: 1px solid var(--border-strong);
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}

.session-item .title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.875rem;
    font-weight: 500;
    min-width: 0;
}

.session-item .btn-delete {
    opacity: 0;
    transition: opacity 0.2s, color 0.2s;
    color: var(--text-muted);
}

.session-item:hover .btn-delete {
    opacity: 1;
}

.session-item .btn-delete:hover {
    color: var(--negative);
}

/* Quick Actions */
.empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: var(--text-secondary);
    animation: fadeIn 0.8s ease-out;
}

.empty-state h2 {
    font-size: 2rem;
    font-weight: 600;
    margin-bottom: 2rem;
    background: var(--brand-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.quick-actions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    width: 100%;
    max-width: 700px;
}

.quick-action-card {
    background: rgba(39, 39, 42, 0.3);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius-md);
    padding: 1.25rem;
    cursor: pointer;
    text-align: left;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
}

.quick-action-card:hover {
    transform: translateY(-4px) scale(1.02);
    border-color: var(--brand-primary);
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(14, 165, 233, 0.3);
    background: var(--bg-elevated);
}

.quick-action-card .q-title {
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
    font-size: 0.95rem;
}

.quick-action-card .q-desc {
    font-size: 0.85rem;
    color: var(--text-muted);
    line-height: 1.4;
}

.new-chat-btn {
    background: var(--brand-gradient) !important;
    color: white !important;
    border-radius: var(--radius-md) !important;
    font-weight: 600 !important;
    letter-spacing: 0.025em !important;
    box-shadow: 0 4px 15px rgba(14, 165, 233, 0.2) !important;
    transition: transform 0.2s, box-shadow 0.2s !important;
}

.new-chat-btn:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(14, 165, 233, 0.4) !important;
}

/* Animations */
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

.loading-spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid var(--border-strong);
    border-radius: 50%;
    border-top-color: var(--brand-primary);
    animation: spin 0.8s cubic-bezier(0.6, 0.2, 0.4, 0.8) infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: var(--border-strong);
    border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}
"""

def setup_theme(dark_mode: bool = True) -> None:
    """Setup the premium theme and custom CSS."""
    ui.colors(**DARK_THEME_COLORS)
    ui.add_css(CUSTOM_CSS)
    if dark_mode:
        ui.dark_mode().enable()
