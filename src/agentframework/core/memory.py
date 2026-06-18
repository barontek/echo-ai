"""Memory and context management tools."""

import logging
from typing import Any
from ..session import SessionManager
from ..conversation import Message

logger = logging.getLogger(__name__)


class MemoryManager:
    """Handles conversational history summarization and pruning."""

    def __init__(self, session_manager: SessionManager | None):
        self.session_manager = session_manager

    @staticmethod
    def _smart_select_messages(
        messages: list[Message], keep_count: int
    ) -> list[Message]:
        """Select an informative subset of messages rather than blind FIFO truncation.

        Priority order:
          1. System messages (always kept)
          2. Messages with tool calls / tool results
          3. Most recent messages (immediate context)
          4. Evenly sampled remainder to preserve conversation arc
        """
        if len(messages) <= keep_count:
            return list(messages)

        n = len(messages)
        must_keep: set[int] = set()

        # 1. Always keep system messages
        for i, m in enumerate(messages):
            if m.role == "system":
                must_keep.add(i)

        # 2. Keep tool interactions (tool calls and tool results)
        for i, m in enumerate(messages):
            if m.tool_calls or m.tool_name:
                must_keep.add(i)

        # 3. Keep a portion of the most recent messages for immediate context
        recent_count = max(keep_count * 2 // 5, 1)
        for i in range(max(0, n - recent_count), n):
            must_keep.add(i)

        # 4. Fill remaining budget by evenly sampling the rest
        remaining_budget = keep_count - len(must_keep)
        if remaining_budget > 0:
            candidates = [i for i in range(n) if i not in must_keep]
            if candidates:
                step = max(len(candidates) // remaining_budget, 1)
                for idx in range(0, len(candidates), step):
                    if len(must_keep) >= keep_count:
                        break
                    must_keep.add(candidates[idx])

        # Preserve original order
        sorted_indices = sorted(must_keep)[:keep_count]
        return [messages[i] for i in sorted_indices]

    async def summarize_if_needed(
        self,
        agent_messages: list[Message],
        llm: Any,
        max_messages: int = 20,
        keep_recent: int | None = None,
    ) -> list[Message]:
        """
        Check if the active state needs memory eviction.
        If it exceeds `max_messages`, we smart-select an informative subset,
        summarize the dropped portion, and store the rolled-up summary in
        session metadata where it can be injected into the LLM system prompt.

        The full message history in the database is never truncated.
        """
        if len(agent_messages) <= max_messages:
            return agent_messages

        if not self.session_manager or not self.session_manager.current_session:
            return agent_messages

        session = self.session_manager.current_session

        logger.info(
            "Triggering contextual memory compression (%d messages)",
            len(agent_messages),
        )

        if keep_recent is None:
            keep_recent = max_messages

        messages_to_keep = self._smart_select_messages(agent_messages, keep_recent)
        kept_indices = {
            id(m)
            for m in messages_to_keep
        }
        messages_to_summarize = [
            m for m in agent_messages if id(m) not in kept_indices
        ]

        current_summary = session.metadata.get("summary", "")

        prompt = "Extract and summarize the crucial facts, technical decisions, requirements, and state progress from the following conversation chunk. Output ONLY the new compacted contextual summary."
        if current_summary:
            prompt += f"\n\nExisting State Summary:\n{current_summary}"

        prompt += "\n\nArchived Conversation Block:\n"
        for m in messages_to_summarize:
            prompt += f"[{m.role.upper()}]: {m.content}\n"

        llm_messages = [{"role": "user", "content": prompt}]

        try:
            # We explicitly bypass tools for the summarizer loop
            response = await llm.chat(messages=llm_messages, tools=[], temperature=0.1)
            new_summary = response.content or ""

            if new_summary:
                # Store the rolled summary into the persistent SQLite blob
                session.metadata["summary"] = new_summary

            # Save updated metadata but do NOT truncate session.messages
            self.session_manager.save_session(session)

            logger.info("Memory compaction successful.")
            return messages_to_keep

        except Exception as e:
            logger.warning("Failed to perform memory summarization: %s", e)

        return agent_messages
