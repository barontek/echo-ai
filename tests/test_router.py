import pytest
from unittest.mock import AsyncMock
from src.agentframework.core import AgentConfig, create_agent
from src.agentframework.core.router import SemanticRouter, RouteSelection


@pytest.mark.asyncio
async def test_semantic_router_selection():
    config = AgentConfig(provider="openai", model="gpt-4o")
    agent = create_agent(config, api_key="dummy_key")

    agent.register_sub_agent(
        name="code_agent",
        description="Handles ONLY software engineering, coding, debugging, and programming questions.",
        tools=["python_execute"],
    )

    agent.register_sub_agent(
        name="research_agent",
        description="Handles deep research, web scraping, and answering factual questions.",
        tools=["google_search", "fetch_web"],
    )

    router = SemanticRouter(agent)

    # Mock the extract_structured from LLM
    agent.llm.extract_structured = AsyncMock()

    # Test Code Routing
    agent.llm.extract_structured.return_value = RouteSelection(
        reasoning="It is a code request", selected_agent="code_agent"
    )
    result1 = await router.route("Write a python script to sort an array")
    assert result1 == "code_agent"

    # Test Research Routing
    agent.llm.extract_structured.return_value = RouteSelection(
        reasoning="It is a research prompt", selected_agent="research_agent"
    )
    result2 = await router.route("Who won the 1993 world series?")
    assert result2 == "research_agent"

    # Test Fallback Routing
    agent.llm.extract_structured.return_value = RouteSelection(
        reasoning="General question", selected_agent="default"
    )
    result3 = await router.route("Hello how are you?")
    assert result3 == "default"

    # Test hallucination handling
    agent.llm.extract_structured.return_value = RouteSelection(
        reasoning="Made up agent", selected_agent="fictional_agent"
    )
    result4 = await router.route("Do something weird")
    assert result4 == "default"

    agent.close()
