"""Base class for idle monitoring implementations.

Defines the abstract interface that all idle monitor backends must implement.
"""

from abc import ABC, abstractmethod
from typing import Callable, Coroutine

# Type alias for idle state callback
IdleCallback = Callable[[bool], Coroutine[None, None, None]]


class IdleMonitorError(Exception):
    """Error related to idle monitoring."""

    pass


class BaseIdleMonitor(ABC):
    """Abstract base class for idle monitoring implementations.

    All idle monitor backends (swayidle, macOS, Windows) must inherit from
    this class and implement its abstract methods. The monitor tracks whether
    the user is idle (no keyboard/mouse activity for a specified duration) and
    calls a callback when idle state changes.

    Lifecycle:
        1. Instantiate with configuration and callback
        2. Call start() to begin monitoring
        3. Call run() in an asyncio task to process idle state changes
        4. Call stop() to clean up resources

    Implementations must:
        - Track idle state internally
        - Call the on_idle_change callback when state transitions occur
        - Handle errors gracefully and raise IdleMonitorError when appropriate
        - Support clean shutdown via stop()
    """

    @property
    @abstractmethod
    def idle(self) -> bool:
        """Current idle state.

        Returns:
            True if user is currently idle, False if active.
        """
        pass

    @property
    @abstractmethod
    def running(self) -> bool:
        """Whether the monitor is currently running.

        Returns:
            True if monitor is running, False otherwise.
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """Start the idle monitor.

        Initialize resources and begin idle detection. This method should be
        idempotent - calling it multiple times should not cause issues.

        Raises:
            IdleMonitorError: If monitor fails to start.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the idle monitor.

        Clean up resources and stop idle detection. This method should be
        idempotent and safe to call even if not running.
        """
        pass

    @abstractmethod
    async def run(self) -> None:
        """Main monitoring loop.

        This method should run continuously (typically in an asyncio task)
        until stop() is called. It monitors idle state and triggers the
        on_idle_change callback when state transitions occur.

        The implementation should:
            - Check idle state periodically or listen for events
            - Call on_idle_change(True) when user becomes idle
            - Call on_idle_change(False) when user becomes active
            - Exit cleanly when stop() is called
            - Handle errors and raise IdleMonitorError if unable to continue

        Raises:
            IdleMonitorError: If monitoring cannot continue.
        """
        pass

    async def restart(self) -> None:
        """Restart the idle monitor.

        Default implementation that subclasses can override if needed.
        Stops and starts the monitor, resetting idle state.
        """
        await self.stop()
        await self.start()
