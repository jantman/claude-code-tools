# Claude Permission Daemon

Remote approval of Claude Code permission requests and notifications via Slack when the user is idle.

## Overview

When you step away from your computer while Claude Code is running, permission requests would normally block until you return. This daemon detects when you're idle and forwards permission requests to Slack where you can approve or deny them from your phone. It also forwards Claude Code notifications (like "waiting for input") to Slack when you're idle.

**Key features:**
- Cross-platform idle detection:
  - **Linux**: swayidle (Wayland/X11)
  - **macOS**: IOHIDSystem via ioreg
  - **Windows**: GetLastInputInfo API
- Slack Socket Mode for real-time notifications
- Approve/deny buttons for permission requests
- One-way notifications (idle prompts, auth events, etc.)
- Automatic passthrough when you return to your computer
- Clean race condition handling
- Idle/active duration tracking in logs

![Slack notification example](docs/slack.png)

## Requirements

- Python 3.14+
- **Linux**: swayidle installed (available in most distro repositories)
- **macOS**: ioreg (included with macOS)
- **Windows**: Windows API (included with Windows)
- A Slack workspace with permission to create apps

## Installation

### 1. Install the package

#### Linux / macOS

Create a virtualenv and install:

```bash
# Create virtualenv directory
mkdir -p ~/.local/share/claude-permission-daemon
python3.14 -m venv ~/.local/share/claude-permission-daemon/venv

# Install the package
~/.local/share/claude-permission-daemon/venv/bin/pip install /path/to/claude_permission_daemon
```

Or if installing from the source directory:

```bash
~/.local/share/claude-permission-daemon/venv/bin/pip install .
```

#### Windows

Create a virtualenv and install:

```powershell
# Create virtualenv directory
mkdir $env:LOCALAPPDATA\claude-permission-daemon
python -m venv $env:LOCALAPPDATA\claude-permission-daemon\venv

# Install the package
& $env:LOCALAPPDATA\claude-permission-daemon\venv\Scripts\pip install C:\path\to\claude_permission_daemon
```

Or if installing from the source directory:

```powershell
& $env:LOCALAPPDATA\claude-permission-daemon\venv\Scripts\pip install .
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

#### Linux / macOS

Create the config file:

```bash
mkdir -p ~/.config/claude-permission-daemon
cp example/config.toml ~/.config/claude-permission-daemon/config.toml
```

Edit `~/.config/claude-permission-daemon/config.toml` with your Slack tokens.

#### Windows

Create the config file:

```powershell
mkdir $env:APPDATA\claude-permission-daemon
copy example\config.toml $env:APPDATA\claude-permission-daemon\config.toml
```

Edit `%APPDATA%\claude-permission-daemon\config.toml` with your Slack tokens.

#### Configuration Example

```toml
[slack]
bot_token = "xoxb-your-bot-token"
app_token = "xapp-your-app-token"
channel = "U12345678"  # Your Slack user ID for DMs
```

### 4. Set up automatic startup

#### Linux (systemd)

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

#### macOS (launchd)

Create `~/Library/LaunchAgents/com.claude.permission-daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude.permission-daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USERNAME/.local/share/claude-permission-daemon/venv/bin/claude-permission-daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/claude-permission-daemon.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/claude-permission-daemon.err</string>
</dict>
</plist>
```

Replace `YOUR_USERNAME` with your actual username, then load the service:

```bash
launchctl load ~/Library/LaunchAgents/com.claude.permission-daemon.plist
launchctl start com.claude.permission-daemon
```

Check status:

```bash
launchctl list | grep claude
tail -f /tmp/claude-permission-daemon.log
```

#### Windows (Task Scheduler)

You can use Task Scheduler to run the daemon at startup, or run it manually when needed:

**Manual start:**
```powershell
& $env:LOCALAPPDATA\claude-permission-daemon\venv\Scripts\claude-permission-daemon.exe
```

**Task Scheduler setup:**
1. Open Task Scheduler
2. Create Basic Task → "Claude Permission Daemon"
3. Trigger: "When I log on"
4. Action: "Start a program"
5. Program: `%LOCALAPPDATA%\claude-permission-daemon\venv\Scripts\claude-permission-daemon.exe`
6. Check "Run whether user is logged on or not" (optional)

### 5. Configure Claude Code

#### Linux / macOS

Add to `~/.claude/settings.json` (use the full path to the hook in your virtualenv):

```json
{
    "hooks": {
        "PermissionRequest": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.local/share/claude-permission-daemon/venv/bin/claude-permission-hook"
                    }
                ]
            }
        ],
        "Notification": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "~/.local/share/claude-permission-daemon/venv/bin/claude-permission-hook"
                    }
                ]
            }
        ]
    }
}
```

#### Windows

Add to `%USERPROFILE%\.claude\settings.json` (use the full path to the hook in your virtualenv):

```json
{
    "hooks": {
        "PermissionRequest": [
            {
                "matcher": "*",
                "hooks": [
                    {
                        "type": "command",
                        "command": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\claude-permission-daemon\\venv\\Scripts\\claude-permission-hook.exe"
                    }
                ]
            }
        ],
        "Notification": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "C:\\Users\\YOUR_USERNAME\\AppData\\Local\\claude-permission-daemon\\venv\\Scripts\\claude-permission-hook.exe"
                    }
                ]
            }
        ]
    }
}
```

Replace `YOUR_USERNAME` with your actual Windows username.

**Note:** The `PermissionRequest` hook uses the `decision.behavior` response format. The `Notification` hook is optional - if configured, you'll receive Slack notifications when Claude is waiting for input (idle prompt) or other events occur while you're away. `permission_prompt` notifications are automatically filtered out since they're already handled by the permission request system.

## Configuration Reference

### Configuration File Location

- **Linux/macOS**: `~/.config/claude-permission-daemon/config.toml`
- **Windows**: `%APPDATA%\claude-permission-daemon\config.toml`

### Configuration Options

```toml
[daemon]
# Socket path for hook communication
# Linux/macOS default: $XDG_RUNTIME_DIR/claude-permissions.sock or /tmp/claude-permissions.sock
# Windows default: \\.\pipe\claude-permissions
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
# Linux only: Path to swayidle binary (default: found in PATH)
# binary = "/usr/bin/swayidle"

[mac]
# macOS only: Path to ioreg binary (default: "ioreg", usually at /usr/sbin/ioreg)
# binary = "/usr/sbin/ioreg"

[windows]
# Windows only: No configuration needed
# Uses built-in GetLastInputInfo API
```

### Environment Variables

All config values can be overridden with environment variables:

- `CLAUDE_PERM_SLACK_BOT_TOKEN`
- `CLAUDE_PERM_SLACK_APP_TOKEN`
- `CLAUDE_PERM_SLACK_CHANNEL`
- `CLAUDE_PERM_IDLE_TIMEOUT`
- `CLAUDE_PERM_REQUEST_TIMEOUT`
- `CLAUDE_PERM_SOCKET_PATH`
- `CLAUDE_PERM_SWAYIDLE_BINARY` (Linux only)
- `CLAUDE_PERM_IOREG_BINARY` (macOS only)
- `CLAUDE_PERM_DEBUG` (set to `1`, `true`, or `yes` to enable debug logging)

## How It Works

### Permission Requests

1. Claude Code invokes `claude-permission-hook` for each permission request
2. The hook connects to the daemon via IPC (Unix socket on Linux/macOS, named pipe on Windows)
3. If you're **active**: daemon returns passthrough → normal local prompt appears
4. If you're **idle**: daemon posts to Slack with Approve/Deny buttons
5. You tap a button → daemon sends response → Claude Code proceeds
6. If you **return** while a request is pending: message updates to "Answered Locally" → local prompt appears

### Notifications

1. Claude Code invokes `claude-permission-hook` for notifications (idle prompts, etc.)
2. The hook connects to the daemon and sends the notification (one-way, no response)
3. If you're **active**: notification is logged but not sent to Slack
4. If you're **idle**: notification is posted to Slack as an info message (no buttons)
5. `permission_prompt` notifications are filtered out (handled by permission system)

## Troubleshooting

### Daemon not starting

#### Linux
Check systemd logs:
```bash
journalctl --user -u claude-permission-daemon -f
```

Run with debug logging:
```bash
~/.local/share/claude-permission-daemon/venv/bin/claude-permission-daemon --debug
```

#### macOS
Check launchd logs:
```bash
tail -f /tmp/claude-permission-daemon.log
tail -f /tmp/claude-permission-daemon.err
```

Run manually with debug logging:
```bash
~/.local/share/claude-permission-daemon/venv/bin/claude-permission-daemon --debug
```

#### Windows
Run manually with debug logging:
```powershell
& $env:LOCALAPPDATA\claude-permission-daemon\venv\Scripts\claude-permission-daemon.exe --debug
```

### Slack messages not appearing

1. Verify your bot token starts with `xoxb-`
2. Verify your app token starts with `xapp-`
3. Check that Socket Mode is enabled in your Slack app
4. Ensure Interactivity is enabled

### Platform-specific idle detection issues

#### Linux: swayidle not working

Verify swayidle is installed and working:
```bash
swayidle -w timeout 5 'echo IDLE' resume 'echo ACTIVE'
```

Install swayidle if missing:
```bash
# Debian/Ubuntu
sudo apt install swayidle

# Arch Linux
sudo pacman -S swayidle

# Fedora
sudo dnf install swayidle
```

#### macOS: ioreg not working

Verify ioreg is available (should be included with macOS):
```bash
ioreg -c IOHIDSystem | grep HIDIdleTime
```

If not found, check the binary path in your config:
```toml
[mac]
binary = "/usr/sbin/ioreg"
```

#### Windows: Idle detection not working

Windows idle detection uses the built-in GetLastInputInfo API which should always be available. If idle detection isn't working:
1. Verify the daemon is running
2. Check debug logs for API errors
3. Ensure Windows isn't in a special power state

## Development

### Running tests

#### Linux / macOS
```bash
python3.14 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -v
```

#### Windows
```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest tests\ -v
```

### Running with debug logging

#### Linux / macOS
```bash
.venv/bin/claude-permission-daemon --debug
```

#### Windows
```powershell
.venv\Scripts\claude-permission-daemon.exe --debug
```

### Testing the hook directly

#### Linux / macOS

Permission request:
```bash
echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | .venv/bin/claude-permission-hook
```

Notification:
```bash
echo '{"hook_event_name":"Notification","notification_type":"idle_prompt","message":"Claude is waiting for input"}' | .venv/bin/claude-permission-hook
```

#### Windows

Permission request:
```powershell
echo '{"tool_name":"Bash","tool_input":{"command":"echo test"}}' | .venv\Scripts\claude-permission-hook.exe
```

Notification:
```powershell
echo '{"hook_event_name":"Notification","notification_type":"idle_prompt","message":"Claude is waiting for input"}' | .venv\Scripts\claude-permission-hook.exe
```

## License

MIT
