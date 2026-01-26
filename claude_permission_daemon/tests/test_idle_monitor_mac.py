"""Tests for idle_monitor_mac module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.config import MacIdleConfig
from claude_permission_daemon.idle_monitor_mac import MacIdleMonitor, IdleMonitorError


class TestMacIdleMonitor:
    """Tests for MacIdleMonitor class."""

    @pytest.fixture
    def config(self) -> MacIdleConfig:
        """Provide Mac idle config."""
        return MacIdleConfig(binary="ioreg")

    @pytest.fixture
    def idle_callback(self) -> AsyncMock:
        """Provide mock idle callback."""
        return AsyncMock()

    @pytest.fixture
    def monitor(
        self, config: MacIdleConfig, idle_callback: AsyncMock
    ) -> MacIdleMonitor:
        """Create MacIdleMonitor instance."""
        return MacIdleMonitor(
            config=config,
            idle_timeout=60,
            on_idle_change=idle_callback,
        )

    def test_initial_state(self, monitor: MacIdleMonitor) -> None:
        """Test initial idle state is False."""
        assert monitor.idle is False
        assert monitor.running is False

    def test_find_binary_in_path(self, monitor: MacIdleMonitor) -> None:
        """Test finding binary in PATH."""
        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            binary = monitor._find_binary()
            assert binary == "/usr/sbin/ioreg"

    def test_find_binary_absolute_path(self) -> None:
        """Test using absolute path."""
        config = MacIdleConfig(binary="/custom/path/ioreg")
        monitor = MacIdleMonitor(
            config=config,
            idle_timeout=30,
            on_idle_change=AsyncMock(),
        )
        binary = monitor._find_binary()
        assert binary == "/custom/path/ioreg"

    def test_find_binary_not_found(self, monitor: MacIdleMonitor) -> None:
        """Test error when binary not found in PATH."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(IdleMonitorError, match="not found"):
                monitor._find_binary()

    async def test_get_idle_time_success(self, monitor: MacIdleMonitor) -> None:
        """Test successful idle time retrieval."""
        # Mock ioreg output with HIDIdleTime
        mock_output = b'"HIDIdleTime" = 45000000000\n'

        mock_process = MagicMock()
        mock_process.returncode = 0

        async def mock_communicate():
            return (mock_output, b"")

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns == 45000000000

    async def test_get_idle_time_no_match(self, monitor: MacIdleMonitor) -> None:
        """Test when HIDIdleTime not found in output."""
        mock_output = b"Some other output\n"

        mock_process = MagicMock()
        mock_process.returncode = 0

        async def mock_communicate():
            return (mock_output, b"")

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns is None

    async def test_get_idle_time_command_failure(
        self, monitor: MacIdleMonitor
    ) -> None:
        """Test when ioreg command fails."""
        mock_process = MagicMock()
        mock_process.returncode = 1

        async def mock_communicate():
            return (b"", b"Error message\n")

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns is None

    async def test_get_idle_time_timeout(self, monitor: MacIdleMonitor) -> None:
        """Test timeout handling."""
        mock_process = MagicMock()

        async def mock_communicate():
            await asyncio.sleep(10)  # Long enough to trigger timeout

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns is None

    async def test_get_idle_time_file_not_found(
        self, monitor: MacIdleMonitor
    ) -> None:
        """Test FileNotFoundError handling."""
        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError(),
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns is None

    async def test_start_success(self, monitor: MacIdleMonitor) -> None:
        """Test successful start."""
        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            await monitor.start()

        assert monitor.running is True
        assert monitor.idle is False

    async def test_start_already_running(self, monitor: MacIdleMonitor) -> None:
        """Test start when already running does nothing."""
        monitor._running = True
        await monitor.start()  # Should not raise

    async def test_start_binary_not_found(self, monitor: MacIdleMonitor) -> None:
        """Test start fails when binary not found."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(IdleMonitorError, match="not found"):
                await monitor.start()

    async def test_stop_not_running(self, monitor: MacIdleMonitor) -> None:
        """Test stop when not running does nothing."""
        await monitor.stop()  # Should not raise

    async def test_stop_cancels_poll_task(self, monitor: MacIdleMonitor) -> None:
        """Test stop cancels running poll task."""
        monitor._running = True

        # Create a real task that we can cancel
        async def dummy_task():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                # Expected when the monitor stops and cancels the poll task; ignore.
                pass

        mock_task = asyncio.create_task(dummy_task())
        monitor._poll_task = mock_task

        await monitor.stop()

        assert monitor.running is False
        assert mock_task.cancelled() or mock_task.done()

    async def test_run_without_start(self, monitor: MacIdleMonitor) -> None:
        """Test run raises if not started."""
        with pytest.raises(IdleMonitorError, match="not started"):
            await monitor.run()

    async def test_run_transitions_to_idle(
        self, monitor: MacIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test run detects transition to idle state."""
        monitor._running = True

        # Mock get_idle_time to return increasing idle time
        idle_times = [
            30_000_000_000,  # 30 seconds - not idle yet
            70_000_000_000,  # 70 seconds - now idle!
            None,  # Stop loop
        ]
        idle_iter = iter(idle_times)

        async def mock_get_idle():
            val = next(idle_iter, None)
            if val is None:
                monitor._running = False
            return val

        with patch.object(monitor, "_get_idle_time_ns", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should have called callback once with True (became idle)
        idle_callback.assert_called_once_with(True)
        assert monitor.idle is True

    async def test_run_transitions_to_active(
        self, monitor: MacIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test run detects transition from idle to active."""
        monitor._running = True
        monitor._current_idle = True  # Start in idle state

        # Mock get_idle_time to return decreasing idle time
        idle_times = [
            70_000_000_000,  # 70 seconds - still idle
            30_000_000_000,  # 30 seconds - now active!
            None,  # Stop loop
        ]
        idle_iter = iter(idle_times)

        async def mock_get_idle():
            val = next(idle_iter, None)
            if val is None:
                monitor._running = False
            return val

        with patch.object(monitor, "_get_idle_time_ns", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should have called callback once with False (became active)
        idle_callback.assert_called_once_with(False)
        assert monitor.idle is False

    async def test_run_no_change(
        self, monitor: MacIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test no callback when state doesn't change."""
        monitor._running = True

        # Mock get_idle_time to return consistent active time
        call_count = [0]

        async def mock_get_idle():
            call_count[0] += 1
            if call_count[0] > 3:
                monitor._running = False
                return None
            return 30_000_000_000  # Always 30 seconds - always active

        with patch.object(monitor, "_get_idle_time_ns", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should not have called callback (no state change)
        idle_callback.assert_not_called()
        assert monitor.idle is False

    async def test_run_handles_none_idle_time(
        self, monitor: MacIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test run continues when idle time cannot be determined."""
        monitor._running = True

        # Mock get_idle_time to return None (error) a few times
        call_count = [0]

        async def mock_get_idle():
            call_count[0] += 1
            if call_count[0] > 3:
                monitor._running = False
            return None  # Can't determine idle time

        with patch.object(monitor, "_get_idle_time_ns", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should not have called callback or changed state
        idle_callback.assert_not_called()
        assert monitor.idle is False

    async def test_run_handles_cancelled(self, monitor: MacIdleMonitor) -> None:
        """Test run handles cancellation gracefully."""
        monitor._running = True

        async def mock_get_idle():
            raise asyncio.CancelledError()

        with patch.object(monitor, "_get_idle_time_ns", side_effect=mock_get_idle):
            with pytest.raises(asyncio.CancelledError):
                await monitor.run()

        assert monitor.running is False

    async def test_restart(
        self, config: MacIdleConfig, idle_callback: AsyncMock
    ) -> None:
        """Test restart resets state."""
        monitor = MacIdleMonitor(
            config=config,
            idle_timeout=60,
            on_idle_change=idle_callback,
        )
        monitor._current_idle = True
        monitor._running = True

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            await monitor.restart()

        # Should have called callback with False (reset to active)
        idle_callback.assert_called_with(False)
        assert monitor.running is True
        assert monitor.idle is False


class TestMacIdleMonitorParseOutput:
    """Tests for ioreg output parsing."""

    @pytest.fixture
    def monitor(self) -> MacIdleMonitor:
        """Create MacIdleMonitor instance."""
        config = MacIdleConfig(binary="ioreg")
        return MacIdleMonitor(
            config=config,
            idle_timeout=60,
            on_idle_change=AsyncMock(),
        )

    async def test_parse_typical_output(self, monitor: MacIdleMonitor) -> None:
        """Test parsing typical ioreg output."""
        output = b'''
+-o IOHIDSystem  <class IOHIDSystem, id 0x100000123, registered, matched, active, busy 0 (0 ms), retain 10>
    {
      "HIDIdleTime" = 12345678901
      "IOClass" = "IOHIDSystem"
    }
'''
        mock_process = MagicMock()
        mock_process.returncode = 0

        async def mock_communicate():
            return (output, b"")

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns == 12345678901

    async def test_parse_zero_idle_time(self, monitor: MacIdleMonitor) -> None:
        """Test parsing zero idle time (just used input)."""
        output = b'"HIDIdleTime" = 0\n'

        mock_process = MagicMock()
        mock_process.returncode = 0

        async def mock_communicate():
            return (output, b"")

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns == 0

    async def test_parse_large_idle_time(self, monitor: MacIdleMonitor) -> None:
        """Test parsing large idle time value."""
        output = b'"HIDIdleTime" = 999999999999999\n'

        mock_process = MagicMock()
        mock_process.returncode = 0

        async def mock_communicate():
            return (output, b"")

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns == 999999999999999

    async def test_parse_invalid_value(self, monitor: MacIdleMonitor) -> None:
        """Test handling invalid HIDIdleTime value."""
        output = b'"HIDIdleTime" = invalid\n'

        mock_process = MagicMock()
        mock_process.returncode = 0

        async def mock_communicate():
            return (output, b"")

        mock_process.communicate = mock_communicate

        with patch("shutil.which", return_value="/usr/sbin/ioreg"):
            with patch(
                "asyncio.create_subprocess_exec",
                return_value=mock_process,
            ):
                idle_ns = await monitor._get_idle_time_ns()

        assert idle_ns is None
