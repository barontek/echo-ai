import pytest
from unittest.mock import MagicMock, patch
from src.agentframework.bootstrap import setup_agent

@pytest.fixture
def mock_dependencies():
    with patch("src.agentframework.bootstrap.load_config") as mock_load, \
         patch("src.agentframework.bootstrap.find_config_path"), \
         patch("src.agentframework.bootstrap.get_safety_config") as mock_get_safety, \
         patch("src.agentframework.bootstrap.get_tools") as mock_get_tools, \
         patch("src.agentframework.bootstrap.create_agent") as mock_create:

        mock_load.return_value = {
            "agent": {"session_enabled": True},
            "model": {"provider": "ollama", "name": "test-model"},
            "observability": {
                "otel_enabled": True,
                "service_name": "test-service",
                "console_export": True,
                "otlp_endpoint": "http://localhost:4317"
            }
        }
        mock_get_safety.return_value = MagicMock(workspace=".")
        mock_get_tools.return_value = []
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        yield mock_agent

def test_setup_agent_with_otel(mock_dependencies):
    mock_agent = mock_dependencies

    # Create a dummy class that can be used with isinstance()
    class DummyTracerProvider:
        def __init__(self, *args, **kwargs):
            self.add_span_processor = MagicMock()
            self.shutdown = MagicMock()

    # Mock opentelemetry modules
    # We patch them where they are used or imported
    with patch("opentelemetry.trace.get_tracer_provider") as mock_get_tp, \
         patch("opentelemetry.trace.set_tracer_provider"), \
         patch("opentelemetry.sdk.trace.TracerProvider", DummyTracerProvider), \
         patch("opentelemetry.sdk.trace.export.BatchSpanProcessor"), \
         patch("opentelemetry.sdk.trace.export.ConsoleSpanExporter"), \
         patch("opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter"), \
         patch("src.agentframework.otel.OpenTelemetryCallback") as mock_callback_cls:

        # mock_get_tp should return something that is NOT a DummyTracerProvider to trigger initialization
        mock_get_tp.return_value = MagicMock()

        mock_callback = MagicMock()
        mock_callback_cls.return_value = mock_callback

        agent = setup_agent()

        assert agent == mock_agent
        # Verify callback was added to the agent
        mock_agent.add_callback.assert_called_with(mock_callback)

def test_setup_agent_otel_import_error(mock_dependencies):
    mock_agent = mock_dependencies

    # Simulate ImportError for opentelemetry
    with patch("src.agentframework.bootstrap.configure_logging"):
        with patch("opentelemetry.trace.get_tracer_provider", side_effect=ImportError("No OTEL")):
            agent = setup_agent()
            assert agent == mock_agent
            # Should not have tried to add the callback
            assert not mock_agent.add_callback.called
