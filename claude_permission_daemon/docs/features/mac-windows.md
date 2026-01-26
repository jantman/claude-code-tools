# Mac and Windows Support

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

Currently this application is written for Linux with Wayland and uses `swayidle` to detect when the system is idle. We need to add support for idle detection on Mac and Windows, and automatically choose the proper idle detection backend for the current operating system. If no appropriate idle backend can be found, the daemon should exit non-zero with an error message explaining what the problem is and how to resolve it.

## Implementation Plan

### Architecture Overview

The current implementation has `IdleMonitor` class hardcoded to use `swayidle` subprocess. We will:

1. Create an abstract base class `BaseIdleMonitor` with the interface contract
2. Rename current `IdleMonitor` to `SwayidleMonitor` (keeping it for Linux/Wayland)
3. Implement `MacIdleMonitor` using `ioreg` command-line tool to query HID idle time
4. Implement `WindowsIdleMonitor` using ctypes to call Windows API `GetLastInputInfo`
5. Add a factory function that detects OS and returns appropriate monitor instance
6. Update configuration to support backend-specific settings
7. Update daemon to use factory function for monitor instantiation

### Idle Detection Approaches

**Linux (existing)**: `swayidle` subprocess that prints IDLE/ACTIVE to stdout
**Mac**: Poll `ioreg -c IOHIDSystem` every second to read `HIDIdleTime` (milliseconds since last input)
**Windows**: Poll `ctypes.windll.user32.GetLastInputInfo()` every second to calculate idle time

Both Mac and Windows implementations will use polling (check idle time every ~1 second) and trigger the callback when idle state transitions occur.

### Milestones and Tasks

#### Milestone 1: Create Abstraction Layer
**Commit prefix**: `Mac/Windows Support - 1.x`

- **1.1**: Create `BaseIdleMonitor` abstract base class
  - Define abstract interface: `start()`, `stop()`, `run()`, `idle` property, `running` property
  - Document the contract in docstrings
  - Add `IdleCallback` type alias to base class module

- **1.2**: Refactor existing `IdleMonitor` to `SwayidleMonitor`
  - Rename `IdleMonitor` class to `SwayidleMonitor`
  - Make it inherit from `BaseIdleMonitor`
  - Update imports in `daemon.py` and any other files
  - Ensure all existing tests still pass

#### Milestone 2: Implement Mac Support
**Commit prefix**: `Mac/Windows Support - 2.x`

- **2.1**: Implement `MacIdleMonitor` class
  - Create new file `idle_monitor_mac.py`
  - Implement polling-based idle detection using `ioreg -c IOHIDSystem`
  - Parse `HIDIdleTime` from output (nanoseconds since last input)
  - Trigger callbacks when crossing idle threshold
  - Handle subprocess errors gracefully
  - Add proper logging

- **2.2**: Add Mac-specific configuration
  - Add `MacIdleConfig` dataclass to `config.py`
  - Support optional `ioreg_binary` path override
  - Add to main `Config` class
  - Update environment variable overrides

- **2.3**: Add unit tests for `MacIdleMonitor`
  - Mock subprocess calls to `ioreg`
  - Test state transitions (active -> idle -> active)
  - Test error handling (command not found, parse errors)
  - Test callback triggering
  - Ensure test coverage matches existing `test_idle_monitor.py`

#### Milestone 3: Implement Windows Support
**Commit prefix**: `Mac/Windows Support - 3.x`

- **3.1**: Implement `WindowsIdleMonitor` class
  - Create new file `idle_monitor_windows.py`
  - Use `ctypes.windll.user32.GetLastInputInfo()` to get last input time
  - Implement polling-based state tracking
  - Trigger callbacks when crossing idle threshold
  - Handle Windows API errors gracefully
  - Add proper logging

- **3.2**: Add Windows-specific configuration
  - Add `WindowsIdleConfig` dataclass to `config.py` (may be minimal or empty initially)
  - Add to main `Config` class
  - Add environment variable support if needed

- **3.3**: Add unit tests for `WindowsIdleMonitor`
  - Mock ctypes Windows API calls
  - Test state transitions
  - Test error handling
  - Test callback triggering
  - Ensure test coverage matches existing idle monitor tests

#### Milestone 4: Add Platform Detection and Factory
**Commit prefix**: `Mac/Windows Support - 4.x`

- **4.1**: Create idle monitor factory
  - Create new file `idle_monitor_factory.py`
  - Implement `create_idle_monitor()` function that:
    - Detects OS using `platform.system()`
    - Returns appropriate monitor instance based on OS
    - Raises descriptive error if no backend available
  - Error messages should explain what's missing and how to fix it

- **4.2**: Update daemon to use factory
  - Modify `daemon.py` to use factory function instead of direct instantiation
  - Update imports
  - Handle factory errors at daemon startup
  - Exit cleanly with non-zero status if backend unavailable

- **4.3**: Add factory tests
  - Test factory returns correct monitor type for each OS
  - Test error handling for unsupported/unknown OS
  - Mock `platform.system()` for different scenarios

#### Milestone 5: Integration and Cross-Platform Polish
**Commit prefix**: `Mac/Windows Support - 5.x`

- **5.1**: Update integration tests
  - Update `test_integration.py` to work with factory pattern
  - Add platform-specific test skipping where appropriate
  - Ensure all integration tests pass on current platform

- **5.2**: Test on actual platforms
  - Test daemon startup and idle detection on Mac (current platform)
  - Verify error messages on unsupported platforms
  - Verify configuration loading works correctly

- **5.3**: Handle backward compatibility
  - Ensure existing `[swayidle]` config section still works
  - Update config validation to check for appropriate backend config
  - Ensure startup errors are clear if backend-specific config is missing

#### Milestone 6: Acceptance Criteria
**Commit prefix**: `Mac/Windows Support - 6.x`

- **6.1**: Update documentation
  - Update `README.md` with platform support information
  - Update installation instructions for each platform
  - Update `example/config.toml` with Mac/Windows sections
  - Update `CLAUDE.md` with Mac/Windows implementation details
  - Add platform-specific troubleshooting notes

- **6.2**: Ensure test coverage
  - Verify all new code has appropriate unit tests
  - Run full test suite: `pytest tests/ -v`
  - Check coverage: `pytest tests/ --cov=src/claude_permission_daemon`
  - Ensure coverage doesn't drop below existing levels

- **6.3**: Final validation
  - All tests passing
  - Daemon starts successfully on Mac
  - Idle detection works correctly on Mac
  - Error messages are clear and helpful
  - Configuration is intuitive

- **6.4**: Move feature to completed
  - Move this file to `docs/features/completed/mac-windows.md`

## Current Status

**Phase**: Planning complete, awaiting approval

## Design Decisions

### Why separate monitor classes instead of one class with OS-specific methods?
- Cleaner separation of concerns
- Easier to test each backend independently
- Simpler to add new backends in future
- Follows Open/Closed Principle (open for extension, closed for modification)

### Why polling for Mac/Windows instead of event-based like swayidle?
- `ioreg` and Windows API don't provide event-based idle notifications out of the box
- Polling every second is lightweight and sufficient for our use case
- Simpler implementation with consistent behavior across platforms
- Could be optimized later if needed

### Why not use third-party libraries like `pyobjc` (Mac) or `pywin32` (Windows)?
- Minimizes dependencies
- `ioreg` command is always available on Mac
- `ctypes` is in Python stdlib
- Reduces installation complexity for users
- Aligns with existing `swayidle` approach (external command)
