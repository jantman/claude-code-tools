"""Main daemon entry point and orchestration.

Coordinates idle monitoring, socket server, and Slack integration.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from . import __version__
from .config import Config, DEFAULT_CONFIG_PATH
from .idle_monitor import IdleMonitor
from .socket_server import SocketServer, send_response
from .state import (
    Action,
    PendingRequest,
    PermissionRequest,
    PermissionResponse,
    StateManager,
)

logger = logging.getLogger(__name__)


class Daemon:
    """Main daemon class coordinating all components."""

    def __init__(self, config: Config) -> None:
        """Initialize the daemon with configuration.

        Args:
            config: Loaded configuration.
        """
        self._config = config
        self._state = StateManager()
        self._idle_monitor: IdleMonitor | None = None
        self._socket_server: SocketServer | None = None
        self._slack_handler = None  # Will be added in Milestone 3
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all daemon components."""
        logger.info(f"Starting Claude Permission Daemon v{__version__}")

        # Register idle state callback
        self._state.register_idle_callback(self._on_idle_change)

        # Start idle monitor
        self._idle_monitor = IdleMonitor(
            config=self._config.swayidle,
            idle_timeout=self._config.daemon.idle_timeout,
            on_idle_change=self._state.set_idle,
        )
        await self._idle_monitor.start()

        # Start socket server
        self._socket_server = SocketServer(
            socket_path=self._config.daemon.socket_path,
            on_request=self._handle_permission_request,
        )
        await self._socket_server.start()

        # Start component tasks
        self._tasks = [
            asyncio.create_task(self._idle_monitor.run(), name="idle_monitor"),
            asyncio.create_task(self._socket_server.run(), name="socket_server"),
        ]

        logger.info("Daemon started successfully")

    async def stop(self) -> None:
        """Stop all daemon components."""
        logger.info("Stopping daemon...")

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Stop components
        if self._socket_server:
            await self._socket_server.stop()
        if self._idle_monitor:
            await self._idle_monitor.stop()

        # Send passthrough to any remaining pending requests
        pending = await self._state.clear_all_pending()
        for p in pending:
            await self._send_passthrough(p)

        logger.info("Daemon stopped")

    async def run(self) -> None:
        """Run the daemon until shutdown signal."""
        await self.start()

        try:
            # Wait for shutdown
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    def request_shutdown(self) -> None:
        """Request daemon shutdown."""
        logger.info("Shutdown requested")
        self._shutdown_event.set()

    async def _on_idle_change(self, idle: bool) -> None:
        """Handle idle state changes.

        When user becomes active, resolve all pending Slack requests
        with passthrough so the local prompt appears.

        Args:
            idle: New idle state (True = idle, False = active).
        """
        if idle:
            logger.debug("User went idle - will use Slack for new requests")
            return

        # User became active - resolve pending requests
        logger.debug("User became active - resolving pending requests")
        pending = await self._state.get_all_pending_requests()

        for p in pending:
            if p.slack_message_ts:
                # Request was posted to Slack - update message and passthrough
                # Slack message update will be implemented in Milestone 3
                logger.info(
                    f"Request {p.request_id} answered locally (user returned)"
                )
            await self._resolve_request(p.request_id, Action.PASSTHROUGH, "User active locally")

    async def _handle_permission_request(
        self,
        request: PermissionRequest,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming permission request from hook script.

        Args:
            request: The permission request.
            writer: StreamWriter to send response back to hook.
        """
        logger.info(
            f"Handling permission request {request.request_id}: "
            f"{request.tool_name}"
        )

        # Create pending request tracking
        pending = PendingRequest(
            request=request,
            hook_writer=writer,
        )
        await self._state.add_pending_request(pending)

        # Check if user is idle
        if not self._state.idle:
            # User is active - passthrough immediately
            logger.info(f"User active, passing through request {request.request_id}")
            await self._resolve_request(
                request.request_id,
                Action.PASSTHROUGH,
                "User active locally",
            )
            return

        # User is idle - will post to Slack (implemented in Milestone 3)
        # For now, just passthrough
        logger.info(
            f"User idle, would post to Slack for request {request.request_id}"
        )
        # TODO: Post to Slack and wait for response
        # For now, passthrough since Slack isn't implemented yet
        await self._resolve_request(
            request.request_id,
            Action.PASSTHROUGH,
            "Slack integration not yet implemented",
        )

    async def _resolve_request(
        self,
        request_id: str,
        action: Action,
        reason: str,
    ) -> None:
        """Resolve a pending request with the given action.

        Args:
            request_id: ID of the request to resolve.
            action: Action to take (approve/deny/passthrough).
            reason: Human-readable reason for the action.
        """
        pending = await self._state.remove_pending_request(request_id)
        if not pending:
            logger.warning(f"Tried to resolve unknown request: {request_id}")
            return

        response = PermissionResponse(action=action, reason=reason)
        logger.info(
            f"Resolving request {request_id}: {action.value} - {reason}"
        )

        await send_response(pending.hook_writer, response)

    async def _send_passthrough(self, pending: PendingRequest) -> None:
        """Send a passthrough response to a pending request.

        Args:
            pending: The pending request to respond to.
        """
        response = PermissionResponse(
            action=Action.PASSTHROUGH,
            reason="Daemon shutting down",
        )
        await send_response(pending.hook_writer, response)


def setup_logging(debug: bool = False) -> None:
    """Configure logging for the daemon.

    Args:
        debug: If True, use DEBUG level; otherwise INFO.
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Reduce noise from third-party libraries
    logging.getLogger("slack_bolt").setLevel(logging.WARNING)
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="Claude Permission Daemon - Remote approval via Slack",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to config file (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument(
        "--debug",
        "-d",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point for the daemon."""
    args = parse_args()
    setup_logging(debug=args.debug)

    # Load configuration
    try:
        config = Config.load(args.config)
    except FileNotFoundError:
        logger.error(f"Config file not found: {args.config}")
        logger.error(f"Create config file or specify path with --config")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)

    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    # Create and run daemon
    daemon = Daemon(config)

    # Set up signal handlers
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, daemon.request_shutdown)

    try:
        loop.run_until_complete(daemon.run())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()

    logger.info("Daemon exited")


if __name__ == "__main__":
    main()
