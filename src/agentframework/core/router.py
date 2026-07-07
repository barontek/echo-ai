"""Semantic Routing module for multi-agent workflows."""

import logging
import re
from pydantic import BaseModel, Field

from .agent import Agent

logger = logging.getLogger(__name__)


class RouteSelection(BaseModel):
    """The structured decision made by the router LLM."""

    reasoning: str = Field(
        ...,
        description="A step-by-step logical explanation for why this specific sub-agent was chosen.",
    )
    selected_agent: str = Field(
        ...,
        description="The name of the chosen sub-agent. If none match, use 'default'.",
    )


HEURISTIC_KEYWORDS = {
    "code": [
        "write code",
        "implement",
        "function",
        "class",
        "debug",
        "refactor",
        "code",
        "programming",
        "script",
        "algorithm",
        "api",
        "endpoint",
        "fix bug",
        "syntax",
        "runtime",
        "compile",
        "import",
        "module",
        "python",
        "javascript",
        "typescript",
        "java",
        "rust",
        "go",
        "c++",
    ],
    "file": [
        "file",
        "read",
        "write",
        "open",
        "save",
        "create",
        "delete",
        "move",
        "copy",
        "directory",
        "folder",
        "path",
        "glob",
        "find file",
        "list files",
        "download",
        "upload",
        "edit file",
        "modify",
        "rename",
        "mkdir",
    ],
    "web": [
        "search",
        "browse",
        "fetch",
        "url",
        "http",
        "website",
        "web page",
        "scrape",
        "crawl",
        "http request",
        "api call",
        "rest",
        "html",
        "download from url",
        "get content",
        "extract",
        "parse html",
    ],
    "memory": [
        "remember",
        "memory",
        "store",
        "recall",
        "forget",
        "context",
        "long term",
        "persist",
        "save to memory",
        "retrieve",
        "search memory",
        "past conversation",
        "what did i say",
        "previous",
        "earlier",
    ],
    "cli": [
        "run command",
        "execute",
        "shell",
        "bash",
        "terminal",
        "cmd",
        "command line",
        "subprocess",
        "shell command",
        "terminal command",
        "run ",
        "install",
        "npm",
        "pip",
        "cargo",
        "apt",
        "brew",
    ],
}


class SemanticRouter:
    """Dynamically routes a user query to the most appropriate Sub-Agent based on its description."""

    def __init__(self, root_agent: Agent):
        """Initialize the router using the root agent's LLM and configured sub-agents."""
        self.agent = root_agent
        self.sub_agents = root_agent.sub_agents

    def _heuristic_route(self, prompt: str) -> str | None:
        """Fast deterministic keyword matching to bypass LLM when possible.

        Returns the sub-agent name if a strong keyword match is found, None otherwise.
        """
        prompt_lower = prompt.lower()

        for agent_name, keywords in HEURISTIC_KEYWORDS.items():
            if agent_name not in self.sub_agents:
                continue

            matches = sum(1 for kw in keywords if kw in prompt_lower)

            if matches >= 2:
                logger.debug(
                    f"Heuristic matched agent '{agent_name}' with {matches} keyword hits"
                )
                return agent_name

            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", prompt_lower) or kw in prompt_lower:
                    logger.debug(
                        f"Heuristic matched agent '{agent_name}' via exact keyword '{kw}'"
                    )
                    return agent_name

        return None

    async def route(self, prompt: str) -> str:
        """Determine the best agent to handle the prompt. Returns the agent's name."""
        if not self.sub_agents:
            return "default"

        heuristic_result = self._heuristic_route(prompt)
        if heuristic_result:
            return heuristic_result

        # Build the dynamic schema configuration for the router to understand
        agent_descriptions = []
        for name, config in self.sub_agents.items():
            agent_descriptions.append(f"""
            - **{name}**: {config.description}
            """)

        system_prompt = (
            "You are an expert Semantic Router for a multi-agent AI system. "
            "Your job is to analyze the user's query and select the single most appropriate "
            "specialized sub-agent from the registry below to handle it.\n\n"
            "### Available Agents\n"
             f"{''.join(agent_descriptions)}\n"
            "- **default**: Use this agent ONLY if the query is a generic conversation "
            "or does not strictly fit any of the specialized profiles above.\n\n"
            "Return the exact name of the chosen agent and your reasoning."
        )

        try:
            if self.agent.llm is None:
                logger.error("No LLM provider available for routing; falling back to default.")
                return "default"

            # We use the raw LLM provider with extract_structured to avoid messing up the chat history
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            async with self.agent._llm_lock:
                result: RouteSelection = await self.agent.llm.extract_structured(
                    messages=messages,
                    response_model=RouteSelection,
                    temperature=0.0,  # Strict determinism
                )

            chosen = result.selected_agent

            if chosen != "default" and chosen not in self.sub_agents:
                logger.warning(
                    "Router hallucinated an unknown agent '%s'. Falling back.", chosen
                )
                return "default"

            return chosen

        except Exception as e:
            logger.error("Semantic Routing failed: %s", str(e))
            return "default"  # Always fallback safely to the root agent
