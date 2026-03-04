"""Core agent implementation with session support."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Callable

from .providers import LLMProvider, get_provider, LLMToolCall
from .tools import Tool, ToolResult
from .session import SessionManager, ChangeTracker

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A message in the conversation."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict | None = None


@dataclass
class AgentConfig:
    """Configuration for the agent."""

    provider: str = "ollama"
    model: str = "qwen3:4b-instruct"
    temperature: float = 0.3
    max_iterations: int = 50
    max_context_messages: int = 50  # Max messages to keep in context (0 = unlimited)
    max_context_chars: int = (
        64000  # Max tokens in context (~16k tokens, 4 chars = 1 token)
    )
    system_prompt: str = ""
    tools: list[Tool] = field(default_factory=list)
    base_url: str | None = None
    session_enabled: bool = True
    session_dir: str = ".agent_sessions"
    parallel_tool_execution: bool = False  # Execute tools sequentially by default


@dataclass
class SubAgentConfig:
    """Configuration for a sub-agent."""

    name: str
    description: str = ""
    model: str | None = None
    tools: list[str] = field(default_factory=list)  # tool names to include
    system_prompt: str = ""


class Agent:
    """An AI agent with tool-calling capabilities."""

    def __init__(self, config: AgentConfig, llm_provider: LLMProvider):
        self.config = config
        self.llm = llm_provider
        self.messages: list[Message] = []
        self.tool_map: dict[str, Tool] = {t.name: t for t in config.tools}

        # Session management
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

        # Add delegate tool if not already present
        if "delegate" not in self.tool_map:
            from .tools.delegate import DelegateTool

            delegate_tool = DelegateTool(agent=self)
            self.tool_map["delegate"] = delegate_tool
            # Also add to config.tools if it exists there
            if self.config.tools is not None:
                self.config.tools.append(delegate_tool)

    async def run(self, user_input: str) -> str:
        """Run the agent with user input and return the response."""
        self.add_user_message(user_input)

        if self.session_manager:
            self.session_manager.add_message("user", user_input)

        response = await self._run_loop()

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

        response = await self._run_loop_streaming(on_chunk)

        if self.session_manager:
            self.session_manager.add_message("assistant", response)

        return response

    async def _run_loop(self) -> str:
        """Main agent loop - get response, execute tools, repeat."""
        has_thinking = False

        for iteration in range(self.config.max_iterations):
            response = await self.llm.chat(
                messages=await self._prepare_messages(),
                tools=self._get_tool_schemas(),
                temperature=self.config.temperature,
            )

            if not response.tool_calls:
                final_content = response.content or ""
                if has_thinking:
                    final_content = f"__THINKING__\nThinking...\n__THINKING_END__\n\n{final_content}"
                self.messages.append(Message(role="assistant", content=final_content))
                return final_content

            # Mark that we have thinking content before tool execution
            if iteration == 0 and response.content:
                has_thinking = True

            # Execute tool calls
            await self._execute_tool_calls(response.tool_calls)

        return "Max iterations reached. The agent could not complete the task."

    async def _run_loop_streaming(
        self, on_chunk: Callable[[str], None] | None = None
    ) -> str:
        """Main agent loop with streaming output."""
        has_thinking = False

        for iteration in range(self.config.max_iterations):
            # Check if provider supports streaming
            if hasattr(self.llm, "chat_streaming"):
                response = await self.llm.chat_streaming(
                    messages=await self._prepare_messages(),
                    tools=self._get_tool_schemas(),
                    temperature=self.config.temperature,
                    on_chunk=on_chunk,
                )
            else:
                response = await self.llm.chat(
                    messages=await self._prepare_messages(),
                    tools=self._get_tool_schemas(),
                    temperature=self.config.temperature,
                )

            if not response.tool_calls:
                final_content = response.content or ""
                if has_thinking:
                    final_content = f"__THINKING__\nThinking...\n__THINKING_END__\n\n{final_content}"
                self.messages.append(Message(role="assistant", content=final_content))
                return final_content

            # Mark that we have thinking content before tool execution
            if iteration == 0 and response.content:
                has_thinking = True

            # Execute tool calls
            await self._execute_tool_calls(response.tool_calls)

        return "Max iterations reached. The agent could not complete the task."

    async def _execute_tool_calls(self, tool_calls: list[LLMToolCall]) -> list[Message]:
        """Execute tool calls and format results as messages."""

        async def execute_and_message(tool_call: LLMToolCall) -> Message:
            result = await self._execute_tool(tool_call)
            if result.error:
                content = f"FAILED - Operation was denied by user: {result.error}"
            else:
                content = result.content or ""
            return Message(
                role="tool",
                content=content,
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                tool_arguments=tool_call.arguments,
            )

        # Execute tools sequentially or in parallel based on config
        if self.config.parallel_tool_execution:
            tool_messages = await asyncio.gather(
                *[execute_and_message(tc) for tc in tool_calls]
            )
        else:
            tool_messages = []
            for tc in tool_calls:
                tool_messages.append(await execute_and_message(tc))

        self.messages.extend(tool_messages)

        if tool_messages:
            tool_results = "\n".join(
                f"Tool '{msg.tool_name}' returned: {msg.content[:200]}"
                for msg in tool_messages
                if msg.content
            )
            self.messages.append(
                Message(
                    role="user",
                    content=f"System Note: Tools executed.\n{tool_results}\n\nProvide a final response to the user summarizing these results.",
                )
            )

        return tool_messages

    async def _prepare_messages(self) -> list[dict[str, str]]:
        """Prepare messages for the LLM with sliding window to prevent context overflow."""
        msgs = []

        # Add sub-agents info to system prompt
        if self.sub_agents:
            sub_agents_info = "\n\nAvailable sub-agents:\n"
            for name, cfg in self.sub_agents.items():
                sub_agents_info += f"- @{name}: {cfg.description}\n"
            system_prompt = self.config.system_prompt + sub_agents_info
        else:
            system_prompt = self.config.system_prompt

        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})

        # Apply sliding window to messages
        filtered_messages = await self._apply_context_window()

        # Track tool_call_id -> tool_name mapping for tool messages
        tool_call_names = {}

        for msg in filtered_messages:
            if msg.role == "tool":
                msgs.append(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                        "name": msg.tool_name,
                    }
                )
                if msg.tool_call_id and msg.tool_name:
                    tool_call_names[msg.tool_call_id] = msg.tool_name
            elif msg.role == "assistant" and msg.tool_call_id:
                # Include assistant tool call messages
                msgs.append(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                    }
                )
            else:
                msgs.append({"role": msg.role, "content": msg.content})

        return msgs

    def _estimate_tokens(self, text: str) -> int:
        """Count tokens using tiktoken with cl100k_base encoding."""
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            return len(text) // 4

    async def _apply_context_window(self) -> list["Message"]:
        """Apply sliding window to messages with summarization to preserve context."""
        if not self.messages:
            return []

        max_msgs = self.config.max_context_messages
        max_tokens = self.config.max_context_chars

        # If both are unlimited, return all
        if max_msgs <= 0 and max_tokens <= 0:
            return self.messages

        # If only messages limit is set
        if max_msgs > 0 and max_tokens <= 0:
            return self.messages[-max_msgs:]

        # Calculate how many tokens to keep for recent vs summary
        keep_recent_tokens = int(max_tokens * 0.7)

        # Get recent messages that fit in token limit
        recent = self._trim_by_tokens(self.messages, keep_recent_tokens)

        # If we kept all messages, just apply message limit
        if len(recent) == len(self.messages):
            return recent[-max_msgs:] if max_msgs > 0 else recent

        # Get messages that were trimmed (old messages to summarize)
        trimmed_count = len(self.messages) - len(recent)
        if trimmed_count <= 2:
            return recent[-max_msgs:] if max_msgs > 0 else recent

        old_messages = self.messages[: -len(recent)] if recent else self.messages[:-1]

        # Summarize old messages asynchronously
        summary = await self.summarize_old_messages(old_messages)

        # Create summary message
        summary_msg = Message(role="system", content=summary)
        result = [summary_msg] + recent
        return result[-max_msgs:] if max_msgs > 0 else result

    def _trim_by_tokens(
        self, messages: list["Message"], max_tokens: int
    ) -> list["Message"]:
        """Trim messages to fit within token limit, keeping most recent."""
        if max_tokens <= 0:
            return messages

        result: list[Message] = []
        total_tokens = 0

        # Go through messages in reverse order
        for msg in reversed(messages):
            # Truncate tool outputs that are too long
            content = msg.content
            if msg.role == "tool" and len(content) > 10000:
                content = (
                    content[:10000]
                    + f"\n\n[Output truncated - was {len(content)} chars]"
                )

            msg_tokens = self._estimate_tokens(content)
            if total_tokens + msg_tokens > max_tokens:
                break
            result.insert(0, msg)
            total_tokens += msg_tokens
            # Replace content with truncated version
            if content != msg.content:
                msg.content = content

        # If we trimmed anything, add a notice
        if result != messages and result:
            # Try to keep at least the last user message for context
            if result[0].role == "tool":
                # Find the corresponding assistant message
                for i, m in enumerate(messages):
                    if (
                        m.role == "assistant"
                        and m.tool_call_id == result[0].tool_call_id
                    ):
                        if i > 0 and messages[i - 1].role == "user":
                            # Insert user message at the start
                            result.insert(0, messages[i - 1])
                        break

        return result

    async def summarize_old_messages(
        self, messages_to_summarize: list["Message"]
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

        prompt = f"""Summarize this conversation concisely, preserving key information, decisions, and any important context:

{chr(10).join(conversation)}

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

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas for the LLM."""
        return [tool.schema for tool in self.config.tools]

    @staticmethod
    def _sanitize_json(json_str: str) -> str:
        """Sanitize JSON string by removing markdown code blocks and trailing commas."""
        import re

        json_str = json_str.strip()
        json_str = re.sub(r"^```json\s*", "", json_str)
        json_str = re.sub(r"^```\s*", "", json_str)
        json_str = re.sub(r"```$", "", json_str)
        json_str = re.sub(r",(\s*[}\]])", r"\1", json_str)
        return json_str

    async def _execute_tool(self, tool_call: LLMToolCall) -> ToolResult:
        """Execute a tool call."""
        tool = self.tool_map.get(tool_call.name)
        if not tool:
            return ToolResult(error=f"Unknown tool: {tool_call.name}")

        try:
            args = tool_call.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(self._sanitize_json(args))
                except json.JSONDecodeError:
                    return ToolResult(error=f"Invalid JSON in arguments: {args}")

            validation_error, validated_args = self._validate_tool_args(tool, args)
            if validation_error:
                return ToolResult(error=validation_error)

            result = await tool.execute(**validated_args)

            # Track file changes for undo
            if (
                tool_call.name == "write_file"
                and validated_args
                and "path" in validated_args
            ):
                try:
                    from pathlib import Path

                    old_content = None
                    if Path(args["path"]).exists():
                        old_content = Path(args["path"]).read_text()
                    self.change_tracker.record_change(
                        "write", args["path"], old_content, args.get("content")
                    )
                except Exception:
                    pass

            return result
        except TypeError as e:
            error_msg = str(e)
            if "missing" in error_msg or "required" in error_msg:
                return ToolResult(error=f"Missing required argument: {error_msg}")
            elif "unexpected keyword" in error_msg:
                return ToolResult(error=f"Invalid argument: {error_msg}")
            return ToolResult(error=f"Argument error: {error_msg}")
        except Exception as e:
            logger.exception(f"Tool {tool_call.name} failed")
            return ToolResult(error=str(e))

    def _validate_tool_args(
        self, tool: Tool, args: dict
    ) -> tuple[str | None, dict | None]:
        """Validate tool arguments using Pydantic. Returns (error, validated_args)."""
        if not tool.parameters_model:
            return None, args

        try:
            validated = tool.parameters_model.model_validate(args)
            return None, validated.model_dump()
        except Exception as e:
            return f"Validation error: {e}", None

    def undo(self) -> str:
        """Undo the last file change."""
        if not self.change_tracker.can_undo():
            return "Nothing to undo."

        change = self.change_tracker.undo()
        if change is None:
            return "Nothing to undo."

        if change["old_content"] is not None:
            try:
                from pathlib import Path

                Path(change["path"]).write_text(change["old_content"])
                return f"Undid write to {change['path']}"
            except Exception as e:
                return f"Undo failed: {e}"
        return f"Undid {change['operation']} on {change['path']}"

    def redo(self) -> str:
        """Redo the last undone change."""
        if not self.change_tracker.can_redo():
            return "Nothing to redo."

        change = self.change_tracker.redo()
        if change is None:
            return "Nothing to redo."

        if change["new_content"] is not None:
            try:
                from pathlib import Path

                Path(change["path"]).write_text(change["new_content"])
                return f"Redid write to {change['path']}"
            except Exception as e:
                return f"Redo failed: {e}"
        return f"Redid {change['operation']} on {change['path']}"

    def save_session(self, session_id: str | None = None) -> str:
        """Save current session."""
        if not self.session_manager or not self.session_manager.current_session:
            return "Session management not enabled."

        if session_id:
            self.session_manager.current_session.id = session_id

        # Save messages
        self.session_manager.current_session.messages = [
            {
                "role": m.role,
                "content": m.content,
                "tool_call_id": m.tool_call_id,
                "tool_name": m.tool_name,
                "tool_arguments": m.tool_arguments,
            }
            for m in self.messages
        ]
        self.session_manager.save_session()
        return f"Session saved: {self.session_manager.current_session.id}"

    def load_session(self, session_id: str) -> str:
        """Load a session."""
        if not self.session_manager:
            return "Session management not enabled."

        session = self.session_manager.load_session(session_id)
        if not session:
            return f"Session not found: {session_id}"

        self.messages = [
            Message(
                role=m["role"],
                content=m["content"],
                tool_call_id=m.get("tool_call_id"),
                tool_name=m.get("tool_name"),
                tool_arguments=m.get("tool_arguments"),
            )
            for m in session.messages
        ]
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
