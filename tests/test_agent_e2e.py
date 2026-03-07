import pytest
from src.agentframework.agent import Agent, AgentConfig
from src.agentframework.providers import LLMProvider, LLMResponse, LLMToolCall
from src.agentframework.tools import Tool, ToolResult
from pydantic import BaseModel

class MockE2EProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        self.responses = responses
        self.call_count = 0
        self.messages_received = []

    async def extract_structured(self, messages, response_model, temperature=0.3):
        return None

    async def chat(self, messages: list[dict], tools: list | None = None, temperature: float = 0.3) -> LLMResponse:
        self.messages_received.append(messages)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return LLMResponse(content="Fallback response")

    async def chat_streaming(
        self, messages: list[dict], tools: list | None = None, temperature: float = 0.3, on_chunk=None
    ) -> LLMResponse:
        resp = await self.chat(messages, tools, temperature)
        if on_chunk and resp.content:
            for word in resp.content.split():
                on_chunk(word + " ")
        return resp

class CalcParams(BaseModel):
    a: int
    b: int

class CalcTool(Tool):
    parameters_model = CalcParams
    def __init__(self):
        super().__init__(name="calc", description="add two numbers")
    async def execute(self, a: int, b: int, **kwargs) -> ToolResult:
        return ToolResult(content=str(a + b))

@pytest.mark.asyncio
async def test_agent_run_loop_e2e():
    """Test that the agent correctly loops when a tool is called."""
    provider = MockE2EProvider([
        LLMResponse(
            content="Let me calculate that.",
            tool_calls=[LLMToolCall(id="1", name="calc", arguments={"a": 5, "b": 7})]
        ),
        LLMResponse(content="The answer is 12.")
    ])
    config = AgentConfig(tools=[CalcTool()], session_enabled=False)
    agent = Agent(config=config, llm_provider=provider)

    response = await agent.run("What is 5 + 7?")

    assert response == "The answer is 12."
    assert provider.call_count == 2

    # Check that tool execution message was added correctly to the agent's internal messages
    tool_msgs = [msg for msg in agent.messages if msg.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "12"
    assert tool_msgs[0].tool_name == "calc"

@pytest.mark.asyncio
async def test_agent_max_iterations():
    """Test that the agent exits gracefully if max_iterations is reached."""
    # LLM always returns a tool call, causing an infinite loop if not for max_iterations
    provider = MockE2EProvider([
        LLMResponse(
            content="",
            tool_calls=[LLMToolCall(id="1", name="calc", arguments={"a": 1, "b": 1})]
        ) for _ in range(10)
    ])
    config = AgentConfig(tools=[CalcTool()], session_enabled=False, max_iterations=3)
    agent = Agent(config=config, llm_provider=provider)

    response = await agent.run("Do math forever")

    assert "Max iterations reached" in response
    assert provider.call_count == 3  # Hit max iterations bounds

@pytest.mark.asyncio
async def test_agent_run_streaming_e2e():
    """Test streaming mode agent loop."""
    provider = MockE2EProvider([
        LLMResponse(
            content="Let me calculate that.",
            tool_calls=[LLMToolCall(id="1", name="calc", arguments={"a": 10, "b": 20})]
        ),
        LLMResponse(content="The answer is 30.")
    ])
    config = AgentConfig(tools=[CalcTool()], session_enabled=False)
    agent = Agent(config=config, llm_provider=provider)

    chunks = []
    def on_chunk(chunk: str):
        chunks.append(chunk.strip())

    response = await agent.run_streaming("10 + 20?", on_chunk=on_chunk)

    assert response == "The answer is 30."
    assert "answer" in chunks
    assert provider.call_count == 2
