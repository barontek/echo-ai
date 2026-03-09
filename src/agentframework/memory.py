"""Memory and context management tools."""

import logging
from typing import Any
from .session import SessionManager
from .agent import Message

logger = logging.getLogger(__name__)

class MemoryManager:
    """Handles conversational history summarization and pruning."""

    def __init__(self, session_manager: SessionManager | None):
        self.session_manager = session_manager

    async def summarize_if_needed(
        self,
        agent_messages: list[Message],
        llm: Any,
        max_messages: int = 20,
        keep_recent: int = 6
    ) -> list[Message]:
        """
        Check if the active state needs memory eviction.
        If it exceeds `max_messages`, we take the oldest bulk block and summarize it.
        Returns the new truncated `agent_messages` state so the local app syncs with the Database.
        """
        if len(agent_messages) <= max_messages:
            return agent_messages

        if not self.session_manager or not self.session_manager.current_session:
            return agent_messages
            
        session = self.session_manager.current_session

        logger.info("Triggering contextual memory compression (%d messages)", len(agent_messages))
        
        # We need to slice off the oldest strings, excluding the latest context block
        messages_to_summarize = agent_messages[:-keep_recent]
        messages_to_keep = agent_messages[-keep_recent:]
        
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
            
            # Truncate the persistent DB session array natively
            session.messages = list(session.messages[-keep_recent:])
            self.session_manager.save_session(session)
            
            logger.info("Memory compaction successful.")
            return messages_to_keep
                
        except Exception as e:
            logger.warning("Failed to perform memory summarization: %s", e)
            
        return agent_messages
