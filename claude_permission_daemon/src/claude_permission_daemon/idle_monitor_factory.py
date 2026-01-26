"""Factory for creating platform-specific idle monitors.

Automatically detects the operating system and returns the appropriate
idle monitor implementation.
"""

import logging
import platform

from .base_idle_monitor import BaseIdleMonitor, IdleCallback, IdleMonitorError
from .config import Config

logger = logging.getLogger(__name__)


def create_idle_monitor(
    config: Config,
    idle_timeout: int,
    on_idle_change: IdleCallback,
) -> BaseIdleMonitor:
    """Create an idle monitor appropriate for the current platform.

    Detects the operating system and returns the correct idle monitor
    implementation (SwayidleMonitor for Linux, MacIdleMonitor for macOS,
    WindowsIdleMonitor for Windows).

    Args:
        config: Complete daemon configuration.
        idle_timeout: Seconds of inactivity before considered idle.
        on_idle_change: Async callback called when idle state changes.

    Returns:
        Platform-specific idle monitor instance.

    Raises:
        IdleMonitorError: If no appropriate idle monitor is available for
            the current platform, or if the backend fails to initialize.
    """
    system = platform.system()
    logger.info(f"Detected operating system: {system}")

    if system == "Linux":
        # Use swayidle for Linux (primarily for Wayland, but works on X11 too)
        from .idle_monitor import SwayidleMonitor

        logger.info("Using SwayidleMonitor (swayidle) for Linux")
        try:
            monitor = SwayidleMonitor(
                config=config.swayidle,
                idle_timeout=idle_timeout,
                on_idle_change=on_idle_change,
            )
            return monitor
        except Exception as e:
            raise IdleMonitorError(
                f"Failed to create SwayidleMonitor: {e}\n\n"
                "To resolve this issue:\n"
                "1. Install swayidle: Most distributions provide it via package manager\n"
                "   - Arch: sudo pacman -S swayidle\n"
                "   - Ubuntu/Debian: sudo apt install swayidle\n"
                "   - Fedora: sudo dnf install swayidle\n"
                "2. Or specify the full path in config.toml:\n"
                "   [swayidle]\n"
                "   binary = \"/full/path/to/swayidle\""
            ) from e

    elif system == "Darwin":  # macOS
        from .idle_monitor_mac import MacIdleMonitor

        logger.info("Using MacIdleMonitor (ioreg) for macOS")
        try:
            monitor = MacIdleMonitor(
                config=config.mac,
                idle_timeout=idle_timeout,
                on_idle_change=on_idle_change,
            )
            return monitor
        except Exception as e:
            raise IdleMonitorError(
                f"Failed to create MacIdleMonitor: {e}\n\n"
                "To resolve this issue:\n"
                "1. Verify ioreg is available: which ioreg\n"
                "   (It should be at /usr/sbin/ioreg on macOS)\n"
                "2. If missing, reinstall macOS Command Line Tools:\n"
                "   xcode-select --install\n"
                "3. Or specify the full path in config.toml:\n"
                "   [mac]\n"
                "   binary = \"/usr/sbin/ioreg\""
            ) from e

    elif system == "Windows":
        from .idle_monitor_windows import WindowsIdleMonitor

        logger.info("Using WindowsIdleMonitor (GetLastInputInfo) for Windows")
        try:
            monitor = WindowsIdleMonitor(
                idle_timeout=idle_timeout,
                on_idle_change=on_idle_change,
            )
            return monitor
        except Exception as e:
            raise IdleMonitorError(
                f"Failed to create WindowsIdleMonitor: {e}\n\n"
                "To resolve this issue:\n"
                "1. Ensure you're running on Windows\n"
                "2. Verify Windows API is accessible\n"
                "3. Check that Python ctypes module is available\n"
                "\nThis error may indicate you're not running on Windows, or\n"
                "the Windows API is not available in your environment."
            ) from e

    else:
        # Unknown or unsupported platform
        raise IdleMonitorError(
            f"Unsupported operating system: {system}\n\n"
            f"The Claude Permission Daemon currently supports:\n"
            f"- Linux (using swayidle)\n"
            f"- macOS (using ioreg)\n"
            f"- Windows (using GetLastInputInfo API)\n\n"
            f"Your system reports as: {system}\n"
            f"Platform details: {platform.platform()}\n\n"
            f"If you believe this platform should be supported, please file\n"
            f"an issue at: https://github.com/anthropics/claude-code/issues"
        )
