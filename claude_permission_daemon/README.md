# Claude Permission Daemon

Remote approval of Claude Code permission requests via Slack when the user is idle.

## Overview

When you step away from your computer while Claude Code is running, permission requests would normally block until you return. This daemon detects when you're idle (using swayidle) and forwards permission requests to Slack where you can approve or deny them from your phone.

**Key features:**
- Idle detection via swayidle (Wayland)
- Slack Socket Mode for real-time notifications
- Approve/deny buttons in Slack messages
- Automatic passthrough when you return to your computer
- Clean race condition handling

## Requirements

- Python 3.14+
- KDE Plasma on Wayland (or any Wayland compositor supporting swayidle)
- A Slack workspace with permission to create apps

## Installation

### 1. Install the package

```bash
pip install --user .
```

Or for development:

```bash
pip install --user -e ".[dev]"
```

### 2. Create a Slack App

1. Go to https://api.slack.com/apps and create a new app
2. Enable **Socket Mode** in "Socket Mode" settings
3. Generate an **App-Level Token** with `connections:write` scope
4. Add **Bot Token Scopes** under "OAuth & Permissions":
   - `chat:write`
5. Enable **Interactivity** under "Interactivity & Shortcuts"
6. Install the app to your workspace
7. Copy the Bot Token (`xoxb-...`) and App Token (`xapp-...`)

To find your User ID for DMs:
- Click your profile in Slack
- Click "..." → "Copy member ID"

### 3. Configure the daemon

Create the config file:

```bash
mkdir -p ~/.config/claude-permission-daemon
cp example/config.toml ~/.config/claude-permission-daemon/config.toml
```

Edit the config file with your Slack tokens:

```toml
[slack]
bot_token = "xoxb-your-bot-token"
app_token = "xapp-your-app-token"
channel = "U12345678"  # Your Slack user ID for DMs
```

### 4. Set up the systemd service

```bash
mkdir -p ~/.config/systemd/user
cp systemd/claude-permission-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-permission-daemon
```

Check status:

```bash
systemctl --user status claude-permission-daemon
journalctl --user -u claude-permission-daemon -f
```

### 5. Configure Claude Code

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
                        "command": "claude-permission-hook"
                    }
                ]
            }
        ]
    }
}
```

## Configuration Reference

### `~/.config/claude-permission-daemon/config.toml`

```toml
[daemon]
# Unix socket path (default: $XDG_RUNTIME_DIR/claude-permissions.sock)
# socket_path = "/run/user/1000/claude-permissions.sock"

# Idle timeout in seconds (default: 60)
idle_timeout = 60

# Request timeout in seconds (default: 300)
request_timeout = 300

[slack]
# Required: Slack Bot Token (xoxb-...)
bot_token = "xoxb-..."

# Required: Slack App Token for Socket Mode (xapp-...)
app_token = "xapp-..."

# Required: Channel or user ID to send messages to
channel = "U12345678"

[swayidle]
# Path to swayidle binary (default: found in PATH)
# binary = "/usr/bin/swayidle"
```

### Environment Variables

All config values can be overridden with environment variables:

- `CLAUDE_PERM_SLACK_BOT_TOKEN`
- `CLAUDE_PERM_SLACK_APP_TOKEN`
- `CLAUDE_PERM_SLACK_CHANNEL`
- `CLAUDE_PERM_IDLE_TIMEOUT`
- `CLAUDE_PERM_REQUEST_TIMEOUT`
- `CLAUDE_PERM_SOCKET_PATH`
- `CLAUDE_PERM_SWAYIDLE_BINARY`

## How It Works

1. Claude Code invokes `claude-permission-hook` for each permission request
2. The hook connects to the daemon via Unix socket
3. If you're **active**: daemon returns passthrough → normal local prompt appears
4. If you're **idle**: daemon posts to Slack with Approve/Deny buttons
5. You tap a button → daemon sends response → Claude Code proceeds
6. If you **return** while a request is pending: message updates to "Answered Locally" → local prompt appears

## Troubleshooting

### Daemon not starting

Check logs:
```bash
journalctl --user -u claude-permission-daemon -f
```

Verify config:
```bash
claude-permission-daemon --debug
```

### Slack messages not appearing

1. Verify your bot token starts with `xoxb-`
2. Verify your app token starts with `xapp-`
3. Check that Socket Mode is enabled in your Slack app
4. Ensure Interactivity is enabled

### swayidle not working

Verify swayidle is installed and working:
```bash
swayidle -w timeout 5 'echo IDLE' resume 'echo ACTIVE'
```

## Development

### Running tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

### Running with debug logging

```bash
claude-permission-daemon --debug
```

### Testing the hook directly

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | claude-permission-hook
```

## License

MIT
