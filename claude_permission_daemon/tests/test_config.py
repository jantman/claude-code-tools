"""Tests for config module."""

import os
from pathlib import Path
from unittest import mock

import pytest

from claude_permission_daemon.config import (
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_SWAYIDLE_BINARY,
    Config,
    DaemonConfig,
    SlackConfig,
    SwayidleConfig,
)


class TestDaemonConfig:
    """Tests for DaemonConfig dataclass."""

    def test_defaults(self) -> None:
        """Test default values are set correctly."""
        config = DaemonConfig()
        assert config.idle_timeout == DEFAULT_IDLE_TIMEOUT
        assert config.request_timeout == DEFAULT_REQUEST_TIMEOUT
        assert isinstance(config.socket_path, Path)


class TestSlackConfig:
    """Tests for SlackConfig dataclass."""

    def test_defaults(self) -> None:
        """Test default values are empty strings."""
        config = SlackConfig()
        assert config.bot_token == ""
        assert config.app_token == ""
        assert config.channel == ""

    def test_validate_empty(self) -> None:
        """Test validation fails for empty config."""
        config = SlackConfig()
        errors = config.validate()
        assert len(errors) == 3
        assert "bot_token is required" in errors[0]
        assert "app_token is required" in errors[1]
        assert "channel is required" in errors[2]

    def test_validate_invalid_prefixes(self) -> None:
        """Test validation fails for invalid token prefixes."""
        config = SlackConfig(
            bot_token="invalid-token",
            app_token="invalid-app-token",
            channel="C12345678",
        )
        errors = config.validate()
        assert len(errors) == 2
        assert "xoxb-" in errors[0]
        assert "xapp-" in errors[1]

    def test_validate_valid(self) -> None:
        """Test validation passes for valid config."""
        config = SlackConfig(
            bot_token="xoxb-valid-token",
            app_token="xapp-valid-token",
            channel="U12345678",
        )
        errors = config.validate()
        assert len(errors) == 0


class TestSwayidleConfig:
    """Tests for SwayidleConfig dataclass."""

    def test_defaults(self) -> None:
        """Test default binary path."""
        config = SwayidleConfig()
        assert config.binary == DEFAULT_SWAYIDLE_BINARY


class TestConfig:
    """Tests for Config dataclass and loading."""

    def test_defaults(self) -> None:
        """Test default nested configs are created."""
        config = Config()
        assert isinstance(config.daemon, DaemonConfig)
        assert isinstance(config.slack, SlackConfig)
        assert isinstance(config.swayidle, SwayidleConfig)

    def test_validate_with_slack_errors(self) -> None:
        """Test validation propagates Slack errors."""
        config = Config()
        errors = config.validate()
        assert len(errors) >= 3  # At least the Slack errors

    def test_validate_invalid_timeouts(self) -> None:
        """Test validation catches invalid timeouts."""
        config = Config(
            daemon=DaemonConfig(idle_timeout=0, request_timeout=-1),
            slack=SlackConfig(
                bot_token="xoxb-valid",
                app_token="xapp-valid",
                channel="C123",
            ),
        )
        errors = config.validate()
        assert any("idle_timeout" in e for e in errors)
        assert any("request_timeout" in e for e in errors)

    def test_load_full_config(self, config_file: Path) -> None:
        """Test loading a complete config file."""
        config = Config.load(config_file)

        assert config.daemon.socket_path == Path("/tmp/test-claude-permissions.sock")
        assert config.daemon.idle_timeout == 30
        assert config.daemon.request_timeout == 120
        assert config.slack.bot_token == "xoxb-test-token-12345"
        assert config.slack.app_token == "xapp-test-token-67890"
        assert config.slack.channel == "U12345678"
        assert config.swayidle.binary == "/usr/bin/swayidle"

    def test_load_minimal_config(self, minimal_config_file: Path) -> None:
        """Test loading config with only required fields uses defaults."""
        config = Config.load(minimal_config_file)

        # Should use defaults for daemon
        assert config.daemon.idle_timeout == DEFAULT_IDLE_TIMEOUT
        assert config.daemon.request_timeout == DEFAULT_REQUEST_TIMEOUT

        # Slack values from file
        assert config.slack.bot_token == "xoxb-minimal-token"
        assert config.slack.app_token == "xapp-minimal-token"
        assert config.slack.channel == "C12345678"

        # Default swayidle
        assert config.swayidle.binary == DEFAULT_SWAYIDLE_BINARY

    def test_load_file_not_found(self, temp_dir: Path) -> None:
        """Test FileNotFoundError for missing config."""
        with pytest.raises(FileNotFoundError):
            Config.load(temp_dir / "nonexistent.toml")

    def test_load_invalid_toml(self, temp_dir: Path) -> None:
        """Test error for invalid TOML syntax."""
        import tomllib

        config_path = temp_dir / "invalid.toml"
        config_path.write_text("this is not valid toml [[[")

        with pytest.raises(tomllib.TOMLDecodeError):
            Config.load(config_path)

    def test_env_var_overrides(self, minimal_config_file: Path) -> None:
        """Test environment variables override config file values."""
        env_overrides = {
            "CLAUDE_PERM_SLACK_BOT_TOKEN": "xoxb-env-override",
            "CLAUDE_PERM_SLACK_APP_TOKEN": "xapp-env-override",
            "CLAUDE_PERM_SLACK_CHANNEL": "U99999999",
            "CLAUDE_PERM_IDLE_TIMEOUT": "120",
            "CLAUDE_PERM_REQUEST_TIMEOUT": "600",
            "CLAUDE_PERM_SOCKET_PATH": "/tmp/env-socket.sock",
            "CLAUDE_PERM_SWAYIDLE_BINARY": "/custom/swayidle",
        }

        with mock.patch.dict(os.environ, env_overrides, clear=False):
            config = Config.load(minimal_config_file)

        assert config.slack.bot_token == "xoxb-env-override"
        assert config.slack.app_token == "xapp-env-override"
        assert config.slack.channel == "U99999999"
        assert config.daemon.idle_timeout == 120
        assert config.daemon.request_timeout == 600
        assert config.daemon.socket_path == Path("/tmp/env-socket.sock")
        assert config.swayidle.binary == "/custom/swayidle"

    def test_env_var_partial_override(self, config_file: Path) -> None:
        """Test partial env var override (some values from file, some from env)."""
        with mock.patch.dict(
            os.environ, {"CLAUDE_PERM_SLACK_CHANNEL": "U_FROM_ENV"}, clear=False
        ):
            config = Config.load(config_file)

        # From env
        assert config.slack.channel == "U_FROM_ENV"
        # From file
        assert config.slack.bot_token == "xoxb-test-token-12345"
        assert config.daemon.idle_timeout == 30
