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


@dataclass
class AgentConfig:
    """Configuration for the agent."""

    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.3
    max_iterations: int = 50
    max_context_messages: int = 50  # Max messages to keep in context (0 = unlimited)
    max_context_chars: int = 100000  # Max characters in context (0 = unlimited)
    system_prompt: str = ""
    tools: list[Tool] = field(default_factory=list)
    base_url: str | None = None
    session_enabled: bool = True
    session_dir: str = ".agent_sessions"


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

    def register_sub_agent(self, name: str, description: str = "", model: str | None = None, tools: list[str] | None = None, system_prompt: str = ""):
        """Register a sub-agent."""
        self.sub_agents[name] = SubAgentConfig(
            name=name,
            description=description,
            model=model,
            tools=tools or [],
            system_prompt=system_prompt,
        )

    async def run(self, user_input: str) -> str:
        """Run the agent with user input and return the response."""
        self.add_user_message(user_input)
        
        if self.session_manager:
            self.session_manager.add_message("user", user_input)
        
        response = await self._run_loop()
        
        if self.session_manager:
            self.session_manager.add_message("assistant", response)
        
        return response

    async def run_streaming(self, user_input: str, on_chunk: Callable[[str], None] | None = None) -> str:
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
                messages=self._prepare_messages(),
                tools=self._get_tool_schemas(),
                temperature=self.config.temperature,
            )

            if not response.tool_calls:
                final_content = response.content
                if has_thinking:
                    final_content = f"__THINKING__\nThinking...\n__THINKING_END__\n\n{response.content}"
                self.messages.append(
                    Message(role="assistant", content=final_content)
                )
                return final_content

            # Mark that we have thinking content before tool execution
            if iteration == 0 and response.content:
                has_thinking = True

            # Execute tool calls concurrently using asyncio.gather()
            async def execute_and_message(tool_call: LLMToolCall) -> Message:
                result = await self._execute_tool(tool_call)
                return Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                )

            tool_messages = await asyncio.gather(
                *[execute_and_message(tc) for tc in response.tool_calls]
            )
            self.messages.extend(tool_messages)

        return "Max iterations reached. The agent could not complete the task."

    async def _run_loop_streaming(self, on_chunk: Callable[[str], None] | None = None) -> str:
        """Main agent loop with streaming output."""
        has_thinking = False
        
        for iteration in range(self.config.max_iterations):
            # Check if provider supports streaming
            if hasattr(self.llm, 'chat_streaming'):
                response = await self.llm.chat_streaming(
                    messages=self._prepare_messages(),
                    tools=self._get_tool_schemas(),
                    temperature=self.config.temperature,
                    on_chunk=on_chunk,
                )
            else:
                response = await self.llm.chat(
                    messages=self._prepare_messages(),
                    tools=self._get_tool_schemas(),
                    temperature=self.config.temperature,
                )

            if not response.tool_calls:
                final_content = response.content
                if has_thinking:
                    final_content = f"__THINKING__\nThinking...\n__THINKING_END__\n\n{response.content}"
                self.messages.append(
                    Message(role="assistant", content=final_content)
                )
                return final_content

            # Mark that we have thinking content before tool execution
            if iteration == 0 and response.content:
                has_thinking = True

            # Execute tool calls concurrently using asyncio.gather()
            async def execute_and_message(tool_call: LLMToolCall) -> Message:
                result = await self._execute_tool(tool_call)
                return Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                )

            tool_messages = await asyncio.gather(
                *[execute_and_message(tc) for tc in response.tool_calls]
            )
            self.messages.extend(tool_messages)

        return "Max iterations reached. The agent could not complete the task."

    def _prepare_messages(self) -> list[dict[str, str]]:
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
        filtered_messages = self._apply_context_window()
        
        # Track tool_call_id -> tool_name mapping for tool messages
        tool_call_names = {}
        
        for msg in filtered_messages:
            if msg.role == "tool":
                msgs.append({
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.tool_name,
                })
                if msg.tool_call_id and msg.tool_name:
                    tool_call_names[msg.tool_call_id] = msg.tool_name
            elif msg.role == "assistant" and msg.tool_call_id:
                # Include assistant tool call messages
                msgs.append({
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                })
            else:
                msgs.append({"role": msg.role, "content": msg.content})

        return msgs
    
    def _apply_context_window(self) -> list["Message"]:
        """Apply sliding window to messages based on configured limits."""
        if not self.messages:
            return []
        
        max_msgs = self.config.max_context_messages
        max_chars = self.config.max_context_chars
        
        # If both are unlimited, return all
        if max_msgs <= 0 and max_chars <= 0:
            return self.messages
        
        # If only messages limit is set
        if max_msgs > 0 and max_chars <= 0:
            return self.messages[-max_msgs:]
        
        # If only chars limit is set
        if max_chars > 0 and max_msgs <= 0:
            return self._trim_by_chars(self.messages, max_chars)
        
        # Both limits set - first trim by chars, then by count
        trimmed = self._trim_by_chars(self.messages, max_chars)
        return trimmed[-max_msgs:] if max_msgs > 0 else trimmed
    
    def _trim_by_chars(self, messages: list["Message"], max_chars: int) -> list["Message"]:
        """Trim messages to fit within character limit, keeping most recent."""
        if max_chars <= 0:
            return messages
        
        # Always keep: system prompt (not in self.messages), first user message, last N messages
        # Build from end, accumulate until we hit limit
        result: list[Message] = []
        total_chars = 0
        
        # Go through messages in reverse order
        for msg in reversed(messages):
            msg_chars = len(msg.content)
            if total_chars + msg_chars > max_chars:
                break
            result.insert(0, msg)
            total_chars += msg_chars
        
        # If we trimmed anything, add a notice
        if result != messages and result:
            # Try to keep at least the last user message for context
            if result[0].role == "tool":
                # Find the corresponding assistant message
                for i, m in enumerate(messages):
                    if m.role == "assistant" and m.tool_call_id == result[0].tool_call_id:
                        if i > 0 and messages[i-1].role == "user":
                            # Insert user message at the start
                            result.insert(0, messages[i-1])
                        break
        
        return result

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas for the LLM."""
        return [tool.schema for tool in self.config.tools]

    async def _execute_tool(self, tool_call: LLMToolCall) -> ToolResult:
        """Execute a tool call."""
        tool = self.tool_map.get(tool_call.name)
        if not tool:
            return ToolResult(error=f"Unknown tool: {tool_call.name}")

        try:
            args = tool_call.arguments
            if isinstance(args, str):
                args = json.loads(args)
            result = await tool.execute(**args)
            
            # Track file changes for undo
            if tool_call.name == "write_file" and "path" in args:
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
        except Exception as e:
            logger.exception(f"Tool {tool_call.name} failed")
            return ToolResult(error=str(e))

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
            {"role": m.role, "content": m.content, "tool_call_id": m.tool_call_id, "tool_name": m.tool_name}
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
            Message(role=m["role"], content=m["content"], tool_call_id=m.get("tool_call_id"), tool_name=m.get("tool_name"))
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
