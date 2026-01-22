"""Tests for idle_monitor module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.config import SwayidleConfig
from claude_permission_daemon.idle_monitor import IdleMonitor, IdleMonitorError


class TestIdleMonitor:
    """Tests for IdleMonitor class."""

    @pytest.fixture
    def config(self) -> SwayidleConfig:
        """Provide swayidle config."""
        return SwayidleConfig(binary="swayidle")

    @pytest.fixture
    def idle_callback(self) -> AsyncMock:
        """Provide mock idle callback."""
        return AsyncMock()

    @pytest.fixture
    def monitor(
        self, config: SwayidleConfig, idle_callback: AsyncMock
    ) -> IdleMonitor:
        """Create IdleMonitor instance."""
        return IdleMonitor(
            config=config,
            idle_timeout=60,
            on_idle_change=idle_callback,
        )

    def test_initial_state(self, monitor: IdleMonitor) -> None:
        """Test initial idle state is False."""
        assert monitor.idle is False
        assert monitor.running is False

    def test_build_command(self, monitor: IdleMonitor) -> None:
        """Test command building."""
        with patch("shutil.which", return_value="/usr/bin/swayidle"):
            cmd = monitor._build_command()

        assert cmd[0] == "/usr/bin/swayidle"
        assert "-w" in cmd
        assert "timeout" in cmd
        assert "60" in cmd
        assert "echo IDLE" in cmd
        assert "resume" in cmd
        assert "echo ACTIVE" in cmd

    def test_build_command_absolute_path(self) -> None:
        """Test command building with absolute path."""
        config = SwayidleConfig(binary="/custom/path/swayidle")
        monitor = IdleMonitor(
            config=config,
            idle_timeout=30,
            on_idle_change=AsyncMock(),
        )
        cmd = monitor._build_command()
        assert cmd[0] == "/custom/path/swayidle"

    def test_find_binary_not_found(self, monitor: IdleMonitor) -> None:
        """Test error when binary not found in PATH."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(IdleMonitorError, match="not found"):
                monitor._find_binary()

    async def test_handle_output_idle(
        self, monitor: IdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test handling IDLE output."""
        await monitor._handle_output("IDLE")

        assert monitor.idle is True
        idle_callback.assert_called_once_with(True)

    async def test_handle_output_active(
        self, monitor: IdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test handling ACTIVE output."""
        # First set to idle
        monitor._current_idle = True

        await monitor._handle_output("ACTIVE")

        assert monitor.idle is False
        idle_callback.assert_called_once_with(False)

    async def test_handle_output_no_change(
        self, monitor: IdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test no callback when state doesn't change."""
        # Already not idle, ACTIVE should do nothing
        await monitor._handle_output("ACTIVE")

        assert monitor.idle is False
        idle_callback.assert_not_called()

    async def test_handle_output_unknown(
        self, monitor: IdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test unknown output is logged but ignored."""
        await monitor._handle_output("UNKNOWN")

        assert monitor.idle is False
        idle_callback.assert_not_called()

    async def test_start_already_running(self, monitor: IdleMonitor) -> None:
        """Test start when already running does nothing."""
        monitor._running = True
        await monitor.start()  # Should not raise

    async def test_stop_not_running(self, monitor: IdleMonitor) -> None:
        """Test stop when not running does nothing."""
        await monitor.stop()  # Should not raise

    async def test_start_binary_not_found(self, monitor: IdleMonitor) -> None:
        """Test start fails when binary not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(IdleMonitorError, match="not found"):
                await monitor.start()

    async def test_start_and_stop(
        self, config: SwayidleConfig, idle_callback: AsyncMock
    ) -> None:
        """Test start and stop with mocked subprocess."""
        monitor = IdleMonitor(
            config=config,
            idle_timeout=60,
            on_idle_change=idle_callback,
        )

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()

        async def mock_wait():
            mock_process.returncode = 0

        mock_process.wait = mock_wait

        with patch("shutil.which", return_value="/usr/bin/swayidle"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                await monitor.start()
                assert monitor.running is True

                await monitor.stop()
                assert monitor.running is False
                mock_process.terminate.assert_called_once()

    async def test_run_without_start(self, monitor: IdleMonitor) -> None:
        """Test run raises if not started."""
        with pytest.raises(IdleMonitorError, match="not started"):
            await monitor.run()

    async def test_restart(
        self, config: SwayidleConfig, idle_callback: AsyncMock
    ) -> None:
        """Test restart resets state and restarts subprocess."""
        monitor = IdleMonitor(
            config=config,
            idle_timeout=60,
            on_idle_change=idle_callback,
        )
        monitor._current_idle = True
        monitor._running = True

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.stdout = MagicMock()
        mock_process.stderr = MagicMock()
        mock_process.terminate = MagicMock()

        async def mock_wait():
            mock_process.returncode = 0

        mock_process.wait = mock_wait

        with patch("shutil.which", return_value="/usr/bin/swayidle"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                await monitor.restart()

                # Should have called callback with False (reset to active)
                idle_callback.assert_called_with(False)
                assert monitor.running is True
                assert monitor.idle is False


class TestIdleMonitorReadLoop:
    """Tests for the read loop functionality."""

    @pytest.fixture
    def config(self) -> SwayidleConfig:
        """Provide swayidle config."""
        return SwayidleConfig(binary="swayidle")

    async def test_run_reads_and_handles_output(self) -> None:
        """Test run loop reads output and calls handler."""
        config = SwayidleConfig(binary="swayidle")
        idle_callback = AsyncMock()
        monitor = IdleMonitor(
            config=config,
            idle_timeout=60,
            on_idle_change=idle_callback,
        )

        # Create mock stdout that returns IDLE then ACTIVE then EOF
        lines = [b"IDLE\n", b"ACTIVE\n", b""]
        line_iter = iter(lines)

        mock_stdout = MagicMock()

        async def mock_readline():
            return next(line_iter)

        mock_stdout.readline = mock_readline

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.stdout = mock_stdout

        monitor._process = mock_process
        monitor._running = True

        # Run should process lines and exit on EOF
        await monitor.run()

        # Should have received IDLE then ACTIVE
        assert idle_callback.call_count == 2
        idle_callback.assert_any_call(True)
        idle_callback.assert_any_call(False)
