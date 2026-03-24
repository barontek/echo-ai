import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.agentframework.api import app


@pytest.mark.asyncio
async def test_api_lifespan():
    with patch("src.agentframework.api.create_agent") as mock_create:
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        with TestClient(app):
            assert hasattr(app.state, "router")
            assert app.state.router is not None

            from src.agentframework.dependencies import get_agent_registry

            registry = get_agent_registry()
            assert registry.has("default")
            assert registry.get("default") == mock_agent

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
    from src.agentframework.api import get_or_create_agent, ChatRequest
    from src.agentframework.dependencies import get_agent_registry

    registry = get_agent_registry()
    registry.clear()

    with patch("src.agentframework.api.create_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.session_manager = MagicMock()
        mock_create.return_value = mock_agent

        req = ChatRequest(
            prompt="hi", session_id="new_session", provider="openai", model="gpt-4"
        )
        agent = get_or_create_agent(req, registry)

        assert agent == mock_agent
        mock_create.assert_called_once()
        mock_agent.session_manager.create_session.assert_called_with("new_session")
        assert registry.has("new_session")
