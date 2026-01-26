"""Tests for idle_monitor_factory module."""

from unittest.mock import AsyncMock, patch

import pytest

from claude_permission_daemon.config import Config
from claude_permission_daemon.idle_monitor_factory import create_idle_monitor
from claude_permission_daemon.base_idle_monitor import IdleMonitorError


class TestIdleMonitorFactory:
    """Tests for create_idle_monitor factory function."""

    @pytest.fixture
    def config(self) -> Config:
        """Provide test configuration."""
        return Config()

    @pytest.fixture
    def idle_callback(self) -> AsyncMock:
        """Provide mock idle callback."""
        return AsyncMock()

    def test_create_linux_monitor(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test factory creates SwayidleMonitor for Linux."""
        with patch("platform.system", return_value="Linux"):
            with patch(
                "claude_permission_daemon.idle_monitor.SwayidleMonitor"
            ) as mock_monitor:
                create_idle_monitor(
                    config=config,
                    idle_timeout=60,
                    on_idle_change=idle_callback,
                )

                # Should have instantiated SwayidleMonitor
                mock_monitor.assert_called_once_with(
                    config=config.swayidle,
                    idle_timeout=60,
                    on_idle_change=idle_callback,
                )

    def test_create_macos_monitor(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test factory creates MacIdleMonitor for macOS."""
        with patch("platform.system", return_value="Darwin"):
            with patch(
                "claude_permission_daemon.idle_monitor_mac.MacIdleMonitor"
            ) as mock_monitor:
                create_idle_monitor(
                    config=config,
                    idle_timeout=60,
                    on_idle_change=idle_callback,
                )

                # Should have instantiated MacIdleMonitor
                mock_monitor.assert_called_once_with(
                    config=config.mac,
                    idle_timeout=60,
                    on_idle_change=idle_callback,
                )

    def test_create_windows_monitor(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test factory creates WindowsIdleMonitor for Windows."""
        with patch("platform.system", return_value="Windows"):
            with patch(
                "claude_permission_daemon.idle_monitor_windows.WindowsIdleMonitor"
            ) as mock_monitor:
                create_idle_monitor(
                    config=config,
                    idle_timeout=60,
                    on_idle_change=idle_callback,
                )

                # Should have instantiated WindowsIdleMonitor
                mock_monitor.assert_called_once_with(
                    idle_timeout=60,
                    on_idle_change=idle_callback,
                )

    def test_unsupported_platform_error(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test factory raises error for unsupported platform."""
        with patch("platform.system", return_value="FreeBSD"):
            with patch("platform.platform", return_value="FreeBSD-13.0-RELEASE"):
                with pytest.raises(IdleMonitorError, match="Unsupported operating system"):
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )

    def test_linux_monitor_creation_failure(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test error handling when Linux monitor creation fails."""
        with patch("platform.system", return_value="Linux"):
            with patch(
                "claude_permission_daemon.idle_monitor.SwayidleMonitor",
                side_effect=Exception("swayidle not found"),
            ):
                with pytest.raises(IdleMonitorError, match="Failed to create SwayidleMonitor"):
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )

    def test_macos_monitor_creation_failure(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test error handling when macOS monitor creation fails."""
        with patch("platform.system", return_value="Darwin"):
            with patch(
                "claude_permission_daemon.idle_monitor_mac.MacIdleMonitor",
                side_effect=Exception("ioreg not found"),
            ):
                with pytest.raises(IdleMonitorError, match="Failed to create MacIdleMonitor"):
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )

    def test_windows_monitor_creation_failure(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test error handling when Windows monitor creation fails."""
        with patch("platform.system", return_value="Windows"):
            with patch(
                "claude_permission_daemon.idle_monitor_windows.WindowsIdleMonitor",
                side_effect=Exception("Windows API not available"),
            ):
                with pytest.raises(IdleMonitorError, match="Failed to create WindowsIdleMonitor"):
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )

    def test_error_messages_contain_resolution_steps(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test that error messages include helpful resolution steps."""
        # Test Linux error message
        with patch("platform.system", return_value="Linux"):
            with patch(
                "claude_permission_daemon.idle_monitor.SwayidleMonitor",
                side_effect=Exception("test error"),
            ):
                with pytest.raises(IdleMonitorError) as exc_info:
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )
                # Check for resolution steps in error message
                error_msg = str(exc_info.value)
                assert "To resolve this issue" in error_msg
                assert "swayidle" in error_msg.lower()

        # Test macOS error message
        with patch("platform.system", return_value="Darwin"):
            with patch(
                "claude_permission_daemon.idle_monitor_mac.MacIdleMonitor",
                side_effect=Exception("test error"),
            ):
                with pytest.raises(IdleMonitorError) as exc_info:
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )
                error_msg = str(exc_info.value)
                assert "To resolve this issue" in error_msg
                assert "ioreg" in error_msg.lower()

        # Test Windows error message
        with patch("platform.system", return_value="Windows"):
            with patch(
                "claude_permission_daemon.idle_monitor_windows.WindowsIdleMonitor",
                side_effect=Exception("test error"),
            ):
                with pytest.raises(IdleMonitorError) as exc_info:
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )
                error_msg = str(exc_info.value)
                assert "To resolve this issue" in error_msg
                assert "Windows" in error_msg

    def test_unsupported_platform_includes_platform_info(
        self, config: Config, idle_callback: AsyncMock
    ) -> None:
        """Test that unsupported platform error includes platform details."""
        with patch("platform.system", return_value="SomeOS"):
            with patch("platform.platform", return_value="SomeOS-1.0-RELEASE"):
                with pytest.raises(IdleMonitorError) as exc_info:
                    create_idle_monitor(
                        config=config,
                        idle_timeout=60,
                        on_idle_change=idle_callback,
                    )
                error_msg = str(exc_info.value)
                assert "SomeOS" in error_msg
                assert "SomeOS-1.0-RELEASE" in error_msg
                assert "currently supports" in error_msg
