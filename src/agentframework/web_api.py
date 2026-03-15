"""FastAPI web backend for Echo AI."""

import asyncio
import contextlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.agentframework.agent import Agent, AgentConfig, create_agent
from src.agentframework.config import get_safety_config, get_tools, load_config
from src.agentframework.session import DBSessionModel
from src.workflows import get_workflow, list_workflows

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for the agent framework."""
    global agent
    if agent is None:
        try:
            agent = _create_runtime_agent(provider="ollama", model="qwen3:4b-instruct")
        except Exception as e:
            # Fallback if Ollama is not initialized yet
            logger.debug(f"Ollama agent initialization deferred: {e}")
    yield
    if agent:
        agent.close()


app = FastAPI(title="Echo AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
agent: Agent | None = None
current_session_id: str | None = None
message_history: list[dict[str, Any]] = []




def filter_messages_for_ui(messages: list[Any]) -> list[dict[str, Any]]:
    """Filter messages for UI rendering, removing raw tool/system noise."""
    filtered = []

    # Internal framework strings to ignore
    internal_patterns = [
        r"System Note: Tools executed",
        r"Tool '.*' returned:",
        r"^FAILED: .*",
        r"\[Persistent Memory\]"
    ]
    import re

    for msg in messages:
        role = getattr(msg, "role", msg.get("role") if isinstance(msg, dict) else "")
        content = getattr(msg, "content", msg.get("content") if isinstance(msg, dict) else "") or ""

        # Extract metadata if available
        metadata = getattr(msg, "metadata", msg.get("metadata") if isinstance(msg, dict) else None)
        timestamp = getattr(msg, "timestamp", msg.get("timestamp") if isinstance(msg, dict) else "")
        thinking = getattr(msg, "thinking", msg.get("thinking") if isinstance(msg, dict) else "")

        if metadata and isinstance(metadata, dict):
            timestamp = timestamp or metadata.get("timestamp", "")
            thinking = thinking or metadata.get("thinking", "")

        # 1. Handle assistant messages with tool calls first
        tool_calls = getattr(msg, "tool_calls", msg.get("tool_calls") if isinstance(msg, dict) else None)
        has_tools = bool(tool_calls)

        # 2. Skip logic (system and tool messages are always skipped)
        if role in ["system", "tool"]:
            continue

        # If it's an assistant message with tools, we NEVER continue/skip it here.
        # Otherwise, check skip conditions:
        if not has_tools:
            # Drop if it's truly empty assistant message
            if role == "assistant" and not content.strip():
                continue

            # Ignore internal framework strings
            is_internal = any(re.search(pattern, content) for pattern in internal_patterns)
            if is_internal:
                continue

        # 3. Extract thinking content if present (stored with markers)
        display_content = content
        if not thinking and "__THINKING__" in content and "__THINKING_END__" in content:
            parts = content.split("__THINKING_END__", 1)
            thinking = parts[0].replace("__THINKING__", "").strip()
            display_content = parts[1].strip()

        msg_dict = {
            "role": role,
            "content": display_content,
            "timestamp": timestamp,
            "has_tools": has_tools,
        }
        if thinking:
            msg_dict["thinking"] = thinking

        filtered.append(msg_dict)

    return filtered



def _create_runtime_agent(
    provider: str,
    model: str,
    api_key: str | None = None,
    session_id: str | None = None,
) -> Agent:
    """Create an agent for the web UI with the same tool config as CLI."""
    # Safety check for model name
    if not model or model == "Loading models..." or "models..." in model:
        model = "qwen3:4b-instruct"
    config = load_config()
    safety_config = get_safety_config(config)
    tools = get_tools(config, safety_config)

    agent_config = AgentConfig(
        provider=provider,
        model=model,
        temperature=config.get("model", {}).get("temperature", 0.3),
        max_iterations=config.get("agent", {}).get("max_iterations", 50),
        system_prompt=config.get("agent", {}).get("system_prompt", ""),
        tools=tools,
        base_url=config.get("model", {}).get("base_url"),
        session_enabled=config.get("agent", {}).get("session_enabled", True),
        session_dir=config.get("agent", {}).get("session_dir", ".agent_sessions"),
    )

    env_info = (
        "\n\n## Environment\n"
        f"- Current working directory: {Path.cwd()}\n"
        f"- Workspace (file operations confined to): {safety_config.workspace or '.'}\n"
    )
    if agent_config.system_prompt:
        agent_config.system_prompt += env_info
    else:
        agent_config.system_prompt = (
            "You are an AI assistant with access to various tools." + env_info
        )

    return create_agent(agent_config, api_key=api_key, session_id=session_id)


class ConfigPayload(BaseModel):
    provider: str = "ollama"
    model: str = "qwen3:4b-instruct"
    api_key: str | None = None


class ChatPayload(BaseModel):
    content: str = Field(default="", min_length=1)


class SessionRenamePayload(BaseModel):
    session_id: str
    new_title: str = Field(min_length=1)


class WsConfigPayload(BaseModel):
    provider: str = "ollama"
    model: str = Field(default="qwen3:4b-instruct", min_length=1)
    api_key: str | None = None
    session_id: str | None = None


class WsMessagePayload(BaseModel):
    type: str | None = None
    content: str | None = None


class WorkflowRunPayload(BaseModel):
    workflow_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)


@app.get("/")
async def index():
    """Serve the main HTML page."""
    return FileResponse("static/index.html")




@app.get("/workflows")
async def workflows_page():
    """Serve the dedicated workflows page."""
    return FileResponse("static/workflows.html")

@app.get("/static/{path:path}")
async def static_files(path: str):
    """Serve static files."""
    return FileResponse(f"static/{path}")


@app.get("/api/models")
async def list_models():
    """List available Ollama models."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:11434/api/tags", timeout=5.0)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return {"models": [m["name"] for m in models]}
    except Exception as e:
        logger.debug(f"Failed to fetch Ollama models: {e}")
    return {"models": ["qwen3:4b-instruct", "llama3.2:latest", "phi3.5:latest"]}


@app.post("/api/config")
async def update_config(config: ConfigPayload):
    """Update agent configuration."""
    global agent
    agent = _create_runtime_agent(config.provider, config.model, api_key=config.api_key)
    return {
        "status": "ok",
        "config": {"provider": config.provider, "model": config.model},
    }


@app.get("/api/sessions")
async def list_sessions():
    """List all sessions."""
    global agent
    if agent is None:
        try:
            agent = _create_runtime_agent(provider="ollama", model="qwen3:4b-instruct")
        except Exception as e:
            logger.debug(f"Deferred agent creation failed: {e}")

    if agent and agent.session_manager:
        sessions = [
            {"id": s.id, "title": s.title, "created_at": s.created_at.isoformat()}
            for s in agent.session_manager.list_sessions()
        ]
        return {"sessions": sessions}
    return {"sessions": []}


@app.post("/api/sessions")
async def create_session():
    """Create a new session."""
    global current_session_id, message_history
    if agent and agent.session_manager:
        agent.session_manager.create_session()
        if agent.session_manager.current_session:
            current_session_id = agent.session_manager.current_session.id
            agent.messages = [] # Clear agent's internal message history
    message_history = []
    return {"session_id": current_session_id}


@app.get("/api/sessions/{session_id}")
async def load_session(session_id: str):
    """Load a session."""
    global current_session_id, message_history
    if agent and agent.session_manager:
        agent.load_session(session_id)
        current_session_id = session_id
        message_history = filter_messages_for_ui(agent.messages)
        title = None
        if agent.session_manager.current_session:
            title = agent.session_manager.current_session.title
        return {
            "session_id": session_id,
            "title": title,
            "messages": message_history
        }

    return {"session_id": session_id, "messages": [], "title": None}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    if not (agent and agent.session_manager):
        return {"status": "ok"}

    with agent.session_manager.SessionLocal() as db:
        db.query(DBSessionModel).filter(DBSessionModel.id == session_id).delete()
        db.commit()

    return {"status": "ok"}


@app.post("/api/sessions/rename")
async def rename_session(payload: SessionRenamePayload):
    """Rename a session by changing its title."""
    if not (agent and agent.session_manager):
        raise HTTPException(status_code=400, detail="Session manager unavailable")

    with agent.session_manager.SessionLocal() as db:
        updated = (
            db.query(DBSessionModel)
            .filter(DBSessionModel.id == payload.session_id)
            .update({"title": payload.new_title})
        )
        if updated == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        db.commit()

    if agent.session_manager.current_session and agent.session_manager.current_session.id == payload.session_id:
        agent.session_manager.current_session.title = payload.new_title

    return {"status": "ok", "session_id": payload.session_id, "title": payload.new_title}


@app.post("/api/sessions/purge")
async def purge_sessions(days: int | None = None):
    """Purge old or all sessions."""
    if not (agent and agent.session_manager):
        raise HTTPException(status_code=400, detail="Session manager unavailable")

    count = agent.session_manager.purge_sessions(older_than_days=days)
    return {"status": "ok", "purged_count": count}


@app.get("/api/workflows")
async def workflows_list():
    """List available workflows for UI consumption."""
    return {"workflows": list_workflows()}


@app.post("/api/workflows/run")
async def workflow_run(payload: WorkflowRunPayload):
    """Run a selected workflow and return its final output."""
    global agent, message_history

    if agent is None:
        agent = _create_runtime_agent(provider="ollama", model="qwen3:4b-instruct")

    try:
        workflow = get_workflow(payload.workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    initial_state = {"topic": payload.topic, "agent": agent}
    final_state = await workflow.compile_and_run(initial_state)
    content = final_state.get("final") or final_state.get("result") or str(final_state)

    timestamp = datetime.now().strftime("%H:%M")
    user_content = f"[Workflow: {payload.workflow_id}] {payload.topic}"
    message_history.append({"role": "user", "content": user_content, "timestamp": timestamp})
    message_history.append({"role": "assistant", "content": content, "timestamp": timestamp})

    return {"workflow_id": payload.workflow_id, "response": content, "timestamp": timestamp}


@app.post("/api/chat")
async def chat(message: ChatPayload):
    """Non-streaming chat endpoint."""
    global agent, message_history

    if agent is None:
        agent = _create_runtime_agent(provider="ollama", model="qwen3:4b-instruct")

    prompt = message.content
    message_history.append(
        {
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
    )

    response = await agent.run(prompt)

    message_history.append(
        {
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().strftime("%H:%M"),
        }
    )

    return {"response": response, "messages": message_history}


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """Handle chat WebSocket connection with non-blocking stop support."""
    await websocket.accept()

    active_agent: Agent | None = None
    streaming_task: asyncio.Task | None = None
    stop_requested = False

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

        timestamp = datetime.now().strftime("%H:%M")
        message_history.append({"role": "user", "content": prompt, "timestamp": timestamp})
        await websocket.send_json(
            {"type": "message", "role": "user", "content": prompt, "timestamp": timestamp}
        )

        accumulated_content = ""
        thinking_content = ""
        in_thinking = False
        send_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=1024)

        async def sender_loop():
            try:
                while True:
                    msg = await send_queue.get()
                    if msg is None:
                        break
                    await websocket.send_json(msg)
            except Exception as e:
                logger.debug(f"WebSocket sender loop error: {e}")

        sender_task = asyncio.create_task(sender_loop())

        def on_chunk(chunk: str) -> None:
            nonlocal accumulated_content, thinking_content, in_thinking
            if stop_requested:
                raise asyncio.CancelledError()

            if "__THINKING__" in chunk:
                chunk = chunk.replace("__THINKING__", "")
                in_thinking = True
            if "__THINKING_END__" in chunk:
                chunk = chunk.replace("__THINKING_END__", "")
                in_thinking = False

            if in_thinking:
                thinking_content += chunk
                payload = {"type": "thinking", "content": thinking_content}
            else:
                accumulated_content += chunk
                payload = {"type": "content", "content": accumulated_content}

            with contextlib.suppress(asyncio.QueueFull):
                send_queue.put_nowait(payload)

        has_tools = False
        try:
            response = await active_agent.run_streaming(prompt, on_chunk=on_chunk)

            # Check for tool calls
            if active_agent.messages:
                last_msg = active_agent.messages[-1]
                if getattr(last_msg, "tool_calls", None):
                    has_tools = True

            if not accumulated_content:
                accumulated_content = response

        except asyncio.CancelledError:
            accumulated_content = "Stopped."
            thinking_content = ""
            has_tools = False
        except Exception as e:
            await websocket.send_json({"type": "error", "content": str(e)})
            return
        finally:
            await send_queue.put(None)
            await sender_task
            streaming_task = None

        timestamp = datetime.now().strftime("%H:%M")
        message_history.append({
            "role": "assistant",
            "content": accumulated_content,
            "timestamp": timestamp,
            "thinking": thinking_content,
            "has_tools": has_tools,
        })

        # Trigger auto-title during conversation if it was a new session
        if active_agent.session_manager and active_agent.session_manager.current_session and not active_agent.session_manager.current_session.title:
             new_title = await active_agent.generate_title()
             if new_title:
                 active_agent.session_manager.current_session.title = new_title
                 active_agent.save_session()

        await websocket.send_json({
            "type": "done",
            "content": accumulated_content,
            "thinking": thinking_content,
            "timestamp": timestamp,
            "has_tools": has_tools,
            "session_id": active_agent.session_manager.current_session.id if active_agent.session_manager and active_agent.session_manager.current_session else None,
            "title": active_agent.session_manager.current_session.title if active_agent.session_manager and active_agent.session_manager.current_session else None
        })

    try:
        # 1. Wait for config
        raw_config = await websocket.receive_text()
        config = WsConfigPayload.model_validate_json(raw_config)
        active_agent = _create_runtime_agent(
            config.provider,
            config.model,
            api_key=config.api_key,
            session_id=config.session_id,
        )
        # Trigger auto-title if needed
        if active_agent.session_manager and active_agent.session_manager.current_session and not active_agent.session_manager.current_session.title:
            new_title = await active_agent.generate_title()
            if new_title:
                active_agent.session_manager.current_session.title = new_title
                active_agent.save_session()

        await websocket.send_json({
            "type": "ready",
            "session_id": active_agent.session_manager.current_session.id if active_agent.session_manager and active_agent.session_manager.current_session else None,
            "title": active_agent.session_manager.current_session.title if active_agent.session_manager and active_agent.session_manager.current_session else None
        })

        # 2. Continuous message loop
        while True:
            raw_message = await websocket.receive_text()
            message = WsMessagePayload.model_validate_json(raw_message)

            if message.type == "pong":
                continue

            if message.type == "stop":
                stop_requested = True
                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                continue

            if message.type == "message" or not message.type:
                prompt = (message.content or "").strip()
                if not prompt:
                    continue

                if streaming_task and not streaming_task.done():
                    streaming_task.cancel()
                    await asyncio.sleep(0.1) # Small delay to ensure cleanup

                stop_requested = False
                streaming_task = asyncio.create_task(run_agent(prompt))

    except (WebSocketDisconnect, json.JSONDecodeError, ValueError):
        pass
    except Exception as e:
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "content": str(e)})
    finally:
        if streaming_task and not streaming_task.done():
            streaming_task.cancel()
        keepalive_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keepalive_task


@app.get("/api/review")
async def review_document():
    """Expose review recommendations for UI hints."""
    review_path = Path("docs/WEB_UI_REVIEW.md")
    if not review_path.exists():
        return {"sections": []}

    lines = review_path.read_text(encoding="utf-8").splitlines()
    sections: list[str] = []
    for line in lines:
        if line.startswith("## "):
            sections.append(line.removeprefix("## ").strip())
    return {"sections": sections}


def run_server(host: str = "127.0.0.1", port: int = 8501):
    """Run the FastAPI server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
