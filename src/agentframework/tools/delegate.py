"""Delegate tool for calling sub-agents."""

from typing import Any

from ..agent import Agent
from . import Tool, ToolResult


class DelegateTool(Tool):
    """Tool for delegating tasks to registered sub-agents."""

    def __init__(self, agent: Agent):
        super().__init__(
            name="delegate",
            description="Delegate a task to a sub-agent. Use this when a task requires specialized capabilities or you need to break down a complex problem.",
        )
        self.agent = agent

    def _get_parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "The name of the sub-agent to delegate to (e.g., 'coder', 'researcher')",
                },
                "task": {
                    "type": "string",
                    "description": "The task description for the sub-agent",
                },
            },
            "required": ["agent_name", "task"],
        }

    async def execute(self, agent_name: str, task: str, **kwargs) -> ToolResult:
        """Execute the delegate tool by running the sub-agent."""
        sub_agents = getattr(self.agent, 'sub_agents', {})
        
        if agent_name not in sub_agents:
            return ToolResult(error=f"Sub-agent '{agent_name}' not found. Available: {list(sub_agents.keys())}")

        sub_config = sub_agents[agent_name]
        
        # Get tool instances from the parent agent
        tool_map = getattr(self.agent, 'tool_map', {})
        selected_tools = []
        
        if sub_config.tools:
            for tool_name in sub_config.tools:
                if tool_name in tool_map:
                    selected_tools.append(tool_map[tool_name])
        
        # Build system prompt for sub-agent
        system_prompt = sub_config.system_prompt or f"You are a specialized sub-agent named @{agent_name}."
        if sub_config.description:
            system_prompt += f"\n\n{sub_config.description}"

        # Create sub-agent instance
        from ..agent import AgentConfig
        from ..providers import get_provider
        
        # Get provider from parent agent
        parent_llm = getattr(self.agent, 'llm', None)
        provider = None
        if parent_llm:
            from ..providers import LLMProvider
            if isinstance(parent_llm, LLMProvider):
                provider = parent_llm
        
        if not provider:
            return ToolResult(error="Could not get LLM provider for sub-agent")

        # Create sub-agent config
        agent_config = AgentConfig(
            provider=getattr(self.agent.config, 'provider', 'ollama'),
            model=sub_config.model or getattr(self.agent.config, 'model', 'qwen3:4b'),
            temperature=getattr(self.agent.config, 'temperature', 0.3),
            system_prompt=system_prompt,
            tools=selected_tools,
            session_enabled=False,
        )

        # Instantiate sub-agent
        sub_agent = Agent(
            config=agent_config,
            llm=provider,
            tool_map={t.name: t for t in selected_tools},
        )

        try:
            result = await sub_agent.run(task)
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(error=f"Sub-agent failed: {str(e)}")
