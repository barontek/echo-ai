import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.agentframework.api import app

@pytest.mark.asyncio
async def test_api_lifespan():
    # Use TestClient as a context manager to trigger lifespan events
    with patch("src.agentframework.api.create_agent") as mock_create:
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        with TestClient(app):
            # Check if router was initialized in app.state
            assert hasattr(app.state, "router")
            assert app.state.router is not None

            # Check if default agent was registered
            from src.agentframework.api import agents
            assert "default" in agents
            assert agents["default"] == mock_agent

            # Verify sub-agents were registered
            mock_agent.register_sub_agent.assert_any_call(
                name="code_agent",
                description="Handles coding, programming, debugging, and software architecture questions.",
            )
            mock_agent.register_sub_agent.assert_any_call(
                name="research_agent",
                description="Handles web scraping, general knowledge, and deep contextual research.",
            )

@pytest.mark.asyncio
async def test_get_or_create_agent_new_session():
    from src.agentframework.api import get_or_create_agent, ChatRequest, agents

    # Clear agents for clean test
    agents.clear()

    with patch("src.agentframework.api.create_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.session_manager = MagicMock()
        mock_create.return_value = mock_agent

        req = ChatRequest(prompt="hi", session_id="new_session", provider="openai", model="gpt-4")
        agent = get_or_create_agent(req)

        assert agent == mock_agent
        mock_create.assert_called_once()
        mock_agent.session_manager.create_session.assert_called_with("new_session")
        assert "new_session" in agents
