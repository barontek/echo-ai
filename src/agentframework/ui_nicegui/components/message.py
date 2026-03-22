"""Message bubble component for NiceGUI."""

import json
from nicegui import ui

from .markdown import render_markdown


def message_bubble(
    role: str, content: str, thinking: str = "", tool_calls: list = None
):
    """Render a chat message bubble."""
    bubble_classes = "message user" if role == "user" else "message assistant"

    with ui.column().classes(bubble_classes).style("width: 100%"):
        with ui.row().classes("message-header"):
            avatar = "👤" if role == "user" else "🤖"
            ui.label(avatar).classes("text-sm")
            ui.label("You" if role == "user" else "Assistant").classes(
                "text-xs text-grey-6"
            )

        content_html = render_markdown(content)
        if content_html:
            ui.html(f'<div class="message-content">{content_html}</div>')

        if tool_calls:
            tool_call_section(tool_calls)

        if thinking:
            thinking_section(thinking)


def tool_call_section(tool_calls: list):
    """Collapsible tool call display."""
    with ui.expansion("Tool Calls", icon="build").classes("tool-calls"):
        for tool in tool_calls:
            name = tool.get("name", "Unknown")
            arguments = tool.get("arguments", {})
            with (
                ui.card()
                .classes("tool-call")
                .style(
                    "background: var(--bg-tertiary); padding: 0.5rem; margin-bottom: 0.5rem;"
                )
            ):
                ui.label(f"🔧 {name}").classes("font-bold text-sm")
                ui.code(
                    json.dumps(arguments, indent=2),
                    props="copyable",
                ).style("font-size: 0.75rem; max-height: 200px; overflow: auto;")


def thinking_section(thinking: str):
    """Display thinking process."""
    thinking_html = render_markdown(thinking)
    with ui.expansion("Thinking", icon="psychology").classes("thinking-section"):
        ui.html(f'<div class="message-content">{thinking_html}</div>')


def streaming_message(content: str = "", thinking: str = ""):
    """Create a placeholder for streaming message."""
    container = ui.column().classes("message assistant").style("width: 100%")
    with container:
        with ui.row().classes("message-header"):
            ui.label("🤖").classes("text-sm")
            ui.label("Assistant").classes("text-xs text-grey-6")
            spinner = ui.html('<div class="loading-spinner"></div>')

    content_label = ui.html('<div class="message-content"></div>')
    thinking_label = ui.html('<div class="message-content text-grey-5"></div>')

    def update_streaming(new_content: str, new_thinking: str = ""):
        content_label.clear()
        with content_label:
            content_html = render_markdown(new_content)
            if content_html:
                ui.html(f'<div class="message-content">{content_html}</div>')
        if new_thinking:
            thinking_label.clear()
            with thinking_label:
                thinking_html = render_markdown(new_thinking)
                ui.html(
                    f'<div class="message-content text-grey-5">{thinking_html}</div>'
                )

    return container, content_label, thinking_label, spinner, update_streaming


def finish_streaming(spinner):
    """Finish streaming - remove spinner."""
    spinner.delete()
