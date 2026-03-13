import pytest
from pydantic import BaseModel, Field
from unittest.mock import AsyncMock

from src.agentframework.agent import AgentConfig, create_agent

class UserProfile(BaseModel):
    name: str = Field(description="The full name of the user.")
    age: int = Field(description="The age of the user in years.")

@pytest.mark.asyncio
async def test_agent_extract_data():
    config = AgentConfig(provider="openai", model="gpt-4o")
    agent = create_agent(config, api_key="dummy_key")

    # Mock the underlying provider's extract_structured method
    agent.llm.extract_structured = AsyncMock()
    mock_response = UserProfile(name="Alice", age=30)
    agent.llm.extract_structured.return_value = mock_response

    result = await agent.extract_data(
        prompt="Hi, my name is Alice and I am 30 years old.",
        response_model=UserProfile
    )

    assert isinstance(result, UserProfile)
    assert result.name == "Alice"
    assert result.age == 30

    # Verify the mock was called correctly
    agent.llm.extract_structured.assert_called_once()
    call_kwargs = agent.llm.extract_structured.call_args.kwargs
    assert call_kwargs["response_model"] == UserProfile
    assert call_kwargs["messages"][0]["content"] == "Hi, my name is Alice and I am 30 years old."

    agent.close()
