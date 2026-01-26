"""Tests for idle_monitor_windows module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_permission_daemon.idle_monitor_windows import (
    WindowsIdleMonitor,
    IdleMonitorError,
)


class TestWindowsIdleMonitor:
    """Tests for WindowsIdleMonitor class."""

    @pytest.fixture
    def idle_callback(self) -> AsyncMock:
        """Provide mock idle callback."""
        return AsyncMock()

    @pytest.fixture
    def monitor(self, idle_callback: AsyncMock) -> WindowsIdleMonitor:
        """Create WindowsIdleMonitor instance."""
        return WindowsIdleMonitor(
            idle_timeout=60,
            on_idle_change=idle_callback,
        )

    def test_initial_state(self, monitor: WindowsIdleMonitor) -> None:
        """Test initial idle state is False."""
        assert monitor.idle is False
        assert monitor.running is False

    def test_get_idle_time_success(self, monitor: WindowsIdleMonitor) -> None:
        """Test successful idle time retrieval."""
        # Mock the Windows API calls
        mock_windll = MagicMock()
        # GetLastInputInfo returns True (success)
        mock_windll.user32.GetLastInputInfo.return_value = True
        # Current tick count: 10000ms
        mock_windll.kernel32.GetTickCount.return_value = 10000

        # Create mock LASTINPUTINFO
        mock_lastinputinfo = MagicMock()
        mock_lastinputinfo.dwTime = 5000  # 5 seconds ago
        mock_lastinputinfo.cbSize = 8

        with patch("claude_permission_daemon.idle_monitor_windows.WINDOWS_AVAILABLE", True):
            with patch("claude_permission_daemon.idle_monitor_windows.windll", mock_windll):
                with patch("claude_permission_daemon.idle_monitor_windows.sizeof", return_value=8):
                    with patch("claude_permission_daemon.idle_monitor_windows.byref", side_effect=lambda x: x):
                        with patch("claude_permission_daemon.idle_monitor_windows.LASTINPUTINFO", return_value=mock_lastinputinfo):
                            idle_seconds = monitor._get_idle_time_seconds()

        # Idle time should be (10000 - 5000) / 1000 = 5 seconds
        assert idle_seconds == 5.0

    def test_get_idle_time_api_failure(self, monitor: WindowsIdleMonitor) -> None:
        """Test when GetLastInputInfo returns False."""
        mock_windll = MagicMock()
        mock_windll.user32.GetLastInputInfo.return_value = False

        with patch("claude_permission_daemon.idle_monitor_windows.windll", mock_windll):
            idle_seconds = monitor._get_idle_time_seconds()

        assert idle_seconds is None

    def test_get_idle_time_api_not_available(
        self, monitor: WindowsIdleMonitor
    ) -> None:
        """Test when Windows API is not available."""
        # Mock windll to raise AttributeError (not on Windows)
        with patch(
            "claude_permission_daemon.idle_monitor_windows.windll",
            side_effect=AttributeError("windll not available"),
        ):
            idle_seconds = monitor._get_idle_time_seconds()

        assert idle_seconds is None

    def test_get_idle_time_exception(self, monitor: WindowsIdleMonitor) -> None:
        """Test exception handling."""
        mock_windll = MagicMock()
        mock_windll.user32.GetLastInputInfo.side_effect = Exception("API error")

        with patch("claude_permission_daemon.idle_monitor_windows.windll", mock_windll):
            idle_seconds = monitor._get_idle_time_seconds()

        assert idle_seconds is None

    def test_get_idle_time_tick_rollover(self, monitor: WindowsIdleMonitor) -> None:
        """Test handling of tick count rollover."""
        mock_windll = MagicMock()
        mock_windll.user32.GetLastInputInfo.return_value = True
        # Current tick rolled over to low value
        mock_windll.kernel32.GetTickCount.return_value = 1000

        # Create mock LASTINPUTINFO with time before rollover
        mock_lastinputinfo = MagicMock()
        mock_lastinputinfo.dwTime = 4294967290  # Near max DWORD
        mock_lastinputinfo.cbSize = 8

        with patch("claude_permission_daemon.idle_monitor_windows.WINDOWS_AVAILABLE", True):
            with patch("claude_permission_daemon.idle_monitor_windows.windll", mock_windll):
                with patch("claude_permission_daemon.idle_monitor_windows.sizeof", return_value=8):
                    with patch("claude_permission_daemon.idle_monitor_windows.byref", side_effect=lambda x: x):
                        with patch("claude_permission_daemon.idle_monitor_windows.LASTINPUTINFO", return_value=mock_lastinputinfo):
                            idle_seconds = monitor._get_idle_time_seconds()

        # Should handle rollover gracefully and return 0
        assert idle_seconds == 0.0

    async def test_start_success(self, monitor: WindowsIdleMonitor) -> None:
        """Test successful start."""
        # Mock successful idle time retrieval
        with patch.object(monitor, "_get_idle_time_seconds", return_value=10.0):
            await monitor.start()

        assert monitor.running is True
        assert monitor.idle is False

    async def test_start_already_running(self, monitor: WindowsIdleMonitor) -> None:
        """Test start when already running does nothing."""
        monitor._running = True
        await monitor.start()  # Should not raise

    async def test_start_api_not_available(
        self, monitor: WindowsIdleMonitor
    ) -> None:
        """Test start fails when Windows API not available."""
        with patch.object(monitor, "_get_idle_time_seconds", return_value=None):
            with pytest.raises(IdleMonitorError, match="not available"):
                await monitor.start()

    async def test_stop_not_running(self, monitor: WindowsIdleMonitor) -> None:
        """Test stop when not running does nothing."""
        await monitor.stop()  # Should not raise

    async def test_stop_cancels_poll_task(
        self, monitor: WindowsIdleMonitor
    ) -> None:
        """Test stop cancels running poll task."""
        monitor._running = True

        # Create a real task that we can cancel
        async def dummy_task():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass

        mock_task = asyncio.create_task(dummy_task())
        monitor._poll_task = mock_task

        await monitor.stop()

        assert monitor.running is False
        assert mock_task.cancelled() or mock_task.done()

    async def test_run_without_start(self, monitor: WindowsIdleMonitor) -> None:
        """Test run raises if not started."""
        with pytest.raises(IdleMonitorError, match="not started"):
            await monitor.run()

    async def test_run_transitions_to_idle(
        self, monitor: WindowsIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test run detects transition to idle state."""
        monitor._running = True

        # Mock get_idle_time to return increasing idle time
        idle_times = [
            30.0,  # 30 seconds - not idle yet
            70.0,  # 70 seconds - now idle!
            None,  # Stop loop
        ]
        idle_iter = iter(idle_times)

        def mock_get_idle():
            val = next(idle_iter, None)
            if val is None:
                monitor._running = False
            return val

        with patch.object(monitor, "_get_idle_time_seconds", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should have called callback once with True (became idle)
        idle_callback.assert_called_once_with(True)
        assert monitor.idle is True

    async def test_run_transitions_to_active(
        self, monitor: WindowsIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test run detects transition from idle to active."""
        monitor._running = True
        monitor._current_idle = True  # Start in idle state

        # Mock get_idle_time to return decreasing idle time
        idle_times = [
            70.0,  # 70 seconds - still idle
            30.0,  # 30 seconds - now active!
            None,  # Stop loop
        ]
        idle_iter = iter(idle_times)

        def mock_get_idle():
            val = next(idle_iter, None)
            if val is None:
                monitor._running = False
            return val

        with patch.object(monitor, "_get_idle_time_seconds", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should have called callback once with False (became active)
        idle_callback.assert_called_once_with(False)
        assert monitor.idle is False

    async def test_run_no_change(
        self, monitor: WindowsIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test no callback when state doesn't change."""
        monitor._running = True

        # Mock get_idle_time to return consistent active time
        call_count = [0]

        def mock_get_idle():
            call_count[0] += 1
            if call_count[0] > 3:
                monitor._running = False
                return None
            return 30.0  # Always 30 seconds - always active

        with patch.object(monitor, "_get_idle_time_seconds", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should not have called callback (no state change)
        idle_callback.assert_not_called()
        assert monitor.idle is False

    async def test_run_handles_none_idle_time(
        self, monitor: WindowsIdleMonitor, idle_callback: AsyncMock
    ) -> None:
        """Test run continues when idle time cannot be determined."""
        monitor._running = True

        # Mock get_idle_time to return None (error) a few times
        call_count = [0]

        def mock_get_idle():
            call_count[0] += 1
            if call_count[0] > 3:
                monitor._running = False
            return None  # Can't determine idle time

        with patch.object(monitor, "_get_idle_time_seconds", side_effect=mock_get_idle):
            with patch("asyncio.sleep", return_value=None):
                await monitor.run()

        # Should not have called callback or changed state
        idle_callback.assert_not_called()
        assert monitor.idle is False

    async def test_run_handles_cancelled(
        self, monitor: WindowsIdleMonitor
    ) -> None:
        """Test run handles cancellation gracefully."""
        monitor._running = True

        def mock_get_idle():
            raise asyncio.CancelledError()

        with patch.object(monitor, "_get_idle_time_seconds", side_effect=mock_get_idle):
            with pytest.raises(asyncio.CancelledError):
                await monitor.run()

        assert monitor.running is False

    async def test_restart(self, idle_callback: AsyncMock) -> None:
        """Test restart resets state."""
        monitor = WindowsIdleMonitor(
            idle_timeout=60,
            on_idle_change=idle_callback,
        )
        monitor._current_idle = True
        monitor._running = True

        with patch.object(monitor, "_get_idle_time_seconds", return_value=10.0):
            await monitor.restart()

        # Should have called callback with False (reset to active)
        idle_callback.assert_called_with(False)
        assert monitor.running is True
        assert monitor.idle is False


class TestWindowsIdleMonitorTickCalculation:
    """Tests for tick count and idle time calculation."""

    @pytest.fixture
    def monitor(self) -> WindowsIdleMonitor:
        """Create WindowsIdleMonitor instance."""
        return WindowsIdleMonitor(
            idle_timeout=60,
            on_idle_change=AsyncMock(),
        )

    def test_zero_idle_time(self, monitor: WindowsIdleMonitor) -> None:
        """Test calculation with zero idle time (just used input)."""
        mock_windll = MagicMock()
        mock_windll.user32.GetLastInputInfo.return_value = True
        mock_windll.kernel32.GetTickCount.return_value = 5000

        # Create mock LASTINPUTINFO
        mock_lastinputinfo = MagicMock()
        mock_lastinputinfo.dwTime = 5000  # Same as current time
        mock_lastinputinfo.cbSize = 8

        with patch("claude_permission_daemon.idle_monitor_windows.WINDOWS_AVAILABLE", True):
            with patch("claude_permission_daemon.idle_monitor_windows.windll", mock_windll):
                with patch("claude_permission_daemon.idle_monitor_windows.sizeof", return_value=8):
                    with patch("claude_permission_daemon.idle_monitor_windows.byref", side_effect=lambda x: x):
                        with patch("claude_permission_daemon.idle_monitor_windows.LASTINPUTINFO", return_value=mock_lastinputinfo):
                            idle_seconds = monitor._get_idle_time_seconds()

        assert idle_seconds == 0.0

    def test_large_idle_time(self, monitor: WindowsIdleMonitor) -> None:
        """Test calculation with large idle time."""
        mock_windll = MagicMock()
        mock_windll.user32.GetLastInputInfo.return_value = True
        # Current: 1 hour in milliseconds
        mock_windll.kernel32.GetTickCount.return_value = 3600000

        # Create mock LASTINPUTINFO
        mock_lastinputinfo = MagicMock()
        mock_lastinputinfo.dwTime = 0  # At system start
        mock_lastinputinfo.cbSize = 8

        with patch("claude_permission_daemon.idle_monitor_windows.WINDOWS_AVAILABLE", True):
            with patch("claude_permission_daemon.idle_monitor_windows.windll", mock_windll):
                with patch("claude_permission_daemon.idle_monitor_windows.sizeof", return_value=8):
                    with patch("claude_permission_daemon.idle_monitor_windows.byref", side_effect=lambda x: x):
                        with patch("claude_permission_daemon.idle_monitor_windows.LASTINPUTINFO", return_value=mock_lastinputinfo):
                            idle_seconds = monitor._get_idle_time_seconds()

        assert idle_seconds == 3600.0  # 1 hour

    def test_millisecond_precision(self, monitor: WindowsIdleMonitor) -> None:
        """Test idle time calculation with millisecond precision."""
        mock_windll = MagicMock()
        mock_windll.user32.GetLastInputInfo.return_value = True
        mock_windll.kernel32.GetTickCount.return_value = 12345

        # Create mock LASTINPUTINFO
        mock_lastinputinfo = MagicMock()
        mock_lastinputinfo.dwTime = 10000
        mock_lastinputinfo.cbSize = 8

        with patch("claude_permission_daemon.idle_monitor_windows.WINDOWS_AVAILABLE", True):
            with patch("claude_permission_daemon.idle_monitor_windows.windll", mock_windll):
                with patch("claude_permission_daemon.idle_monitor_windows.sizeof", return_value=8):
                    with patch("claude_permission_daemon.idle_monitor_windows.byref", side_effect=lambda x: x):
                        with patch("claude_permission_daemon.idle_monitor_windows.LASTINPUTINFO", return_value=mock_lastinputinfo):
                            idle_seconds = monitor._get_idle_time_seconds()

        # (12345 - 10000) / 1000 = 2.345 seconds
        assert idle_seconds == 2.345
