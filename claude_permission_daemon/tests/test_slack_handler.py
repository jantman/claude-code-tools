"""Tests for slack_handler module."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.config import SlackConfig
from claude_permission_daemon.slack_handler import (
    NOTIFICATION_TYPE_EMOJI,
    SlackHandler,
    format_answered_locally,
    format_approved,
    format_denied,
    format_notification,
    format_permission_request,
    to_local_time,
)
from claude_permission_daemon.state import (
    Action,
    Notification,
    PendingRequest,
    PermissionRequest,
)


class TestFormatPermissionRequest:
    """Tests for format_permission_request function."""

    def test_bash_command(self) -> None:
        """Test formatting a Bash command request."""
        request = PermissionRequest(
            request_id="test-id-123",
            tool_name="Bash",
            tool_input={"command": "npm install lodash"},
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_permission_request(request)

        assert len(blocks) >= 4
        # Check header
        assert blocks[0]["type"] == "header"
        assert "Permission Request" in blocks[0]["text"]["text"]
        # Check tool name section
        assert "Bash" in blocks[1]["text"]["text"]
        # Check command in code block
        assert "npm install lodash" in blocks[2]["text"]["text"]
        # Check buttons
        actions_block = blocks[-1]
        assert actions_block["type"] == "actions"
        assert len(actions_block["elements"]) == 2
        assert actions_block["elements"][0]["action_id"] == "approve_permission"
        assert actions_block["elements"][1]["action_id"] == "deny_permission"
        # Check request_id in button values
        assert actions_block["elements"][0]["value"] == "test-id-123"
        assert actions_block["elements"][1]["value"] == "test-id-123"

    def test_file_operation(self) -> None:
        """Test formatting a file write request."""
        request = PermissionRequest(
            request_id="test-id-456",
            tool_name="Write",
            tool_input={
                "file_path": "/tmp/test.txt",
                "content": "Hello, world!",
            },
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_permission_request(request)

        # Should contain file path and content
        input_text = blocks[2]["text"]["text"]
        assert "/tmp/test.txt" in input_text
        assert "Hello, world!" in input_text

    def test_with_description(self) -> None:
        """Test formatting request with description."""
        request = PermissionRequest(
            request_id="test-id-789",
            tool_name="Bash",
            tool_input={
                "command": "echo test",
                "description": "Run a test command",
            },
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_permission_request(request)

        # Find description section
        description_found = False
        for block in blocks:
            if block.get("type") == "section":
                text = block.get("text", {}).get("text", "")
                if "Description" in text:
                    assert "Run a test command" in text
                    description_found = True
                    break

        assert description_found

    def test_long_content_truncated(self) -> None:
        """Test that long content is truncated."""
        long_content = "x" * 1000
        request = PermissionRequest(
            request_id="test-id",
            tool_name="Write",
            tool_input={
                "file_path": "/tmp/test.txt",
                "content": long_content,
            },
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_permission_request(request)
        input_text = blocks[2]["text"]["text"]

        # Should be truncated
        assert len(input_text) < 1000
        assert "..." in input_text


class TestFormatApproved:
    """Tests for format_approved function."""

    def test_approved_message(self) -> None:
        """Test approved message formatting."""
        request = PermissionRequest(
            request_id="test-id",
            tool_name="Bash",
            tool_input={"command": "echo test"},
            timestamp=datetime.now(UTC),
        )

        blocks = format_approved(request)

        assert len(blocks) >= 2
        # Check header shows approved
        assert blocks[0]["type"] == "header"
        assert "Approved" in blocks[0]["text"]["text"]
        assert "Bash" in blocks[0]["text"]["text"]
        # Check context shows approved via Slack
        context_block = blocks[-1]
        assert context_block["type"] == "context"
        assert "Approved via Slack" in context_block["elements"][0]["text"]


class TestFormatDenied:
    """Tests for format_denied function."""

    def test_denied_message(self) -> None:
        """Test denied message formatting."""
        request = PermissionRequest(
            request_id="test-id",
            tool_name="Bash",
            tool_input={"command": "rm -rf /"},
            timestamp=datetime.now(UTC),
        )

        blocks = format_denied(request)

        assert len(blocks) >= 2
        # Check header shows denied
        assert blocks[0]["type"] == "header"
        assert "Denied" in blocks[0]["text"]["text"]
        assert "Bash" in blocks[0]["text"]["text"]
        # Check context
        context_block = blocks[-1]
        assert "Denied via Slack" in context_block["elements"][0]["text"]


class TestFormatAnsweredLocally:
    """Tests for format_answered_locally function."""

    def test_answered_locally_message(self) -> None:
        """Test answered locally message formatting."""
        request = PermissionRequest(
            request_id="test-id",
            tool_name="Bash",
            tool_input={"command": "ls -la"},
            timestamp=datetime.now(UTC),
        )

        blocks = format_answered_locally(request)

        assert len(blocks) >= 2
        # Check header shows answered locally
        assert blocks[0]["type"] == "header"
        assert "Answered Locally" in blocks[0]["text"]["text"]
        # Check context
        context_block = blocks[-1]
        assert "returned to your computer" in context_block["elements"][0]["text"]


class TestSlackHandler:
    """Tests for SlackHandler class."""

    @pytest.fixture
    def config(self) -> SlackConfig:
        """Provide Slack config."""
        return SlackConfig(
            bot_token="xoxb-test-token",
            app_token="xapp-test-token",
            channel="C12345678",
        )

    @pytest.fixture
    def action_callback(self) -> AsyncMock:
        """Provide mock action callback."""
        return AsyncMock()

    @pytest.fixture
    def handler(
        self, config: SlackConfig, action_callback: AsyncMock
    ) -> SlackHandler:
        """Create SlackHandler instance."""
        return SlackHandler(config=config, on_action=action_callback)

    def test_initial_state(self, handler: SlackHandler) -> None:
        """Test initial state."""
        assert handler.running is False

    async def test_start_already_running(self, handler: SlackHandler) -> None:
        """Test start when already running does nothing."""
        handler._running = True
        await handler.start()  # Should not raise

    async def test_stop_not_running(self, handler: SlackHandler) -> None:
        """Test stop when not running does nothing."""
        await handler.stop()  # Should not raise

    async def test_run_without_start(self, handler: SlackHandler) -> None:
        """Test run raises if not started."""
        with pytest.raises(RuntimeError, match="not started"):
            await handler.run()

    async def test_post_without_app(self, handler: SlackHandler) -> None:
        """Test posting without app connected returns None."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)

        result = await handler.post_permission_request(pending)
        assert result is None

    async def test_handle_approve(
        self, handler: SlackHandler, action_callback: AsyncMock
    ) -> None:
        """Test approve action handler."""
        ack = AsyncMock()
        body = {
            "actions": [{"value": "request-123"}],
        }

        await handler._handle_approve(ack, body)

        ack.assert_called_once()
        action_callback.assert_called_once_with("request-123", Action.APPROVE)

    async def test_handle_deny(
        self, handler: SlackHandler, action_callback: AsyncMock
    ) -> None:
        """Test deny action handler."""
        ack = AsyncMock()
        body = {
            "actions": [{"value": "request-456"}],
        }

        await handler._handle_deny(ack, body)

        ack.assert_called_once()
        action_callback.assert_called_once_with("request-456", Action.DENY)


class TestSlackHandlerWithMockedApp:
    """Tests for SlackHandler with mocked Slack app."""

    @pytest.fixture
    def config(self) -> SlackConfig:
        """Provide Slack config."""
        return SlackConfig(
            bot_token="xoxb-test-token",
            app_token="xapp-test-token",
            channel="C12345678",
        )

    async def test_post_permission_request_success(
        self, config: SlackConfig
    ) -> None:
        """Test successful permission request posting."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        # Mock the app and client
        mock_client = AsyncMock()
        mock_client.chat_postMessage.return_value = {
            "ts": "1234567890.123456",
            "channel": "C12345678",
        }

        mock_app = MagicMock()
        mock_app.client = mock_client
        handler._app = mock_app

        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        request = PermissionRequest.create("Bash", {"command": "echo test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)

        result = await handler.post_permission_request(pending)

        assert result is not None
        message_ts, channel = result
        assert message_ts == "1234567890.123456"
        assert channel == "C12345678"

        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "C12345678"
        assert "blocks" in call_kwargs

    async def test_post_permission_request_failure(
        self, config: SlackConfig
    ) -> None:
        """Test permission request posting failure."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        # Mock the app and client to raise
        mock_client = AsyncMock()
        mock_client.chat_postMessage.side_effect = Exception("API error")

        mock_app = MagicMock()
        mock_app.client = mock_client
        handler._app = mock_app

        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)

        result = await handler.post_permission_request(pending)
        assert result is None

    async def test_update_message_approved(self, config: SlackConfig) -> None:
        """Test updating message to approved."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        mock_client = AsyncMock()
        mock_app = MagicMock()
        mock_app.client = mock_client
        handler._app = mock_app

        request = PermissionRequest.create("Bash", {"command": "test"})

        await handler.update_message_approved(
            channel="C12345678",
            message_ts="1234567890.123456",
            request=request,
        )

        mock_client.chat_update.assert_called_once()
        call_kwargs = mock_client.chat_update.call_args[1]
        assert call_kwargs["channel"] == "C12345678"
        assert call_kwargs["ts"] == "1234567890.123456"
        assert "Approved" in call_kwargs["text"]

    async def test_update_message_denied(self, config: SlackConfig) -> None:
        """Test updating message to denied."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        mock_client = AsyncMock()
        mock_app = MagicMock()
        mock_app.client = mock_client
        handler._app = mock_app

        request = PermissionRequest.create("Bash", {"command": "test"})

        await handler.update_message_denied(
            channel="C12345678",
            message_ts="1234567890.123456",
            request=request,
        )

        mock_client.chat_update.assert_called_once()
        assert "Denied" in mock_client.chat_update.call_args[1]["text"]

    async def test_update_message_answered_locally(
        self, config: SlackConfig
    ) -> None:
        """Test updating message to answered locally."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        mock_client = AsyncMock()
        mock_app = MagicMock()
        mock_app.client = mock_client
        handler._app = mock_app

        request = PermissionRequest.create("Bash", {"command": "test"})

        await handler.update_message_answered_locally(
            channel="C12345678",
            message_ts="1234567890.123456",
            request=request,
        )

        mock_client.chat_update.assert_called_once()
        assert "Answered locally" in mock_client.chat_update.call_args[1]["text"]

    async def test_update_message_without_app(self, config: SlackConfig) -> None:
        """Test update methods do nothing without app."""
        handler = SlackHandler(config=config, on_action=AsyncMock())
        request = PermissionRequest.create("Bash", {"command": "test"})

        # These should not raise
        await handler.update_message_approved("C123", "ts", request)
        await handler.update_message_denied("C123", "ts", request)
        await handler.update_message_answered_locally("C123", "ts", request)

    async def test_post_notification_success(self, config: SlackConfig) -> None:
        """Test successful notification posting."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        mock_client = AsyncMock()
        mock_client.chat_postMessage.return_value = {
            "ts": "1234567890.123456",
            "channel": "C12345678",
        }

        mock_app = MagicMock()
        mock_app.client = mock_client
        handler._app = mock_app

        notification = Notification.create(
            message="Claude is waiting for input",
            notification_type="idle_prompt",
            cwd="/home/user/project",
        )

        result = await handler.post_notification(notification)

        assert result is True
        mock_client.chat_postMessage.assert_called_once()
        call_kwargs = mock_client.chat_postMessage.call_args[1]
        assert call_kwargs["channel"] == "C12345678"
        assert "blocks" in call_kwargs

    async def test_post_notification_failure(self, config: SlackConfig) -> None:
        """Test notification posting failure."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        mock_client = AsyncMock()
        mock_client.chat_postMessage.side_effect = Exception("API error")

        mock_app = MagicMock()
        mock_app.client = mock_client
        handler._app = mock_app

        notification = Notification.create(
            message="Test notification",
            notification_type="idle_prompt",
        )

        result = await handler.post_notification(notification)
        assert result is False

    async def test_post_notification_without_app(self, config: SlackConfig) -> None:
        """Test posting notification without app returns False."""
        handler = SlackHandler(config=config, on_action=AsyncMock())

        notification = Notification.create(
            message="Test notification",
            notification_type="idle_prompt",
        )

        result = await handler.post_notification(notification)
        assert result is False


class TestFormatNotification:
    """Tests for format_notification function."""

    def test_idle_prompt_notification(self) -> None:
        """Test formatting an idle_prompt notification."""
        notification = Notification(
            notification_id="test-id",
            message="Claude is waiting for input",
            notification_type="idle_prompt",
            cwd="/home/user/project",
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_notification(notification)

        assert len(blocks) >= 2
        # Check header with emoji
        assert blocks[0]["type"] == "header"
        assert "⏳" in blocks[0]["text"]["text"]  # idle_prompt emoji
        assert "Idle Prompt" in blocks[0]["text"]["text"]

        # Check message section
        message_found = False
        for block in blocks:
            if block.get("type") == "section":
                text = block.get("text", {}).get("text", "")
                if "Claude is waiting for input" in text:
                    message_found = True
                    break
        assert message_found

        # Check context
        context_block = blocks[-1]
        assert context_block["type"] == "context"
        context_text = context_block["elements"][0]["text"]
        # Time is converted to local timezone, so calculate expected local time
        expected_local_time = to_local_time(
            datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC)
        ).strftime("%H:%M:%S")
        assert expected_local_time in context_text
        assert "/home/user/project" in context_text

    def test_auth_success_notification(self) -> None:
        """Test formatting an auth_success notification."""
        notification = Notification(
            notification_id="test-id",
            message="Authentication successful",
            notification_type="auth_success",
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_notification(notification)

        assert blocks[0]["type"] == "header"
        assert "🔑" in blocks[0]["text"]["text"]  # auth_success emoji
        assert "Auth Success" in blocks[0]["text"]["text"]

    def test_unknown_notification_type(self) -> None:
        """Test formatting notification with unknown type uses default emoji."""
        notification = Notification(
            notification_id="test-id",
            message="Some notification",
            notification_type="unknown_type",
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_notification(notification)

        assert blocks[0]["type"] == "header"
        assert "📢" in blocks[0]["text"]["text"]  # default emoji

    def test_long_message_truncated(self) -> None:
        """Test that long messages are truncated."""
        long_message = "x" * 1000
        notification = Notification(
            notification_id="test-id",
            message=long_message,
            notification_type="idle_prompt",
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_notification(notification)

        # Find message section
        for block in blocks:
            if block.get("type") == "section":
                text = block.get("text", {}).get("text", "")
                if "x" in text:
                    assert len(text) <= 503  # 500 + "..."
                    assert "..." in text
                    break

    def test_empty_message(self) -> None:
        """Test notification with empty message."""
        notification = Notification(
            notification_id="test-id",
            message="",
            notification_type="idle_prompt",
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_notification(notification)

        # Should still have header and context, but no message section
        assert len(blocks) >= 2
        assert blocks[0]["type"] == "header"
        # No section block with message
        section_count = sum(1 for b in blocks if b.get("type") == "section")
        assert section_count == 0

    def test_long_cwd_truncated(self) -> None:
        """Test that long cwd paths are truncated."""
        long_cwd = "/home/user/" + "very_long_directory_name/" * 10
        notification = Notification(
            notification_id="test-id",
            message="Test",
            notification_type="idle_prompt",
            cwd=long_cwd,
            timestamp=datetime(2025, 1, 20, 10, 30, 0, tzinfo=UTC),
        )

        blocks = format_notification(notification)

        context_block = blocks[-1]
        context_text = context_block["elements"][0]["text"]
        # Should be truncated with ...
        assert "..." in context_text
        assert len(context_text) < len(long_cwd) + 50  # Some margin for formatting

    def test_notification_type_emoji_mapping(self) -> None:
        """Test notification type emoji mapping."""
        assert "idle_prompt" in NOTIFICATION_TYPE_EMOJI
        assert "auth_success" in NOTIFICATION_TYPE_EMOJI
        assert "elicitation_dialog" in NOTIFICATION_TYPE_EMOJI
