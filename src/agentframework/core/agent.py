"""Core agent implementation with session support."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ..constants import THINKING_END, THINKING_START
from ..providers import LLMProvider, get_provider, LLMToolCall, LLMResponse
from ..tools import Tool, ToolResult
from ..session import SessionManager, ChangeTracker
from ..conversation import (
    Message,
    apply_context_window,
    create_assistant_message,
    format_messages_for_llm,
    sanitize_json,
    summarize_old_messages,
)
from .tool_runtime import (
    execute_tool_calls as runtime_execute_tool_calls,
)
from .session_runtime import (
    undo_change,
    redo_change,
    serialize_messages,
    deserialize_messages,
)
from .callbacks import CallbackManager, AgentCallback

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for the agent."""

    provider: str = "ollama"
    model: str = "qwen3:4b-instruct"
    temperature: float = 0.3
    timeout: int = 60
    max_iterations: int = 50
    max_history_messages: int = 20
    max_context_messages: int = 50
    max_context_chars: int = 64000
    system_prompt: str = ""
    tools: list[Tool] = field(default_factory=list)
    base_url: str | None = None
    session_enabled: bool = True
    session_dir: str = str(Path.home() / ".echo-ai" / "sessions")
    parallel_tool_execution: bool = False
    num_ctx: int | None = None


@dataclass
class SubAgentConfig:
    """Configuration for a sub-agent."""

    name: str
    description: str = ""
    model: str | None = None
    tools: list[str] = field(default_factory=list)
    system_prompt: str = ""


def get_tool_schemas(tools: list[Tool]) -> list[dict[str, Any]]:
    """Get tool schemas for the LLM."""
    return [tool.schema for tool in tools]


def _extract_thinking(messages: list[Message]) -> str | None:
    """Extract thinking from the last assistant message in the message list."""
    for msg in reversed(messages):
        if msg.role == "assistant" and THINKING_START in msg.content:
            parts = msg.content.split(THINKING_END, 1)
            return parts[0].replace(THINKING_START, "").strip()
    return None


class Agent:
    """An AI agent with tool-calling capabilities."""

    def __init__(
        self,
        config: AgentConfig,
        llm_provider: LLMProvider,
        session_id: str | None = None,
    ):
        self.config = config
        self.llm = llm_provider
        self.messages: list[Message] = []
        self.tool_map: dict[str, Tool] = {t.name: t for t in config.tools}

        self.session_manager = None
        self.change_tracker = ChangeTracker()
        from .memory import MemoryManager

        self.memory_manager: MemoryManager | None = None
        self.callback_manager = CallbackManager()
        self.sub_agents: dict[str, SubAgentConfig] = {}
        self._pending_summary: list[Message] | None = None
        self._session_gen = 0

        if config.session_enabled:
            self.session_manager = SessionManager(config.session_dir)
            if session_id:
                session = self.session_manager.load_session(session_id)
                if session:
                    self.messages = deserialize_messages(session.messages)
                else:
                    # If an ID was provided but not found, we don't create it immediately
                    # to avoid ghost sessions. It will be created on the first message.
                    pass

        self.memory_manager = MemoryManager(self.session_manager)

    def add_callback(self, callback: AgentCallback) -> None:
        """Register a new observer callback."""
        self.callback_manager.add_callback(callback)

    def add_system_message(self, content: str) -> None:
        """Add a system message to the conversation."""
        self.messages.append(Message(role="system", content=content))

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation."""
        self.messages.append(Message(role="user", content=content))

    def register_sub_agent(
        self,
        name: str,
        description: str = "",
        model: str | None = None,
        tools: list[str] | None = None,
        system_prompt: str = "",
    ):
        """Register a sub-agent."""
        self.sub_agents[name] = SubAgentConfig(
            name=name,
            description=description,
            model=model,
            tools=tools or [],
            system_prompt=system_prompt,
        )

        if "delegate" not in self.tool_map:
            from ..tools.delegate import DelegateTool

            delegate_tool = DelegateTool(agent=self)
            self.tool_map["delegate"] = delegate_tool
            if self.config.tools is not None:
                self.config.tools.append(delegate_tool)

    async def run(self, user_input: str) -> str:
        """Run the agent with user input and return the response.

        Uses streaming internally for all models to ensure consistent behavior.
        """
        if not self.messages:
            await self.load_persistent_memory()

        self.add_user_message(user_input)

        if self.session_manager:
            self._ensure_session()
            self.session_manager.add_message(
                "user", user_input, timestamp=datetime.now().strftime("%H:%M")
            )

        accumulated = []

        def collect_chunk(chunk: str) -> None:
            accumulated.append(chunk)

        response, updated_messages = await self._run_loop_streaming(
            self.messages, collect_chunk
        )

        self.messages = updated_messages

        thinking = _extract_thinking(self.messages)
        if self.session_manager:
            self.session_manager.add_message(
                "assistant", response, timestamp=datetime.now().strftime("%H:%M"), thinking=thinking
            )

        return response

    async def run_streaming(
        self, user_input: str, on_chunk: Callable[[str], None] | None = None
    ) -> str:
        """Run the agent with streaming output."""
        logger.warning(
            "agent:trace run_streaming input=%s msgs_before=%d session=%s",
            user_input[:30],
            len(self.messages),
            self.session_manager.current_session.id
            if self.session_manager and self.session_manager.current_session
            else None,
        )

        if not self.messages:
            await self.load_persistent_memory()

        self.add_user_message(user_input)

        if self.session_manager:
            self._ensure_session()
            self.session_manager.add_message(
                "user", user_input, timestamp=datetime.now().strftime("%H:%M")
            )

        response, updated_messages = await self._run_loop_streaming(
            self.messages, on_chunk
        )

        self.messages = updated_messages

        if self._pending_summary:
            asyncio.create_task(self._background_summarize())

        thinking = _extract_thinking(self.messages)
        if self.session_manager:
            self.session_manager.add_message(
                "assistant", response, timestamp=datetime.now().strftime("%H:%M"), thinking=thinking
            )

        return response

    async def generate_title(self) -> str | None:
        """Generate a short title for the session based on history."""
        if not self.messages:
            return None

        # Try to find the first user message
        first_user_msg = next(
            (m.content for m in self.messages if m.role == "user"), None
        )
        if not first_user_msg:
            return None

        # Simple fallback: use first words of user message (don't use the LLM prompt!)
        simple_title = first_user_msg[:30].strip()
        if len(first_user_msg) > 30:
            simple_title += "..."

        prompt = (
            "Summarize the following user request into a very short, "
            "descriptive title (max 5 words). Do not use quotes or a period.\n\n"
            f"User request: {first_user_msg}"
        )

        try:
            # We use the LLM directly to get a short summary
            try:
                title_response = await asyncio.wait_for(
                    self.llm.chat(
                        messages=[{"role": "user", "content": prompt}], temperature=0.3
                    ),
                    timeout=30.0,  # Increased timeout for slower reasoning models
                )
                raw = title_response.thinking or title_response.content
                if THINKING_START in title_response.content:
                    after_thinking = title_response.content.split(THINKING_END, 1)[1]
                    raw = after_thinking.strip()
                raw = re.sub(
                    rf"{re.escape(THINKING_START)}.*?{re.escape(THINKING_END)}",
                    "",
                    raw,
                    flags=re.DOTALL,
                ).strip()
                return raw.strip().strip('"').strip("'")
            except (asyncio.TimeoutError, Exception) as e:
                logger.debug(f"Title generation failed or timed out: {e}")
                return simple_title  # Use first words of user message, not the prompt
        except Exception as e:
            logger.error(f"Failed to generate session title: {e}")
            return simple_title  # Use fallback instead of None

    async def extract_data(self, prompt: str, response_model: type[Any]) -> Any:
        """Extract strictly typed JSON data mapped to the given Pydantic model natively."""
        # Note: Tracing hooks could be initialized here if we wanted to log this,
        # but for simplicity we bypass the conversational buffer.
        messages = [{"role": "user", "content": prompt}]
        return await self.llm.extract_structured(
            messages=messages,
            response_model=response_model,
            temperature=self.config.temperature,
        )

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Call the LLM, using streaming if available and on_chunk is provided."""
        if on_chunk is not None:
            try:
                return await self.llm.chat_streaming(
                    messages=messages,
                    tools=tools,
                    temperature=self.config.temperature,
                    on_chunk=on_chunk,
                )
            except NotImplementedError:
                pass
        return await self.llm.chat(
            messages=messages,
            tools=tools,
            temperature=self.config.temperature,
        )

    async def _run_loop(
        self, messages: list[Message], thinking_process: str | None = None
    ) -> tuple[str, list[Message]]:
        """Main agent loop - delegates to streaming implementation with no chunk callback."""
        return await self._run_loop_streaming(
            messages, on_chunk=None, thinking_process=thinking_process
        )

    async def _run_loop_streaming(
        self,
        messages: list[Message],
        on_chunk: Callable[[str], None] | None = None,
        thinking_process: str | None = None,
    ) -> tuple[str, list[Message]]:
        """Main agent loop with streaming output. Returns (response, updated_messages)."""
        current_messages = list(messages)
        request_id = str(uuid4())

        self.callback_manager.on_run_start(
            request_id, current_messages[-1].content if current_messages else ""
        )

        max_msgs = getattr(self.config, "max_history_messages", 20)
        if self.memory_manager:
            current_messages = await self.memory_manager.summarize_if_needed(
                agent_messages=current_messages, llm=self.llm, max_messages=max_msgs
            )
            self.messages = list(current_messages)

        for iteration in range(self.config.max_iterations):
            logger.debug(
                "agent_iteration_start",
                extra={"request_id": request_id, "iteration": iteration},
            )
            llm_messages = await self._prepare_messages(current_messages)

            self.callback_manager.on_llm_start(request_id, llm_messages)

            partial_chunks: list[str] = []

            def wrapped_on_chunk(chunk: str) -> None:
                partial_chunks.append(chunk)
                if on_chunk:
                    on_chunk(chunk)

            try:
                response = await self._call_llm(
                    llm_messages,
                    get_tool_schemas(self.config.tools),
                    on_chunk=wrapped_on_chunk,
                )
            except asyncio.CancelledError:
                partial_response = "".join(partial_chunks)
                if partial_response:
                    assistant_msg = create_assistant_message(
                        partial_response, thinking_process
                    )
                    current_messages.append(assistant_msg)

                    if self._pending_summary:
                        asyncio.create_task(self._background_summarize())

                    if self.session_manager:
                        self.session_manager.add_message(
                            "assistant",
                            partial_response,
                            timestamp=datetime.now().strftime("%H:%M"),
                        )

                logger.debug(
                    "Generation stopped by user",
                    extra={"partial_length": len(partial_response)},
                )
                return partial_response, current_messages

            self.callback_manager.on_llm_end(request_id, response)

            if not response.tool_calls:
                logger.debug(
                    "agent_iteration_final",
                    extra={"request_id": request_id, "iteration": iteration},
                )
                final_content = response.content or ""
                self.callback_manager.on_run_end(request_id, final_content)
                assistant_msg = create_assistant_message(
                    final_content, response.thinking or thinking_process
                )
                current_messages.append(assistant_msg)

                if self._pending_summary:
                    asyncio.create_task(self._background_summarize())

                return final_content, current_messages

            if iteration == 0 and response.thinking:
                thinking_process = response.thinking

            # Record assistant's tool-calling message in history
            # Arguments must remain a dict (JSON object) — Ollama rejects string-encoded args
            tool_call_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                }
                for tc in response.tool_calls
            ]
            assistant_msg = Message(
                role="assistant",
                content=response.content or "",
                tool_calls=tool_call_dicts,
            )
            current_messages.append(assistant_msg)
            if self.session_manager:
                self.session_manager.add_message(
                    "assistant", assistant_msg.content, tool_calls=tool_call_dicts
                )

            tool_messages, updated_messages = await self._execute_tool_calls(
                response.tool_calls,
                current_messages,
                request_id=request_id,
                iteration=iteration,
            )
            current_messages = updated_messages

            # Persist tool execution results - attach to last assistant message
            if self.session_manager and tool_messages:
                tool_results = []
                for msg in tool_messages:
                    tool_results.append(
                        {
                            "tool_call_id": msg.tool_call_id,
                            "tool_name": msg.tool_name,
                            "arguments": msg.tool_arguments,
                            "content": msg.content,
                            "error": None,
                        }
                    )
                self.messages = list(current_messages)
                self.session_manager.add_tool_results_to_last_assistant(tool_results)
                self.save_session()

        err_msg = "Max iterations reached. The agent could not complete the task."
        self.callback_manager.on_run_error(request_id, Exception(err_msg))
        return (
            err_msg,
            current_messages,
        )

    async def _execute_tool_calls(
        self,
        tool_calls: list[LLMToolCall],
        current_messages: list[Message] | None = None,
        request_id: str | None = None,
        iteration: int | None = None,
    ) -> tuple[list[Message], list[Message]]:
        """Execute tool calls and return (tool_messages, updated_messages)."""
        if current_messages is None:
            current_messages = list(self.messages)

        tool_messages, timings = await runtime_execute_tool_calls(
            tool_calls,
            self.tool_map,
            parallel=self.config.parallel_tool_execution,
            change_tracker=self.change_tracker,
            callback_manager=self.callback_manager,
            run_id=request_id or "",
        )

        critical_errors = [
            msg
            for msg in tool_messages
            if msg.error_category in ("execution_error", "timeout")
        ]
        if critical_errors:
            logger.warning(
                "Critical tool execution failure(s) detected",
                extra={
                    "request_id": request_id,
                    "iteration": iteration,
                    "failed_tools": [
                        {
                            "name": msg.tool_name,
                            "error": msg.content[:100],
                            "category": msg.error_category,
                        }
                        for msg in critical_errors
                    ],
                },
            )

        if timings:
            total_latency = sum(timings.values())
            logger.debug(
                "tool_execution",
                extra={
                    "request_id": request_id,
                    "iteration": iteration,
                    "timings": timings,
                    "total_latency": total_latency,
                    "latency_ms": round(total_latency * 1000, 2),
                },
            )
            for tool_call in tool_calls:
                elapsed = timings.get(tool_call.id)
                if elapsed is None:
                    continue
                logger.debug(
                    "tool_call_latency",
                    extra={
                        "request_id": request_id,
                        "iteration": iteration,
                        "tool_name": tool_call.name,
                        "tool_call_id": tool_call.id,
                        "latency_ms": round(elapsed * 1000, 2),
                    },
                )

        new_messages = current_messages + tool_messages

        return tool_messages, new_messages

    async def _execute_tool(self, tool_call: LLMToolCall) -> ToolResult:
        """Execute a single tool call (backward compatibility wrapper)."""
        msgs, _timings = await runtime_execute_tool_calls(
            [tool_call],
            self.tool_map,
            parallel=False,
            change_tracker=self.change_tracker,
            callback_manager=self.callback_manager,
        )
        msg = msgs[0]
        if msg.content.startswith("FAILED"):
            error = msg.content
            if ": " in error:
                error = error.split(": ", 1)[1]
            return ToolResult(error=error)
        return ToolResult(content=msg.content)

    @staticmethod
    def _sanitize_json(json_str: str) -> str:
        """Sanitize JSON string (backward compatibility wrapper)."""
        return sanitize_json(json_str)

    async def _prepare_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Prepare messages for the LLM with lazy summarization to prevent context overflow."""
        before_count = len(messages)
        filtered_messages, dropped = await apply_context_window(
            messages,
            self.config.max_context_messages,
            self.config.max_context_chars,
            summarize_fn=None,  # Lazy - no summarization during generation
        )

        if dropped:
            self._pending_summary = dropped

        logger.debug(
            "context_window",
            extra={
                "context_before": before_count,
                "context_after": len(filtered_messages),
                "dropped_count": len(dropped),
                "max_messages": self.config.max_context_messages,
                "max_chars": self.config.max_context_chars,
            },
        )

        system_prompt = self.config.system_prompt

        summary = self._get_session_summary()
        if summary:
            section = f"[Conversation Summary]\n{summary}"
            system_prompt = (
                f"{system_prompt}\n\n{section}" if system_prompt else section
            )

        return format_messages_for_llm(
            filtered_messages,
            system_prompt=system_prompt,
            sub_agents=self.sub_agents,
        )

    def _get_session_summary(self) -> str:
        """Return the conversation summary from session metadata, if any."""
        if self.session_manager and self.session_manager.current_session:
            return self.session_manager.current_session.metadata.get("summary", "")
        return ""

    def undo(self) -> str:
        """Undo the last file change."""
        return undo_change(self.change_tracker)

    async def load_persistent_memory(self) -> None:
        """Load all stored memories and inject them as a system message.

        Called automatically on the first turn of a new conversation.
        Finds a MemoryTool in the tool map and loads its stored facts,
        then prepends a system message so the LLM always has this context.
        """
        from ..tools.memory import MemoryTool

        memory_tool = next(
            (t for t in self.tool_map.values() if isinstance(t, MemoryTool)), None
        )
        if not memory_tool:
            return

        memories_str = memory_tool.load_memories()
        if not memories_str:
            return

        system_msg = (
            "[Persistent Memory]\n"
            "The following facts were previously saved about the user. "
            "Use them to personalize your responses:\n\n" + memories_str
        )
        self.messages.insert(0, Message(role="system", content=system_msg))

    async def _background_summarize(self) -> None:
        """Background task to summarize dropped messages after streaming completes."""
        if not self._pending_summary:
            return

        # Snapshot both gen and the dropped messages. A subsequent load_session
        # (session switch) could clear self.messages and bump _session_gen while
        # this async LLM call is in-flight. If gen doesn't match after the await,
        # skip the insert to avoid leaking old summaries into the new session.
        gen = self._session_gen
        dropped = list(self._pending_summary)
        try:
            summary = await summarize_old_messages(dropped, self.llm)
            if summary and gen == self._session_gen:
                # Remove the original dropped messages from self.messages by identity
                dropped_ids = {id(m) for m in dropped}
                self.messages = [
                    m for m in self.messages if id(m) not in dropped_ids
                ]

                summary_msg = Message(role="system", content=summary)
                self.messages.insert(1, summary_msg)
                logger.info(
                    "Background summarization completed",
                    extra={
                        "summary_length": len(summary),
                        "dropped_count": len(dropped),
                    },
                )
        except Exception as e:
            logger.error("Background summarization failed: %s", e)
        finally:
            self._pending_summary = None

    def redo(self) -> str:
        """Redo the last undone change."""
        return redo_change(self.change_tracker)

    def save_session(self, session_id: str | None = None) -> str:
        """Save current session."""
        if not self.session_manager:
            return "Session management not enabled."

        self._ensure_session(session_id)
        if not self.session_manager.current_session:
            return "Failed to create session."

        serialized = serialize_messages(self.messages)
        existing = self.session_manager.current_session.messages

        # Only sync messages if self.messages is not behind the session store.
        # When memory summarization truncates self.messages, existing has the
        # full history — overwriting would permanently delete old messages from DB.
        if len(serialized) >= len(existing):
            self.session_manager.current_session.messages = serialized

        self.session_manager.save_session()
        return f"Session saved: {self.session_manager.current_session.id}"

    def load_session(self, session_id: str) -> str:
        """Load a session."""
        if not self.session_manager:
            return "Session management not enabled."

        session = self.session_manager.load_session(session_id)
        if not session:
            return f"Session not found: {session_id}"

        self.messages = deserialize_messages(session.messages)
        # Stale _pending_summary from a previous session's context-window drop
        # must be cleared — otherwise _background_summarize may insert old
        # summaries into self.messages after this load_session replaces them.
        self._pending_summary = None
        # Bump generation so any in-flight _background_summarize task from the
        # prior session detects the mismatch and skips its insert.
        self._session_gen += 1
        return f"Session loaded: {session_id}"

    def list_sessions(
        self, limit: int = 50, offset: int = 0, search: str | None = None
    ) -> tuple[list, int]:
        """List saved sessions.

        Returns:
            Tuple of (session ids list, total count)
        """
        if not self.session_manager:
            return [], 0
        sessions, total = self.session_manager.list_sessions(limit, offset, search)
        return [s.id for s in sessions], total

    def _ensure_session(
        self, session_id: str | None = None, title: str | None = None
    ) -> None:
        """Ensure a session is created if it doesn't exist."""
        if self.session_manager and not self.session_manager.current_session:
            self.session_manager.create_session(session_id, title=title)
        elif self.session_manager and self.session_manager.current_session:
            if session_id:
                self.session_manager.current_session.id = session_id
            if title:
                self.session_manager.current_session.title = title

    def close(self) -> None:
        """Close the agent and its associated managers."""
        if self.session_manager:
            self.session_manager.close()
        if hasattr(self, "llm"):
            # If the provider has a close method, call it
            try:
                close_method = getattr(self.llm, "close", None)
                if close_method:
                    import inspect

                    if inspect.iscoroutinefunction(close_method):
                        try:
                            # Try to run in current loop or create task
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(close_method())
                            else:
                                loop.run_until_complete(close_method())
                        except Exception as e:
                            logger.debug(f"Async close method failed: {e}")
                    else:
                        close_method()
            except Exception as e:
                logger.debug(f"Provider shutdown failed: {e}")

        # Shutdown OpenTelemetry if initialized
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider

            provider = trace.get_tracer_provider()
            if isinstance(provider, TracerProvider):
                provider.shutdown()
        except Exception as e:
            logger.debug(f"OpenTelemetry shutdown failed: {e}")


def create_agent(
    config: AgentConfig, api_key: str | None = None, session_id: str | None = None
) -> Agent:
    """Create an agent with the given configuration."""
    provider = get_provider(
        config.provider,
        model=config.model,
        api_key=api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        num_ctx=config.num_ctx,
    )
    return Agent(config, provider, session_id=session_id)
