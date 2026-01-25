"""Tests for state module."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.state import (
    Action,
    MessageType,
    Notification,
    PendingRequest,
    PermissionRequest,
    PermissionResponse,
    StateManager,
)


class TestAction:
    """Tests for Action enum."""

    def test_values(self) -> None:
        """Test enum values match expected strings."""
        assert Action.APPROVE.value == "approve"
        assert Action.DENY.value == "deny"
        assert Action.PASSTHROUGH.value == "passthrough"


class TestMessageType:
    """Tests for MessageType enum."""

    def test_values(self) -> None:
        """Test enum values match expected strings."""
        assert MessageType.PERMISSION_REQUEST.value == "permission_request"
        assert MessageType.NOTIFICATION.value == "notification"


class TestPermissionRequest:
    """Tests for PermissionRequest dataclass."""

    def test_create_generates_id(self) -> None:
        """Test create() generates unique request_id."""
        req1 = PermissionRequest.create("Bash", {"command": "ls"})
        req2 = PermissionRequest.create("Bash", {"command": "ls"})

        assert req1.request_id != req2.request_id
        assert len(req1.request_id) == 36  # UUID format

    def test_create_sets_timestamp(self) -> None:
        """Test create() sets timestamp to current time."""
        before = datetime.now(UTC)
        req = PermissionRequest.create("Bash", {"command": "ls"})
        after = datetime.now(UTC)

        assert before <= req.timestamp <= after

    def test_stores_tool_info(self) -> None:
        """Test tool_name and tool_input are stored."""
        req = PermissionRequest.create(
            "Write",
            {"file_path": "/tmp/test.txt", "content": "hello"},
        )

        assert req.tool_name == "Write"
        assert req.tool_input["file_path"] == "/tmp/test.txt"
        assert req.tool_input["content"] == "hello"


class TestNotification:
    """Tests for Notification dataclass."""

    def test_create_generates_id(self) -> None:
        """Test create() generates unique notification_id."""
        notif1 = Notification.create("Test message", "idle_prompt")
        notif2 = Notification.create("Test message", "idle_prompt")

        assert notif1.notification_id != notif2.notification_id
        assert len(notif1.notification_id) == 36  # UUID format

    def test_create_sets_timestamp(self) -> None:
        """Test create() sets timestamp to current time."""
        before = datetime.now(UTC)
        notif = Notification.create("Test message", "idle_prompt")
        after = datetime.now(UTC)

        assert before <= notif.timestamp <= after

    def test_stores_notification_info(self) -> None:
        """Test message and notification_type are stored."""
        notif = Notification.create(
            message="Claude is waiting for input",
            notification_type="idle_prompt",
            cwd="/home/user/project",
        )

        assert notif.message == "Claude is waiting for input"
        assert notif.notification_type == "idle_prompt"
        assert notif.cwd == "/home/user/project"

    def test_cwd_optional(self) -> None:
        """Test cwd defaults to None."""
        notif = Notification.create("Test", "test_type")
        assert notif.cwd is None


class TestPermissionResponse:
    """Tests for PermissionResponse dataclass."""

    def test_to_dict_approve(self) -> None:
        """Test to_dict() for approve action."""
        resp = PermissionResponse(Action.APPROVE, "Approved via Slack")
        d = resp.to_dict()

        assert d["action"] == "approve"
        assert d["reason"] == "Approved via Slack"

    def test_to_dict_deny(self) -> None:
        """Test to_dict() for deny action."""
        resp = PermissionResponse(Action.DENY, "Denied via Slack")
        d = resp.to_dict()

        assert d["action"] == "deny"
        assert d["reason"] == "Denied via Slack"

    def test_to_dict_passthrough(self) -> None:
        """Test to_dict() for passthrough action."""
        resp = PermissionResponse(Action.PASSTHROUGH, "User active locally")
        d = resp.to_dict()

        assert d["action"] == "passthrough"
        assert d["reason"] == "User active locally"


class TestPendingRequest:
    """Tests for PendingRequest dataclass."""

    def test_request_id_property(self) -> None:
        """Test request_id property delegates to request."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        req = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=req, hook_writer=mock_writer)

        assert pending.request_id == req.request_id

    def test_slack_info_optional(self) -> None:
        """Test Slack info fields default to None."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        req = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=req, hook_writer=mock_writer)

        assert pending.slack_message_ts is None
        assert pending.slack_channel is None


class TestStateManager:
    """Tests for StateManager class."""

    @pytest.fixture
    def state_manager(self) -> StateManager:
        """Create a fresh StateManager for each test."""
        return StateManager()

    @pytest.fixture
    def mock_pending_request(self) -> PendingRequest:
        """Create a mock PendingRequest."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        req = PermissionRequest.create("Bash", {"command": "test"})
        return PendingRequest(request=req, hook_writer=mock_writer)

    async def test_initial_idle_state(self, state_manager: StateManager) -> None:
        """Test initial idle state is False."""
        assert state_manager.idle is False

    async def test_set_idle_true(self, state_manager: StateManager) -> None:
        """Test setting idle to True."""
        await state_manager.set_idle(True)
        assert state_manager.idle is True

    async def test_set_idle_false(self, state_manager: StateManager) -> None:
        """Test setting idle to False."""
        await state_manager.set_idle(True)
        await state_manager.set_idle(False)
        assert state_manager.idle is False

    async def test_set_idle_no_change_no_callback(
        self, state_manager: StateManager
    ) -> None:
        """Test callback not called when idle state doesn't change."""
        callback = AsyncMock()
        state_manager.register_idle_callback(callback)

        # Set to False when already False - no callback
        await state_manager.set_idle(False)
        callback.assert_not_called()

    async def test_idle_callback_called_on_change(
        self, state_manager: StateManager
    ) -> None:
        """Test callback is called when idle state changes."""
        callback = AsyncMock()
        state_manager.register_idle_callback(callback)

        await state_manager.set_idle(True)
        callback.assert_called_once_with(True)

        callback.reset_mock()
        await state_manager.set_idle(False)
        callback.assert_called_once_with(False)

    async def test_multiple_callbacks(self, state_manager: StateManager) -> None:
        """Test multiple callbacks are all called."""
        callback1 = AsyncMock()
        callback2 = AsyncMock()

        state_manager.register_idle_callback(callback1)
        state_manager.register_idle_callback(callback2)

        await state_manager.set_idle(True)

        callback1.assert_called_once_with(True)
        callback2.assert_called_once_with(True)

    async def test_callback_exception_doesnt_break_others(
        self, state_manager: StateManager
    ) -> None:
        """Test that one callback raising doesn't prevent others."""
        callback1 = AsyncMock(side_effect=Exception("test error"))
        callback2 = AsyncMock()

        state_manager.register_idle_callback(callback1)
        state_manager.register_idle_callback(callback2)

        await state_manager.set_idle(True)

        # callback2 should still be called despite callback1 raising
        callback2.assert_called_once_with(True)

    async def test_add_and_get_pending_request(
        self, state_manager: StateManager, mock_pending_request: PendingRequest
    ) -> None:
        """Test adding and retrieving a pending request."""
        await state_manager.add_pending_request(mock_pending_request)

        retrieved = await state_manager.get_pending_request(
            mock_pending_request.request_id
        )
        assert retrieved is mock_pending_request

    async def test_get_nonexistent_request(self, state_manager: StateManager) -> None:
        """Test getting a nonexistent request returns None."""
        result = await state_manager.get_pending_request("nonexistent-id")
        assert result is None

    async def test_remove_pending_request(
        self, state_manager: StateManager, mock_pending_request: PendingRequest
    ) -> None:
        """Test removing a pending request."""
        await state_manager.add_pending_request(mock_pending_request)

        removed = await state_manager.remove_pending_request(
            mock_pending_request.request_id
        )
        assert removed is mock_pending_request

        # Should no longer exist
        retrieved = await state_manager.get_pending_request(
            mock_pending_request.request_id
        )
        assert retrieved is None

    async def test_remove_nonexistent_request(
        self, state_manager: StateManager
    ) -> None:
        """Test removing nonexistent request returns None."""
        result = await state_manager.remove_pending_request("nonexistent-id")
        assert result is None

    async def test_get_all_pending_requests(
        self, state_manager: StateManager
    ) -> None:
        """Test getting all pending requests."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)

        req1 = PermissionRequest.create("Bash", {"command": "cmd1"})
        req2 = PermissionRequest.create("Write", {"file_path": "/tmp/test"})

        pending1 = PendingRequest(request=req1, hook_writer=mock_writer)
        pending2 = PendingRequest(request=req2, hook_writer=mock_writer)

        await state_manager.add_pending_request(pending1)
        await state_manager.add_pending_request(pending2)

        all_pending = await state_manager.get_all_pending_requests()
        assert len(all_pending) == 2
        assert pending1 in all_pending
        assert pending2 in all_pending

    async def test_update_slack_info(
        self, state_manager: StateManager, mock_pending_request: PendingRequest
    ) -> None:
        """Test updating Slack message info."""
        await state_manager.add_pending_request(mock_pending_request)

        await state_manager.update_slack_info(
            mock_pending_request.request_id,
            message_ts="1234567890.123456",
            channel="C12345678",
        )

        pending = await state_manager.get_pending_request(
            mock_pending_request.request_id
        )
        assert pending is not None
        assert pending.slack_message_ts == "1234567890.123456"
        assert pending.slack_channel == "C12345678"

    async def test_update_slack_info_nonexistent(
        self, state_manager: StateManager
    ) -> None:
        """Test updating Slack info for nonexistent request does nothing."""
        # Should not raise
        await state_manager.update_slack_info(
            "nonexistent-id",
            message_ts="1234567890.123456",
            channel="C12345678",
        )

    async def test_set_monitor_task(
        self, state_manager: StateManager, mock_pending_request: PendingRequest
    ) -> None:
        """Test setting monitor task for a pending request."""
        await state_manager.add_pending_request(mock_pending_request)

        mock_task = MagicMock(spec=asyncio.Task)
        await state_manager.set_monitor_task(
            mock_pending_request.request_id,
            mock_task,
        )

        pending = await state_manager.get_pending_request(
            mock_pending_request.request_id
        )
        assert pending is not None
        assert pending.monitor_task is mock_task

    async def test_set_monitor_task_nonexistent(
        self, state_manager: StateManager
    ) -> None:
        """Test setting monitor task for nonexistent request does nothing."""
        mock_task = MagicMock(spec=asyncio.Task)
        # Should not raise
        await state_manager.set_monitor_task("nonexistent-id", mock_task)

    async def test_clear_all_pending(self, state_manager: StateManager) -> None:
        """Test clearing all pending requests."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)

        req1 = PermissionRequest.create("Bash", {"command": "cmd1"})
        req2 = PermissionRequest.create("Write", {"file_path": "/tmp/test"})

        pending1 = PendingRequest(request=req1, hook_writer=mock_writer)
        pending2 = PendingRequest(request=req2, hook_writer=mock_writer)

        await state_manager.add_pending_request(pending1)
        await state_manager.add_pending_request(pending2)

        cleared = await state_manager.clear_all_pending()
        assert len(cleared) == 2

        # All should be gone
        all_pending = await state_manager.get_all_pending_requests()
        assert len(all_pending) == 0

    async def test_idle_since_initial(self, state_manager: StateManager) -> None:
        """Test idle_since is set on initialization."""
        # Should be close to now
        now = datetime.now(UTC)
        assert (now - state_manager.idle_since).total_seconds() < 1

    async def test_idle_since_updates_on_state_change(
        self, state_manager: StateManager
    ) -> None:
        """Test idle_since updates when state changes."""
        initial_since = state_manager.idle_since

        # Small delay to ensure time difference
        await asyncio.sleep(0.01)

        await state_manager.set_idle(True)
        assert state_manager.idle_since > initial_since

        idle_since = state_manager.idle_since
        await asyncio.sleep(0.01)

        await state_manager.set_idle(False)
        assert state_manager.idle_since > idle_since

    async def test_idle_since_unchanged_when_state_unchanged(
        self, state_manager: StateManager
    ) -> None:
        """Test idle_since doesn't change when setting same state."""
        await state_manager.set_idle(True)
        idle_since = state_manager.idle_since

        await asyncio.sleep(0.01)
        await state_manager.set_idle(True)  # Same state

        assert state_manager.idle_since == idle_since

    async def test_state_duration_seconds(self, state_manager: StateManager) -> None:
        """Test state_duration_seconds returns time since last change."""
        # Wait a bit
        await asyncio.sleep(0.05)
        duration = state_manager.state_duration_seconds
        assert duration >= 0.05

    async def test_get_state_description_seconds(
        self, state_manager: StateManager
    ) -> None:
        """Test get_state_description for short durations."""
        # Mock the datetime to control duration
        fixed_time = datetime.now(UTC)
        with patch.object(
            state_manager, "_idle_since", fixed_time - timedelta(seconds=30)
        ):
            desc = state_manager.get_state_description()
            assert "active for 30s" in desc

    async def test_get_state_description_minutes(
        self, state_manager: StateManager
    ) -> None:
        """Test get_state_description for minute durations."""
        fixed_time = datetime.now(UTC)
        with patch.object(
            state_manager, "_idle_since", fixed_time - timedelta(minutes=5, seconds=30)
        ):
            desc = state_manager.get_state_description()
            assert "active for 5m 30s" in desc

    async def test_get_state_description_hours(
        self, state_manager: StateManager
    ) -> None:
        """Test get_state_description for hour durations."""
        fixed_time = datetime.now(UTC)
        with patch.object(
            state_manager, "_idle_since", fixed_time - timedelta(hours=2, minutes=15)
        ):
            desc = state_manager.get_state_description()
            assert "active for 2h 15m" in desc

    async def test_get_state_description_idle_state(
        self, state_manager: StateManager
    ) -> None:
        """Test get_state_description shows 'idle' when idle."""
        await state_manager.set_idle(True)
        fixed_time = datetime.now(UTC)
        with patch.object(
            state_manager, "_idle_since", fixed_time - timedelta(seconds=45)
        ):
            desc = state_manager.get_state_description()
            assert "idle for 45s" in desc
