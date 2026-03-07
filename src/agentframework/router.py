"""Semantic Routing module for multi-agent workflows."""

import logging
from pydantic import BaseModel, Field

from .agent import Agent

logger = logging.getLogger(__name__)

class RouteSelection(BaseModel):
    """The structured decision made by the router LLM."""
    reasoning: str = Field(..., description="A step-by-step logical explanation for why this specific sub-agent was chosen.")
    selected_agent: str = Field(..., description="The name of the chosen sub-agent. If none match, use 'default'.")

class SemanticRouter:
    """Dynamically routes a user query to the most appropriate Sub-Agent based on its description."""

    def __init__(self, root_agent: Agent):
        """Initialize the router using the root agent's LLM and configured sub-agents."""
        self.agent = root_agent
        self.sub_agents = root_agent.sub_agents

    async def route(self, prompt: str) -> str:
        """Determine the best agent to handle the prompt. Returns the agent's name."""
        if not self.sub_agents:
            return "default"

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
            # We use the raw LLM provider with extract_structured to avoid messing up the chat history
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

            result: RouteSelection = await self.agent.llm.extract_structured(
                messages=messages,
                response_model=RouteSelection,
                temperature=0.0 # Strict determinism
            )

            chosen = result.selected_agent

            if chosen != "default" and chosen not in self.sub_agents:
                logger.warning("Router hallucinated an unknown agent '%s'. Falling back.", chosen)
                return "default"

            return chosen

        except Exception as e:
            logger.error("Semantic Routing failed: %s", str(e))
            return "default"  # Always fallback safely to the root agent
