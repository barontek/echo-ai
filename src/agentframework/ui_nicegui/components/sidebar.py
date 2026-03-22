"""Sidebar component for session management."""

from nicegui import ui

from ..state import get_state


def sidebar_header():
    """Render sidebar header with title and theme toggle."""
    with ui.column().classes("sidebar-header"):
        with ui.row().classes("w-full justify-between items-center"):
            ui.label("Echo AI").classes("text-h5 text-primary")
            ui.button(
                icon="dark_mode",
                on_click=lambda: toggle_theme(),
            ).props("flat round dense").style("color: var(--text-secondary)")


def theme_toggle():
    """Theme toggle button."""
    ui.button(
        icon="dark_mode",
        on_click=lambda: ui.dark_mode().toggle(),
    ).props("flat round dense").style("color: var(--text-secondary)")


def toggle_theme():
    """Toggle between dark and light theme."""
    ui.dark_mode().toggle()


def model_selector(models: list, current_model: str = "qwen3:4b-instruct"):
    """Model selection dropdown."""
    with ui.column().classes("sidebar-section"):
        ui.label("Model").classes("text-xs text-grey-5 uppercase mb-2")
        ui.select(
            options=models,
            value=current_model,
            on_change=lambda e: update_model(e.value),
        ).props("outlined dense").style("width: 100%")


def update_model(model: str):
    """Update the current model."""
    state = get_state()
    state.model = model


def session_list(sessions: list, active_id: str = ""):
    """Render the session list."""
    with ui.column().classes("session-list"):
        for session in sessions:
            session_item(session, is_active=session.get("id") == active_id)

        if not sessions:
            ui.label("No sessions yet").classes(
                "text-center text-grey-6 q-pa-md"
            ).style("font-size: 0.875rem")


def session_item(session: dict, is_active: bool = False):
    """Render a single session item."""
    item_classes = "session-item active" if is_active else "session-item"

    with ui.row().classes(item_classes).style("padding: 0.5rem;"):
        ui.label("💬").classes("session-icon")

        title = session.get("title") or "New Chat"
        if title and len(title) > 30:
            title = title[:30] + "..."
        title_label = ui.label(title).classes("title flex-grow")
        title_label._title = session.get("title", "New Chat")

        ui.button(
            "×",
            on_click=lambda e, s=session: confirm_delete(e, s),
        ).props("flat round size-xs").style("color: var(--text-secondary);")

        if is_active:
            title_label.style("color: var(--accent-blue);")


def confirm_delete(e, session):
    """Confirm and delete a session."""
    e.stop_propagation()
    state = get_state()
    state.delete_session(session["id"])
    ui.notify(f"Deleted: {session.get('title', 'session')}")
    ui.navigate.to("/nicegui/")


def new_chat_button():
    """New chat button."""
    ui.button(
        "+ New Chat",
        on_click=lambda: create_new_session(),
    ).props("outline").classes("w-full").style("margin-top: 0.5rem;")


def create_new_session():
    """Create a new chat session."""
    state = get_state()
    session = state.create_session()
    if session:
        ui.navigate.to(f"/nicegui/sessions/{session['id']}")


def search_sessions():
    """Session search input."""
    ui.input(
        placeholder="Search sessions...",
        on_change=lambda e: filter_sessions(e.value),
    ).props("outlined dense").classes("w-full").style("margin-bottom: 0.5rem;")


def filter_sessions(query: str):
    """Filter sessions by query."""
    items = ui.context.client.find_children("session-item")
    for item in items:
        title = getattr(item, "_title", "")
        visible = query.lower() in title.lower() if title else False
        item.visible = visible
