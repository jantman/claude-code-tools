"""Idle monitoring via swayidle subprocess.

Manages a swayidle subprocess that reports idle/active state changes.
"""

import asyncio
import logging
import shutil
from typing import Callable, Coroutine

from .config import SwayidleConfig

logger = logging.getLogger(__name__)

# Type alias for idle state callback
IdleCallback = Callable[[bool], Coroutine[None, None, None]]


class IdleMonitorError(Exception):
    """Error related to idle monitoring."""

    pass


class IdleMonitor:
    """Monitors user idle state using swayidle subprocess.

    Spawns swayidle configured to print IDLE/ACTIVE to stdout,
    then reads and parses that output to track idle state.
    """

    def __init__(
        self,
        config: SwayidleConfig,
        idle_timeout: int,
        on_idle_change: IdleCallback,
    ) -> None:
        """Initialize the idle monitor.

        Args:
            config: Swayidle configuration (binary path).
            idle_timeout: Seconds of inactivity before considered idle.
            on_idle_change: Async callback called when idle state changes.
        """
        self._config = config
        self._idle_timeout = idle_timeout
        self._on_idle_change = on_idle_change
        self._process: asyncio.subprocess.Process | None = None
        self._running = False
        self._current_idle = False
        self._stderr_task: asyncio.Task | None = None

    @property
    def idle(self) -> bool:
        """Current idle state."""
        return self._current_idle

    @property
    def running(self) -> bool:
        """Whether the monitor is currently running."""
        return self._running

    def _find_binary(self) -> str:
        """Find the swayidle binary path.

        Returns:
            Resolved path to swayidle binary.

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
                f"swayidle binary '{binary}' not found in PATH. "
                "Install swayidle or specify full path in config."
            )
        return found

    def _build_command(self) -> list[str]:
        """Build the swayidle command with arguments.

        Returns:
            Command list suitable for asyncio.create_subprocess_exec.
        """
        binary = self._find_binary()
        return [
            binary,
            "-w",  # Wait for command to finish
            "timeout",
            str(self._idle_timeout),
            "echo IDLE",
            "resume",
            "echo ACTIVE",
        ]

    async def start(self) -> None:
        """Start the swayidle subprocess and begin monitoring.

        Raises:
            IdleMonitorError: If subprocess fails to start.
        """
        if self._running:
            logger.warning("IdleMonitor already running")
            return

        cmd = self._build_command()
        logger.info(f"Starting swayidle: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise IdleMonitorError(f"Failed to start swayidle: {e}") from e
        except OSError as e:
            raise IdleMonitorError(f"Failed to start swayidle: {e}") from e

        self._running = True
        self._current_idle = False
        # Start stderr reader task
        self._stderr_task = asyncio.create_task(
            self._read_stderr(), name="swayidle_stderr"
        )
        logger.info("IdleMonitor started")

    async def stop(self) -> None:
        """Stop the swayidle subprocess."""
        if not self._running or self._process is None:
            return

        self._running = False

        # Cancel stderr reader task
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

        if self._process.returncode is None:
            logger.info("Terminating swayidle subprocess")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("swayidle did not terminate, killing")
                self._process.kill()
                await self._process.wait()

        self._process = None
        logger.info("IdleMonitor stopped")

    async def run(self) -> None:
        """Main loop: read swayidle output and trigger callbacks.

        This should be run as an asyncio task. It will run until stop() is called
        or the subprocess exits unexpectedly.
        """
        if self._process is None or self._process.stdout is None:
            logger.error("IdleMonitor.run() called but process or stdout is None")
            raise IdleMonitorError("IdleMonitor not started")

        logger.debug("Starting idle monitor read loop")
        loop_count = 0

        try:
            while self._running:
                try:
                    line = await asyncio.wait_for(
                        self._process.stdout.readline(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    loop_count += 1
                    # Log every 60 iterations (roughly once per minute) to show we're alive
                    if loop_count % 60 == 0:
                        logger.debug(
                            f"Idle monitor still waiting for swayidle output "
                            f"(loop count: {loop_count})"
                        )
                    # Check if still running and continue
                    if not self._running:
                        break
                    # Check if process died
                    if self._process.returncode is not None:
                        logger.error(
                            f"swayidle exited unexpectedly: {self._process.returncode}"
                        )
                        break
                    continue

                if not line:
                    # EOF - process exited
                    if self._running:
                        logger.error("swayidle stdout closed unexpectedly")
                    break

                text = line.decode().strip()
                if not text:
                    continue

                logger.debug(f"swayidle stdout: {text}")
                await self._handle_output(text)

        except Exception:
            logger.exception("Error in idle monitor read loop")
            raise
        finally:
            self._running = False

    async def _handle_output(self, text: str) -> None:
        """Handle a line of output from swayidle.

        Args:
            text: Trimmed output line from swayidle.
        """
        if text == "IDLE":
            if not self._current_idle:
                self._current_idle = True
                logger.info("User is now idle")
                await self._on_idle_change(True)
        elif text == "ACTIVE":
            if self._current_idle:
                self._current_idle = False
                logger.info("User is now active")
                await self._on_idle_change(False)
        else:
            logger.warning(f"Unexpected swayidle output: {text}")

    async def _read_stderr(self) -> None:
        """Read and log stderr from swayidle subprocess."""
        if self._process is None or self._process.stderr is None:
            return

        try:
            while self._running:
                try:
                    line = await asyncio.wait_for(
                        self._process.stderr.readline(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    if not self._running:
                        break
                    continue

                if not line:
                    break

                text = line.decode().strip()
                if text:
                    logger.warning(f"swayidle stderr: {text}")
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error reading swayidle stderr")

    async def restart(self) -> None:
        """Restart the swayidle subprocess.

        Useful for recovery after unexpected exit.
        """
        logger.info("Restarting IdleMonitor")
        await self.stop()
        # Reset idle state on restart
        if self._current_idle:
            self._current_idle = False
            await self._on_idle_change(False)
        await self.start()
