from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from src.agentframework.config import find_config_path, load_config, get_safety_config, get_tools
from src.agentframework.safety import SafetyConfig

def test_find_config_path_explicit():
    with patch("pathlib.Path.exists", return_value=True):
        assert find_config_path("custom.yaml") == Path("custom.yaml")

def test_find_config_path_not_found():
    with patch("pathlib.Path.exists", return_value=False):
        assert find_config_path("missing.yaml") is None
        assert find_config_path() is None

def test_load_config_empty():
    with patch("src.agentframework.config.find_config_path", return_value=None):
        assert load_config() == {}

def test_load_config_valid():
    content = "test: value"
    with patch("src.agentframework.config.find_config_path", return_value=Path("config.yaml")):
        with patch("builtins.open", mock_open(read_data=content)):
            assert load_config() == {"test": "value"}

def test_get_safety_config_defaults():
    config = {}
    safety = get_safety_config(config)
    assert isinstance(safety, SafetyConfig)
    assert safety.workspace == "."
    assert "bash" in safety.require_approval_for

@patch("src.agentframework.config.Prompt.ask")
@patch("src.agentframework.config.console.print")
def test_approval_callback_denied(mock_print, mock_ask):
    config = {"safety": {"require_approval_for": ["bash"]}}
    safety = get_safety_config(config)

    mock_ask.return_value = "n"
    assert safety.approval_callback("bash", "rm -rf /") is False
    assert mock_print.called

@patch("src.agentframework.config.Prompt.ask")
@patch("src.agentframework.config.console.print")
def test_approval_callback_approved(mock_print, mock_ask):
    config = {"safety": {"require_approval_for": ["bash"]}}
    safety = get_safety_config(config)

    mock_ask.return_value = "y"
    assert safety.approval_callback("bash", "ls") is True

@patch("src.agentframework.config.Prompt.ask")
def test_approval_callback_write_file_warning(mock_ask):
    config = {"safety": {"require_approval_for": ["write_file"]}}
    safety = get_safety_config(config)

    mock_ask.return_value = "y"
    with patch("pathlib.Path.exists", return_value=True):
        assert safety.approval_callback("write_file", "write: test.txt") is True

@patch("src.agentframework.config.Prompt.ask")
def test_approval_callback_read_file_warning(mock_ask):
    config = {"safety": {"require_approval_for": ["read_file"], "read_size_threshold": 100}}
    safety = get_safety_config(config)

    mock_ask.return_value = "y"
    mock_stat = MagicMock()
    mock_stat.st_size = 500
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat", return_value=mock_stat):
        assert safety.approval_callback("read_file", "read: large.txt") is True

def test_get_tools_instantiation():
    config = {
        "tools": {
            "enabled": ["read_file", "unknown_tool"],
            "read_file": {"workspace": "/tmp"}
        }
    }
    safety = SafetyConfig(workspace=".")

    with patch("src.agentframework.config.TOOL_REGISTRY", {"read_file": MagicMock()}) as mock_registry:
        tools = get_tools(config, safety)
        assert len(tools) == 1
        assert mock_registry["read_file"].called

def test_get_tools_default_params():
    config = {"tools": {"enabled": ["cat_tool"]}}
    safety = SafetyConfig()

    mock_tool_class = MagicMock()
    with patch("src.agentframework.config.TOOL_REGISTRY", {"cat_tool": mock_tool_class}), \
         patch("src.agentframework.config.TOOL_CONFIG_KEYS", {"cat_tool": {"param": "default"}}):
        get_tools(config, safety)
        mock_tool_class.assert_called_with(param="default")
