"""Unix domain socket server for hook script connections.

Accepts connections from hook scripts, receives permission requests,
and sends responses back.
"""

import asyncio
import json
import logging
import os
import stat
from pathlib import Path
from typing import Callable, Coroutine

from .state import PendingRequest, PermissionRequest, PermissionResponse

logger = logging.getLogger(__name__)

# Type alias for request handler callback
RequestHandler = Callable[
    [PermissionRequest, asyncio.StreamWriter],
    Coroutine[None, None, None],
]


class SocketServerError(Exception):
    """Error related to socket server operations."""

    pass


class SocketServer:
    """Unix domain socket server for hook script communication.

    Listens for connections from hook scripts, parses JSON requests,
    and coordinates with the daemon to send responses.
    """

    def __init__(
        self,
        socket_path: Path,
        on_request: RequestHandler,
    ) -> None:
        """Initialize the socket server.

        Args:
            socket_path: Path to the Unix domain socket.
            on_request: Async callback called when a request is received.
                        Receives (PermissionRequest, StreamWriter) to allow
                        sending the response later.
        """
        self._socket_path = socket_path
        self._on_request = on_request
        self._server: asyncio.Server | None = None
        self._running = False
        self._active_connections: set[asyncio.StreamWriter] = set()

    @property
    def running(self) -> bool:
        """Whether the server is currently running."""
        return self._running

    @property
    def socket_path(self) -> Path:
        """Path to the Unix domain socket."""
        return self._socket_path

    async def start(self) -> None:
        """Start listening on the Unix socket.

        Raises:
            SocketServerError: If socket creation fails.
        """
        if self._running:
            logger.warning("SocketServer already running")
            return

        # Remove existing socket file if present
        if self._socket_path.exists():
            logger.info(f"Removing existing socket: {self._socket_path}")
            self._socket_path.unlink()

        # Ensure parent directory exists
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._server = await asyncio.start_unix_server(
                self._handle_connection,
                path=str(self._socket_path),
            )
        except OSError as e:
            raise SocketServerError(f"Failed to create socket: {e}") from e

        # Set socket permissions to user-only (0600)
        os.chmod(self._socket_path, stat.S_IRUSR | stat.S_IWUSR)

        self._running = True
        logger.info(f"SocketServer listening on {self._socket_path}")

    async def stop(self) -> None:
        """Stop the socket server and close all connections."""
        if not self._running:
            return

        self._running = False

        # Close all active connections
        for writer in list(self._active_connections):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._active_connections.clear()

        # Stop the server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Remove socket file
        if self._socket_path.exists():
            self._socket_path.unlink()

        logger.info("SocketServer stopped")

    async def run(self) -> None:
        """Run the server until stopped.

        This keeps the server running. The actual connection handling
        happens in _handle_connection which is called by asyncio.
        """
        if not self._server:
            raise SocketServerError("Server not started")

        logger.debug("SocketServer running")
        try:
            while self._running:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.debug("SocketServer run cancelled")

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming connection from a hook script.

        Args:
            reader: Stream reader for the connection.
            writer: Stream writer for the connection.
        """
        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug(f"New connection from {peer}")
        self._active_connections.add(writer)

        try:
            # Read the request (single JSON object, newline-terminated)
            try:
                data = await asyncio.wait_for(
                    reader.readline(),
                    timeout=30.0,  # 30 second timeout for initial request
                )
            except asyncio.TimeoutError:
                logger.warning(f"Connection from {peer} timed out waiting for request")
                return

            if not data:
                logger.debug(f"Connection from {peer} closed without data")
                return

            # Parse the JSON request
            try:
                request_data = json.loads(data.decode())
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from {peer}: {e}")
                await self._send_error(writer, f"Invalid JSON: {e}")
                return

            # Validate required fields
            if "tool_name" not in request_data:
                logger.error(f"Missing tool_name from {peer}")
                await self._send_error(writer, "Missing required field: tool_name")
                return

            # Create the permission request
            request = PermissionRequest.create(
                tool_name=request_data["tool_name"],
                tool_input=request_data.get("tool_input", {}),
            )

            logger.info(
                f"Received permission request: {request.request_id} "
                f"for {request.tool_name}"
            )

            # Call the handler - it's responsible for sending the response
            # The writer is passed so the response can be sent later
            await self._on_request(request, writer)

        except Exception:
            logger.exception(f"Error handling connection from {peer}")
        finally:
            # Note: We don't close the writer here because the response
            # may be sent later (after Slack interaction). The daemon
            # is responsible for closing after sending the response.
            self._active_connections.discard(writer)

    async def _send_error(
        self,
        writer: asyncio.StreamWriter,
        message: str,
    ) -> None:
        """Send an error response and close the connection.

        Args:
            writer: Stream writer for the connection.
            message: Error message to send.
        """
        error_response = {"error": message}
        await send_response(writer, error_response)


async def send_response(
    writer: asyncio.StreamWriter,
    response: PermissionResponse | dict,
) -> None:
    """Send a response to a hook script and close the connection.

    Args:
        writer: Stream writer for the connection.
        response: PermissionResponse or dict to send.
    """
    try:
        if isinstance(response, PermissionResponse):
            data = response.to_dict()
        else:
            data = response

        json_data = json.dumps(data) + "\n"
        writer.write(json_data.encode())
        await writer.drain()
    except Exception:
        logger.exception("Error sending response")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
