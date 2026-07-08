"""Chat endpoints: WebSocket, SSE, and sync chat."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from .. import web_models
from ..config import get_safety_config, load_config as _load_config
from ..core import Agent
from ..core.session_runtime import deserialize_messages
from ..safety import SafetyConfig
from ..web_models import (
    AppState,
    ChatPayload,
    ChatRequest,
    WsConfigPayload,
    WsMessagePayload,
    get_state,
    require_unlocked,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


@router.post("/api/chat")
async def chat(
    message: ChatPayload,
    state: Annotated[AppState, Depends(get_state)],
    _unlocked: None = Depends(require_unlocked),
):
    """Non-streaming chat endpoint.

    Sends a message and waits for the complete response.
    Use for simple integrations or testing.

    For real-time streaming, use the WebSocket endpoint `/ws/chat`.

    Body:
        - content: The user's message
        - session_id: Optional session ID to continue a conversation

    Returns:
        {
            "response": "The assistant's response...",
            "messages": [...]
        }

    Example:
        ```bash
        curl -X POST http://localhost:8000/api/chat \\
          -H "Content-Type: application/json" \\
          -d '{"content": "Hello!"}'
        ```
    """
    if state.agent is None:
        raise HTTPException(
            status_code=400,
            detail="No agent initialized. Select a model from the frontend UI first.",
        )

    prompt = message.content
    state.message_history.append(
        {
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
    )

    response = await state.agent.run(prompt)

    state.message_history.append(
        {
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
    )

    return {"response": response, "messages": state.message_history}


@router.post("/chat")
async def handle_chat(
    request: ChatRequest,
    _unlocked: None = Depends(require_unlocked),
):
    """Synchronous chat endpoint."""
    try:
        from .. import web_api as _web_api
        agent = _web_api.get_or_create_agent(request)
        response = await agent.run(request.prompt)
        session_id = None
        if agent.session_manager and agent.session_manager.current_session:
            session_id = agent.session_manager.current_session.id
        return {
            "session_id": session_id,
            "response": response,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream")
async def stream_chat(
    prompt: str,
    session_id: str | None = None,
    provider: str = "ollama",
    model: str = "",
    _unlocked: None = Depends(require_unlocked),
):
    """Server-Sent Events (SSE) streaming endpoint."""
    from .. import web_api as _web_api
    req = ChatRequest(
        prompt=prompt, session_id=session_id, provider=provider, model=model
    )
    agent = _web_api.get_or_create_agent(req)

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_chunk(chunk: str):
        queue.put_nowait(chunk)

    async def chat_runner():
        try:
            await agent.run_streaming(prompt, on_chunk=on_chunk)
        finally:
            await queue.put(None)

    task = asyncio.create_task(chat_runner())

    async def event_generator():
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket chat endpoint for real-time streaming.

    Connect to: `wss://localhost:8080/ws/chat` (HTTPS/WSS required)

    ## Sending Messages

    Send JSON messages to the server:

    ```json
    {"type": "message", "content": "Hello!"}
    ```

    Optional: include session_id to continue a conversation.
    ```json
    {"type": "message", "content": "Hello!", "session_id": "20260319_143052"}
    ```

    To stop generation mid-stream:
    ```json
    {"type": "stop"}
    ```

    ## Receiving Messages

    Server sends JSON events:

    ```json
    {"type": "content", "content": "Hello"}  // Streaming content
    {"type": "thinking", "content": "Let me think..."}  // Model thinking
    {"type": "done", "content": "...", "tool_calls": [...]}  // Complete response
    {"type": "error", "content": "Error message"}  // Error occurred
    ```

    ## JavaScript Example

    ```javascript
    const ws = new WebSocket('wss://localhost:8080/ws/chat');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'content') {
            console.log('Received:', data.content);
        }
    };
    ws.send(JSON.stringify({type: 'message', content: 'Hi!'}));
    ```
    """
    from .. import web_api as _web_api

    scheme = websocket.scope.get("scheme", "ws")
    if scheme == "http":
        await websocket.close(code=4001, reason="HTTPS/WSS required")
        return

    api_key = _web_api._get_api_key()
    if api_key:
        auth = websocket.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or auth.removeprefix("Bearer ") != api_key:
            await websocket.close(code=4001, reason="Unauthorized: invalid or missing API key")
            return

    await websocket.accept()

    if web_models._state is None:
        await websocket.send_json(
            {"type": "error", "content": "Server not initialized"}
        )
        await websocket.close(code=1011, reason="Server not initialized")
        return

    if web_models.get_state().agent is None:
        await websocket.send_json(
            {"type": "error", "content": "Database is locked. Unlock via /api/unlock first."}
        )
        await websocket.close(code=4001, reason="Database is locked")
        return

    _ws_message_history: list[dict[str, Any]] = []
    active_agent: Agent | None = None
    streaming_task: asyncio.Task | None = None
    stop_requested = False
    pending_approvals: dict[str, asyncio.Future[bool]] = {}
    bg_tasks: set[asyncio.Task] = set()

    async def send_keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(15)
                await websocket.send_json({"type": "ping"})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"Keepalive error: {e}")

    keepalive_task = asyncio.create_task(send_keepalive())

    async def run_agent(prompt: str):
        nonlocal streaming_task, stop_requested
        if not active_agent:
            return

        # Ensure session exists and send session_start immediately
        if active_agent.session_manager:
            active_agent._ensure_session()
            if active_agent.session_manager.current_session:
                sid = active_agent.session_manager.current_session.id
                logger.warning(
                    "ws:trace run_agent session_start=%s messages=%d",
                    sid,
                    len(active_agent.messages),
                )
                try:
                    await websocket.send_json(
                        {
                            "type": "session_start",
                            "session_id": sid,
                        }
                    )
                except WebSocketDisconnect:
                    return

        timestamp = datetime.now().strftime("%H:%M")
        _ws_message_history.append(
            {"role": "user", "content": prompt, "timestamp": timestamp}
        )
        try:
            await websocket.send_json(
                {
                    "type": "message",
                    "role": "user",
                    "content": prompt,
                    "timestamp": timestamp,
                }
            )
        except WebSocketDisconnect:
            return

        accumulated_content = ""
        send_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1024)

        async def sender_loop():
            try:
                while True:
                    msg = await send_queue.get()
                    if msg is None:
                        break
                    try:
                        await websocket.send_json(msg)
                    except (WebSocketDisconnect, RuntimeError):
                        break
            except Exception as e:
                logger.debug(f"WebSocket sender loop error: {e}")

        sender_task = asyncio.create_task(sender_loop())

        def on_chunk(chunk: str) -> None:
            nonlocal accumulated_content
            if stop_requested:
                raise asyncio.CancelledError()
            accumulated_content += chunk
            with contextlib.suppress(asyncio.QueueFull):
                send_queue.put_nowait(
                    {"type": "content", "content": accumulated_content}
                )

        has_tools = False
        tool_calls_info = []

        if (
            active_agent.session_manager
            and active_agent.session_manager.current_session
        ):
            try:
                await websocket.send_json(
                    {
                        "type": "session_start",
                        "session_id": active_agent.session_manager.current_session.id,
                    }
                )
            except WebSocketDisconnect:
                return

        try:
            msg_count_before = len(active_agent.messages)
            await active_agent.run_streaming(prompt, on_chunk=on_chunk)
            for msg in active_agent.messages[msg_count_before:]:
                tc = getattr(msg, "tool_calls", None)
                if tc:
                    has_tools = True
                    tool_calls_info.extend(_web_api._extract_tool_calls_info(tc))

        except asyncio.CancelledError:
            has_tools = False
            tool_calls_info = []
            logger.debug("Generation cancelled, preserving partial content")
        except Exception as e:
            logger.error(f"WebSocket chat error: {e}", exc_info=True)
            await websocket.send_json(
                {
                    "type": "error",
                    "content": "An error occurred while processing your request. Please try again.",
                }
            )
            return
        finally:
            await send_queue.put(None)
            await sender_task
            streaming_task = None

        timestamp = datetime.now().strftime("%H:%M")

        _ws_message_history.append(
            {
                "role": "assistant",
                "content": accumulated_content,
                "timestamp": timestamp,
                "has_tools": has_tools,
            }
        )

        try:
            await websocket.send_json(
                {
                    "type": "done",
                    "content": accumulated_content,
                    "timestamp": timestamp,
                    "has_tools": has_tools,
                    "tool_calls": tool_calls_info,
                    "session_id": active_agent.session_manager.current_session.id
                    if active_agent.session_manager
                    and active_agent.session_manager.current_session
                    else None,
                    "title": active_agent.session_manager.current_session.title
                    if active_agent.session_manager
                    and active_agent.session_manager.current_session
                    else None,
                }
            )
        except WebSocketDisconnect:
            pass

        # Generate title in background (after sending done)
        if (
            active_agent.session_manager
            and active_agent.session_manager.current_session
            and not active_agent.session_manager.current_session.title
            and getattr(active_agent.session_manager.current_session, 'title_generation_attempted', None) is not True
        ):
            t = asyncio.create_task(_web_api._generate_title_async(active_agent, websocket))
            bg_tasks.add(t)
            t.add_done_callback(bg_tasks.discard)

    try:
        # 1. Wait for config
        raw_config = await websocket.receive_text()
        config = WsConfigPayload.model_validate_json(raw_config)

        # Build async approval callback that sends requests to the frontend
        async def ws_approval_callback(tool_name: str, details: str) -> bool:
            request_id = uuid.uuid4().hex[:12]
            future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
            pending_approvals[request_id] = future

            try:
                await websocket.send_json({
                    "type": "approval_request",
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "arguments": details,
                })
                return await asyncio.wait_for(future, timeout=120.0)
            except asyncio.TimeoutError:
                return False
            except WebSocketDisconnect:
                return False
            finally:
                pending_approvals.pop(request_id, None)

        base_conf = _load_config()
        base_safety = get_safety_config(base_conf)
        base_dict = {
            k: v for k, v in base_safety.__dict__.items()
            if not k.startswith("_") and k != "async_approval_callback"
        }
        ws_safety_config = SafetyConfig(
            **base_dict,
            async_approval_callback=ws_approval_callback,
        )

        active_agent = _web_api._create_runtime_agent(
            config.provider,
            config.model,
            api_key=config.api_key,
            session_id=config.session_id,
            safety_config_override=ws_safety_config,
        )
        # Store in global state so REST endpoints (sessions, config) use the same agent
        if web_models._state is not None:
            web_models._state.agent = active_agent
        assert active_agent is not None
        # Schedule background title gen for loaded untitled sessions (non-blocking)
        if (
            active_agent.session_manager
            and active_agent.session_manager.current_session
            and not active_agent.session_manager.current_session.title
            and getattr(active_agent.session_manager.current_session, 'title_generation_attempted', None) is not True
        ):
            t = asyncio.create_task(_web_api._generate_title_async(active_agent, websocket))
            bg_tasks.add(t)
            t.add_done_callback(bg_tasks.discard)

        await websocket.send_json(
            {
                "type": "ready",
                "session_id": active_agent.session_manager.current_session.id
                if active_agent.session_manager
                and active_agent.session_manager.current_session
                else None,
                "title": active_agent.session_manager.current_session.title
                if active_agent.session_manager
                and active_agent.session_manager.current_session
                else None,
            }
        )

        # 2. Continuous message loop
        while True:
            raw_message = await websocket.receive_text()
            data = json.loads(raw_message)

            # Handle approval responses before validating as chat message
            if data.get("type") == "approval_response":
                request_id = data.get("request_id")
                approved = data.get("approved", False)
                if request_id and request_id in pending_approvals:
                    pending_approvals[request_id].set_result(approved)
                continue

            message = WsMessagePayload.model_validate(data)

            if message.type == "pong":
                continue

            if message.type == "stop":
                stop_requested = True
                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                continue

            if message.type == "edit":
                edit_index = message.index
                edit_content = message.content

                logger.debug(
                    "ws:edit",
                    extra={
                        "index": edit_index,
                        "content": edit_content[:30] if edit_content else None,
                        "session_id": message.session_id,
                    },
                )

                if edit_index is None:
                    await websocket.send_json(
                        {"type": "error", "content": "Missing edit index"}
                    )
                    continue

                if not active_agent.session_manager or not message.session_id:
                    await websocket.send_json(
                        {"type": "error", "content": "No active session"}
                    )
                    continue

                session = active_agent.session_manager.load_session(message.session_id)
                if not session:
                    await websocket.send_json(
                        {"type": "error", "content": "Session not found"}
                    )
                    continue
                logger.debug(
                    "ws:edit:session_loaded",
                    extra={
                        "session_id": session.id if session else None,
                        "messages_count": len(session.messages) if session else 0,
                        "all_roles": [m.get("role") for m in session.messages]
                        if session
                        else [],
                    },
                )
                if (
                    not session
                    or edit_index < 0
                    or edit_index >= len(session.messages) - 1
                ):
                    await websocket.send_json(
                        {"type": "error", "content": "Invalid edit index"}
                    )
                    continue

                # Frontend excludes system message from its array, but session includes it
                # So frontend index 0 = session index 1, frontend index N = session index N+1
                target_index = edit_index + 1
                target_msg = session.messages[target_index]

                if target_msg.get("role") != "user":
                    await websocket.send_json(
                        {"type": "error", "content": "Can only edit user messages"}
                    )
                    continue

                logger.debug(
                    "ws:edit:target_msg",
                    extra={
                        "target_msg": target_msg,
                        "role": target_msg.get("role"),
                        "edit_index": edit_index,
                        "target_index": target_index,
                        "session_messages": session.messages,
                    },
                )

                if not edit_content:
                    await websocket.send_json(
                        {"type": "error", "content": "Missing edit content"}
                    )
                    continue

                logger.debug(
                    "ws:edit:processing",
                    extra={
                        "edit_index": edit_index,
                        "target_index": target_index,
                        "session_messages_before": len(session.messages),
                        "edit_content": edit_content[:50],
                    },
                )

                # Load session and truncate everything at and after target_index
                # run_agent will add the new user message
                active_agent.session_manager.current_session = session

                active_agent.session_manager.truncate_history(target_index)

                # Deserialize session messages to agent messages
                active_agent.messages = deserialize_messages(session.messages)

                # Also update local message_history to match the truncated session
                # _ws_message_history has no system message, so use edit_index
                _ws_message_history[:] = _ws_message_history[:edit_index]

                # Truncate any existing streaming task and run agent with new prompt
                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                    await asyncio.sleep(0.1)

                stop_requested = False
                streaming_task = asyncio.create_task(run_agent(edit_content))
                continue

            if message.type == "message" or not message.type:
                prompt = (message.content or "").strip()
                if not prompt:
                    continue

                # Load the session if session_id is provided
                if message.session_id and active_agent.session_manager:
                    prev_msg_count = len(active_agent.messages)
                    active_agent.messages = []
                    active_agent._pending_summary = None
                    prev_session_id = (
                        active_agent.session_manager.current_session.id
                        if active_agent.session_manager.current_session
                        else None
                    )
                    load_result = active_agent.load_session(message.session_id)
                    if load_result.startswith("Session not found"):
                        logger.warning(
                            "ws:session not visible, creating directly: %s",
                            message.session_id,
                        )
                        active_agent.session_manager.create_session(
                            session_id=message.session_id
                        )
                        active_agent.messages = []
                        load_result = active_agent.load_session(message.session_id)
                        if not load_result or load_result.startswith("Session not found"):
                            logger.error("Failed to load newly created session: %s", message.session_id)
                            await websocket.send_json({"type": "error", "content": "Failed to create session"})
                            continue
                    logger.warning(
                        "ws:trace load_session"
                        " requested=%s prev_session=%s prev_msgs=%d"
                        " result=%s"
                        " now_session=%s now_msgs=%d"
                        " db_path=%s"
                        " messages=%s",
                        message.session_id,
                        prev_session_id,
                        prev_msg_count,
                        load_result,
                        active_agent.session_manager.current_session.id
                        if active_agent.session_manager.current_session
                        else None,
                        len(active_agent.messages),
                        str(active_agent.session_manager.db_path),
                        [m.get("role") if isinstance(m, dict) else getattr(m, "role", "?")
                         for m in active_agent.messages[:3]],
                    )

                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                    await asyncio.sleep(0.1)  # Small delay to ensure cleanup

                stop_requested = False
                streaming_task = asyncio.create_task(run_agent(prompt))

    except (WebSocketDisconnect, json.JSONDecodeError, ValueError):
        pass
    except Exception as e:
        import traceback
        tb = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"WebSocket connection error: {e}\n{tb}", exc_info=True)
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "error",
                    "content": f"WebSocket error: {e}",
                }
            )
    finally:
        # Cancel any pending approval requests (deny by default)
        for future in pending_approvals.values():
            if not future.done():
                future.cancel()
        pending_approvals.clear()
        if streaming_task and not streaming_task.done():
            streaming_task.cancel()
        for t in list(bg_tasks):
            if not t.done():
                t.cancel()
        bg_tasks.clear()
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keepalive_task
