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


class TestDaemonStartStop:
    """Tests for Daemon start and stop methods."""

    @pytest.fixture
    def mock_idle_monitor(self) -> MagicMock:
        """Create a mock IdleMonitor."""
        mock = MagicMock()
        mock.start = AsyncMock()
        mock.stop = AsyncMock()
        mock.run = AsyncMock()
        return mock

    @pytest.fixture
    def mock_socket_server(self) -> MagicMock:
        """Create a mock SocketServer."""
        mock = MagicMock()
        mock.start = AsyncMock()
        mock.stop = AsyncMock()
        mock.run = AsyncMock()
        return mock

    @pytest.fixture
    def mock_slack_handler(self) -> MagicMock:
        """Create a mock SlackHandler."""
        mock = MagicMock()
        mock.start = AsyncMock()
        mock.stop = AsyncMock()
        mock.run = AsyncMock()
        return mock

    async def test_start_creates_components(
        self,
        test_config: Config,
        mock_idle_monitor: MagicMock,
        mock_socket_server: MagicMock,
        mock_slack_handler: MagicMock,
    ) -> None:
        """Test that start creates all components."""
        daemon = Daemon(test_config)

        with patch(
            "claude_permission_daemon.daemon.IdleMonitor",
            return_value=mock_idle_monitor,
        ) as mock_idle_cls, patch(
            "claude_permission_daemon.daemon.SocketServer",
            return_value=mock_socket_server,
        ) as mock_socket_cls, patch(
            "claude_permission_daemon.daemon.SlackHandler",
            return_value=mock_slack_handler,
        ) as mock_slack_cls:
            await daemon.start()

            # Verify components were created
            mock_idle_cls.assert_called_once()
            mock_socket_cls.assert_called_once()
            mock_slack_cls.assert_called_once()

            # Verify components were started
            mock_idle_monitor.start.assert_called_once()
            mock_socket_server.start.assert_called_once()
            mock_slack_handler.start.assert_called_once()

            # Verify tasks were created
            assert len(daemon._tasks) == 3

            # Cleanup
            await daemon.stop()

    async def test_start_registers_idle_callback(
        self,
        test_config: Config,
        mock_idle_monitor: MagicMock,
        mock_socket_server: MagicMock,
        mock_slack_handler: MagicMock,
    ) -> None:
        """Test that start registers idle state callback."""
        daemon = Daemon(test_config)

        with patch(
            "claude_permission_daemon.daemon.IdleMonitor",
            return_value=mock_idle_monitor,
        ), patch(
            "claude_permission_daemon.daemon.SocketServer",
            return_value=mock_socket_server,
        ), patch(
            "claude_permission_daemon.daemon.SlackHandler",
            return_value=mock_slack_handler,
        ):
            await daemon.start()

            # Verify idle callback was registered
            assert len(daemon._state._idle_callbacks) == 1

            await daemon.stop()

    async def test_stop_cancels_tasks(
        self,
        test_config: Config,
        mock_idle_monitor: MagicMock,
        mock_socket_server: MagicMock,
        mock_slack_handler: MagicMock,
    ) -> None:
        """Test that stop cancels all tasks."""
        daemon = Daemon(test_config)

        with patch(
            "claude_permission_daemon.daemon.IdleMonitor",
            return_value=mock_idle_monitor,
        ), patch(
            "claude_permission_daemon.daemon.SocketServer",
            return_value=mock_socket_server,
        ), patch(
            "claude_permission_daemon.daemon.SlackHandler",
            return_value=mock_slack_handler,
        ):
            await daemon.start()
            assert len(daemon._tasks) == 3

            await daemon.stop()

            # Tasks should be cleared
            assert daemon._tasks == []

    async def test_stop_stops_components(
        self,
        test_config: Config,
        mock_idle_monitor: MagicMock,
        mock_socket_server: MagicMock,
        mock_slack_handler: MagicMock,
    ) -> None:
        """Test that stop stops all components."""
        daemon = Daemon(test_config)

        with patch(
            "claude_permission_daemon.daemon.IdleMonitor",
            return_value=mock_idle_monitor,
        ), patch(
            "claude_permission_daemon.daemon.SocketServer",
            return_value=mock_socket_server,
        ), patch(
            "claude_permission_daemon.daemon.SlackHandler",
            return_value=mock_slack_handler,
        ):
            await daemon.start()
            await daemon.stop()

            # Verify components were stopped
            mock_slack_handler.stop.assert_called_once()
            mock_socket_server.stop.assert_called_once()
            mock_idle_monitor.stop.assert_called_once()

    async def test_stop_sends_passthrough_to_pending(
        self,
        test_config: Config,
        mock_idle_monitor: MagicMock,
        mock_socket_server: MagicMock,
        mock_slack_handler: MagicMock,
    ) -> None:
        """Test that stop sends passthrough to pending requests."""
        daemon = Daemon(test_config)

        with patch(
            "claude_permission_daemon.daemon.IdleMonitor",
            return_value=mock_idle_monitor,
        ), patch(
            "claude_permission_daemon.daemon.SocketServer",
            return_value=mock_socket_server,
        ), patch(
            "claude_permission_daemon.daemon.SlackHandler",
            return_value=mock_slack_handler,
        ), patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon.start()

            # Add a pending request
            mock_writer = MagicMock()
            request = PermissionRequest.create("Bash", {"command": "test"})
            pending = PendingRequest(request=request, hook_writer=mock_writer)
            await daemon._state.add_pending_request(pending)

            await daemon.stop()

            # Verify passthrough was sent
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] is mock_writer
            assert call_args[0][1].action == Action.PASSTHROUGH

    async def test_request_shutdown_sets_event(self, test_config: Config) -> None:
        """Test that request_shutdown sets the shutdown event."""
        daemon = Daemon(test_config)
        assert not daemon._shutdown_event.is_set()

        daemon.request_shutdown()

        assert daemon._shutdown_event.is_set()
