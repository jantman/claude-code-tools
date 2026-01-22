"""Unit tests for the daemon module.

Tests the Daemon class and helper functions with mocked components.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.config import Config, DaemonConfig, SlackConfig, SwayidleConfig
from claude_permission_daemon.daemon import Daemon, setup_logging, parse_args
from claude_permission_daemon.state import Action, PendingRequest, PermissionRequest, StateManager


@pytest.fixture
def test_config(temp_dir: Path) -> Config:
    """Create a test configuration."""
    return Config(
        daemon=DaemonConfig(
            socket_path=temp_dir / "test.sock",
            idle_timeout=60,
            request_timeout=300,
        ),
        slack=SlackConfig(
            bot_token="xoxb-test-token",
            app_token="xapp-test-token",
            channel="C12345678",
        ),
        swayidle=SwayidleConfig(binary="swayidle"),
    )


class TestDaemonInit:
    """Tests for Daemon initialization."""

    def test_init_creates_state_manager(self, test_config: Config) -> None:
        """Test that Daemon creates a StateManager on init."""
        daemon = Daemon(test_config)
        assert daemon._state is not None
        assert isinstance(daemon._state, StateManager)

    def test_init_stores_config(self, test_config: Config) -> None:
        """Test that Daemon stores the config."""
        daemon = Daemon(test_config)
        assert daemon._config is test_config

    def test_init_components_none(self, test_config: Config) -> None:
        """Test that components are None before start."""
        daemon = Daemon(test_config)
        assert daemon._idle_monitor is None
        assert daemon._socket_server is None
        assert daemon._slack_handler is None

    def test_init_shutdown_event_not_set(self, test_config: Config) -> None:
        """Test that shutdown event is not set on init."""
        daemon = Daemon(test_config)
        assert not daemon._shutdown_event.is_set()

    def test_init_tasks_empty(self, test_config: Config) -> None:
        """Test that tasks list is empty on init."""
        daemon = Daemon(test_config)
        assert daemon._tasks == []
