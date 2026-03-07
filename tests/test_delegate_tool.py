import pytest
from src.agentframework.agent import Agent, AgentConfig
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall

class MockProvider(LLMProvider):
    def __init__(self, responses):
        self.responses = list(responses)
        self.idx = 0

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None # Corrected typo from Nones)

    async def chat(self, messages, tools=None, temperature=0.3):
        if self.idx < len(self.responses):
            response = self.responses[self.idx]
            self.idx += 1
            return response
        return LLMResponse(content="done")


@pytest.mark.asyncio
async def test_delegate_tool_success():
    # Setup mock provider for the sub-agent
    _sub_agent_response = LLMResponse(content="Sub-agent analyzed the file successfully.")

    # Setup mock provider for the main agent
    _main_provider = MockProvider([
        LLMResponse(
            content="Delegating check...",
            tool_calls=[LLMToolCall(id="1", name="delegate", arguments={"agent_name": "researcher", "task": "analyze file"})]
        ),
        LLMResponse(content="All done.")
    ])

    # We patch the chat method of the sub-agent creation to simplify
    # But essentially we can just reuse the main provider or use a custom one.
    # Since DelegateTool reuses the provider instance, both agents will pull from the sequence.
    # We insert the sub_agent_response into the sequence so the sub-agent gets it.

    provider = MockProvider([
        # Main Agent Turn 1: Delegate
        LLMResponse(
            content="Delegating",
            tool_calls=[LLMToolCall(id="call_1", name="delegate", arguments={"agent_name": "researcher", "task": "analyze"})]
        ),
        # Sub Agent Turn 1: Solves it
        LLMResponse(content="Sub agent result."),
        # Main Agent Turn 2: Done
        LLMResponse(content="Final Response.")
    ])

    agent = Agent(config=AgentConfig(session_enabled=False), llm_provider=provider)
    agent.register_sub_agent(name="researcher", description="Analyzes stuff")

    result = await agent.run("Please analyze the file using the researcher")

    assert result == "Final Response."

    # Check that the delegate tool actually populated messages
    tool_messages = [m for m in agent.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert "Sub agent result." in tool_messages[0].content


@pytest.mark.asyncio
async def test_delegate_tool_missing_agent():
    provider = MockProvider([
        # Main Agent Turn 1: Delegate to unknown
        LLMResponse(
            content="Delegating",
            tool_calls=[LLMToolCall(id="call_1", name="delegate", arguments={"agent_name": "unknown_agent", "task": "analyze"})]
        ),
        # Main Agent Turn 2: Done
        LLMResponse(content="Final Response.")
    ])

    agent = Agent(config=AgentConfig(session_enabled=False), llm_provider=provider)
    # Register dummy to inject delegate tool
    agent.register_sub_agent("researcher")

    _result = await agent.run("Please analyze")

    tool_messages = [m for m in agent.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert "not found" in tool_messages[0].content
