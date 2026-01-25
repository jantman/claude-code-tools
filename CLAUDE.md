# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains the **Claude Permission Daemon** - a system that forwards Claude Code permission requests to Slack when the user is idle, enabling remote approval/denial from a phone. It detects idle state via `swayidle`, posts interactive Slack messages with Approve/Deny buttons, and handles race conditions when users return.

## Development Commands

```bash
# Install in development mode (Python 3.14+ required)
cd claude_permission_daemon
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run tests with coverage
pytest tests/ --cov=src/claude_permission_daemon

# Run single test file
pytest tests/test_daemon.py -v

# Run daemon with debug logging
claude-permission-daemon --debug

# Check systemd service status
systemctl --user status claude-permission-daemon
journalctl --user -u claude-permission-daemon -f

# Test hook manually (permission request)
echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | claude-permission-hook

# Test hook manually (notification)
echo '{"hook_event_name":"Notification","notification_type":"idle_prompt","message":"test"}' | claude-permission-hook
```

## Architecture

```
Claude Code
    ↓ (hook event via stdin JSON)
hook.py (stdlib-only, no external deps)
    ↓ (Unix socket: $XDG_RUNTIME_DIR/claude-permissions.sock)
socket_server.py
    ↓ (async queue)
daemon.py (main orchestrator)
    ├─→ slack_handler.py (Socket Mode WebSocket → post messages, handle button clicks)
    ├─→ idle_monitor.py (swayidle subprocess → IDLE/ACTIVE state)
    └─→ state.py (pending requests, idle duration, thread-safe operations)
```

### Key Components (`claude_permission_daemon/src/claude_permission_daemon/`)

- **daemon.py**: Orchestrator managing lifecycle, callbacks, and graceful shutdown with timeouts
- **hook.py**: Entry point from Claude Code - uses only Python stdlib for reliability
- **socket_server.py**: Unix domain socket server routing requests to handlers
- **slack_handler.py**: Slack Socket Mode integration for posting messages and handling button callbacks
- **idle_monitor.py**: Spawns swayidle, parses stdout for IDLE/ACTIVE markers
- **state.py**: Thread-safe state manager with `asyncio.Lock`, tracks pending requests and idle state
- **config.py**: TOML config loading with environment variable overrides

### Data Flow for Permission Requests

1. Claude Code triggers PermissionRequest hook → invokes `claude-permission-hook`
2. Hook reads JSON from stdin, connects to daemon via Unix socket
3. If user is **active**: immediate passthrough response
4. If user is **idle**: posts to Slack with buttons, waits for response
5. User clicks button OR returns from idle → response sent to hook → Claude proceeds

### Hook Response Format

The hook uses Claude Code's `PermissionRequest` hook format:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": { "behavior": "allow" }
  }
}
```

### State Transitions

When user returns while Slack message is pending: message updates to "Answered Locally", normal local prompt appears, subsequent Slack clicks are ignored.

### Remote Answer Detection

The daemon detects when a permission request is answered remotely (e.g., via SSH into a tmux session) while `swayidle` still reports the user as idle. This is done by monitoring the hook script's socket connection - when Claude Code proceeds (because the user answered locally), the hook script exits and the connection closes. The daemon detects this EOF and updates the Slack message to "Answered Remotely" with a globe emoji (🌐).

## Configuration

User config: `~/.config/claude-permission-daemon/config.toml` (see `example/config.toml`)

All settings support environment variable overrides (e.g., `CLAUDE_PERMISSION_SLACK_BOT_TOKEN`).

## Claude Code Integration

The `.claude/settings.json` configures hooks to route both `PermissionRequest` and `Notification` events through the daemon.

## Custom Skills

- `/goodcommit` - Creates detailed commit messages with one-sentence summary
- `/independent` - Enables autonomous feature work with periodic commits

## Testing

7 test modules covering unit and integration tests. Uses `pytest-asyncio` for async test support. Tests are in `claude_permission_daemon/tests/`.
