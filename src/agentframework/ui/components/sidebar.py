"""Sidebar component for session management."""

from nicegui import ui

from ..state import get_state
from ..config import DEFAULT_MODEL


def sidebar_header():
    """Render sidebar header with title and theme toggle."""
    with ui.row().classes("sidebar-header w-full"):
        ui.label("Echo AI").classes("brand-text")
        ui.space()
        ui.button(
            icon="dark_mode",
            on_click=lambda: toggle_theme(),
        ).props("flat round dense size=sm").style("color: var(--text-secondary)")


def theme_toggle():
    """Theme toggle button."""
    ui.button(
        icon="dark_mode",
        on_click=lambda: ui.dark_mode().toggle(),
    ).props("flat round dense").style("color: var(--text-secondary)")


def toggle_theme():
    """Toggle between dark and light theme."""
    ui.dark_mode().toggle()


def model_selector(models: list, current_model: str = DEFAULT_MODEL):
    """Model selection dropdown."""
    with ui.column().classes("sidebar-section w-full gap-0"):
        ui.label("Model").classes("text-xs text-grey-6 uppercase tracking-wider mb-2 font-semibold")
        ui.select(
            options=models,
            value=current_model,
            on_change=lambda e: update_model(e.value),
        ).props("outlined dense options-dense dark").style("width: 100%")


def update_model(model: str):
    """Update the current model."""
    state = get_state()
    state.model = model


@ui.refreshable
def session_list(sessions: list, active_id: str = "", search_query: str = ""):
    """Render the session list."""
    with ui.column().classes("session-list w-full"):
        filtered = sessions
        if search_query:
            q = str(search_query).lower()
            filtered = [s for s in sessions if q in (s.get("title") or "new chat").lower()]

        for session in filtered:
            session_item(session, is_active=session.get("id") == active_id)

        if not filtered:
            ui.label("No sessions found" if search_query else "No sessions yet").classes(
                "text-center text-grey-6 w-full"
            ).style("font-size: 0.875rem; padding: 1rem; box-sizing: border-box; margin: 0;")


def session_item(session: dict, is_active: bool = False):
    """Render a single session item."""
    item_classes = "session-item active" if is_active else "session-item"

    with ui.row().classes(item_classes).on("click", lambda: ui.navigate.to(f"/sessions/{session['id']}")):
        ui.icon("chat_bubble_outline", size="xs").classes("opacity-70")

        title = session.get("title") or "New Chat"
        if title and len(title) > 30:
            title = title[:30] + "..."
        ui.label(title).classes("title")

        ui.button(
            icon="delete_outline",
        ).on("click.stop", lambda e, s=session: confirm_delete(e, s)).props("flat round dense size=sm").classes("btn-delete")


def confirm_delete(e, session):
    """Confirm and delete a session."""
    state = get_state()
    state.delete_session(session["id"])
    ui.notify(f"Deleted: {session.get('title', 'session')}")
    ui.navigate.to("/")


def new_chat_button():
    """New chat button."""
    ui.button(
        "New Chat",
        icon="add",
        on_click=lambda: create_new_session(),
    ).props("unelevated").classes("new-chat-btn mb-2 full-width").style("height: 42px; font-size: 0.9rem;")


def create_new_session():
    """Create a new chat session."""
    state = get_state()
    session = state.create_session()
    if session:
        ui.navigate.to(f"/sessions/{session['id']}")


def search_sessions(sessions: list, active_id: str = ""):
    """Session search input."""
    def handle_search(e):
        val = str(e.value) if e.value is not None else ""
        session_list.refresh(sessions, active_id, search_query=val)

    ui.input(
        placeholder="Search chats...",
        on_change=handle_search,
    ).props("outlined dense dark clearable").classes("mb-2 full-width").style("font-size: 0.9rem;")

    with ui.row().classes("w-full items-center justify-between mt-2 mb-2"):
        ui.label("Session History").classes("text-xs text-grey-6 uppercase tracking-wider font-semibold")
