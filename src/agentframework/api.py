"""FastAPI server for the Echo AI framework."""

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
import json

from src.agentframework.agent import AgentConfig, create_agent
from src.agentframework.router import SemanticRouter

app = FastAPI(
    title="Echo AI API",
    description="High-performance async server for multi-agent capabilities.",
    version="1.0.0"
)

# A global dictionary holding active agent instances.
# In a true deployment, you'd use a redis cache or dependency injection.
agents = {}

class ChatRequest(BaseModel):
    session_id: str | None = None
    prompt: str
    provider: str = "ollama"
    model: str = "qwen3:4b-instruct"
    api_key: str | None = None
    stream: bool = False

class RouteRequest(BaseModel):
    prompt: str

@app.on_event("startup")
async def startup_event():
    """Initialize a default agent and router on startup."""
    config = AgentConfig(provider="ollama", model="qwen3:4b-instruct")
    agent = create_agent(config)

    # Register some example sub-agents for routing tests
    agent.register_sub_agent(
        name="code_agent",
        description="Handles coding, programming, debugging, and software architecture questions.",
    )
    agent.register_sub_agent(
        name="research_agent",
        description="Handles web scraping, general knowledge, and deep contextual research.",
    )

    agents["default"] = agent
    app.state.router = SemanticRouter(agent)

def get_or_create_agent(req: ChatRequest):
    """Retrieve an existing agent for a session or create a new one."""
    key = req.session_id or "default"

    if key not in agents:
        config = AgentConfig(
            provider=req.provider,
            model=req.model,
            session_enabled=True
        )
        agent = create_agent(config, api_key=req.api_key)

        if req.session_id and agent.session_manager:
            # Load or create session history in SQLite
            agent.session_manager.create_session(req.session_id)

        agents[key] = agent

    return agents[key]

@app.post("/chat")
async def chat(request: ChatRequest):
    """Synchronous chat endpoint."""
    try:
        agent = get_or_create_agent(request)
        response = await agent.run(request.prompt)
        return {
            "session_id": agent.session_manager.current_session.id if agent.session_manager.current_session else None,
            "response": response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/route")
async def route_intent(request: RouteRequest):
    """Determine the optimal sub-agent for a user prompt via Semantic Routing."""
    try:
        router = app.state.router
        target = await router.route(request.prompt)
        return {"target_agent": target}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stream")
async def stream_chat(prompt: str, session_id: str | None = None, provider: str = "ollama", model: str = "qwen3:4b-instruct"):
    """Server-Sent Events (SSE) streaming endpoint."""
    req = ChatRequest(prompt=prompt, session_id=session_id, provider=provider, model=model)
    agent = get_or_create_agent(req)

    queue = asyncio.Queue()

    def on_chunk(chunk: str):
        # We need to drop this onto the event loop synchronously from the hook callback
        queue.put_nowait(chunk)

    async def chat_runner():
        try:
            await agent.run_streaming(prompt, on_chunk=on_chunk)
        finally:
            await queue.put(None)  # Sentinel to close generator

    # Push the agent executor into the background
    asyncio.create_task(chat_runner())

    async def event_generator():
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            # Format as SSE
            yield f"data: {json.dumps({'chunk': chunk})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
