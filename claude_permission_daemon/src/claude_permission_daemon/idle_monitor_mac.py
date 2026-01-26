"""Idle monitoring for macOS using ioreg.

Monitors user idle state by polling IOHIDSystem via ioreg command.
"""

import asyncio
import logging
import re
import shutil

from .base_idle_monitor import BaseIdleMonitor, IdleCallback, IdleMonitorError
from .config import MacIdleConfig

logger = logging.getLogger(__name__)

# Regex to extract HIDIdleTime from ioreg output
# Example: "HIDIdleTime" = 12345678901
IDLE_TIME_PATTERN = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')


class MacIdleMonitor(BaseIdleMonitor):
    """Monitors user idle state on macOS using ioreg.

    Polls the IOHIDSystem service via `ioreg -c IOHIDSystem` to read HIDIdleTime,
    which reports nanoseconds since last user input (keyboard/mouse/trackpad).
    """

    def __init__(
        self,
        config: MacIdleConfig,
        idle_timeout: int,
        on_idle_change: IdleCallback,
    ) -> None:
        """Initialize the Mac idle monitor.

        Args:
            config: macOS idle configuration (ioreg binary path).
            idle_timeout: Seconds of inactivity before considered idle.
            on_idle_change: Async callback called when idle state changes.
        """
        self._config = config
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

    def _find_binary(self) -> str:
        """Find the ioreg binary path.

        Returns:
            Resolved path to ioreg binary.

        Raises:
            IdleMonitorError: If binary not found.
        """
        binary = self._config.binary
        if "/" in binary:
            # Absolute or relative path specified
            return binary

        # Search in PATH
        found = shutil.which(binary)
        if found is None:
            raise IdleMonitorError(
                f"ioreg binary '{binary}' not found in PATH. "
                "On macOS, ioreg should be available at /usr/sbin/ioreg. "
                "If not found, specify full path in config."
            )
        return found

    async def _get_idle_time_ns(self) -> int | None:
        """Query IOHIDSystem for current idle time.

        Returns:
            Idle time in nanoseconds, or None if unable to determine.
        """
        binary = self._find_binary()
        cmd = [binary, "-c", "IOHIDSystem"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=5.0
            )
        except asyncio.TimeoutError:
            logger.warning("ioreg command timed out")
            return None
        except (FileNotFoundError, OSError) as e:
            logger.error(f"Failed to execute ioreg: {e}")
            return None

        if proc.returncode != 0:
            stderr_text = stderr.decode().strip() if stderr else ""
            logger.error(
                f"ioreg exited with code {proc.returncode}: {stderr_text}"
            )
            return None

        # Parse output for HIDIdleTime
        output = stdout.decode()
        match = IDLE_TIME_PATTERN.search(output)
        if not match:
            logger.warning("Could not find HIDIdleTime in ioreg output")
            return None

        try:
            idle_ns = int(match.group(1))
            return idle_ns
        except ValueError as e:
            logger.error(f"Failed to parse HIDIdleTime value: {e}")
            return None

    async def start(self) -> None:
        """Start the idle monitor.

        Raises:
            IdleMonitorError: If monitor fails to start.
        """
        if self._running:
            logger.warning("MacIdleMonitor already running")
            return

        # Verify ioreg is available
        try:
            self._find_binary()
        except IdleMonitorError:
            raise

        self._running = True
        self._current_idle = False

        # Create background polling task
        self._poll_task = asyncio.create_task(self.run(), name="mac_idle_poll")

        logger.info("MacIdleMonitor started")

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
                # Expected when stopping: the polling task is cancelled intentionally.
                logger.debug("MacIdleMonitor poll task cancelled during stop()")
            self._poll_task = None

        logger.info("MacIdleMonitor stopped")

    async def run(self) -> None:
        """Main monitoring loop.

        Polls ioreg every second to check idle time and triggers callbacks
        when idle state transitions occur.
        """
        if not self._running:
            logger.error("MacIdleMonitor.run() called but monitor not started")
            raise IdleMonitorError("MacIdleMonitor not started")

        logger.debug("Starting Mac idle monitor poll loop")
        poll_interval = 1.0  # Check every second
        loop_count = 0

        try:
            while self._running:
                idle_ns = await self._get_idle_time_ns()

                if idle_ns is not None:
                    idle_seconds = idle_ns / 1_000_000_000
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
                            f"Mac idle monitor poll (idle: {self._current_idle}, "
                            f"idle_time: {idle_seconds:.1f}s, loop: {loop_count})"
                        )
                else:
                    # Failed to get idle time - log occasionally but keep running
                    loop_count += 1
                    if loop_count % 60 == 0:
                        logger.warning(
                            "Unable to determine idle time from ioreg "
                            f"(loop count: {loop_count})"
                        )

                # Wait before next poll
                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.debug("Mac idle monitor poll loop cancelled")
            raise
        except Exception:
            logger.exception("Error in Mac idle monitor poll loop")
            raise
        finally:
            self._running = False

    async def restart(self) -> None:
        """Restart the idle monitor.

        Useful for recovery after unexpected issues.
        """
        logger.info("Restarting MacIdleMonitor")
        await self.stop()
        # Reset idle state on restart
        if self._current_idle:
            self._current_idle = False
            await self._on_idle_change(False)
        await self.start()
