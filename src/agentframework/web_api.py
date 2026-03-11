"""FastAPI web backend for Echo AI."""

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.agentframework.agent import Agent, AgentConfig, create_agent


app = FastAPI(title="Echo AI API")

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
message_history: list[dict] = []
stop_flag = {"stop": False}


class StopGeneration(Exception):
    """Exception to stop generation."""

    pass


@app.get("/")
async def index():
    """Serve the main HTML page."""
    return FileResponse("static/index.html")


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
    except Exception:
        pass
    return {"models": ["qwen3:4b-instruct", "llama3.2:latest", "phi3.5:latest"]}


@app.post("/api/config")
async def update_config(config: dict[str, Any]):
    """Update agent configuration."""
    global agent
    provider = config.get("provider", "ollama")
    model = config.get("model", "qwen3:4b-instruct")
    api_key = config.get("api_key")

    agent_config = AgentConfig(provider=provider, model=model)
    agent = create_agent(agent_config, api_key=api_key)

    return {"status": "ok", "config": {"provider": provider, "model": model}}


@app.get("/api/sessions")
async def list_sessions():
    """List all sessions."""
    if agent and agent.session_manager:
        sessions = agent.list_sessions()
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
    message_history = []
    return {"session_id": current_session_id}


@app.get("/api/sessions/{session_id}")
async def load_session(session_id: str):
    """Load a session."""
    global current_session_id, message_history
    if agent and agent.session_manager:
        agent.load_session(session_id)
        current_session_id = session_id
        message_history = [
            {"role": msg.role, "content": msg.content} for msg in agent.messages
        ]
        return {"session_id": session_id, "messages": message_history}
    return {"session_id": session_id, "messages": []}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(message: dict[str, Any]):
    """Non-streaming chat endpoint."""
    global agent, message_history

    if agent is None:
        agent_config = AgentConfig(provider="ollama", model="qwen3:4b-instruct")
        agent = create_agent(agent_config)

    prompt = message.get("content", "")
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
    """WebSocket chat with streaming."""
    global agent, message_history

    await websocket.accept()

    try:
        # Receive initial config
        data = await websocket.receive_text()
        config = json.loads(data)

        provider = config.get("provider", "ollama")
        model = config.get("model", "qwen3:4b-instruct")
        api_key = config.get("api_key")

        agent_config = AgentConfig(provider=provider, model=model)
        agent = create_agent(agent_config, api_key=api_key)
        active_agent = agent

        # Send ready confirmation
        await websocket.send_json({"type": "ready"})

        streaming_task = None

        while True:
            # Receive user message
            data = await websocket.receive_text()
            message = json.loads(data)

            # Handle stop command
            if message.get("type") == "stop":
                stop_flag["stop"] = True
                # Cancel any existing streaming task
                if streaming_task:
                    streaming_task.cancel()
                continue

            prompt = message.get("content", "")
            timestamp = datetime.now().strftime("%H:%M")

            # Reset stop flag
            stop_flag["stop"] = False
            message_history.append(
                {"role": "user", "content": prompt, "timestamp": timestamp}
            )

            # Send user message
            await websocket.send_json(
                {
                    "type": "message",
                    "role": "user",
                    "content": prompt,
                    "timestamp": timestamp,
                }
            )

            # Setup for streaming
            accumulated_content = ""
            thinking_content = ""
            in_thinking = False
            send_queue: asyncio.Queue = asyncio.Queue()

            async def sender_loop():
                while True:
                    msg = await send_queue.get()
                    if msg is None:
                        break
                    await websocket.send_json(msg)

            sender_task = asyncio.create_task(sender_loop())

            async def run_with_cancellation():
                """Run streaming in a way that can be cancelled."""
                nonlocal accumulated_content, thinking_content, in_thinking

                # Create the task
                task = asyncio.current_task()

                def on_chunk(chunk: str):
                    nonlocal accumulated_content, thinking_content, in_thinking

                    # Check if cancelled
                    if task is not None and task.cancelled():
                        raise asyncio.CancelledError()

                    if stop_flag["stop"]:
                        raise asyncio.CancelledError()

                    if "__THINKING__" in chunk:
                        chunk = chunk.replace("__THINKING__", "")
                        in_thinking = True

                    if "__THINKING_END__" in chunk:
                        chunk = chunk.replace("__THINKING_END__", "")
                        in_thinking = False

                    if in_thinking or "__THINKING__" in chunk:
                        thinking_content += chunk
                        send_queue.put_nowait(
                            {"type": "thinking", "content": thinking_content}
                        )
                    else:
                        accumulated_content += chunk
                        send_queue.put_nowait(
                            {"type": "content", "content": accumulated_content}
                        )

                return await active_agent.run_streaming(prompt, on_chunk=on_chunk)

            # Run as a task that can be cancelled
            streaming_task = asyncio.create_task(run_with_cancellation())

            try:
                response = await streaming_task
            except asyncio.CancelledError:
                # Clean up
                await send_queue.put(None)
                await sender_task
                accumulated_content = "Stopped."
                thinking_content = ""
                timestamp = datetime.now().strftime("%H:%M")
                await websocket.send_json(
                    {
                        "type": "done",
                        "content": accumulated_content,
                        "thinking": thinking_content,
                        "timestamp": timestamp,
                    }
                )
                continue
            finally:
                streaming_task = None

            # Cleanup sender
            await send_queue.put(None)
            await sender_task

            # Check if stopped
            if stop_flag["stop"]:
                accumulated_content = "Stopped."
                thinking_content = ""
                stop_flag["stop"] = False

            timestamp = datetime.now().strftime("%H:%M")

            message_history.append(
                {
                    "role": "assistant",
                    "content": accumulated_content,
                    "timestamp": timestamp,
                    "thinking": thinking_content,
                }
            )

            await websocket.send_json(
                {
                    "type": "done",
                    "content": accumulated_content,
                    "thinking": thinking_content,
                    "timestamp": timestamp,
                }
            )

            # Send user message
            await websocket.send_json(
                {
                    "type": "message",
                    "role": "user",
                    "content": prompt,
                    "timestamp": timestamp,
                }
            )

            # Setup for streaming
            accumulated_content = ""
            thinking_content = ""
            in_thinking = False
            send_queue: asyncio.Queue = asyncio.Queue()

            async def sender():
                while True:
                    msg = await send_queue.get()
                    if msg is None:
                        break
                    await websocket.send_json(msg)

            sender_task = asyncio.create_task(sender())

            def on_chunk(chunk: str):
                nonlocal accumulated_content, thinking_content, in_thinking

                # Check stop flag - raise exception to actually stop streaming
                if stop_flag["stop"]:
                    raise StopGeneration("Generation stopped by user")

                if "__THINKING__" in chunk:
                    chunk = chunk.replace("__THINKING__", "")
                    in_thinking = True

                if "__THINKING_END__" in chunk:
                    chunk = chunk.replace("__THINKING_END__", "")
                    in_thinking = False

                if in_thinking or "__THINKING__" in chunk:
                    thinking_content += chunk
                    send_queue.put_nowait(
                        {"type": "thinking", "content": thinking_content}
                    )
                else:
                    accumulated_content += chunk
                    send_queue.put_nowait(
                        {"type": "content", "content": accumulated_content}
                    )

            # Run streaming
            try:
                response = await agent.run_streaming(prompt, on_chunk=on_chunk)
            except StopGeneration:
                # Stopped by user - cleanup and send stopped message
                await send_queue.put(None)
                await sender_task
                accumulated_content = "Stopped."
                thinking_content = ""
                stop_flag["stop"] = False
                timestamp = datetime.now().strftime("%H:%M")
                await websocket.send_json(
                    {
                        "type": "done",
                        "content": accumulated_content,
                        "thinking": thinking_content,
                        "timestamp": timestamp,
                    }
                )
                continue

            # Cleanup sender
            await send_queue.put(None)
            await sender_task

            # Check if stopped
            if stop_flag["stop"]:
                accumulated_content = "Stopped."
                thinking_content = ""
                stop_flag["stop"] = False
            else:
                accumulated_content = (
                    accumulated_content if accumulated_content else response
                )

            timestamp = datetime.now().strftime("%H:%M")

            message_history.append(
                {
                    "role": "assistant",
                    "content": accumulated_content,
                    "timestamp": timestamp,
                    "thinking": thinking_content,
                }
            )

            await websocket.send_json(
                {
                    "type": "done",
                    "content": accumulated_content,
                    "thinking": thinking_content,
                    "timestamp": timestamp,
                }
            )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await websocket.send_json({"type": "error", "content": str(e)})


def run_server(host: str = "0.0.0.0", port: int = 8501):
    """Run the FastAPI server."""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
