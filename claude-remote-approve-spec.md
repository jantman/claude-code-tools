# Claude Code Remote Permission Approval System

## Project Overview

A system to remotely approve Claude Code permission requests via Slack when the user is away from their computer. The system detects user idle state using Wayland protocols and only sends Slack notifications when the user has been idle for a configurable period.

### Goals

1. Receive permission requests from Claude Code via the `PermissionRequest` hook
2. Detect when the user is idle (no keyboard/mouse input) using swayidle
3. When idle: send permission details to Slack with Approve/Deny buttons
4. When active: pass through to normal Claude Code permission flow
5. Handle the race condition where user returns to computer while Slack message is pending
6. Provide a clean, maintainable implementation suitable for a single-user desktop

### Non-Goals

- Multi-user support
- Web UI (Slack is the only remote interface)
- Support for compositors other than KDE Plasma on Wayland (though the architecture should be adaptable)

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Permission Daemon (systemd user service)                               │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Main Process (Python asyncio)                                    │  │
│  │                                                                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────┐  │  │
│  │  │ Idle Monitor│  │ Socket Srv  │  │ Slack Bolt (Socket Mode) │  │  │
│  │  │ (swayidle)  │  │ (Unix)      │  │                          │  │  │
│  │  └──────┬──────┘  └──────┬──────┘  └────────────┬─────────────┘  │  │
│  │         │                │                      │                │  │
│  │         ▼                ▼                      ▼                │  │
│  │  ┌─────────────────────────────────────────────────────────────┐ │  │
│  │  │                    State Manager                            │ │  │
│  │  │  - idle: bool                                               │ │  │
│  │  │  - pending_requests: Dict[request_id, RequestContext]       │ │  │
│  │  └─────────────────────────────────────────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
         ▲                           ▲                          │
         │ Unix Socket               │ stdout/stderr            │ WebSocket
         │                           │                          │ (outbound)
         │                           │                          ▼
┌────────┴────────┐         ┌────────┴────────┐         ┌──────────────┐
│ Hook Script     │         │ swayidle        │         │  Slack API   │
│ (ephemeral)     │         │ (subprocess)    │         │              │
└─────────────────┘         └─────────────────┘         └──────────────┘
         ▲
         │ Spawned by Claude Code
         │
┌────────┴────────┐
│  Claude Code    │
└─────────────────┘
```

## Components

### 1. Permission Daemon (`claude-permission-daemon`)

The main long-running process. Runs as a systemd user service.

**Responsibilities:**
- Manage swayidle subprocess for idle detection
- Listen on Unix domain socket for hook script connections
- Maintain Slack connection via Socket Mode
- Track pending permission requests
- Coordinate responses between Slack and hook scripts

**Technology:** Python 3.11+, asyncio, slack-bolt

**Socket Location:** `$XDG_RUNTIME_DIR/claude-permissions.sock` (typically `/run/user/1000/claude-permissions.sock`)

### 2. Hook Script (`claude-permission-hook`)

A small, fast script invoked by Claude Code for each permission request.

**Responsibilities:**
- Parse JSON from stdin (Claude Code provides tool details)
- Connect to daemon's Unix socket
- Send request details to daemon
- Wait for response from daemon
- Output appropriate JSON to stdout for Claude Code

**Technology:** Python 3 (single file, no external dependencies beyond stdlib)

**Timeout:** The hook script should have a reasonable timeout (e.g., 5 minutes) after which it exits with no output, allowing Claude Code's normal permission flow to proceed.

### 3. Idle Monitor (swayidle subprocess)

Managed by the daemon as a subprocess.

**Configuration:**
```bash
swayidle -w \
    timeout $IDLE_TIMEOUT 'echo IDLE' \
    resume 'echo ACTIVE'
```

The daemon reads stdout from swayidle and updates its internal `idle` state accordingly.

**Default IDLE_TIMEOUT:** 60 seconds (configurable)

### 4. Slack Integration

Uses Slack's Socket Mode for bidirectional communication without requiring inbound webhooks.

**Required Slack App Permissions (OAuth Scopes):**
- `chat:write` - Post messages
- `connections:write` - Use Socket Mode

**Required Slack App Features:**
- Socket Mode: Enabled
- Interactivity: Enabled (for button callbacks)

## Configuration

Configuration file: `~/.config/claude-permission-daemon/config.toml`

```toml
[daemon]
# Socket path (default: $XDG_RUNTIME_DIR/claude-permissions.sock)
socket_path = "/run/user/1000/claude-permissions.sock"

# How long user must be idle before we send to Slack (seconds)
idle_timeout = 60

# How long hook script waits for response before giving up (seconds)
request_timeout = 300

[slack]
# Slack Bot Token (xoxb-...)
bot_token = "xoxb-your-token-here"

# Slack App Token for Socket Mode (xapp-...)
app_token = "xapp-your-token-here"

# Channel or user ID to send permission requests to
# Use a DM channel ID for private notifications
channel = "U01234567"  # Your Slack user ID for DMs

[swayidle]
# Path to swayidle binary (default: found in PATH)
binary = "/usr/bin/swayidle"
```

Environment variables can override config file:
- `CLAUDE_PERM_SLACK_BOT_TOKEN`
- `CLAUDE_PERM_SLACK_APP_TOKEN`
- `CLAUDE_PERM_SLACK_CHANNEL`
- `CLAUDE_PERM_IDLE_TIMEOUT`

## Data Structures

### Permission Request (Hook → Daemon)

```json
{
    "request_id": "uuid-v4",
    "tool_name": "Bash",
    "tool_input": {
        "command": "npm install lodash",
        "description": "Install lodash dependency"
    },
    "timestamp": "2025-01-20T10:30:00Z"
}
```

### Permission Response (Daemon → Hook)

```json
{
    "action": "approve" | "deny" | "passthrough",
    "reason": "Approved via Slack" | "Denied via Slack" | "User active locally"
}
```

### Pending Request Context (Internal)

```python
@dataclass
class PendingRequest:
    request_id: str
    tool_name: str
    tool_input: dict
    timestamp: datetime
    hook_writer: asyncio.StreamWriter  # To send response back to hook
    slack_message_ts: Optional[str]     # Slack message ID if posted
    slack_channel: Optional[str]        # Channel where message was posted
```

## Protocol Flows

### Flow 1: User is Active (idle < threshold)

```
Claude Code              Hook Script              Daemon
    │                        │                       │
    │──PermissionRequest────▶│                       │
    │                        │──connect + request───▶│
    │                        │                       │ (checks idle=False)
    │                        │◀──{"action":"passthrough"}──│
    │◀──(no output, exit 0)──│                       │
    │                        │                       │
    │ (shows normal permission prompt to user)       │
```

### Flow 2: User is Idle, Approves via Slack

```
Claude Code     Hook Script       Daemon                    Slack
    │               │                │                        │
    │──PermReq─────▶│                │                        │
    │               │──request──────▶│                        │
    │               │                │ (checks idle=True)     │
    │               │                │──post message─────────▶│
    │               │                │                        │
    │               │                │    (user taps Approve) │
    │               │                │◀──interaction callback─│
    │               │                │──update message───────▶│
    │               │◀──{"action":"approve"}──│               │
    │◀──{"decision":"approve"}──│    │                        │
    │               │                │                        │
    │ (proceeds with tool execution) │                        │
```

### Flow 3: User Returns While Slack Pending

```
Claude Code     Hook Script       Daemon          swayidle      Slack
    │               │                │                │           │
    │──PermReq─────▶│                │                │           │
    │               │──request──────▶│                │           │
    │               │                │ (idle=True)    │           │
    │               │                │──post msg─────────────────▶│
    │               │                │                │           │
    │               │                │◀──"ACTIVE"────│           │
    │               │                │ (idle=False)  │           │
    │               │                │──update msg ("answered locally")─▶│
    │               │◀──{"action":"passthrough"}──│   │           │
    │◀──(no output)─│                │                │           │
    │               │                │                │           │
    │ (shows normal prompt)          │                │           │
```

## Slack Message Format

### Permission Request Message

```
┌─────────────────────────────────────────────────┐
│ 🔐 Claude Code Permission Request               │
├─────────────────────────────────────────────────┤
│                                                 │
│ Tool: Bash                                      │
│                                                 │
│ ┌─────────────────────────────────────────────┐ │
│ │ npm install lodash                          │ │
│ └─────────────────────────────────────────────┘ │
│                                                 │
│ Description: Install lodash dependency          │
│                                                 │
│ Requested: 10:30 AM                             │
│                                                 │
│  [  ✓ Approve  ]    [  ✗ Deny  ]               │
│                                                 │
└─────────────────────────────────────────────────┘
```

### After Approval

```
┌─────────────────────────────────────────────────┐
│ ✅ Approved: Bash                               │
├─────────────────────────────────────────────────┤
│ npm install lodash                              │
│                                                 │
│ Approved at 10:31 AM                            │
└─────────────────────────────────────────────────┘
```

### After Local Activity Detected

```
┌─────────────────────────────────────────────────┐
│ ⌨️ Answered Locally: Bash                       │
├─────────────────────────────────────────────────┤
│ npm install lodash                              │
│                                                 │
│ You returned to your computer                   │
└─────────────────────────────────────────────────┘
```

## Claude Code Hook Configuration

Add to `~/.claude/settings.json`:

```json
{
    "hooks": {
        "PermissionRequest": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "/home/USER/.local/bin/claude-permission-hook"
                    }
                ]
            }
        ]
    }
}
```

## Hook Script Output Format

The hook script must output valid JSON that Claude Code understands:

**To approve:**
```json
{"decision": "approve", "reason": "Approved via Slack"}
```

**To deny:**
```json
{"decision": "deny", "reason": "Denied via Slack"}
```

**To pass through to normal flow:**
Exit with code 0 and no output (or empty output).

## Installation

### Dependencies

System packages (Arch Linux):
```bash
pacman -S python python-pip swayidle
```

Python packages:
```bash
pip install --user slack-bolt aiofiles tomli
```

### File Locations

```
~/.local/bin/claude-permission-hook          # Hook script (executable)
~/.local/bin/claude-permission-daemon        # Daemon script (executable)
~/.config/claude-permission-daemon/config.toml  # Configuration
~/.config/systemd/user/claude-permission-daemon.service  # Systemd unit
```

### Systemd User Service

`~/.config/systemd/user/claude-permission-daemon.service`:

```ini
[Unit]
Description=Claude Code Permission Daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/claude-permission-daemon
Restart=on-failure
RestartSec=5

# Ensure access to Wayland
Environment=WAYLAND_DISPLAY=wayland-0

[Install]
WantedBy=graphical-session.target
```

Enable and start:
```bash
systemctl --user daemon-reload
systemctl --user enable --now claude-permission-daemon
```

## Slack App Setup

1. Go to https://api.slack.com/apps and create a new app
2. Enable Socket Mode in "Socket Mode" settings
3. Generate an App-Level Token with `connections:write` scope
4. Add Bot Token Scopes under "OAuth & Permissions":
   - `chat:write`
5. Enable Interactivity under "Interactivity & Shortcuts"
6. Install the app to your workspace
7. Copy the Bot Token (`xoxb-...`) and App Token (`xapp-...`) to config

To find your User ID for DMs:
- Click your profile in Slack
- Click "..." → "Copy member ID"

## Error Handling

### Daemon Not Running

If the hook script cannot connect to the daemon socket:
- Log warning to stderr
- Exit with code 0 and no output
- Claude Code shows normal permission prompt

### Slack Connection Lost

If the daemon loses Slack connection while a request is pending:
- Attempt reconnection (slack-bolt handles this automatically)
- If request times out waiting for Slack, respond with `passthrough`

### swayidle Crashes

If swayidle subprocess exits unexpectedly:
- Log error
- Restart swayidle subprocess
- Default to `idle=False` while swayidle is unavailable

### Hook Script Timeout

If hook script doesn't receive response within `request_timeout`:
- Exit with code 0 and no output
- Daemon should clean up the pending request

## Testing

### Manual Testing Steps

1. Start daemon in foreground for debugging:
   ```bash
   claude-permission-daemon --debug
   ```

2. Test idle detection:
   ```bash
   # In another terminal, wait for idle timeout
   # Daemon should log "Idle state: True"
   # Move mouse
   # Daemon should log "Idle state: False"
   ```

3. Test hook script directly:
   ```bash
   echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | \
       claude-permission-hook
   ```

4. Test with Claude Code:
   ```bash
   # Start claude in a directory
   claude
   # Ask it to run a command that requires permission
   # Verify Slack message appears (if idle) or normal prompt (if active)
   ```

### Unit Tests

Create tests for:
- Hook script JSON parsing
- Daemon state management
- Slack message formatting
- Response handling

## Security Considerations

1. **Socket Permissions:** Unix socket is created with user-only permissions (0600)
2. **Slack Tokens:** Store tokens in config file with restricted permissions (0600)
3. **No Remote Code Execution:** The system only approves/denies; it doesn't modify what Claude Code executes
4. **Local Network Only:** Daemon only listens on Unix socket, not network
