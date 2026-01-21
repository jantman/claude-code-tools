# Claude Code Remote Access via HTTP over LAN

If you don't need idle detection and just want remote access to approve permissions, a simpler approach uses tmux and ttyd to expose your terminal via a web browser.

### Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Your Desktop                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  tmux session "claude"                                │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  Claude Code                                    │  │  │
│  │  │  (permission prompt visible here)               │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│       ▲                              ▲                      │
│       │ attach                       │ attach               │
│  ┌────┴─────┐                  ┌─────┴──────┐               │
│  │  Kitty   │                  │   ttyd     │               │
│  │ terminal │                  │ :7681      │               │
│  └──────────┘                  └─────┬──────┘               │
│                                      │                      │
└──────────────────────────────────────┼──────────────────────┘
                                       │ HTTP (LAN only)
                                       ▼
                              ┌──────────────────┐
                              │  Phone/iPad via  │
                              │  VPN + browser   │
                              └──────────────────┘
```

### Installation

```bash
# Arch Linux
pacman -S tmux ttyd
```

### Super Simple Version:

1. In one terminal window: `tmux new-session -s claude` and then run claude in this tmux session
2. In another terminal window: `ttyd -W tmux attach -t claude`

### Wrapper Script

Create `~/.local/bin/claude-remote`:

```bash
#!/bin/bash
set -euo pipefail

SESSION_NAME="claude"
TTYD_PORT="${CLAUDE_TTYD_PORT:-7681}"
TTYD_PID_FILE="${XDG_RUNTIME_DIR}/claude-ttyd.pid"

start_session() {
    # Create tmux session if it doesn't exist
    if ! tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        tmux new-session -d -s "$SESSION_NAME" -x 120 -y 40
        echo "Created new tmux session: $SESSION_NAME"
    fi
    
    # Start ttyd if not already running
    if [[ -f "$TTYD_PID_FILE" ]] && kill -0 "$(cat "$TTYD_PID_FILE")" 2>/dev/null; then
        echo "ttyd already running on port $TTYD_PORT"
    else
        ttyd -p "$TTYD_PORT" -W tmux attach -t "$SESSION_NAME" &
        echo $! > "$TTYD_PID_FILE"
        echo "Started ttyd on port $TTYD_PORT"
    fi
    
    # Attach locally
    exec tmux attach -t "$SESSION_NAME"
}

stop_ttyd() {
    if [[ -f "$TTYD_PID_FILE" ]]; then
        kill "$(cat "$TTYD_PID_FILE")" 2>/dev/null || true
        rm -f "$TTYD_PID_FILE"
        echo "Stopped ttyd"
    fi
}

status() {
    echo "=== tmux session ==="
    if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
        echo "Session '$SESSION_NAME' exists"
        tmux list-windows -t "$SESSION_NAME"
    else
        echo "No session"
    fi
    
    echo ""
    echo "=== ttyd ==="
    if [[ -f "$TTYD_PID_FILE" ]] && kill -0 "$(cat "$TTYD_PID_FILE")" 2>/dev/null; then
        echo "Running on http://localhost:$TTYD_PORT"
    else
        echo "Not running"
    fi
}

case "${1:-start}" in
    start)
        start_session
        ;;
    stop)
        stop_ttyd
        ;;
    status)
        status
        ;;
    url)
        # Print URL for easy copying
        IP=$(hostname -I | awk '{print $1}')
        echo "http://${IP}:${TTYD_PORT}"
        ;;
    *)
        echo "Usage: $0 {start|stop|status|url}"
        exit 1
        ;;
esac
```

Make executable:
```bash
chmod +x ~/.local/bin/claude-remote
```

### Usage

```bash
# Start Claude Code in remote-accessible tmux session
claude-remote

# Inside the session, run claude as normal
claude

# From another terminal, check status
claude-remote status

# Get URL for phone access
claude-remote url

# Stop ttyd (session keeps running)
claude-remote stop
```

### tmux Configuration

Add to `~/.tmux.conf` for better phone experience:

```tmux
# Resize based on active client, not smallest
setw -g aggressive-resize on

# Larger scrollback for reviewing Claude output
set -g history-limit 50000

# Mouse support (useful for phone scrolling)
set -g mouse on
```

### ttyd Options

For additional security or features, modify the ttyd command in the script:

```bash
# Read-only mode (view only, can't type)
ttyd -R -p "$TTYD_PORT" tmux attach -t "$SESSION_NAME" &

# With basic auth
ttyd -c user:password -p "$TTYD_PORT" -W tmux attach -t "$SESSION_NAME" &

# HTTPS with self-signed cert
ttyd --ssl --ssl-cert ~/.local/share/ttyd/cert.pem \
     --ssl-key ~/.local/share/ttyd/key.pem \
     -p "$TTYD_PORT" -W tmux attach -t "$SESSION_NAME" &
```

### systemd User Service (Optional)

If you want ttyd always available when logged in, create `~/.config/systemd/user/claude-ttyd.service`:

```ini
[Unit]
Description=ttyd for Claude Code tmux session
After=graphical-session.target

[Service]
Type=simple
ExecStartPre=/usr/bin/tmux new-session -d -s claude -x 120 -y 40 || true
ExecStart=/usr/bin/ttyd -p 7681 -W /usr/bin/tmux attach -t claude
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
```

Enable:
```bash
systemctl --user daemon-reload
systemctl --user enable --now claude-ttyd
```

### Phone Browser Tips

- **Landscape mode** works better for terminal width
- **Pinch to zoom** to make text readable
- **Request desktop site** if the touch keyboard obscures too much
- ttyd supports touch scrolling for reviewing output

### Combining Both Approaches

You can use tmux/ttyd alongside the Slack notification system:

1. Slack notifies you that a permission is needed
2. You open the ttyd URL on your phone
3. You type `y` or `n` directly in the terminal
4. More context visible than just the Slack message

This hybrid gives you push notifications (Slack) with full terminal access (ttyd) when needed.

## Future Enhancements (Out of Scope for Initial Implementation)

- Pushover/Telegram support as alternative to Slack
- Web UI for status monitoring
- Approval rules engine (auto-approve certain patterns)
- Notification when Claude Code task completes
- Integration with tmux/ttyd for full remote access
- Mobile app

## Glossary

- **Claude Code:** Anthropic's CLI tool for AI-assisted coding
- **Hook:** A script that Claude Code invokes at specific lifecycle points
- **PermissionRequest:** Hook event fired when Claude Code needs user approval for a tool
- **Socket Mode:** Slack's WebSocket-based connection method that doesn't require public endpoints
- **swayidle:** Wayland idle management daemon that monitors user activity
- **ext-idle-notify:** Wayland protocol for idle detection, supported by KDE Plasma
