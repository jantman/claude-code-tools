# Claude Code Remote Permission Approval System - Implementation Plan

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
