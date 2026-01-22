"""State management for Claude Permission Daemon.

Contains data classes for requests/responses and the StateManager for coordinating state.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Callable, Coroutine
from uuid import uuid4

logger = logging.getLogger(__name__)


class Action(Enum):
    """Possible actions for a permission response."""

    APPROVE = "approve"
    DENY = "deny"
    PASSTHROUGH = "passthrough"


@dataclass
class PermissionRequest:
    """A permission request from Claude Code via the hook."""

    request_id: str
    tool_name: str
    tool_input: dict
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(cls, tool_name: str, tool_input: dict) -> "PermissionRequest":
        """Create a new permission request with generated ID and timestamp."""
        return cls(
            request_id=str(uuid4()),
            tool_name=tool_name,
            tool_input=tool_input,
        )


@dataclass
class PermissionResponse:
    """Response to a permission request."""

    action: Action
    reason: str

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "action": self.action.value,
            "reason": self.reason,
        }


@dataclass
class PendingRequest:
    """Internal tracking of a pending permission request.

    Holds the request, the asyncio writer to respond to the hook,
    and optional Slack message tracking info.
    """

    request: PermissionRequest
    hook_writer: asyncio.StreamWriter
    slack_message_ts: str | None = None
    slack_channel: str | None = None

    @property
    def request_id(self) -> str:
        """Convenience accessor for request_id."""
        return self.request.request_id


# Type alias for state change callbacks
IdleStateCallback = Callable[[bool], Coroutine[None, None, None]]


class StateManager:
    """Manages daemon state including idle status and pending requests.

    Thread-safe via asyncio locks. Provides callbacks for state changes.
    """

    def __init__(self) -> None:
        self._idle: bool = False
        self._pending_requests: dict[str, PendingRequest] = {}
        self._lock = asyncio.Lock()
        self._idle_callbacks: list[IdleStateCallback] = []

    @property
    def idle(self) -> bool:
        """Current idle state."""
        return self._idle

    def register_idle_callback(self, callback: IdleStateCallback) -> None:
        """Register a callback to be called when idle state changes.

        Callback receives the new idle state (True = idle, False = active).
        """
        self._idle_callbacks.append(callback)

    async def set_idle(self, idle: bool) -> None:
        """Set the idle state and notify callbacks if changed."""
        async with self._lock:
            if self._idle == idle:
                return
            old_state = self._idle
            self._idle = idle
            logger.info(f"Idle state changed: {old_state} -> {idle}")

        # Call callbacks outside the lock to avoid deadlocks
        for callback in self._idle_callbacks:
            try:
                await callback(idle)
            except Exception:
                logger.exception("Error in idle state callback")

    async def add_pending_request(self, pending: PendingRequest) -> None:
        """Add a pending request to track."""
        async with self._lock:
            self._pending_requests[pending.request_id] = pending
            logger.debug(f"Added pending request: {pending.request_id}")

    async def get_pending_request(self, request_id: str) -> PendingRequest | None:
        """Get a pending request by ID."""
        async with self._lock:
            return self._pending_requests.get(request_id)

    async def remove_pending_request(self, request_id: str) -> PendingRequest | None:
        """Remove and return a pending request by ID."""
        async with self._lock:
            pending = self._pending_requests.pop(request_id, None)
            if pending:
                logger.debug(f"Removed pending request: {request_id}")
            return pending

    async def get_all_pending_requests(self) -> list[PendingRequest]:
        """Get a list of all pending requests."""
        async with self._lock:
            return list(self._pending_requests.values())

    async def update_slack_info(
        self, request_id: str, message_ts: str, channel: str
    ) -> None:
        """Update Slack message info for a pending request."""
        async with self._lock:
            if pending := self._pending_requests.get(request_id):
                pending.slack_message_ts = message_ts
                pending.slack_channel = channel
                logger.debug(f"Updated Slack info for {request_id}: ts={message_ts}")

    async def clear_all_pending(self) -> list[PendingRequest]:
        """Clear and return all pending requests."""
        async with self._lock:
            pending = list(self._pending_requests.values())
            self._pending_requests.clear()
            logger.debug(f"Cleared {len(pending)} pending requests")
            return pending
