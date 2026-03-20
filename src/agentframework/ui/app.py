"""FastHTML app for Echo AI chat UI.

Phase 2: Core components with API integration.
"""

from fasthtml.common import *  # noqa: F403, F405, E501
import httpx
import json

from .components import (
    main_page,
    chat_container,
    session_item,
    message_bubble,
)
from .markdown import format_message_content

app, rt = fast_app(debug=True, exts=["ws"])


def get_api(url: str, path: str = "") -> dict:
    """Fetch data from FastAPI endpoints."""
    base = url.rstrip("/")
    try:
        resp = httpx.get(f"{base}{path}", timeout=5)
        return resp.json()
    except Exception:
        return {}


def post_api(url: str, path: str = "", json_data: dict | None = None) -> dict:
    """Post data to FastAPI endpoints."""
    base = url.rstrip("/")
    try:
        resp = httpx.post(f"{base}{path}", json=json_data, timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@rt("/")
def get():
    """Main chat page - fetches initial data from API."""
    api_base = "http://127.0.0.1:8000/api"

    models_data = get_api(api_base, "/models")
    models = models_data.get("models", ["qwen3:4b-instruct"])

    sessions_data = get_api(api_base, "/sessions")
    sessions = sessions_data.get("sessions", [])

    return main_page(models, sessions, [], models[0] if models else "")


@rt("/sessions/new")
def new_session():
    """Create a new session. Must be defined before /sessions/{session_id}."""
    api_base = "http://127.0.0.1:8000/api"

    data = post_api(api_base, "/sessions")
    session_id = data.get("session_id")

    if session_id:
        return session_item({"id": session_id, "title": "New Chat"})
    return P("Failed to create session", style="color: red;")


@rt("/sessions/{session_id}")
def get_session(session_id: str):
    """Load a session and return its messages."""
    api_base = "http://127.0.0.1:8000/api"

    data = get_api(api_base, f"/sessions/{session_id}")
    messages = data.get("messages", [])

    bubbles = []
    for msg in messages:
        bubbles.append(
            message_bubble(
                role=msg.get("role", "assistant"),
                content=msg.get("content", ""),
                thinking=msg.get("thinking", ""),
            )
        )

    return chat_container(messages)


@rt("/models")
def update_model():
    """Handle model selection."""
    api_base = "http://127.0.0.1:8000/api"
    models_data = get_api(api_base, "/models")
    models = models_data.get("models", [])

    options = [Option(m, value=m) for m in models]
    return Select(
        *options,
        id="model-select",
        name="model",
        hx_get="/ui/models",
        hx_target="#model-select",
        hx_swap="outerHTML",
    )


@rt("/chat")
async def chat(message: str = ""):
    """Handle chat message submission."""
    if not message.strip():
        return ""

    user_msg = message_bubble(role="user", content=message)

    return Div(user_msg, id="new-message", cls="new-message")


@rt("/sessions/delete/{session_id}")
def delete_session(session_id: str):
    """Delete a session."""
    api_base = "http://127.0.0.1:8000/api"

    post_api(api_base, "/sessions/delete", {"session_id": session_id})

    return P(f"Deleted: {session_id}", style="color: green;")


@app.ws("/ws/chat")
async def chat_ws(message: str, model: str, send):
    """Handle incoming form submissions via WebSocket and stream the response."""
    import websockets

    if not message.strip():
        return

    temp_id = "streaming-msg"

    user_bubble = message_bubble(role="user", content=message)
    await send(Div(user_bubble, id="chat-container", hx_swap_oob="beforeend"))

    loading_msg = Div(
        Div("Assistant", cls="role"),
        Div("Thinking...", id=f"{temp_id}-content", cls="content"),
        id=temp_id,
        cls="message assistant",
    )
    await send(Div(loading_msg, id="chat-container", hx_swap_oob="beforeend"))

    ws_url = "ws://127.0.0.1:8000/ws/chat"

    try:
        async with websockets.connect(ws_url) as ws:
            await ws.send(
                json.dumps({"type": "message", "content": message, "model": model})
            )
            accumulated = ""

            async for response in ws:
                data = json.loads(response)

                if data["type"] == "content":
                    accumulated += data["content"]
                    html_content = format_message_content(accumulated)
                    await send(
                        Div(
                            html_content,
                            id=f"{temp_id}-content",
                            hx_swap_oob="innerHTML",
                        )
                    )

                elif data["type"] == "done":
                    final = message_bubble(
                        role="assistant",
                        content=data["content"],
                        thinking=data.get("thinking", ""),
                    )
                    await send(Div(final, id=temp_id, hx_swap_oob="outerHTML"))
                    break

                elif data["type"] == "error":
                    await send(
                        Div(
                            f"Error: {data['content']}",
                            id=temp_id,
                            cls="message assistant",
                            style="color: red;",
                            hx_swap_oob="outerHTML",
                        )
                    )
                    break

    except Exception as e:
        await send(
            Div(
                f"Error: {str(e)}",
                id=temp_id,
                cls="message assistant",
                style="color: red;",
                hx_swap_oob="outerHTML",
            )
        )
