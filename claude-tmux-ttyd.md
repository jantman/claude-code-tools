# Claude Code Remote Access (Obsolete)

This document previously described a tmux + ttyd setup for remotely accessing Claude Code sessions over a LAN browser. That approach is now obsolete.

## Use Claude Code Remote Control Instead

Claude Code now has built-in remote control support. To connect to a running session remotely:

```bash
claude --remote-control "SessionName"
```

See the official documentation for details: https://code.claude.com/docs/en/remote-control#interactive-session
