"""Extended tests for safety module - covering edge cases."""

import pytest
import tempfile
from unittest.mock import patch

from src.agentframework.safety import (
    SafetyConfig,
    SecurityValidator,
    create_safety_validator,
)


class TestSafetyEdgeCases:
    @pytest.fixture
    def validator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir, allowed_commands=["*"])
            yield SecurityValidator(config)

    def test_check_path_traversal_empty(self, validator):
        assert validator.check_path_traversal("") is False

    def test_is_blocked_extension_empty(self, validator):
        assert validator.is_blocked_extension("") is False

    def test_is_blocked_path_empty(self, validator):
        assert validator.is_blocked_path("") is False

    def test_check_bash_command_empty_subcommand(self, validator):
        safe, reason = validator.check_command_safety("echo")
        assert safe is True

    def test_check_bash_command_variable_assignment_only(self, validator):
        safe, reason = validator.check_command_safety("DEBUG=1")
        assert safe is True

    def test_check_bash_command_bare_semicolon(self, validator):
        safe, reason = validator.check_command_safety(";")
        assert safe is True

    def test_check_bash_command_malformed(self, validator):
        safe, reason = validator.check_command_safety("echo 'unclosed")
        assert safe is False
        assert "Malformed" in reason


class TestCheckNetworkAllowed:
    @pytest.fixture
    def validator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir, allow_network=True)
            yield SecurityValidator(config)

    def test_network_enabled_no_domain_list(self, validator):
        allowed, reason = validator.check_network_allowed("https://example.com")
        assert allowed is True

    def test_network_disabled(self):
        config = SafetyConfig(allow_network=False)
        validator = SecurityValidator(config)
        allowed, reason = validator.check_network_allowed("https://example.com")
        assert allowed is False
        assert "disabled" in reason


class TestCheckFileSize:
    @pytest.fixture
    def validator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir, max_file_size=100)
            yield SecurityValidator(config)

    def test_check_file_size_with_path(self, validator, tmp_path):
        small = tmp_path / "small.txt"
        small.write_text("hello")
        assert validator.check_file_size(path=str(small)) is True

    def test_check_file_size_path_exceeds(self, validator, tmp_path):
        big = tmp_path / "big.txt"
        big.write_text("x" * 200)
        assert validator.check_file_size(path=str(big)) is False

    def test_check_file_size_path_not_found(self, validator):
        assert validator.check_file_size(path="/nonexistent/file.txt") is True


class TestRequiresApprovalEdgeCases:
    @pytest.fixture
    def validator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir)
            yield SecurityValidator(config)

    def test_require_approval_none_config(self, validator):
        validator.config.require_approval_for = None
        assert validator.requires_approval("bash") is False

    def test_require_approval_read_over_size(self, validator, tmp_path):
        config = SafetyConfig(workspace=str(tmp_path), read_requires_approval=False)
        validator = SecurityValidator(config)
        assert validator.requires_approval("read_file") is False


class TestLogApproval:
    def test_log_approval_no_audit_path(self):
        validator = SecurityValidator(SafetyConfig())
        validator.log_approval("bash", "test cmd", True)

    def test_log_approval_writes_to_file(self, tmp_path):
        audit = tmp_path / "audit.log"
        config = SafetyConfig(audit_log_path=str(audit))
        validator = SecurityValidator(config)
        validator.log_approval("bash", "rm -rf /", False)
        content = audit.read_text()
        assert "DENIED" in content
        assert "bash" in content
        assert "rm -rf /" in content

    def test_log_approval_approved(self, tmp_path):
        audit = tmp_path / "audit.log"
        config = SafetyConfig(audit_log_path=str(audit))
        validator = SecurityValidator(config)
        validator.log_approval("bash", "ls", True)
        content = audit.read_text()
        assert "APPROVED" in content

    def test_log_approval_write_error(self, tmp_path):
        audit = tmp_path / "audit.log"
        config = SafetyConfig(audit_log_path=str(audit))
        validator = SecurityValidator(config)
        with patch("builtins.open", side_effect=Exception("write error")):
            validator.log_approval("bash", "test", True)


class TestGetApprovalEdgeCases:
    def test_get_approval_no_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir)
            validator = SecurityValidator(config)
            result = validator.get_approval("write_file", "rm /")
            assert result is False

    def test_get_approval_non_required_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir)
            validator = SecurityValidator(config)
            result = validator.get_approval("echo", "hello")
            assert result is True


class TestGetApprovalAsync:
    @pytest.mark.asyncio
    async def test_async_approval_no_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir)
            validator = SecurityValidator(config)
            result = await validator.get_approval_async("write_file", "rm /")
            assert result is False

    @pytest.mark.asyncio
    async def test_async_approval_non_required_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(workspace=tmpdir)
            validator = SecurityValidator(config)
            result = await validator.get_approval_async("echo", "hello")
            assert result is True

    @pytest.mark.asyncio
    async def test_async_approval_with_async_callback(self):
        async def async_callback(tool, details):
            return True

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(
                workspace=tmpdir,
                async_approval_callback=async_callback,
            )
            validator = SecurityValidator(config)
            result = await validator.get_approval_async("write_file", "test")
            assert result is True

    @pytest.mark.asyncio
    async def test_async_approval_with_sync_callback(self):
        def sync_callback(tool, details):
            return True

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(
                workspace=tmpdir,
                async_approval_callback=sync_callback,
            )
            validator = SecurityValidator(config)
            result = await validator.get_approval_async("write_file", "test")
            assert result is True

    @pytest.mark.asyncio
    async def test_async_approval_fallback_to_sync_callback(self):
        def sync_callback(tool, details):
            return True

        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(
                workspace=tmpdir,
                approval_callback=sync_callback,
            )
            validator = SecurityValidator(config)
            result = await validator.get_approval_async("write_file", "test")
            assert result is True


class TestCreateSafetyValidator:
    def test_create_with_no_config(self):
        validator = create_safety_validator()
        assert isinstance(validator, SecurityValidator)
        assert validator.config.workspace == "."

    def test_create_with_custom_config(self):
        config = SafetyConfig(workspace="/tmp", allow_network=True)
        validator = create_safety_validator(config)
        assert validator.config.workspace == "/tmp"
        assert validator.config.allow_network is True


class TestCheckCommandSafetyBlockedCommands:
    def test_blocked_commands_with_non_string_pattern(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SafetyConfig(
                workspace=tmpdir,
                allowed_commands=["*"],
                blocked_commands=[123],
            )
            validator = SecurityValidator(config)
            safe, reason = validator.check_command_safety("any_command")
            assert safe is True
