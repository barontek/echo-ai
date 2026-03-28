import unittest.mock
from src.agentframework.bootstrap import setup_agent
from src.agentframework.logging_utils import configure_logging
from fastapi.testclient import TestClient
from src.agentframework.api import app


def test_setup_agent_success():
    with (
        unittest.mock.patch(
            "src.agentframework.bootstrap.load_config", return_value={}
        ),
        unittest.mock.patch("src.agentframework.bootstrap.get_safety_config"),
        unittest.mock.patch("src.agentframework.bootstrap.get_tools", return_value=[]),
        unittest.mock.patch(
            "src.agentframework.bootstrap.create_agent"
        ) as mock_create_agent,
    ):
        agent = setup_agent()
        assert mock_create_agent.called
        assert isinstance(agent, unittest.mock.MagicMock)


def test_setup_logging():
    with unittest.mock.patch("logging.basicConfig"):
        with unittest.mock.patch("logging.getLogger") as mock_get_logger:
            mock_root = unittest.mock.MagicMock()
            mock_get_logger.return_value = mock_root
            configure_logging(debug_enabled=True)
            assert mock_root.addHandler.called
            assert mock_root.setLevel.called


def test_api_chat_endpoint():
    client = TestClient(app)
    with unittest.mock.patch("src.agentframework.api.get_or_create_agent") as mock_get:
        mock_agent = unittest.mock.MagicMock()
        mock_agent.run = unittest.mock.AsyncMock(return_value="API Response")
        mock_get.return_value = mock_agent

        response = client.post("/chat", json={"prompt": "hello", "session_id": "test"})
        assert response.status_code == 200
        assert response.json()["response"] == "API Response"


def test_api_route_endpoint():
    client = TestClient(app)
    app.state.router = unittest.mock.MagicMock()
    app.state.router.route = unittest.mock.AsyncMock(return_value="code_agent")

    response = client.post("/route", json={"prompt": "write some code"})
    assert response.status_code == 200
    assert response.json()["target_agent"] == "code_agent"


def test_cli_main_entrypoint():
    from src.agentframework.cli import main

    with (
        unittest.mock.patch("src.agentframework.cli.setup_agent"),
        unittest.mock.patch("src.agentframework.cli.asyncio.run") as mock_run,
    ):
        mock_run.side_effect = lambda coro: coro.close()

        with unittest.mock.patch("sys.argv", ["chat"]):
            main()
            assert not mock_run.called

        with unittest.mock.patch("sys.argv", ["chat", "do something"]):
            main()
            assert mock_run.called
