"""Tests for socket_server module."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_permission_daemon.socket_server import (
    SocketServer,
    SocketServerError,
    send_response,
)
from claude_permission_daemon.state import Action, PermissionRequest, PermissionResponse


class TestSocketServer:
    """Tests for SocketServer class."""

    @pytest.fixture
    def temp_socket_path(self, temp_dir: Path) -> Path:
        """Provide temporary socket path."""
        return temp_dir / "test.sock"

    @pytest.fixture
    def request_handler(self) -> AsyncMock:
        """Provide mock request handler."""
        return AsyncMock()

    @pytest.fixture
    def server(
        self, temp_socket_path: Path, request_handler: AsyncMock
    ) -> SocketServer:
        """Create SocketServer instance."""
        return SocketServer(
            socket_path=temp_socket_path,
            on_request=request_handler,
        )

    def test_initial_state(
        self, server: SocketServer, temp_socket_path: Path
    ) -> None:
        """Test initial state."""
        assert server.running is False
        assert server.socket_path == temp_socket_path

    async def test_start_creates_socket(
        self, server: SocketServer, temp_socket_path: Path
    ) -> None:
        """Test start creates socket file."""
        await server.start()
        try:
            assert server.running is True
            assert temp_socket_path.exists()
        finally:
            await server.stop()

    async def test_start_removes_existing_socket(
        self, temp_socket_path: Path, request_handler: AsyncMock
    ) -> None:
        """Test start removes existing socket file."""
        # Create a fake existing socket file
        temp_socket_path.touch()

        server = SocketServer(
            socket_path=temp_socket_path,
            on_request=request_handler,
        )

        await server.start()
        try:
            assert server.running is True
        finally:
            await server.stop()

    async def test_start_already_running(self, server: SocketServer) -> None:
        """Test start when already running does nothing."""
        await server.start()
        try:
            await server.start()  # Should not raise
            assert server.running is True
        finally:
            await server.stop()

    async def test_stop_not_running(self, server: SocketServer) -> None:
        """Test stop when not running does nothing."""
        await server.stop()  # Should not raise

    async def test_stop_removes_socket(
        self, server: SocketServer, temp_socket_path: Path
    ) -> None:
        """Test stop removes socket file."""
        await server.start()
        await server.stop()

        assert server.running is False
        assert not temp_socket_path.exists()

    async def test_socket_permissions(
        self, server: SocketServer, temp_socket_path: Path
    ) -> None:
        """Test socket is created with restricted permissions."""
        import stat

        await server.start()
        try:
            mode = temp_socket_path.stat().st_mode
            # Check only user read/write permissions
            assert mode & stat.S_IRUSR
            assert mode & stat.S_IWUSR
            assert not (mode & stat.S_IRGRP)
            assert not (mode & stat.S_IWGRP)
            assert not (mode & stat.S_IROTH)
            assert not (mode & stat.S_IWOTH)
        finally:
            await server.stop()

    async def test_run_without_start(self, server: SocketServer) -> None:
        """Test run raises if not started."""
        with pytest.raises(SocketServerError, match="not started"):
            await server.run()


class TestSocketServerConnections:
    """Tests for socket server connection handling."""

    @pytest.fixture
    def temp_socket_path(self, temp_dir: Path) -> Path:
        """Provide temporary socket path."""
        return temp_dir / "test.sock"

    async def test_handle_valid_request(self, temp_socket_path: Path) -> None:
        """Test handling a valid permission request."""
        received_requests: list[PermissionRequest] = []
        received_writers: list[asyncio.StreamWriter] = []

        async def handler(
            request: PermissionRequest, writer: asyncio.StreamWriter
        ) -> None:
            received_requests.append(request)
            received_writers.append(writer)
            # Send response
            response = PermissionResponse(Action.APPROVE, "Test approved")
            await send_response(writer, response)

        server = SocketServer(socket_path=temp_socket_path, on_request=handler)
        await server.start()

        try:
            # Connect and send request
            reader, writer = await asyncio.open_unix_connection(
                str(temp_socket_path)
            )

            request_data = {
                "tool_name": "Bash",
                "tool_input": {"command": "echo test"},
            }
            writer.write(json.dumps(request_data).encode() + b"\n")
            await writer.drain()

            # Read response
            response_data = await reader.readline()
            response = json.loads(response_data.decode())

            assert response["action"] == "approve"
            assert response["reason"] == "Test approved"
            assert len(received_requests) == 1
            assert received_requests[0].tool_name == "Bash"
            assert received_requests[0].tool_input == {"command": "echo test"}

        finally:
            await server.stop()

    async def test_handle_invalid_json(self, temp_socket_path: Path) -> None:
        """Test handling invalid JSON."""
        handler = AsyncMock()
        server = SocketServer(socket_path=temp_socket_path, on_request=handler)
        await server.start()

        try:
            reader, writer = await asyncio.open_unix_connection(
                str(temp_socket_path)
            )

            # Send invalid JSON
            writer.write(b"not valid json\n")
            await writer.drain()

            # Should receive error response
            response_data = await reader.readline()
            response = json.loads(response_data.decode())

            assert "error" in response
            assert "Invalid JSON" in response["error"]
            handler.assert_not_called()

        finally:
            await server.stop()

    async def test_handle_missing_tool_name(self, temp_socket_path: Path) -> None:
        """Test handling request missing tool_name."""
        handler = AsyncMock()
        server = SocketServer(socket_path=temp_socket_path, on_request=handler)
        await server.start()

        try:
            reader, writer = await asyncio.open_unix_connection(
                str(temp_socket_path)
            )

            # Send request without tool_name
            request_data = {"tool_input": {"command": "test"}}
            writer.write(json.dumps(request_data).encode() + b"\n")
            await writer.drain()

            # Should receive error response
            response_data = await reader.readline()
            response = json.loads(response_data.decode())

            assert "error" in response
            assert "tool_name" in response["error"]
            handler.assert_not_called()

        finally:
            await server.stop()

    async def test_handle_empty_tool_input(self, temp_socket_path: Path) -> None:
        """Test handling request with missing tool_input uses empty dict."""
        received_requests: list[PermissionRequest] = []

        async def handler(
            request: PermissionRequest, writer: asyncio.StreamWriter
        ) -> None:
            received_requests.append(request)
            await send_response(
                writer, PermissionResponse(Action.PASSTHROUGH, "test")
            )

        server = SocketServer(socket_path=temp_socket_path, on_request=handler)
        await server.start()

        try:
            reader, writer = await asyncio.open_unix_connection(
                str(temp_socket_path)
            )

            # Send request without tool_input
            request_data = {"tool_name": "Bash"}
            writer.write(json.dumps(request_data).encode() + b"\n")
            await writer.drain()

            await reader.readline()  # Wait for response

            assert len(received_requests) == 1
            assert received_requests[0].tool_input == {}

        finally:
            await server.stop()


class TestSendResponse:
    """Tests for send_response helper function."""

    async def test_send_permission_response(self) -> None:
        """Test sending a PermissionResponse."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        response = PermissionResponse(Action.APPROVE, "Approved via Slack")
        await send_response(mock_writer, response)

        # Check write was called with JSON
        call_args = mock_writer.write.call_args[0][0]
        data = json.loads(call_args.decode().strip())
        assert data["action"] == "approve"
        assert data["reason"] == "Approved via Slack"

        mock_writer.close.assert_called_once()

    async def test_send_dict_response(self) -> None:
        """Test sending a dict response."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        response = {"error": "Test error"}
        await send_response(mock_writer, response)

        call_args = mock_writer.write.call_args[0][0]
        data = json.loads(call_args.decode().strip())
        assert data["error"] == "Test error"

    async def test_send_response_handles_error(self) -> None:
        """Test send_response handles write errors gracefully."""
        mock_writer = MagicMock(spec=asyncio.StreamWriter)
        mock_writer.write = MagicMock(side_effect=Exception("Write failed"))
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        response = PermissionResponse(Action.DENY, "Test")

        # Should not raise
        await send_response(mock_writer, response)

        # Should still try to close
        mock_writer.close.assert_called_once()
