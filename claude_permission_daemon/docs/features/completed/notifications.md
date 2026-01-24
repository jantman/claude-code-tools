# Notifications Hook

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

I would like this application to also handle Claude's `Notification` hook, and send these notifications to me via Slack if I'm idle. These notifications (I believe) are not actionable, i.e. they're a one-way notification with no response needed. Be sure to update the application code, documentation (README), and tests, and ensure the tests pass.

In addition to this work, I'd also like the idle monitor to track how long the user has been idle or active, and for the application to include the current idle/active state and duration in log messages when it determines whether to send something via Slack or not.

---

## Research: Claude Code Notification Hook

The Notification hook receives JSON via stdin with this structure:

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl",
  "cwd": "/Users/...",
  "permission_mode": "default",
  "hook_event_name": "Notification",
  "message": "Claude needs your permission to use Bash",
  "notification_type": "permission_prompt"
}
```

**Key differences from permission requests:**
- Contains `hook_event_name: "Notification"` and `notification_type` field
- Does NOT contain `tool_name` or `tool_input` fields
- **NO response is expected** - this is one-way notification
- Exit code 0 = success (output logged to debug only)
- Exit code 2 = blocking error (stderr shown to user)

**Common notification types:**
- `permission_prompt` - Permission requests from Claude Code (**IGNORED** - handled by existing PreToolUse permission system)
- `idle_prompt` - When Claude is waiting for user input (60+ seconds idle)
- `auth_success` - Authentication success notifications
- `elicitation_dialog` - When Claude Code needs input for MCP tool elicitation

**Important**: Notifications with `notification_type: "permission_prompt"` will be ignored/filtered out since these are already handled by the existing permission request system via the PreToolUse hook.

---

# Implementation Plan

## Status: COMPLETED

Commit message prefix format: `Notifications - {Milestone}.{Task}: {summary}`

## Milestones and Tasks

### Milestone 1: Idle Duration Tracking

**Goal**: Track and report how long the user has been in the current idle/active state.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 1.1 | Add duration tracking to StateManager | Add `_idle_since: datetime` field to track when current state started, add `idle_duration` property |
| 1.2 | Update log messages with state and duration | Modify `daemon.py` to include state and duration in log messages when deciding whether to send to Slack |
| 1.3 | Add unit tests for duration tracking | Tests for duration calculation and state transition tracking |

**Exit Criteria**: StateManager tracks duration, logs include state info, tests pass.

### Milestone 2: Notification Data Structures

**Goal**: Add data structures and types for handling notifications.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 2.1 | Add Notification dataclass to state.py | `Notification` dataclass with `notification_id`, `message`, `notification_type`, `cwd`, `timestamp` |
| 2.2 | Add message type enum | `MessageType` enum to distinguish `PERMISSION_REQUEST` from `NOTIFICATION` |
| 2.3 | Add unit tests | Tests for new data structures |

**Exit Criteria**: Data structures defined and tested.

### Milestone 3: Socket Server Notification Support

**Goal**: Enable socket server to distinguish and handle notifications.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 3.1 | Add notification detection logic | Detect notifications by presence of `hook_event_name` or `notification_type` (absence of `tool_name`) |
| 3.2 | Filter out `permission_prompt` notifications | Ignore notifications with `notification_type: "permission_prompt"` (handled by existing permission system) |
| 3.3 | Add notification request handler callback type | `NotificationHandler` type alias for notification callback |
| 3.4 | Update `_handle_connection` to route appropriately | Route permission requests to `on_request`, notifications to `on_notification` |
| 3.5 | Add unit tests | Tests for notification detection, filtering, and routing |

**Exit Criteria**: Socket server correctly routes notifications vs permission requests, filters permission_prompt.

### Milestone 4: Slack Notification Formatting

**Goal**: Add Slack message formatting for notifications.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 4.1 | Add `format_notification()` function | Format notification as Slack Block Kit message (no buttons, info-only) |
| 4.2 | Add `post_notification()` method to SlackHandler | Method to post notification to Slack (no response tracking needed) |
| 4.3 | Add unit tests | Tests for formatting and posting |

**Exit Criteria**: Notifications can be formatted and posted to Slack.

### Milestone 5: Daemon Notification Handling

**Goal**: Integrate notification handling into the daemon.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 5.1 | Add notification handler to Daemon | `_handle_notification()` method that posts to Slack when idle |
| 5.2 | Wire notification handler to socket server | Pass notification handler callback when creating SocketServer |
| 5.3 | Update hook.py for notifications | Handle notification messages (no response output, just exit 0) |
| 5.4 | Add unit tests | Tests for notification handling flow |
| 5.5 | Add integration tests | End-to-end notification flow tests |

**Exit Criteria**: Notifications flow from hook through daemon to Slack when idle.

### Milestone 6: Acceptance Criteria

**Goal**: Final validation, documentation, and cleanup.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 6.1 | Update README documentation | Document notification hook support, configuration, and usage |
| 6.2 | Update CLAUDE.md if needed | Ensure dev context is current |
| 6.3 | Run full test suite | All tests passing |
| 6.4 | Move feature to completed | Move this file to `docs/features/completed/` |

**Exit Criteria**: Feature complete, documented, all tests passing.

---

## Progress Log

### Milestone 1: Idle Duration Tracking

**Status**: NOT STARTED

### Milestone 2: Notification Data Structures

**Status**: NOT STARTED

### Milestone 3: Socket Server Notification Support

**Status**: NOT STARTED

### Milestone 4: Slack Notification Formatting

**Status**: NOT STARTED

### Milestone 5: Daemon Notification Handling

**Status**: NOT STARTED

### Milestone 6: Acceptance Criteria

**Status**: NOT STARTED
