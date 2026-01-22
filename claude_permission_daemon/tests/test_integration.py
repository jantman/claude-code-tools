"""Integration tests for the full permission flow.

Tests end-to-end scenarios focusing on component interactions.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.config import Config, DaemonConfig, SlackConfig, SwayidleConfig
from claude_permission_daemon.socket_server import SocketServer, send_response
from claude_permission_daemon.state import (
    Action,
    PendingRequest,
    PermissionRequest,
    PermissionResponse,
    StateManager,
)


@pytest.fixture
def integration_config(temp_dir: Path) -> Config:
    """Create a config for integration testing."""
    return Config(
        daemon=DaemonConfig(
            socket_path=temp_dir / "test.sock",
            idle_timeout=5,
            request_timeout=60,
        ),
        slack=SlackConfig(
            bot_token="xoxb-test-token",
            app_token="xapp-test-token",
            channel="C12345678",
        ),
        swayidle=SwayidleConfig(binary="swayidle"),
    )


class TestSocketServerIntegration:
    """Integration tests for socket server with real connections."""

    async def test_socket_server_full_flow(self, temp_dir: Path) -> None:
        """Test full request/response flow through socket server."""
        socket_path = temp_dir / "test.sock"
        received_requests = []

        async def handler(request: PermissionRequest, writer: asyncio.StreamWriter):
            received_requests.append(request)
            response = PermissionResponse(Action.APPROVE, "Test approved")
            await send_response(writer, response)

        server = SocketServer(socket_path=socket_path, on_request=handler)
        await server.start()

        try:
            # Connect and send request
            reader, writer = await asyncio.open_unix_connection(str(socket_path))

            request = {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
            }
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()

            # Read response
            response_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = json.loads(response_data.decode())

            assert response["action"] == "approve"
            assert response["reason"] == "Test approved"
            assert len(received_requests) == 1
            assert received_requests[0].tool_name == "Bash"

        finally:
            await server.stop()

    async def test_multiple_concurrent_connections(self, temp_dir: Path) -> None:
        """Test handling multiple concurrent connections."""
        socket_path = temp_dir / "test.sock"
        received_count = 0
        received_lock = asyncio.Lock()

        async def handler(request: PermissionRequest, writer: asyncio.StreamWriter):
            nonlocal received_count
            async with received_lock:
                received_count += 1
            await asyncio.sleep(0.05)  # Simulate processing
            response = PermissionResponse(Action.PASSTHROUGH, "Test")
            await send_response(writer, response)

        server = SocketServer(socket_path=socket_path, on_request=handler)
        await server.start()

        try:
            # Send multiple concurrent requests
            async def send_request(n: int):
                reader, writer = await asyncio.open_unix_connection(str(socket_path))
                request = {"tool_name": f"Tool{n}", "tool_input": {}}
                writer.write(json.dumps(request).encode() + b"\n")
                await writer.drain()
                return await asyncio.wait_for(reader.readline(), timeout=5.0)

            results = await asyncio.gather(*[send_request(i) for i in range(3)])

            assert received_count == 3
            for result in results:
                response = json.loads(result.decode())
                assert response["action"] == "passthrough"

        finally:
            await server.stop()

    async def test_deferred_response(self, temp_dir: Path) -> None:
        """Test that responses can be sent after handler returns."""
        socket_path = temp_dir / "test.sock"
        pending_writers = []

        async def handler(request: PermissionRequest, writer: asyncio.StreamWriter):
            # Don't respond immediately - store writer for later
            pending_writers.append((request, writer))

        server = SocketServer(socket_path=socket_path, on_request=handler)
        await server.start()

        try:
            # Connect and send request
            reader, writer = await asyncio.open_unix_connection(str(socket_path))

            request = {"tool_name": "Bash", "tool_input": {}}
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()

            # Wait for handler to receive request
            await asyncio.sleep(0.1)
            assert len(pending_writers) == 1

            # Now send response through stored writer
            req, pending_writer = pending_writers[0]
            response = PermissionResponse(Action.DENY, "Denied later")
            await send_response(pending_writer, response)

            # Read response
            response_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            parsed = json.loads(response_data.decode())

            assert parsed["action"] == "deny"
            assert parsed["reason"] == "Denied later"

        finally:
            await server.stop()


class TestStateManagerIntegration:
    """Integration tests for state manager with callbacks."""

    async def test_idle_callback_triggers_on_change(self) -> None:
        """Test that idle callbacks are triggered correctly."""
        state = StateManager()
        callback_calls = []

        async def callback(idle: bool):
            callback_calls.append(idle)

        state.register_idle_callback(callback)

        # Initial state is False, so setting to True should trigger
        await state.set_idle(True)
        assert callback_calls == [True]

        # Setting to same value should not trigger
        await state.set_idle(True)
        assert callback_calls == [True]

        # Setting to False should trigger
        await state.set_idle(False)
        assert callback_calls == [True, False]

    async def test_pending_request_lifecycle(self) -> None:
        """Test adding, updating, and removing pending requests."""
        state = StateManager()
        mock_writer = MagicMock(spec=asyncio.StreamWriter)

        # Add request
        request = PermissionRequest.create("Bash", {"command": "test"})
        pending = PendingRequest(request=request, hook_writer=mock_writer)
        await state.add_pending_request(pending)

        # Get request
        retrieved = await state.get_pending_request(request.request_id)
        assert retrieved is pending

        # Update Slack info
        await state.update_slack_info(
            request.request_id, "1234567890.123456", "C12345678"
        )
        retrieved = await state.get_pending_request(request.request_id)
        assert retrieved.slack_message_ts == "1234567890.123456"
        assert retrieved.slack_channel == "C12345678"

        # Remove request
        removed = await state.remove_pending_request(request.request_id)
        assert removed is pending

        # Should no longer exist
        assert await state.get_pending_request(request.request_id) is None

    async def test_clear_pending_with_callback(self) -> None:
        """Test clearing pending requests when idle state changes."""
        state = StateManager()
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        cleared_on_active = []

        async def on_active(idle: bool):
            if not idle:  # User became active
                pending = await state.get_all_pending_requests()
                cleared_on_active.extend(pending)
                await state.clear_all_pending()

        state.register_idle_callback(on_active)

        # Add some pending requests
        for i in range(3):
            request = PermissionRequest.create(f"Tool{i}", {})
            pending = PendingRequest(request=request, hook_writer=mock_writer)
            await state.add_pending_request(pending)

        # Set idle then active
        await state.set_idle(True)
        await state.set_idle(False)

        # Should have captured all pending before clearing
        assert len(cleared_on_active) == 3

        # Should be empty now
        assert len(await state.get_all_pending_requests()) == 0


class TestHookScript:
    """Tests for the hook script functionality."""

    async def test_hook_passthrough_no_daemon(self, temp_dir: Path) -> None:
        """Test hook returns passthrough when daemon not running."""
        from claude_permission_daemon.hook import connect_to_daemon

        # Socket doesn't exist
        socket_path = temp_dir / "nonexistent.sock"

        result = connect_to_daemon(socket_path, timeout=5)
        assert result is None

    def test_hook_format_output_approve(self) -> None:
        """Test hook formats approve response correctly."""
        from claude_permission_daemon.hook import format_output

        response = {"action": "approve", "reason": "Approved via Slack"}
        output = format_output(response)

        assert output is not None
        data = json.loads(output)
        assert data["decision"] == "approve"
        assert data["reason"] == "Approved via Slack"

    def test_hook_format_output_deny(self) -> None:
        """Test hook formats deny response correctly."""
        from claude_permission_daemon.hook import format_output

        response = {"action": "deny", "reason": "Denied via Slack"}
        output = format_output(response)

        assert output is not None
        data = json.loads(output)
        assert data["decision"] == "deny"
        assert data["reason"] == "Denied via Slack"

    def test_hook_format_output_passthrough(self) -> None:
        """Test hook returns None for passthrough."""
        from claude_permission_daemon.hook import format_output

        response = {"action": "passthrough", "reason": "User active"}
        output = format_output(response)
        assert output is None

    def test_hook_format_output_unknown(self) -> None:
        """Test hook returns None for unknown action."""
        from claude_permission_daemon.hook import format_output

        response = {"action": "unknown", "reason": "Something"}
        output = format_output(response)
        assert output is None

    def test_hook_read_request_empty(self) -> None:
        """Test reading empty stdin returns None."""
        from claude_permission_daemon.hook import read_request_from_stdin
        from io import StringIO
        import sys

        old_stdin = sys.stdin
        sys.stdin = StringIO("")
        try:
            result = read_request_from_stdin()
            assert result is None
        finally:
            sys.stdin = old_stdin

    def test_hook_read_request_valid(self) -> None:
        """Test reading valid JSON from stdin."""
        from claude_permission_daemon.hook import read_request_from_stdin
        from io import StringIO
        import sys

        old_stdin = sys.stdin
        sys.stdin = StringIO('{"tool_name": "Bash", "tool_input": {"command": "test"}}')
        try:
            result = read_request_from_stdin()
            assert result is not None
            assert result["tool_name"] == "Bash"
        finally:
            sys.stdin = old_stdin

    def test_hook_read_request_invalid_json(self) -> None:
        """Test reading invalid JSON returns None."""
        from claude_permission_daemon.hook import read_request_from_stdin
        from io import StringIO
        import sys

        old_stdin = sys.stdin
        sys.stdin = StringIO("not valid json")
        try:
            result = read_request_from_stdin()
            assert result is None
        finally:
            sys.stdin = old_stdin


class TestEndToEndFlow:
    """End-to-end flow tests using socket server."""

    async def test_approve_flow(self, temp_dir: Path) -> None:
        """Test complete approve flow through socket."""
        socket_path = temp_dir / "test.sock"

        # Simulate daemon behavior
        async def daemon_handler(
            request: PermissionRequest, writer: asyncio.StreamWriter
        ):
            # Simulate "idle" state - would post to Slack and wait for approval
            # For testing, just approve immediately
            response = PermissionResponse(Action.APPROVE, "Approved via Slack")
            await send_response(writer, response)

        server = SocketServer(socket_path=socket_path, on_request=daemon_handler)
        await server.start()

        try:
            # Simulate hook script behavior
            reader, writer = await asyncio.open_unix_connection(str(socket_path))

            request = {
                "tool_name": "Bash",
                "tool_input": {"command": "npm install lodash"},
            }
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()

            response_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = json.loads(response_data.decode())

            # Hook would output this as Claude Code format
            from claude_permission_daemon.hook import format_output
            output = format_output(response)

            assert output is not None
            claude_response = json.loads(output)
            assert claude_response["decision"] == "approve"

        finally:
            await server.stop()

    async def test_deny_flow(self, temp_dir: Path) -> None:
        """Test complete deny flow through socket."""
        socket_path = temp_dir / "test.sock"

        async def daemon_handler(
            request: PermissionRequest, writer: asyncio.StreamWriter
        ):
            response = PermissionResponse(Action.DENY, "Denied via Slack")
            await send_response(writer, response)

        server = SocketServer(socket_path=socket_path, on_request=daemon_handler)
        await server.start()

        try:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))

            request = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()

            response_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = json.loads(response_data.decode())

            from claude_permission_daemon.hook import format_output
            output = format_output(response)

            assert output is not None
            claude_response = json.loads(output)
            assert claude_response["decision"] == "deny"

        finally:
            await server.stop()

    async def test_passthrough_flow(self, temp_dir: Path) -> None:
        """Test complete passthrough flow (user active)."""
        socket_path = temp_dir / "test.sock"

        async def daemon_handler(
            request: PermissionRequest, writer: asyncio.StreamWriter
        ):
            # User is active - passthrough
            response = PermissionResponse(Action.PASSTHROUGH, "User active locally")
            await send_response(writer, response)

        server = SocketServer(socket_path=socket_path, on_request=daemon_handler)
        await server.start()

        try:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))

            request = {"tool_name": "Bash", "tool_input": {"command": "echo test"}}
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()

            response_data = await asyncio.wait_for(reader.readline(), timeout=5.0)
            response = json.loads(response_data.decode())

            from claude_permission_daemon.hook import format_output
            output = format_output(response)

            # Passthrough means no output (Claude Code shows local prompt)
            assert output is None

        finally:
            await server.stop()
