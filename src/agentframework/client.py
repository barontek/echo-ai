"""Unified Client interface for Echo AI UIs."""

import asyncio
from dataclasses import dataclass
from typing import AsyncGenerator

from .core import Agent
from .chat_commands import normalize_command
from .constants import THINKING_START, THINKING_END


@dataclass
class ChatEvent:
    """Base class for chat stream events."""

    pass


@dataclass
class ContentEvent(ChatEvent):
    """Represents a chunk of assistant content."""

    content: str


@dataclass
class ThinkingEvent(ChatEvent):
    """Represents a chunk of an assistant's thinking process."""

    content: str


@dataclass
class CommandResultEvent(ChatEvent):
    """Result of executing a built-in slash command."""

    result: str
    should_exit: bool = False


@dataclass
class ErrorEvent(ChatEvent):
    """Represents an error in the stream."""

    error: str


class EchoClient:
    """A proxy between the UI and the underlying Agent.

    Handles streaming unification, thinking tag extraction, and slash commands.
    """

    __slots__ = ("agent",)

    def __init__(self, agent: Agent):
        self.agent = agent

    async def stream_chat(self, user_input: str) -> AsyncGenerator[ChatEvent, None]:
        """Stream chat completions from the agent."""
        if not user_input.strip():
            return

        # Intercept built-in commands
        if user_input.strip().startswith("/"):
            cmd = normalize_command(user_input.strip().split()[0].lower())
            args = (
                user_input.strip().split(maxsplit=1)[1]
                if len(user_input.strip().split()) > 1
                else ""
            )

            # Some commands (like /save, /load) might return string results, others might rely on the console directly.
            # In our new abstraction, execute_command ideally would cleanly return string outputs, but for now we adapt it.
            # We'll use a mocked console to capture the rich output or simply replicate the logic if execute_command uses a console param.
            # Given that chat_commands.py expects a rich console, we might need a custom approach here, but to minimize changes,
            # we can intercept purely state-changing commands or let the UI handle the "console" part if it wants.
            # Actually, let's implement the core logic for typical commands cleanly without rich console dependency,
            # or refactor execute_command if needed.

            # Since the plan stated unified command handling, we will handle save/load natively as a string returned in CommandResultEvent
            if cmd == "/exit":
                yield CommandResultEvent(result="Exiting...", should_exit=True)
                return
            elif cmd == "/save":
                result = self.agent.save_session(args if args else None)
                yield CommandResultEvent(result=result)
                return
            elif cmd == "/load":
                if args:
                    result = self.agent.load_session(args)
                    yield CommandResultEvent(result=result)
                else:
                    yield CommandResultEvent(result="Usage: /load <session_id>")
                return
            elif cmd == "/chats":
                sessions, total = self.agent.list_sessions()
                if sessions:
                    result = f"Saved sessions ({total} total):\n" + "\n".join(
                        [f"  - {s}" for s in sessions]
                    )
                else:
                    result = "No saved sessions."
                yield CommandResultEvent(result=result)
                return
            elif cmd == "/undo":
                result = self.agent.undo()
                yield CommandResultEvent(result=result)
                return
            elif cmd == "/redo":
                result = self.agent.redo()
                yield CommandResultEvent(result=result)
                return
            elif cmd == "/help":
                result = (
                    "Commands:\n"
                    "  /save [name] - Save current session\n"
                    "  /load <name> - Load a session\n"
                    "  /chats       - List saved sessions\n"
                    "  /undo        - Undo last file change\n"
                    "  /redo        - Redo last undone change\n"
                    "  /exit        - Exit"
                )
                yield CommandResultEvent(result=result)
                return

        # Setup streaming queue
        queue = asyncio.Queue()

        # We must manage state correctly because chunks might split thinking tags.
        # This state tracks whether we've seen THINKING_START but not THINKING_END
        in_thinking = False
        buffer = ""

        def process_buffer():
            nonlocal in_thinking, buffer
            while buffer:
                if in_thinking:
                    end_idx = buffer.find(THINKING_END)
                    if end_idx != -1:
                        if end_idx > 0:
                            queue.put_nowait(ThinkingEvent(content=buffer[:end_idx]))
                        in_thinking = False
                        buffer = buffer[end_idx + len(THINKING_END) :]
                    else:
                        # Check for partial end tag at the end (THINKING_END is longer)
                        partial_match = False
                        for i in range(len(THINKING_END) - 1, 0, -1):
                            if buffer.endswith(THINKING_END[:i]):
                                if len(buffer) > i:
                                    queue.put_nowait(ThinkingEvent(content=buffer[:-i]))
                                buffer = buffer[-i:]
                                partial_match = True
                                break

                        if not partial_match:
                            queue.put_nowait(ThinkingEvent(content=buffer))
                            buffer = ""
                        break
                else:
                    start_idx = buffer.find(THINKING_START)
                    if start_idx != -1:
                        if start_idx > 0:
                            queue.put_nowait(ContentEvent(content=buffer[:start_idx]))
                        in_thinking = True
                        buffer = buffer[start_idx + len(THINKING_START) :]
                    else:
                        # Check for partial start tag at the end (THINKING_START is shorter)
                        partial_match = False
                        for i in range(len(THINKING_START) - 1, 0, -1):
                            if buffer.endswith(THINKING_START[:i]):
                                if len(buffer) > i:
                                    queue.put_nowait(ContentEvent(content=buffer[:-i]))
                                buffer = buffer[-i:]
                                partial_match = True
                                break

                        if not partial_match:
                            queue.put_nowait(ContentEvent(content=buffer))
                            buffer = ""
                        break

        def on_chunk(chunk: str):
            nonlocal buffer
            buffer += chunk
            process_buffer()

        # Background task to run agent
        async def agent_task():
            nonlocal buffer
            try:
                await self.agent.run_streaming(user_input, on_chunk=on_chunk)
            except Exception as e:
                buffer = ""
                queue.put_nowait(ErrorEvent(error=str(e)))
            finally:
                if buffer:
                    if in_thinking:
                        queue.put_nowait(ThinkingEvent(content=buffer))
                    else:
                        queue.put_nowait(ContentEvent(content=buffer))
                queue.put_nowait(None)  # Sentinel to finish

        task = asyncio.create_task(agent_task())

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
