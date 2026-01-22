"""Configuration loading for Claude Permission Daemon.

Loads configuration from TOML file with environment variable overrides.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "claude-permission-daemon" / "config.toml"
DEFAULT_SOCKET_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")) / "claude-permissions.sock"
DEFAULT_IDLE_TIMEOUT = 60
DEFAULT_REQUEST_TIMEOUT = 300
DEFAULT_SWAYIDLE_BINARY = "swayidle"


@dataclass
class DaemonConfig:
    """Configuration for the daemon itself."""

    socket_path: Path = field(default_factory=lambda: DEFAULT_SOCKET_PATH)
    idle_timeout: int = DEFAULT_IDLE_TIMEOUT
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT


@dataclass
class SlackConfig:
    """Configuration for Slack integration."""

    bot_token: str = ""
    app_token: str = ""
    channel: str = ""

    def validate(self) -> list[str]:
        """Validate Slack configuration, returning list of errors."""
        errors = []
        if not self.bot_token:
            errors.append("Slack bot_token is required")
        elif not self.bot_token.startswith("xoxb-"):
            errors.append("Slack bot_token should start with 'xoxb-'")
        if not self.app_token:
            errors.append("Slack app_token is required")
        elif not self.app_token.startswith("xapp-"):
            errors.append("Slack app_token should start with 'xapp-'")
        if not self.channel:
            errors.append("Slack channel is required")
        return errors


@dataclass
class SwayidleConfig:
    """Configuration for swayidle subprocess."""

    binary: str = DEFAULT_SWAYIDLE_BINARY


@dataclass
class Config:
    """Complete daemon configuration."""

    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    swayidle: SwayidleConfig = field(default_factory=SwayidleConfig)

    def validate(self) -> list[str]:
        """Validate configuration, returning list of errors."""
        errors = []
        errors.extend(self.slack.validate())
        if self.daemon.idle_timeout < 1:
            errors.append("idle_timeout must be at least 1 second")
        if self.daemon.request_timeout < 1:
            errors.append("request_timeout must be at least 1 second")
        return errors

    @classmethod
    def load(cls, config_path: Path | None = None) -> Self:
        """Load configuration from TOML file with environment variable overrides.

        Args:
            config_path: Path to config file. Defaults to ~/.config/claude-permission-daemon/config.toml

        Returns:
            Loaded and merged Config instance.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            tomllib.TOMLDecodeError: If config file is invalid TOML.
        """
        if config_path is None:
            config_path = DEFAULT_CONFIG_PATH

        # Load TOML file
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        # Build config from file data
        daemon_data = data.get("daemon", {})
        slack_data = data.get("slack", {})
        swayidle_data = data.get("swayidle", {})

        daemon_config = DaemonConfig(
            socket_path=Path(daemon_data.get("socket_path", DEFAULT_SOCKET_PATH)),
            idle_timeout=daemon_data.get("idle_timeout", DEFAULT_IDLE_TIMEOUT),
            request_timeout=daemon_data.get("request_timeout", DEFAULT_REQUEST_TIMEOUT),
        )

        slack_config = SlackConfig(
            bot_token=slack_data.get("bot_token", ""),
            app_token=slack_data.get("app_token", ""),
            channel=slack_data.get("channel", ""),
        )

        swayidle_config = SwayidleConfig(
            binary=swayidle_data.get("binary", DEFAULT_SWAYIDLE_BINARY),
        )

        config = cls(
            daemon=daemon_config,
            slack=slack_config,
            swayidle=swayidle_config,
        )

        # Apply environment variable overrides
        config._apply_env_overrides()

        return config

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        # Slack overrides
        if bot_token := os.environ.get("CLAUDE_PERM_SLACK_BOT_TOKEN"):
            self.slack.bot_token = bot_token
        if app_token := os.environ.get("CLAUDE_PERM_SLACK_APP_TOKEN"):
            self.slack.app_token = app_token
        if channel := os.environ.get("CLAUDE_PERM_SLACK_CHANNEL"):
            self.slack.channel = channel

        # Daemon overrides
        if idle_timeout := os.environ.get("CLAUDE_PERM_IDLE_TIMEOUT"):
            self.daemon.idle_timeout = int(idle_timeout)
        if request_timeout := os.environ.get("CLAUDE_PERM_REQUEST_TIMEOUT"):
            self.daemon.request_timeout = int(request_timeout)
        if socket_path := os.environ.get("CLAUDE_PERM_SOCKET_PATH"):
            self.daemon.socket_path = Path(socket_path)

        # Swayidle overrides
        if swayidle_binary := os.environ.get("CLAUDE_PERM_SWAYIDLE_BINARY"):
            self.swayidle.binary = swayidle_binary
