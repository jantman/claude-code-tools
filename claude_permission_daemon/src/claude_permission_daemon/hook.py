#!/usr/bin/env python3
"""Hook script for Claude Code permission requests and notifications.

This script is invoked by Claude Code for:
- Permission requests (PreToolUse hook): Returns JSON to approve/deny
- Notifications (Notification hook): One-way, no response expected

It connects to the permission daemon via Unix socket and either:
- Returns a JSON response to approve/deny the request (permissions)
- Sends the notification and exits (notifications)
- Exits with no output to passthrough to normal flow

IMPORTANT: This script uses only Python stdlib - no external dependencies.
This ensures it can run without activating a virtual environment.
"""

import json
import os
import platform
import socket
import sys
from pathlib import Path


def _get_default_socket_path() -> Path:
    """Get platform-appropriate default socket path.

    Note: This duplicates logic from config.py but hook.py must remain
    stdlib-only and cannot import from other modules.
    """
    # Check for XDG_RUNTIME_DIR first (Linux standard)
    if "XDG_RUNTIME_DIR" in os.environ:
        return Path(os.environ["XDG_RUNTIME_DIR"]) / "claude-permissions.sock"

    # Platform-specific defaults
    system = platform.system()
    if system == "Linux":
        # Try common Linux runtime directories
        uid = os.getuid()
        runtime_dir = Path(f"/run/user/{uid}")
        if runtime_dir.exists():
            return runtime_dir / "claude-permissions.sock"
        # Fallback to /tmp for Linux if /run/user doesn't exist
        return Path("/tmp") / "claude-permissions.sock"
    elif system == "Darwin":
        # macOS: use /tmp
        return Path("/tmp") / "claude-permissions.sock"
    elif system == "Windows":
        # Windows: use named pipe (not a file path)
        return Path(r"\\.\pipe\claude-permissions")
    else:
        # Unknown platform: use /tmp as safest fallback
        return Path("/tmp") / "claude-permissions.sock"


# Default socket path
DEFAULT_SOCKET_PATH = _get_default_socket_path()

# Timeout for waiting for response (5 minutes)
DEFAULT_TIMEOUT = 300


def get_socket_path() -> Path:
    """Get the socket path from environment or default."""
    if path := os.environ.get("CLAUDE_PERM_SOCKET_PATH"):
        return Path(path)
    return DEFAULT_SOCKET_PATH


def get_timeout() -> int:
    """Get the timeout from environment or default."""
    if timeout := os.environ.get("CLAUDE_PERM_REQUEST_TIMEOUT"):
        return int(timeout)
    return DEFAULT_TIMEOUT


def read_request_from_stdin() -> dict | None:
    """Read and parse the permission request from stdin.

    Returns:
        Parsed request dict, or None if parsing fails.
    """
    try:
        data = sys.stdin.read()
        if not data:
            return None
        return json.loads(data)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON from stdin: {e}", file=sys.stderr)
        return None


def connect_to_daemon(socket_path: Path, timeout: int) -> socket.socket | None:
    """Connect to the permission daemon.

    Args:
        socket_path: Path to the Unix socket.
        timeout: Connection timeout in seconds.

    Returns:
        Connected socket, or None if connection fails.
    """
    if not socket_path.exists():
        print(
            f"Daemon socket not found: {socket_path}",
            file=sys.stderr,
        )
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(str(socket_path))
        return sock
    except socket.error as e:
        print(f"Failed to connect to daemon: {e}", file=sys.stderr)
        return None


def send_request(sock: socket.socket, request: dict) -> dict | None:
    """Send a request to the daemon and receive response.

    Args:
        sock: Connected socket.
        request: Request dict to send.

    Returns:
        Response dict, or None if communication fails.
    """
    debug = os.environ.get("CLAUDE_PERM_DEBUG", "").lower() in ("1", "true", "yes")

    try:
        # Send request as newline-terminated JSON
        request_json = json.dumps(request) + "\n"
        sock.sendall(request_json.encode())
        if debug:
            print(f"[DEBUG] Sent request, waiting for response...", file=sys.stderr)

        # Receive response (may take a while for Slack interaction)
        response_data = b""
        while True:
            chunk = sock.recv(4096)
            if debug:
                print(
                    f"[DEBUG] Received chunk: {len(chunk)} bytes",
                    file=sys.stderr,
                )
            if not chunk:
                break
            response_data += chunk
            # Response is newline-terminated
            if b"\n" in response_data:
                break

        if not response_data:
            print("No response from daemon", file=sys.stderr)
            return None

        if debug:
            print(f"[DEBUG] Response: {response_data.decode().strip()}", file=sys.stderr)

        return json.loads(response_data.decode().strip())

    except socket.timeout:
        print("Timeout waiting for daemon response", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"Invalid JSON response from daemon: {e}", file=sys.stderr)
        return None
    except socket.error as e:
        print(f"Socket error: {e}", file=sys.stderr)
        return None


def format_output(response: dict) -> str | None:
    """Format the daemon response as Claude Code output.

    Uses the hookSpecificOutput format for PermissionRequest hooks.
    See: https://code.claude.com/docs/en/hooks

    Args:
        response: Response dict from daemon.

    Returns:
        JSON string for Claude Code, or None for passthrough.
    """
    action = response.get("action")

    if action == "approve":
        # Use the PermissionRequest hook format with decision.behavior
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "allow",
                }
            }
        })
    elif action == "deny":
        return json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                }
            }
        })
    elif action == "passthrough":
        # Return None to indicate passthrough (no output)
        return None
    else:
        # Unknown action, passthrough
        print(f"Unknown action from daemon: {action}", file=sys.stderr)
        return None


def is_notification(request: dict) -> bool:
    """Check if the request is a notification (not a permission request).

    Args:
        request: The parsed request dict.

    Returns:
        True if this is a notification, False if permission request.
    """
    return (
        request.get("hook_event_name") == "Notification"
        or "notification_type" in request
    )


def send_notification(sock: socket.socket, request: dict) -> None:
    """Send a notification to the daemon (no response expected).

    Args:
        sock: Connected socket.
        request: Request dict to send.
    """
    try:
        # Send request as newline-terminated JSON
        request_json = json.dumps(request) + "\n"
        sock.sendall(request_json.encode())
        # No response expected for notifications
    except socket.error as e:
        print(f"Socket error sending notification: {e}", file=sys.stderr)


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    # Read request from stdin
    request = read_request_from_stdin()
    if request is None:
        # Failed to read request, passthrough
        return 0

    # Check if this is a notification or permission request
    notification = is_notification(request)

    # For permission requests, validate tool_name is present
    if not notification and "tool_name" not in request:
        print("Request missing tool_name", file=sys.stderr)
        return 0

    # Get socket path and timeout
    socket_path = get_socket_path()
    timeout = get_timeout()

    # Connect to daemon
    sock = connect_to_daemon(socket_path, timeout)
    if sock is None:
        # Daemon not available, passthrough
        return 0

    try:
        if notification:
            # Handle notification - one-way, no response
            send_notification(sock, request)
            return 0

        # Handle permission request
        response = send_request(sock, request)
        if response is None:
            # Communication failed, passthrough
            return 0

        # Check for error response
        if "error" in response:
            print(f"Daemon error: {response['error']}", file=sys.stderr)
            return 0

        # Format output for Claude Code
        output = format_output(response)
        if output is not None:
            print(output)

        return 0

    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
