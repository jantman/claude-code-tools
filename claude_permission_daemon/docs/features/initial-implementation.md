# Initial Implementation

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

Implement a Python-based daemon that enables remote approval of Claude Code permission requests via Slack when the user is idle. Based on specification in `claude-remote-approve-spec.md`.

## Project Structure

```
claude-permission-daemon/
├── pyproject.toml
├── README.md
├── src/
│   └── claude_permission_daemon/
│       ├── __init__.py
│       ├── daemon.py           # Main daemon entry point & orchestration
│       ├── config.py           # TOML + env var configuration loading
│       ├── state.py            # StateManager and data classes
│       ├── idle_monitor.py     # swayidle subprocess management
│       ├── socket_server.py    # Unix domain socket server
│       ├── slack_handler.py    # Slack Socket Mode + message formatting
│       └── hook.py             # Hook script (standalone, no external deps)
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_state.py
│   ├── test_idle_monitor.py
│   ├── test_socket_server.py
│   ├── test_slack_handler.py
│   └── test_integration.py
├── systemd/
│   └── claude-permission-daemon.service
└── example/
    └── config.toml
```

## Implementation Phases

### Phase 1: Project Foundation
1. Create `pyproject.toml` with dependencies and entry points
2. Implement `config.py` - TOML parsing with env var overrides
3. Implement `state.py` - Data classes and StateManager
4. Create example config file
5. Set up pytest infrastructure

### Phase 2: Core Components
1. Implement `idle_monitor.py` - swayidle subprocess with asyncio
2. Implement `socket_server.py` - Unix socket server accepting hook connections
3. Basic `daemon.py` shell (without Slack integration)
4. Unit tests for each component

### Phase 3: Slack Integration
1. Implement `slack_handler.py`:
   - Socket Mode connection via slack-bolt
   - Message block formatting (request, approved, denied, resolved locally)
   - Button action handlers (approve/deny)
2. Wire Slack handler into daemon event loop
3. Implement message updates on state changes

### Phase 4: Hook Script & Integration
1. Implement `hook.py` (stdlib only, no external deps):
   - JSON parsing from stdin
   - Unix socket client with 5-minute timeout
   - JSON output for Claude Code
2. Complete daemon orchestration in `daemon.py`:
   - Wire all callbacks between components
   - Handle race condition (user returns while pending)
3. Integration tests

### Phase 5: Deployment Files
1. Create systemd user service file
2. Write README with installation instructions
3. Create install/uninstall helper scripts

## Key Architectural Decisions

### Event Loop Structure
Single asyncio event loop with `asyncio.gather()` running:
- IdleMonitor (swayidle subprocess reader)
- SocketServer (Unix socket accepting hook connections)
- SlackHandler (Socket Mode WebSocket)

### State Management
- `StateManager` class with async-safe locking
- `PendingRequest` dataclass holds: request_id, tool_name, tool_input, timestamp, hook_writer (StreamWriter), slack_message_ts
- Callbacks for state transitions (idle->active triggers resolution of pending requests)

### Race Condition Handling
When swayidle reports ACTIVE and requests are pending in Slack:
1. Update all Slack messages to "Answered Locally"
2. Send "passthrough" response to all waiting hooks
3. Remove from pending requests dict

### Button Routing
Embed `request_id` in Slack button `value` field for routing callbacks to correct pending request.

## Critical Files to Create

| File | Purpose |
|------|---------|
| `src/claude_permission_daemon/daemon.py` | Main orchestration, signal handling, asyncio.gather |
| `src/claude_permission_daemon/slack_handler.py` | slack-bolt Socket Mode, Block Kit messages |
| `src/claude_permission_daemon/state.py` | PendingRequest, PermissionResponse, StateManager |
| `src/claude_permission_daemon/hook.py` | Standalone hook (stdlib only) |
| `src/claude_permission_daemon/idle_monitor.py` | swayidle subprocess management |
| `src/claude_permission_daemon/socket_server.py` | asyncio Unix socket server |
| `src/claude_permission_daemon/config.py` | TOML + env var config loading |

## Dependencies

Be sure to always use the newest versions (check pypi.org for this) as well as Python 3.14.

```toml
dependencies = [
    "slack-bolt>=1.18.0",
    "aiohttp>=3.9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.0.0",
]
```

Note: Python 3.11+ has `tomllib` in stdlib, so no external TOML dependency needed.

## Verification Plan

### Unit Tests
- Run `pytest tests/` after each phase
- Mock swayidle subprocess, Slack client for isolated testing

### Manual Testing
1. Start daemon with `--debug` flag:
   ```bash
   python -m claude_permission_daemon.daemon --debug
   ```

2. Test idle detection:
   - Wait for idle timeout, verify "Idle state: True" logged
   - Move mouse, verify "Idle state: False" logged

3. Test hook directly:
   ```bash
   echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | \
       python -m claude_permission_daemon.hook
   ```

4. Test with Claude Code:
   - Configure hook in `~/.claude/settings.json`
   - Run Claude, request permission-requiring action
   - Verify Slack message appears when idle
   - Verify local prompt when active

### Integration Test
- Full daemon with mocked swayidle and Slack
- End-to-end: hook request -> Slack message -> button click -> hook response
- Race condition: post to Slack, then simulate ACTIVE, verify passthrough

## Reference Files

- Specification: `claude-remote-approve-spec.md`
- Existing notification script pattern: `claude_notify.sh`

---

# Implementation Plan

## Status: IN PROGRESS

## Dependency Versions (as of 2026-01-22)

Based on PyPI research:
- **slack-bolt**: 1.27.0 (released 2025-11-13)
- **aiohttp**: 3.13.3 (released 2026-01-03)
- **pytest**: 9.x (released 2025-12)
- **pytest-asyncio**: 1.3.0 (released 2025-11-10)
- **pytest-cov**: 7.0.0 (released 2025-09-09)

Python 3.14 will be used as specified. Note: `tomllib` is in stdlib since Python 3.11.

## Milestones and Tasks

Commit message prefix format: `Init - {Milestone}.{Task}: {summary}`

### Milestone 1: Project Foundation

**Goal**: Set up project structure, configuration loading, state management, and testing infrastructure.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 1.1 | Create project skeleton | `pyproject.toml`, `src/claude_permission_daemon/__init__.py`, directory structure |
| 1.2 | Implement `config.py` | TOML config loading with env var overrides, validation |
| 1.3 | Implement `state.py` | `PendingRequest`, `PermissionResponse` dataclasses, `StateManager` class |
| 1.4 | Create example config | `example/config.toml` with documented options |
| 1.5 | Set up pytest infrastructure | `tests/conftest.py`, `test_config.py`, `test_state.py` |

**Exit Criteria**: All tests pass, `config.py` and `state.py` fully implemented and tested.

### Milestone 2: Core Components

**Goal**: Implement idle monitoring and socket server components.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 2.1 | Implement `idle_monitor.py` | `IdleMonitor` class managing swayidle subprocess, asyncio stream reading, callbacks on state change |
| 2.2 | Implement `socket_server.py` | Unix domain socket server accepting hook connections, JSON protocol handling |
| 2.3 | Create basic `daemon.py` shell | Entry point, argument parsing, signal handling, asyncio.gather skeleton |
| 2.4 | Unit tests for core components | `test_idle_monitor.py`, `test_socket_server.py` with mocked subprocess |

**Exit Criteria**: All tests pass, daemon can start/stop cleanly, idle state changes detected and logged.

### Milestone 3: Slack Integration

**Goal**: Implement Slack Socket Mode connection and message handling.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 3.1 | Implement `slack_handler.py` base | `SlackHandler` class with Socket Mode connection, async wrapper |
| 3.2 | Implement Block Kit messages | `format_permission_request()`, `format_approved()`, `format_denied()`, `format_answered_locally()` |
| 3.3 | Implement button action handlers | Approve/deny button callbacks with request_id routing |
| 3.4 | Wire Slack into daemon | Integrate `SlackHandler` into `daemon.py` event loop |
| 3.5 | Unit tests for Slack handler | `test_slack_handler.py` with mocked Slack client |

**Exit Criteria**: All tests pass, Slack messages can be posted and button actions received.

### Milestone 4: Hook Script & Full Integration

**Goal**: Implement hook script and complete end-to-end integration.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 4.1 | Implement `hook.py` | Standalone script (stdlib only), stdin JSON parsing, socket client, timeout handling |
| 4.2 | Complete daemon orchestration | Wire all callbacks, implement race condition handling |
| 4.3 | Integration tests | `test_integration.py` with end-to-end scenarios |

**Exit Criteria**: All tests pass, full flow works: hook → daemon → Slack → response → hook output.

### Milestone 5: Deployment & Documentation

**Goal**: Create deployment files and documentation.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 5.1 | Create systemd service file | `systemd/claude-permission-daemon.service` |
| 5.2 | Write project README | Installation instructions, configuration guide, usage examples |
| 5.3 | Create helper scripts | Install/uninstall scripts (optional) |

**Exit Criteria**: Documentation complete, systemd service file ready for use.

### Milestone 6: Acceptance Criteria

**Goal**: Final validation and documentation.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 6.1 | Documentation review | Ensure README.md, all docstrings, and comments are accurate and complete |
| 6.2 | Test coverage verification | Ensure all code has appropriate unit test coverage |
| 6.3 | Full test suite pass | All test sessions passing |
| 6.4 | Move feature to completed | Move this file to `docs/features/completed/` |

**Exit Criteria**: Feature complete, all tests passing, documentation reviewed.

---

## Progress Log

### Milestone 1: Project Foundation

**Status**: COMPLETE

- [x] Task 1.1: Create project skeleton
- [x] Task 1.2: Implement `config.py`
- [x] Task 1.3: Implement `state.py`
- [x] Task 1.4: Create example config
- [x] Task 1.5: Set up pytest infrastructure (39 tests passing)

### Milestone 2: Core Components

**Status**: COMPLETE

- [x] Task 2.1: Implement `idle_monitor.py`
- [x] Task 2.2: Implement `socket_server.py`
- [x] Task 2.3: Create basic `daemon.py` shell
- [x] Task 2.4: Unit tests for core components (69 tests passing)

### Milestone 3: Slack Integration

**Status**: COMPLETE

- [x] Task 3.1: Implement `slack_handler.py` base
- [x] Task 3.2: Implement Block Kit messages
- [x] Task 3.3: Implement button action handlers
- [x] Task 3.4: Wire Slack into daemon
- [x] Task 3.5: Unit tests for Slack handler (89 tests passing)

### Milestone 4: Hook Script & Full Integration

**Status**: NOT STARTED

- [ ] Task 4.1: Implement `hook.py`
- [ ] Task 4.2: Complete daemon orchestration
- [ ] Task 4.3: Integration tests

### Milestone 5: Deployment & Documentation

**Status**: NOT STARTED

- [ ] Task 5.1: Create systemd service file
- [ ] Task 5.2: Write project README
- [ ] Task 5.3: Create helper scripts

### Milestone 6: Acceptance Criteria

**Status**: NOT STARTED

- [ ] Task 6.1: Documentation review
- [ ] Task 6.2: Test coverage verification
- [ ] Task 6.3: Full test suite pass
- [ ] Task 6.4: Move feature to completed
