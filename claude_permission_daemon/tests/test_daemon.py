"""Unit tests for the daemon module.

Tests the Daemon class and helper functions with mocked components.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.config import Config, DaemonConfig, SlackConfig, SwayidleConfig
from claude_permission_daemon.daemon import Daemon, setup_logging, parse_args
from claude_permission_daemon.state import (
    Action,
    Notification,
    PendingRequest,
    PermissionRequest,
    StateManager,
)


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


class TestDaemonPermissionHandling:
    """Tests for permission request handling."""

    async def test_handle_request_active_user_passthrough(
        self, test_config: Config
    ) -> None:
        """Test that active user gets passthrough immediately."""
        daemon = Daemon(test_config)

        # User is active (default state)
        assert not daemon._state.idle

        mock_reader = MagicMock()
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "echo test"})

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._handle_permission_request(request, mock_reader, mock_writer)

            # Should send passthrough immediately
            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.PASSTHROUGH
            assert "User active" in response.reason

    async def test_handle_request_idle_user_posts_to_slack(
        self, test_config: Config
    ) -> None:
        """Test that idle user gets request posted to Slack."""
        daemon = Daemon(test_config)

        # Set user to idle
        await daemon._state.set_idle(True)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.post_permission_request = AsyncMock(
            return_value=("1234567890.123456", "C12345678")
        )
        daemon._slack_handler = mock_slack_handler

        mock_reader = MagicMock()
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "echo test"})

        await daemon._handle_permission_request(request, mock_reader, mock_writer)

        # Should post to Slack
        mock_slack_handler.post_permission_request.assert_called_once()

        # Should update pending request with Slack info
        pending = await daemon._state.get_pending_request(request.request_id)
        assert pending is not None
        assert pending.slack_message_ts == "1234567890.123456"
        assert pending.slack_channel == "C12345678"

    async def test_handle_request_idle_slack_failure_passthrough(
        self, test_config: Config
    ) -> None:
        """Test that Slack failure results in passthrough."""
        daemon = Daemon(test_config)

        # Set user to idle
        await daemon._state.set_idle(True)

        # Create mock Slack handler that fails
        mock_slack_handler = MagicMock()
        mock_slack_handler.post_permission_request = AsyncMock(return_value=None)
        daemon._slack_handler = mock_slack_handler

        mock_reader = MagicMock()
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "echo test"})

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._handle_permission_request(request, mock_reader, mock_writer)

            # Should send passthrough
            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.PASSTHROUGH
            assert "Failed to post to Slack" in response.reason

    async def test_handle_request_idle_no_slack_handler_passthrough(
        self, test_config: Config
    ) -> None:
        """Test that missing Slack handler results in passthrough."""
        daemon = Daemon(test_config)

        # Set user to idle but no Slack handler
        await daemon._state.set_idle(True)
        daemon._slack_handler = None

        mock_reader = MagicMock()
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "echo test"})

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._handle_permission_request(request, mock_reader, mock_writer)

            # Should send passthrough
            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.PASSTHROUGH
            assert "Slack handler not available" in response.reason

    async def test_resolve_request_approve(self, test_config: Config) -> None:
        """Test resolving a request with approve."""
        daemon = Daemon(test_config)

        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._resolve_request(
                request.request_id, Action.APPROVE, "Test approve"
            )

            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.APPROVE
            assert response.reason == "Test approve"

        # Request should be removed
        assert await daemon._state.get_pending_request(request.request_id) is None

    async def test_resolve_request_deny(self, test_config: Config) -> None:
        """Test resolving a request with deny."""
        daemon = Daemon(test_config)

        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._resolve_request(
                request.request_id, Action.DENY, "Test deny"
            )

            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.DENY
            assert response.reason == "Test deny"

    async def test_resolve_request_unknown_id_no_error(
        self, test_config: Config
    ) -> None:
        """Test resolving unknown request doesn't raise error."""
        daemon = Daemon(test_config)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            # Should not raise
            await daemon._resolve_request(
                "unknown-id", Action.APPROVE, "Test"
            )

            # Should not call send_response
            mock_send.assert_not_called()


class TestDaemonSlackActionHandling:
    """Tests for Slack action handling."""

    async def test_handle_slack_action_approve(self, test_config: Config) -> None:
        """Test handling Slack approve action."""
        daemon = Daemon(test_config)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.update_message_approved = AsyncMock()
        daemon._slack_handler = mock_slack_handler

        # Add pending request with Slack info
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(
            request=request,
            hook_writer=mock_writer,
            slack_message_ts="1234567890.123456",
            slack_channel="C12345678",
        )
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._handle_slack_action(request.request_id, Action.APPROVE)

            # Should update Slack message
            mock_slack_handler.update_message_approved.assert_called_once_with(
                channel="C12345678",
                message_ts="1234567890.123456",
                request=request,
            )

            # Should send approve response
            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.APPROVE
            assert "Approved via Slack" in response.reason

    async def test_handle_slack_action_deny(self, test_config: Config) -> None:
        """Test handling Slack deny action."""
        daemon = Daemon(test_config)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.update_message_denied = AsyncMock()
        daemon._slack_handler = mock_slack_handler

        # Add pending request with Slack info
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "rm -rf /"})
        pending = PendingRequest(
            request=request,
            hook_writer=mock_writer,
            slack_message_ts="1234567890.123456",
            slack_channel="C12345678",
        )
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._handle_slack_action(request.request_id, Action.DENY)

            # Should update Slack message
            mock_slack_handler.update_message_denied.assert_called_once_with(
                channel="C12345678",
                message_ts="1234567890.123456",
                request=request,
            )

            # Should send deny response
            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.DENY
            assert "Denied via Slack" in response.reason

    async def test_handle_slack_action_unknown_request(
        self, test_config: Config
    ) -> None:
        """Test handling Slack action for unknown request."""
        daemon = Daemon(test_config)

        # No pending request with this ID
        await daemon._handle_slack_action("unknown-id", Action.APPROVE)

        # Should not raise - just log warning

    async def test_handle_slack_action_no_slack_info(
        self, test_config: Config
    ) -> None:
        """Test handling Slack action when request has no Slack info."""
        daemon = Daemon(test_config)
        daemon._slack_handler = MagicMock()

        # Add pending request without Slack info
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(
            request=request,
            hook_writer=mock_writer,
            # No slack_message_ts or slack_channel
        )
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            await daemon._handle_slack_action(request.request_id, Action.APPROVE)

            # Should still send response
            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.APPROVE


class TestDaemonIdleStateChange:
    """Tests for idle state change handling (race condition logic)."""

    async def test_on_idle_change_to_idle_does_nothing(
        self, test_config: Config
    ) -> None:
        """Test that going idle doesn't resolve pending requests."""
        daemon = Daemon(test_config)

        # Add a pending request
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            # Go idle
            await daemon._on_idle_change(True)

            # Should not send any response
            mock_send.assert_not_called()

            # Request should still be pending
            assert await daemon._state.get_pending_request(request.request_id) is not None

    async def test_on_idle_change_to_active_resolves_pending(
        self, test_config: Config
    ) -> None:
        """Test that becoming active resolves pending requests with passthrough."""
        daemon = Daemon(test_config)

        # Add a pending request (no Slack info - just tracked)
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            # Become active
            await daemon._on_idle_change(False)

            # Should send passthrough
            mock_send.assert_called_once()
            response = mock_send.call_args[0][1]
            assert response.action == Action.PASSTHROUGH
            assert "User active" in response.reason

    async def test_on_idle_change_to_active_updates_slack_message(
        self, test_config: Config
    ) -> None:
        """Test that becoming active updates Slack message to 'answered locally'."""
        daemon = Daemon(test_config)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.update_message_answered_locally = AsyncMock()
        daemon._slack_handler = mock_slack_handler

        # Add pending request with Slack info
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(
            request=request,
            hook_writer=mock_writer,
            slack_message_ts="1234567890.123456",
            slack_channel="C12345678",
        )
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ):
            # Become active
            await daemon._on_idle_change(False)

            # Should update Slack message
            mock_slack_handler.update_message_answered_locally.assert_called_once_with(
                channel="C12345678",
                message_ts="1234567890.123456",
                request=request,
            )

    async def test_on_idle_change_to_active_multiple_pending(
        self, test_config: Config
    ) -> None:
        """Test that becoming active resolves all pending requests."""
        daemon = Daemon(test_config)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.update_message_answered_locally = AsyncMock()
        daemon._slack_handler = mock_slack_handler

        # Add multiple pending requests
        requests = []
        for i in range(3):
            mock_writer = MagicMock()
            request = PermissionRequest.create(f"Tool{i}", {})
            pending = PendingRequest(
                request=request,
                hook_writer=mock_writer,
                slack_message_ts=f"123456789{i}.123456",
                slack_channel="C12345678",
            )
            await daemon._state.add_pending_request(pending)
            requests.append(request)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            # Become active
            await daemon._on_idle_change(False)

            # Should send passthrough for all 3
            assert mock_send.call_count == 3

            # Should update Slack for all 3
            assert mock_slack_handler.update_message_answered_locally.call_count == 3

    async def test_on_idle_change_to_active_no_pending(
        self, test_config: Config
    ) -> None:
        """Test that becoming active with no pending requests is fine."""
        daemon = Daemon(test_config)

        # No pending requests
        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ) as mock_send:
            # Become active - should not raise
            await daemon._on_idle_change(False)

            # Should not send any response
            mock_send.assert_not_called()


class TestConnectionMonitoring:
    """Tests for connection monitoring (answered remotely) functionality."""

    async def test_handle_answered_remotely_updates_slack(
        self, test_config: Config
    ) -> None:
        """Test that answered remotely updates Slack message."""
        daemon = Daemon(test_config)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.update_message_answered_remotely = AsyncMock()
        daemon._slack_handler = mock_slack_handler

        # Add pending request with Slack info
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(
            request=request,
            hook_writer=mock_writer,
            slack_message_ts="1234567890.123456",
            slack_channel="C12345678",
        )
        await daemon._state.add_pending_request(pending)

        # Handle as answered remotely
        await daemon._handle_answered_remotely(request.request_id)

        # Should update Slack message
        mock_slack_handler.update_message_answered_remotely.assert_called_once_with(
            channel="C12345678",
            message_ts="1234567890.123456",
            request=request,
        )

        # Should be removed from pending
        remaining = await daemon._state.get_pending_request(request.request_id)
        assert remaining is None

    async def test_handle_answered_remotely_already_resolved(
        self, test_config: Config
    ) -> None:
        """Test that answered remotely handles already-resolved request gracefully."""
        daemon = Daemon(test_config)

        # No pending request - should not raise
        await daemon._handle_answered_remotely("nonexistent-id")

    async def test_resolve_request_cancels_monitor_task(
        self, test_config: Config
    ) -> None:
        """Test that resolving a request cancels its monitor task."""
        daemon = Daemon(test_config)

        # Add pending request with a monitor task
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "test"})

        # Create a mock task that can be cancelled
        async def dummy_task():
            await asyncio.sleep(100)

        task = asyncio.create_task(dummy_task())

        pending = PendingRequest(
            request=request,
            hook_writer=mock_writer,
            monitor_task=task,
        )
        await daemon._state.add_pending_request(pending)

        with patch(
            "claude_permission_daemon.daemon.send_response",
            new_callable=AsyncMock,
        ):
            await daemon._resolve_request(
                request.request_id, Action.APPROVE, "Test"
            )

        # Task should be cancelled
        assert task.cancelled()

    async def test_request_posted_to_slack_starts_monitor(
        self, test_config: Config
    ) -> None:
        """Test that posting to Slack starts a connection monitor."""
        daemon = Daemon(test_config)

        # Set user to idle
        await daemon._state.set_idle(True)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.post_permission_request = AsyncMock(
            return_value=("1234567890.123456", "C12345678")
        )
        daemon._slack_handler = mock_slack_handler

        # Create a mock reader that blocks on read (simulating open connection)
        mock_reader = AsyncMock()

        async def slow_read(n):
            await asyncio.sleep(100)  # Block "forever"
            return b""

        mock_reader.read = slow_read
        mock_writer = MagicMock()
        request = PermissionRequest.create("Bash", {"command": "echo test"})

        await daemon._handle_permission_request(request, mock_reader, mock_writer)

        # Give the monitor task a moment to start
        await asyncio.sleep(0.1)

        # Should have a monitor task
        pending = await daemon._state.get_pending_request(request.request_id)
        assert pending is not None
        assert pending.monitor_task is not None
        assert not pending.monitor_task.done()

        # Clean up
        pending.monitor_task.cancel()
        try:
            await pending.monitor_task
        except asyncio.CancelledError:
            pass


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_setup_logging_default(self) -> None:
        """Test setup_logging with default (INFO level)."""
        import logging

        # Clear any existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging(debug=False)

        assert root_logger.level == logging.INFO

    def test_setup_logging_debug(self) -> None:
        """Test setup_logging with debug mode."""
        import logging

        # Clear any existing handlers
        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        setup_logging(debug=True)

        assert root_logger.level == logging.DEBUG

    def test_setup_logging_reduces_third_party_noise(self) -> None:
        """Test that setup_logging sets third-party loggers to WARNING."""
        import logging

        setup_logging(debug=False)

        slack_bolt_logger = logging.getLogger("slack_bolt")
        slack_sdk_logger = logging.getLogger("slack_sdk")

        assert slack_bolt_logger.level == logging.WARNING
        assert slack_sdk_logger.level == logging.WARNING

    def test_parse_args_defaults(self) -> None:
        """Test parse_args with no arguments."""
        import sys
        from claude_permission_daemon.config import DEFAULT_CONFIG_PATH

        original_argv = sys.argv
        sys.argv = ["claude-permission-daemon"]
        try:
            args = parse_args()
            assert args.config == DEFAULT_CONFIG_PATH
            assert args.debug is False
        finally:
            sys.argv = original_argv

    def test_parse_args_config_short(self) -> None:
        """Test parse_args with -c config option."""
        import sys
        from pathlib import Path

        original_argv = sys.argv
        sys.argv = ["claude-permission-daemon", "-c", "/custom/config.toml"]
        try:
            args = parse_args()
            assert args.config == Path("/custom/config.toml")
        finally:
            sys.argv = original_argv

    def test_parse_args_config_long(self) -> None:
        """Test parse_args with --config option."""
        import sys
        from pathlib import Path

        original_argv = sys.argv
        sys.argv = ["claude-permission-daemon", "--config", "/other/config.toml"]
        try:
            args = parse_args()
            assert args.config == Path("/other/config.toml")
        finally:
            sys.argv = original_argv

    def test_parse_args_debug_short(self) -> None:
        """Test parse_args with -d debug option."""
        import sys

        original_argv = sys.argv
        sys.argv = ["claude-permission-daemon", "-d"]
        try:
            args = parse_args()
            assert args.debug is True
        finally:
            sys.argv = original_argv

    def test_parse_args_debug_long(self) -> None:
        """Test parse_args with --debug option."""
        import sys

        original_argv = sys.argv
        sys.argv = ["claude-permission-daemon", "--debug"]
        try:
            args = parse_args()
            assert args.debug is True
        finally:
            sys.argv = original_argv

    def test_parse_args_combined(self) -> None:
        """Test parse_args with multiple options."""
        import sys
        from pathlib import Path

        original_argv = sys.argv
        sys.argv = ["claude-permission-daemon", "-d", "-c", "/test/config.toml"]
        try:
            args = parse_args()
            assert args.debug is True
            assert args.config == Path("/test/config.toml")
        finally:
            sys.argv = original_argv


class TestDaemonNotificationHandling:
    """Tests for notification handling."""

    async def test_handle_notification_active_user_not_sent(
        self, test_config: Config
    ) -> None:
        """Test that active user doesn't get notification sent to Slack."""
        daemon = Daemon(test_config)

        # User is active (default state)
        assert not daemon._state.idle

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.post_notification = AsyncMock(return_value=True)
        daemon._slack_handler = mock_slack_handler

        notification = Notification.create(
            message="Claude is waiting for input",
            notification_type="idle_prompt",
        )

        await daemon._handle_notification(notification)

        # Should NOT post to Slack when active
        mock_slack_handler.post_notification.assert_not_called()

    async def test_handle_notification_idle_user_sent_to_slack(
        self, test_config: Config
    ) -> None:
        """Test that idle user gets notification sent to Slack."""
        daemon = Daemon(test_config)

        # Set user to idle
        await daemon._state.set_idle(True)

        # Create mock Slack handler
        mock_slack_handler = MagicMock()
        mock_slack_handler.post_notification = AsyncMock(return_value=True)
        daemon._slack_handler = mock_slack_handler

        notification = Notification.create(
            message="Claude is waiting for input",
            notification_type="idle_prompt",
            cwd="/home/user/project",
        )

        await daemon._handle_notification(notification)

        # Should post to Slack
        mock_slack_handler.post_notification.assert_called_once_with(notification)

    async def test_handle_notification_idle_no_slack_handler(
        self, test_config: Config
    ) -> None:
        """Test that missing Slack handler doesn't raise error."""
        daemon = Daemon(test_config)

        # Set user to idle but no Slack handler
        await daemon._state.set_idle(True)
        daemon._slack_handler = None

        notification = Notification.create(
            message="Test notification",
            notification_type="idle_prompt",
        )

        # Should not raise
        await daemon._handle_notification(notification)

    async def test_handle_notification_slack_failure_logged(
        self, test_config: Config
    ) -> None:
        """Test that Slack failure is handled gracefully."""
        daemon = Daemon(test_config)

        # Set user to idle
        await daemon._state.set_idle(True)

        # Create mock Slack handler that fails
        mock_slack_handler = MagicMock()
        mock_slack_handler.post_notification = AsyncMock(return_value=False)
        daemon._slack_handler = mock_slack_handler

        notification = Notification.create(
            message="Test notification",
            notification_type="idle_prompt",
        )

        # Should not raise despite failure
        await daemon._handle_notification(notification)

        # Should have tried to post
        mock_slack_handler.post_notification.assert_called_once()

    async def test_socket_server_created_with_notification_handler(
        self,
        test_config: Config,
    ) -> None:
        """Test that socket server is created with notification handler."""
        daemon = Daemon(test_config)

        mock_idle_monitor = MagicMock()
        mock_idle_monitor.start = AsyncMock()
        mock_idle_monitor.stop = AsyncMock()
        mock_idle_monitor.run = AsyncMock()

        mock_socket_server = MagicMock()
        mock_socket_server.start = AsyncMock()
        mock_socket_server.stop = AsyncMock()
        mock_socket_server.run = AsyncMock()

        mock_slack_handler = MagicMock()
        mock_slack_handler.start = AsyncMock()
        mock_slack_handler.stop = AsyncMock()
        mock_slack_handler.run = AsyncMock()

        with patch(
            "claude_permission_daemon.daemon.IdleMonitor",
            return_value=mock_idle_monitor,
        ), patch(
            "claude_permission_daemon.daemon.SocketServer",
            return_value=mock_socket_server,
        ) as mock_socket_cls, patch(
            "claude_permission_daemon.daemon.SlackHandler",
            return_value=mock_slack_handler,
        ):
            await daemon.start()

            # Verify SocketServer was created with on_notification callback
            mock_socket_cls.assert_called_once()
            call_kwargs = mock_socket_cls.call_args[1]
            assert "on_notification" in call_kwargs
            assert call_kwargs["on_notification"] == daemon._handle_notification

            await daemon.stop()
