"""Slack integration via Socket Mode.

Handles posting permission request messages and receiving button callbacks.
"""

import asyncio
import logging
from typing import Callable, Coroutine

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from .config import SlackConfig
from .state import Action, Notification, PendingRequest, PermissionRequest

logger = logging.getLogger(__name__)

# Type alias for action callback
ActionCallback = Callable[[str, Action], Coroutine[None, None, None]]


class SlackHandler:
    """Handles Slack Socket Mode connection and message interactions.

    Posts permission request messages with approve/deny buttons and
    handles button callback actions.
    """

    def __init__(
        self,
        config: SlackConfig,
        on_action: ActionCallback,
    ) -> None:
        """Initialize the Slack handler.

        Args:
            config: Slack configuration with tokens and channel.
            on_action: Callback when user clicks approve/deny button.
                      Receives (request_id, action).
        """
        self._config = config
        self._on_action = on_action
        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None
        self._running = False

    @property
    def running(self) -> bool:
        """Whether the handler is currently running."""
        return self._running

    async def start(self) -> None:
        """Start the Slack Socket Mode connection.

        Raises:
            Exception: If connection fails.
        """
        if self._running:
            logger.warning("SlackHandler already running")
            return

        logger.info("Starting Slack Socket Mode connection")

        # Create the Bolt app
        self._app = AsyncApp(token=self._config.bot_token)

        # Register action handlers
        self._app.action("approve_permission")(self._handle_approve)
        self._app.action("deny_permission")(self._handle_deny)

        # Create Socket Mode handler
        self._handler = AsyncSocketModeHandler(
            app=self._app,
            app_token=self._config.app_token,
        )

        # Connect to Slack (non-blocking - just establishes connection)
        await self._handler.connect_async()
        self._running = True
        logger.info("Slack Socket Mode connected")

    async def stop(self) -> None:
        """Stop the Slack Socket Mode connection."""
        if not self._running:
            return

        logger.info("Stopping Slack Socket Mode connection")
        self._running = False

        if self._handler:
            try:
                await asyncio.wait_for(self._handler.close_async(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Slack handler close timed out after 5s")
            except Exception:
                logger.exception("Error closing Slack handler")
            self._handler = None

        self._app = None
        logger.info("Slack Socket Mode disconnected")

    async def run(self) -> None:
        """Run until stopped.

        This keeps the handler alive. The Socket Mode handler
        manages the WebSocket connection internally.
        """
        if not self._running:
            raise RuntimeError("SlackHandler not started")

        logger.debug("SlackHandler running")
        try:
            while self._running:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.debug("SlackHandler run cancelled")

    async def post_permission_request(
        self, pending: PendingRequest
    ) -> tuple[str, str] | None:
        """Post a permission request message to Slack.

        Args:
            pending: The pending request to post.

        Returns:
            Tuple of (message_ts, channel) if successful, None otherwise.
        """
        if not self._app:
            logger.error("Cannot post message: Slack not connected")
            return None

        request = pending.request
        blocks = format_permission_request(request)

        try:
            client: AsyncWebClient = self._app.client
            response = await client.chat_postMessage(
                channel=self._config.channel,
                text=f"Permission request: {request.tool_name}",
                blocks=blocks,
            )

            message_ts = response["ts"]
            channel = response["channel"]
            logger.info(
                f"Posted permission request {request.request_id} "
                f"to Slack: {channel}/{message_ts}"
            )
            return (message_ts, channel)

        except Exception:
            logger.exception("Failed to post permission request to Slack")
            return None

    async def update_message_approved(
        self, channel: str, message_ts: str, request: PermissionRequest
    ) -> None:
        """Update a message to show it was approved.

        Args:
            channel: Slack channel ID.
            message_ts: Message timestamp.
            request: The original permission request.
        """
        if not self._app:
            return

        blocks = format_approved(request)
        try:
            await self._app.client.chat_update(
                channel=channel,
                ts=message_ts,
                text=f"Approved: {request.tool_name}",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to update Slack message (approved)")

    async def update_message_denied(
        self, channel: str, message_ts: str, request: PermissionRequest
    ) -> None:
        """Update a message to show it was denied.

        Args:
            channel: Slack channel ID.
            message_ts: Message timestamp.
            request: The original permission request.
        """
        if not self._app:
            return

        blocks = format_denied(request)
        try:
            await self._app.client.chat_update(
                channel=channel,
                ts=message_ts,
                text=f"Denied: {request.tool_name}",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to update Slack message (denied)")

    async def update_message_answered_locally(
        self, channel: str, message_ts: str, request: PermissionRequest
    ) -> None:
        """Update a message to show it was answered locally.

        Args:
            channel: Slack channel ID.
            message_ts: Message timestamp.
            request: The original permission request.
        """
        if not self._app:
            return

        blocks = format_answered_locally(request)
        try:
            await self._app.client.chat_update(
                channel=channel,
                ts=message_ts,
                text=f"Answered locally: {request.tool_name}",
                blocks=blocks,
            )
        except Exception:
            logger.exception("Failed to update Slack message (answered locally)")

    async def post_notification(self, notification: Notification) -> bool:
        """Post a notification message to Slack.

        Unlike permission requests, notifications don't have buttons and
        don't expect a response. They are info-only messages.

        Args:
            notification: The notification to post.

        Returns:
            True if successfully posted, False otherwise.
        """
        if not self._app:
            logger.error("Cannot post notification: Slack not connected")
            return False

        blocks = format_notification(notification)

        try:
            client: AsyncWebClient = self._app.client
            await client.chat_postMessage(
                channel=self._config.channel,
                text=f"Notification: {notification.notification_type}",
                blocks=blocks,
            )

            logger.info(
                f"Posted notification {notification.notification_id} "
                f"type={notification.notification_type} to Slack"
            )
            return True

        except Exception:
            logger.exception("Failed to post notification to Slack")
            return False

    async def _handle_approve(self, ack, body) -> None:
        """Handle approve button click.

        Args:
            ack: Slack acknowledge function.
            body: Request body from Slack.
        """
        await ack()

        try:
            action = body["actions"][0]
            request_id = action["value"]
            logger.info(f"Received approve action for request {request_id}")
            await self._on_action(request_id, Action.APPROVE)
        except Exception:
            logger.exception("Error handling approve action")

    async def _handle_deny(self, ack, body) -> None:
        """Handle deny button click.

        Args:
            ack: Slack acknowledge function.
            body: Request body from Slack.
        """
        await ack()

        try:
            action = body["actions"][0]
            request_id = action["value"]
            logger.info(f"Received deny action for request {request_id}")
            await self._on_action(request_id, Action.DENY)
        except Exception:
            logger.exception("Error handling deny action")


def format_permission_request(request: PermissionRequest) -> list[dict]:
    """Format a permission request as Slack Block Kit blocks.

    Args:
        request: The permission request to format.

    Returns:
        List of Slack Block Kit block dicts.
    """
    # Format the tool input for display
    tool_input = request.tool_input
    if "command" in tool_input:
        # Bash command
        input_display = tool_input["command"]
    elif "file_path" in tool_input:
        # File operation
        input_display = tool_input["file_path"]
        if "content" in tool_input:
            content = tool_input["content"]
            if len(content) > 200:
                content = content[:200] + "..."
            input_display += f"\n\n{content}"
    else:
        # Generic display
        import json
        input_display = json.dumps(tool_input, indent=2)
        if len(input_display) > 500:
            input_display = input_display[:500] + "..."

    # Get description if present
    description = tool_input.get("description", "")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🔐 Claude Code Permission Request",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Tool:* {request.tool_name}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{input_display}```",
            },
        },
    ]

    if description:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Description:* {description}",
            },
        })

    # Add timestamp
    timestamp = request.timestamp.strftime("%H:%M:%S")
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Requested at {timestamp}",
            },
        ],
    })

    # Add buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "✓ Approve",
                    "emoji": True,
                },
                "style": "primary",
                "action_id": "approve_permission",
                "value": request.request_id,
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "✗ Deny",
                    "emoji": True,
                },
                "style": "danger",
                "action_id": "deny_permission",
                "value": request.request_id,
            },
        ],
    })

    return blocks


def format_approved(request: PermissionRequest) -> list[dict]:
    """Format an approved message.

    Args:
        request: The original permission request.

    Returns:
        List of Slack Block Kit block dicts.
    """
    tool_input = request.tool_input
    if "command" in tool_input:
        input_display = tool_input["command"]
    elif "file_path" in tool_input:
        input_display = tool_input["file_path"]
    else:
        input_display = str(tool_input)[:100]

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"✅ Approved: {request.tool_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{input_display}```",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Approved via Slack",
                },
            ],
        },
    ]


def format_denied(request: PermissionRequest) -> list[dict]:
    """Format a denied message.

    Args:
        request: The original permission request.

    Returns:
        List of Slack Block Kit block dicts.
    """
    tool_input = request.tool_input
    if "command" in tool_input:
        input_display = tool_input["command"]
    elif "file_path" in tool_input:
        input_display = tool_input["file_path"]
    else:
        input_display = str(tool_input)[:100]

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"❌ Denied: {request.tool_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{input_display}```",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Denied via Slack",
                },
            ],
        },
    ]


def format_answered_locally(request: PermissionRequest) -> list[dict]:
    """Format a message for request answered locally (user returned).

    Args:
        request: The original permission request.

    Returns:
        List of Slack Block Kit block dicts.
    """
    tool_input = request.tool_input
    if "command" in tool_input:
        input_display = tool_input["command"]
    elif "file_path" in tool_input:
        input_display = tool_input["file_path"]
    else:
        input_display = str(tool_input)[:100]

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"⌨️ Answered Locally: {request.tool_name}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{input_display}```",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "You returned to your computer",
                },
            ],
        },
    ]


# Emoji mapping for notification types
NOTIFICATION_TYPE_EMOJI = {
    "idle_prompt": "⏳",
    "auth_success": "🔑",
    "elicitation_dialog": "💬",
}


def format_notification(notification: Notification) -> list[dict]:
    """Format a notification as Slack Block Kit blocks.

    Notifications are info-only messages without action buttons.

    Args:
        notification: The notification to format.

    Returns:
        List of Slack Block Kit block dicts.
    """
    # Get emoji for notification type
    emoji = NOTIFICATION_TYPE_EMOJI.get(notification.notification_type, "📢")

    # Format the notification type for display
    type_display = notification.notification_type.replace("_", " ").title()

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Claude Code: {type_display}",
                "emoji": True,
            },
        },
    ]

    # Add message if present
    if notification.message:
        # Truncate long messages
        message = notification.message
        if len(message) > 500:
            message = message[:500] + "..."

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message,
            },
        })

    # Add context with timestamp and optional cwd
    context_parts = [f"Received at {notification.timestamp.strftime('%H:%M:%S')}"]
    if notification.cwd:
        # Show just the last part of the path for brevity
        cwd_display = notification.cwd
        if len(cwd_display) > 50:
            cwd_display = "..." + cwd_display[-47:]
        context_parts.append(f"in `{cwd_display}`")

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": " • ".join(context_parts),
            },
        ],
    })

    return blocks
