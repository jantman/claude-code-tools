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
from .slack_handler import SlackHandler
from .socket_server import SocketServer, send_response
from .state import (
    Action,
    Notification,
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
        self._slack_handler: SlackHandler | None = None
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
            on_notification=self._handle_notification,
        )
        await self._socket_server.start()

        # Start Slack handler
        self._slack_handler = SlackHandler(
            config=self._config.slack,
            on_action=self._handle_slack_action,
        )
        await self._slack_handler.start()

        # Start component tasks
        self._tasks = [
            asyncio.create_task(self._idle_monitor.run(), name="idle_monitor"),
            asyncio.create_task(self._socket_server.run(), name="socket_server"),
            asyncio.create_task(self._slack_handler.run(), name="slack_handler"),
        ]

        logger.info("Daemon started successfully")

    async def stop(self) -> None:
        """Stop all daemon components."""
        logger.info("Stopping daemon...")

        # Cancel all tasks
        logger.debug("Cancelling tasks...")
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete with timeout
        if self._tasks:
            logger.debug("Waiting for tasks to complete...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=10.0,
                )
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for tasks to cancel")
        self._tasks.clear()

        # Stop components
        logger.debug("Stopping Slack handler...")
        if self._slack_handler:
            await self._slack_handler.stop()
        logger.debug("Stopping socket server...")
        if self._socket_server:
            await self._socket_server.stop()
        logger.debug("Stopping idle monitor...")
        if self._idle_monitor:
            await self._idle_monitor.stop()

        # Send passthrough to any remaining pending requests
        logger.debug("Clearing pending requests...")
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
            if p.slack_message_ts and p.slack_channel and self._slack_handler:
                # Request was posted to Slack - update message
                logger.info(
                    f"Request {p.request_id} answered locally (user returned)"
                )
                await self._slack_handler.update_message_answered_locally(
                    channel=p.slack_channel,
                    message_ts=p.slack_message_ts,
                    request=p.request,
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
        state_desc = self._state.get_state_description()
        if not self._state.idle:
            # User is active - passthrough immediately
            logger.info(
                f"User {state_desc}, passing through request {request.request_id}"
            )
            await self._resolve_request(
                request.request_id,
                Action.PASSTHROUGH,
                "User active locally",
            )
            return

        # User is idle - post to Slack
        if not self._slack_handler:
            logger.error(
                f"User {state_desc}, but Slack handler not available, passing through"
            )
            await self._resolve_request(
                request.request_id,
                Action.PASSTHROUGH,
                "Slack handler not available",
            )
            return

        logger.info(
            f"User {state_desc}, posting to Slack for request {request.request_id}"
        )
        result = await self._slack_handler.post_permission_request(pending)

        if result is None:
            # Failed to post to Slack - passthrough
            logger.error("Failed to post to Slack, passing through")
            await self._resolve_request(
                request.request_id,
                Action.PASSTHROUGH,
                "Failed to post to Slack",
            )
            return

        # Update pending request with Slack message info
        message_ts, channel = result
        await self._state.update_slack_info(request.request_id, message_ts, channel)
        logger.info(f"Request {request.request_id} posted to Slack, awaiting response")

    async def _handle_slack_action(self, request_id: str, action: Action) -> None:
        """Handle an action from Slack (approve/deny button click).

        Args:
            request_id: ID of the request being acted on.
            action: The action taken (APPROVE or DENY).
        """
        pending = await self._state.get_pending_request(request_id)
        if not pending:
            logger.warning(f"Received Slack action for unknown request: {request_id}")
            return

        # Update the Slack message
        if pending.slack_message_ts and pending.slack_channel and self._slack_handler:
            if action == Action.APPROVE:
                await self._slack_handler.update_message_approved(
                    channel=pending.slack_channel,
                    message_ts=pending.slack_message_ts,
                    request=pending.request,
                )
                reason = "Approved via Slack"
            else:
                await self._slack_handler.update_message_denied(
                    channel=pending.slack_channel,
                    message_ts=pending.slack_message_ts,
                    request=pending.request,
                )
                reason = "Denied via Slack"
        else:
            reason = f"{action.value.capitalize()}d via Slack"

        # Resolve the request
        await self._resolve_request(request_id, action, reason)

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

    async def _handle_notification(self, notification: Notification) -> None:
        """Handle an incoming notification from hook script.

        Notifications are one-way; they are sent to Slack when the user is idle
        but no response is expected.

        Args:
            notification: The notification to handle.
        """
        state_desc = self._state.get_state_description()
        logger.info(
            f"Handling notification {notification.notification_id}: "
            f"type={notification.notification_type}"
        )

        # Only send to Slack if user is idle
        if not self._state.idle:
            logger.info(
                f"User {state_desc}, not sending notification to Slack"
            )
            return

        # User is idle - post to Slack
        if not self._slack_handler:
            logger.warning(
                f"User {state_desc}, but Slack handler not available, "
                f"notification dropped"
            )
            return

        logger.info(
            f"User {state_desc}, posting notification to Slack"
        )
        success = await self._slack_handler.post_notification(notification)

        if success:
            logger.info(
                f"Notification {notification.notification_id} posted to Slack"
            )
        else:
            logger.error(
                f"Failed to post notification {notification.notification_id} to Slack"
            )


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
