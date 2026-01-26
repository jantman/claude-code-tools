"""Idle monitoring for Windows using ctypes.

Monitors user idle state by polling GetLastInputInfo via ctypes.
"""

import asyncio
import logging
from ctypes import Structure, c_uint

from .base_idle_monitor import BaseIdleMonitor, IdleCallback, IdleMonitorError

logger = logging.getLogger(__name__)

# Import Windows-specific items only when needed to avoid ImportError on non-Windows
try:
    from ctypes import byref, sizeof, windll
    from ctypes.wintypes import DWORD

    WINDOWS_AVAILABLE = True
except (ImportError, AttributeError):
    # Not on Windows or windll not available
    WINDOWS_AVAILABLE = False
    DWORD = None  # type: ignore
    # Create dummy objects for testing on non-Windows platforms
    windll = None  # type: ignore
    byref = None  # type: ignore
    sizeof = None  # type: ignore


if WINDOWS_AVAILABLE:

    class LASTINPUTINFO(Structure):
        """Structure for GetLastInputInfo Win32 API call."""

        _fields_ = [
            ("cbSize", c_uint),
            ("dwTime", DWORD),  # type: ignore
        ]

else:
    # Dummy class for non-Windows platforms
    LASTINPUTINFO = None  # type: ignore


class WindowsIdleMonitor(BaseIdleMonitor):
    """Monitors user idle state on Windows using GetLastInputInfo.

    Polls the Windows API GetLastInputInfo function to determine milliseconds
    since last user input (keyboard/mouse). Compares this to the idle timeout
    to track idle state transitions.
    """

    def __init__(
        self,
        idle_timeout: int,
        on_idle_change: IdleCallback,
    ) -> None:
        """Initialize the Windows idle monitor.

        Args:
            idle_timeout: Seconds of inactivity before considered idle.
            on_idle_change: Async callback called when idle state changes.
        """
        self._idle_timeout = idle_timeout
        self._on_idle_change = on_idle_change
        self._running = False
        self._current_idle = False
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def idle(self) -> bool:
        """Current idle state."""
        return self._current_idle

    @property
    def running(self) -> bool:
        """Whether the monitor is currently running."""
        return self._running

    def _get_idle_time_seconds(self) -> float | None:
        """Query Windows API for current idle time.

        Returns:
            Idle time in seconds, or None if unable to determine.
        """
        if not WINDOWS_AVAILABLE:
            logger.error("Windows API not available on this platform")
            return None

        try:
            # Create LASTINPUTINFO structure
            last_input_info = LASTINPUTINFO()  # type: ignore
            last_input_info.cbSize = sizeof(LASTINPUTINFO)  # type: ignore

            # Call GetLastInputInfo
            if not windll.user32.GetLastInputInfo(byref(last_input_info)):
                logger.warning("GetLastInputInfo failed")
                return None

            # Get current tick count
            current_ticks = windll.kernel32.GetTickCount()

            # Calculate idle time (tick count is in milliseconds)
            idle_ms = current_ticks - last_input_info.dwTime

            # Handle tick count rollover (happens after ~49.7 days)
            # If idle_ms is negative, the tick count rolled over
            if idle_ms < 0:
                # Estimate by assuming small idle time
                idle_ms = 0
                logger.debug("Tick count rollover detected, resetting idle time to 0")

            return idle_ms / 1000.0

        except AttributeError as e:
            # This happens if windll.user32 or windll.kernel32 is not available
            # (e.g., not on Windows)
            logger.error(f"Windows API not available: {e}")
            return None
        except Exception as e:
            logger.error(f"Error querying Windows idle time: {e}")
            return None

    async def start(self) -> None:
        """Start the idle monitor.

        Raises:
            IdleMonitorError: If monitor fails to start.
        """
        if self._running:
            logger.warning("WindowsIdleMonitor already running")
            return

        # Verify Windows API is available with a test call
        test_idle = self._get_idle_time_seconds()
        if test_idle is None:
            raise IdleMonitorError(
                "Failed to query Windows idle time. "
                "GetLastInputInfo API not available. "
                "This feature requires Windows."
            )

        self._running = True
        self._current_idle = False
        logger.info("WindowsIdleMonitor started")

    async def stop(self) -> None:
        """Stop the idle monitor."""
        if not self._running:
            return

        self._running = False

        # Cancel poll task if running
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        logger.info("WindowsIdleMonitor stopped")

    async def run(self) -> None:
        """Main monitoring loop.

        Polls GetLastInputInfo every second to check idle time and triggers
        callbacks when idle state transitions occur.
        """
        if not self._running:
            logger.error("WindowsIdleMonitor.run() called but monitor not started")
            raise IdleMonitorError("WindowsIdleMonitor not started")

        logger.debug("Starting Windows idle monitor poll loop")
        poll_interval = 1.0  # Check every second
        loop_count = 0

        try:
            while self._running:
                idle_seconds = self._get_idle_time_seconds()

                if idle_seconds is not None:
                    is_idle = idle_seconds >= self._idle_timeout

                    # Trigger callback if state changed
                    if is_idle and not self._current_idle:
                        self._current_idle = True
                        logger.info(f"User is now idle ({idle_seconds:.1f}s)")
                        await self._on_idle_change(True)
                    elif not is_idle and self._current_idle:
                        self._current_idle = False
                        logger.info(f"User is now active ({idle_seconds:.1f}s)")
                        await self._on_idle_change(False)

                    # Debug logging every 60 iterations
                    loop_count += 1
                    if loop_count % 60 == 0:
                        logger.debug(
                            f"Windows idle monitor poll (idle: {self._current_idle}, "
                            f"idle_time: {idle_seconds:.1f}s, loop: {loop_count})"
                        )
                else:
                    # Failed to get idle time - log occasionally but keep running
                    loop_count += 1
                    if loop_count % 60 == 0:
                        logger.warning(
                            "Unable to determine idle time from Windows API "
                            f"(loop count: {loop_count})"
                        )

                # Wait before next poll
                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.debug("Windows idle monitor poll loop cancelled")
            raise
        except Exception:
            logger.exception("Error in Windows idle monitor poll loop")
            raise
        finally:
            self._running = False

    async def restart(self) -> None:
        """Restart the idle monitor.

        Useful for recovery after unexpected issues.
        """
        logger.info("Restarting WindowsIdleMonitor")
        await self.stop()
        # Reset idle state on restart
        if self._current_idle:
            self._current_idle = False
            await self._on_idle_change(False)
        await self.start()
