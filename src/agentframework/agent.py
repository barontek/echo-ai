"""Core agent implementation with session support."""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, overload
from uuid import uuid4

from .providers import LLMProvider, get_provider, LLMToolCall
from .tools import Tool, ToolResult
from .session import SessionManager, ChangeTracker
from .conversation import Message, apply_context_window, create_assistant_message, format_messages_for_llm, estimate_tokens, sanitize_json
from .tool_runtime import execute_tool_calls as runtime_execute_tool_calls, create_tool_result_notice
from .session_runtime import undo_change, redo_change, serialize_messages, deserialize_messages

logger = logging.getLogger(__name__)



@dataclass
class AgentConfig:
    """Configuration for the agent."""

    provider: str = "ollama"
    model: str = "qwen3:4b-instruct"
    temperature: float = 0.3
    max_iterations: int = 50
    max_context_messages: int = 50
    max_context_chars: int = 64000
    system_prompt: str = ""
    tools: list[Tool] = field(default_factory=list)
    base_url: str | None = None
    session_enabled: bool = True
    session_dir: str = ".agent_sessions"
    parallel_tool_execution: bool = False


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


class Agent:
    """An AI agent with tool-calling capabilities."""

    def __init__(self, config: AgentConfig, llm_provider: LLMProvider):
        self.config = config
        self.llm = llm_provider
        self.messages: list[Message] = []
        self.tool_map: dict[str, Tool] = {t.name: t for t in config.tools}

        self.session_manager = None
        self.change_tracker = ChangeTracker()
        self.sub_agents: dict[str, SubAgentConfig] = {}

        if config.session_enabled:
            self.session_manager = SessionManager(config.session_dir)
            self.session_manager.create_session()

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
            from .tools.delegate import DelegateTool

            delegate_tool = DelegateTool(agent=self)
            self.tool_map["delegate"] = delegate_tool
            if self.config.tools is not None:
                self.config.tools.append(delegate_tool)

    async def run(self, user_input: str) -> str:
        """Run the agent with user input and return the response."""
        self.add_user_message(user_input)

        if self.session_manager:
            self.session_manager.add_message("user", user_input)

        response, updated_messages = await self._run_loop(self.messages)

        self.messages = updated_messages

        if self.session_manager:
            self.session_manager.add_message("assistant", response)

        return response

    async def run_streaming(
        self, user_input: str, on_chunk: Callable[[str], None] | None = None
    ) -> str:
        """Run the agent with streaming output."""
        self.add_user_message(user_input)

        if self.session_manager:
            self.session_manager.add_message("user", user_input)

        response, updated_messages = await self._run_loop_streaming(
            self.messages, on_chunk
        )

        self.messages = updated_messages

        if self.session_manager:
            self.session_manager.add_message("assistant", response)

        return response

    async def _run_loop(
        self, messages: list[Message], has_thinking: bool = False
    ) -> tuple[str, list[Message]]:
        """Main agent loop - get response, execute tools, repeat. Returns (response, updated_messages)."""
        current_messages = list(messages)
        request_id = str(uuid4())

        for iteration in range(self.config.max_iterations):
            logger.debug("agent_stream_iteration_start", extra={"request_id": request_id, "iteration": iteration})
            llm_messages = await self._prepare_messages(current_messages)

            response = await self.llm.chat(
                messages=llm_messages,
                tools=get_tool_schemas(self.config.tools),
                temperature=self.config.temperature,
            )

            if not response.tool_calls:
                logger.debug("agent_iteration_final", extra={"request_id": request_id, "iteration": iteration})
                final_content = response.content or ""
                assistant_msg = create_assistant_message(final_content, has_thinking)
                current_messages.append(assistant_msg)
                return final_content, current_messages

            if iteration == 0 and response.content:
                has_thinking = True

            tool_messages, updated_messages = await self._execute_tool_calls(
                response.tool_calls, current_messages
            )
            current_messages = updated_messages

        return (
            "Max iterations reached. The agent could not complete the task.",
            current_messages,
        )

    async def _run_loop_streaming(
        self,
        messages: list[Message],
        on_chunk: Callable[[str], None] | None = None,
        has_thinking: bool = False,
    ) -> tuple[str, list[Message]]:
        """Main agent loop with streaming output. Returns (response, updated_messages)."""
        current_messages = list(messages)
        request_id = str(uuid4())

        for iteration in range(self.config.max_iterations):
            logger.debug("agent_iteration_start", extra={"request_id": request_id, "iteration": iteration})
            llm_messages = await self._prepare_messages(current_messages)

            if hasattr(self.llm, "chat_streaming"):
                response = await self.llm.chat_streaming(
                    messages=llm_messages,
                    tools=get_tool_schemas(self.config.tools),
                    temperature=self.config.temperature,
                    on_chunk=on_chunk,
                )
            else:
                response = await self.llm.chat(
                    messages=llm_messages,
                    tools=get_tool_schemas(self.config.tools),
                    temperature=self.config.temperature,
                )

            if not response.tool_calls:
                logger.debug("agent_iteration_final", extra={"request_id": request_id, "iteration": iteration})
                final_content = response.content or ""
                assistant_msg = create_assistant_message(final_content, has_thinking)
                current_messages.append(assistant_msg)
                return final_content, current_messages

            if iteration == 0 and response.content:
                has_thinking = True

            tool_messages, updated_messages = await self._execute_tool_calls(
                response.tool_calls, current_messages
            )
            current_messages = updated_messages

        return (
            "Max iterations reached. The agent could not complete the task.",
            current_messages,
        )


    @overload
    async def _execute_tool_calls(
        self,
        tool_calls: list[LLMToolCall],
        current_messages: None = None,
    ) -> list[Message]: ...

    @overload
    async def _execute_tool_calls(
        self,
        tool_calls: list[LLMToolCall],
        current_messages: list[Message],
    ) -> tuple[list[Message], list[Message]]: ...

    async def _execute_tool_calls(
        self,
        tool_calls: list[LLMToolCall],
        current_messages: list[Message] | None = None,
    ) -> list[Message] | tuple[list[Message], list[Message]]:
        """Execute tool calls and return (tool_messages, updated_messages)."""
        if current_messages is None:
            current_messages = list(self.messages)
            use_old_api = True
        else:
            use_old_api = False

        tool_messages, timings = await runtime_execute_tool_calls(
            tool_calls,
            self.tool_map,
            parallel=self.config.parallel_tool_execution,
            change_tracker=self.change_tracker,
        )

        if timings:
            total_latency = sum(timings.values())
            logger.debug("tool_execution", extra={"timings": timings, "total_latency": total_latency})

        new_messages = current_messages + tool_messages

        notice = create_tool_result_notice(tool_messages)
        if notice:
            new_messages.append(notice)

        if use_old_api:
            return tool_messages
        return tool_messages, new_messages

    async def _execute_tool(self, tool_call: LLMToolCall) -> ToolResult:
        """Execute a single tool call (backward compatibility wrapper)."""
        msgs, _timings = await runtime_execute_tool_calls(
            [tool_call], self.tool_map, parallel=False, change_tracker=self.change_tracker
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
        """Prepare messages for the LLM with sliding window to prevent context overflow."""
        before_count = len(messages)
        filtered_messages = await apply_context_window(
            messages,
            self.config.max_context_messages,
            self.config.max_context_chars,
            summarize_fn=self._summarize_old_messages,
        )
        logger.debug("context_window", extra={"before": before_count, "after": len(filtered_messages), "max_messages": self.config.max_context_messages, "max_chars": self.config.max_context_chars})

        return format_messages_for_llm(
            filtered_messages,
            system_prompt=self.config.system_prompt,
            sub_agents=self.sub_agents,
        )

    async def _summarize_old_messages(
        self, messages_to_summarize: list[Message]
    ) -> str:
        """Summarize old messages using the LLM to preserve context."""
        if not messages_to_summarize:
            return ""

        conversation = []
        for msg in messages_to_summarize:
            if msg.role == "user":
                conversation.append(f"User: {msg.content[:500]}")
            elif msg.role == "assistant":
                if msg.content:
                    conversation.append(f"Assistant: {msg.content[:500]}")
                if msg.tool_name:
                    conversation.append(f"Assistant used tool: {msg.tool_name}")
            elif msg.role == "tool":
                tool_name = msg.tool_name or "unknown"
                content = msg.content[:300] if msg.content else ""
                conversation.append(f"Tool {tool_name} returned: {content}")

        conversation_str = chr(10).join(conversation)
        token_count = estimate_tokens(conversation_str)

        if token_count > 8000:
            chars_to_keep = 8000 * 4
            if len(conversation_str) > chars_to_keep:
                half = chars_to_keep // 2
                conversation_str = (
                    conversation_str[:half]
                    + "\n[...conversation truncated for summarization...]\n"
                    + conversation_str[-half:]
                )

        prompt = f"""Summarize this conversation concisely, preserving key information, decisions, and any important context:

{conversation_str}

Provide a brief summary (2-3 sentences):"""

        try:
            summary_response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=None,
                temperature=0.3,
            )
            return summary_response.content or ""
        except Exception:
            return f"[{len(messages_to_summarize)} previous messages summarized]"

    def undo(self) -> str:
        """Undo the last file change."""
        return undo_change(self.change_tracker)

    def redo(self) -> str:
        """Redo the last undone change."""
        return redo_change(self.change_tracker)

    def save_session(self, session_id: str | None = None) -> str:
        """Save current session."""
        if not self.session_manager or not self.session_manager.current_session:
            return "Session management not enabled."

        if session_id:
            self.session_manager.current_session.id = session_id

        self.session_manager.current_session.messages = serialize_messages(self.messages)
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
        return f"Session loaded: {session_id}"

    def list_sessions(self) -> list:
        """List saved sessions."""
        if not self.session_manager:
            return []
        return [s.id for s in self.session_manager.list_sessions()]


def create_agent(config: AgentConfig, api_key: str | None = None) -> Agent:
    """Create an agent with the given configuration."""
    provider = get_provider(
        config.provider,
        model=config.model,
        api_key=api_key,
        base_url=config.base_url,
    )
    return Agent(config, provider)
