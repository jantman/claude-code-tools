# Remote Updates

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

This application is working great, but it doesn't currently detect if a claude permission request is approved not via slack when swayidle reports that the session is still idle, such as if claude is running via `tmux` and I connect to the session remotely over SSH and approve it. Please evaluate the possible solutions to this problem, present them to me for decision, and then implement the one(s) I pick including relevant documentation and test updates.

## Solution Analysis

**Problem**: When user connects remotely (SSH/tmux) while `swayidle` still reports idle, permission requests answered locally are not detected. The Slack message remains active with buttons even though the request was already handled.

**Chosen Solution**: Detect socket disconnection from hook script.

When a permission request is answered locally (via terminal), Claude Code proceeds and the hook script exits. The daemon can detect when the socket connection closes unexpectedly (without the daemon sending a response), indicating the request was "answered locally" (or more accurately, "answered remotely" from the perspective of not being answered via Slack).

## Implementation Plan

### Milestone 1: Add connection monitoring infrastructure

**Prefix**: `Remote Updates - 1`

#### Task 1.1: Extend socket handling to include reader
Currently, only the `StreamWriter` is passed to the daemon. We need to also pass the `StreamReader` so we can detect when the connection closes (EOF on read).

- Modify `PendingRequest` dataclass in `state.py` to store `hook_reader: asyncio.StreamReader | None`
- Update `SocketServer._handle_permission_request()` to pass the reader to the callback
- Update `RequestHandler` type alias to include the reader parameter
- Update `Daemon._handle_permission_request()` to accept and store the reader

#### Task 1.2: Add connection monitoring method
Add a method to check if a hook connection is still alive by attempting to read from it (non-blocking check for EOF).

- Add `async def monitor_connection()` method to `Daemon` that monitors a single pending request's connection
- The method should detect EOF (connection closed) and return when detected

### Milestone 2: Implement monitoring logic and Slack updates

**Prefix**: `Remote Updates - 2`

#### Task 2.1: Start monitoring when request posted to Slack
When a permission request is successfully posted to Slack, start a background task that monitors the hook connection.

- In `Daemon._handle_permission_request()`, after posting to Slack successfully, create a monitoring task
- Store the task reference to allow cancellation when request is resolved normally
- Modify `PendingRequest` to store `monitor_task: asyncio.Task | None`

#### Task 2.2: Handle connection closure detection
When monitoring detects the connection closed:

- Call a new handler method `_handle_answered_remotely()`
- Update the Slack message to show "Answered Remotely" status
- Clean up the pending request (but don't try to send response since connection is closed)

#### Task 2.3: Add Slack message format for "Answered Remotely"
- Add `update_message_answered_remotely()` to `SlackHandler`
- Add `format_answered_remotely()` function with appropriate messaging (distinct from "Answered Locally" which implies swayidle detected user return)

#### Task 2.4: Cancel monitoring on normal resolution
When a request is resolved normally (via Slack button or user becoming active), cancel the monitoring task.

- Modify `_resolve_request()` to cancel the monitoring task if present
- Ensure clean cancellation without errors

### Milestone 3: Testing and edge cases

**Prefix**: `Remote Updates - 3`

#### Task 3.1: Handle race conditions
Ensure proper handling when:
- Slack response arrives at same time as connection closure
- Multiple requests pending simultaneously
- Connection closes during shutdown

#### Task 3.2: Add unit tests
- Test connection monitoring detection
- Test "answered remotely" flow
- Test race condition handling
- Test cancellation of monitoring on normal resolution

#### Task 3.3: Add integration tests
- Test end-to-end flow with simulated hook disconnection

### Milestone 4: Acceptance Criteria

**Prefix**: `Remote Updates - 4`

#### Task 4.1: Documentation updates
- Update `CLAUDE.md` with information about remote answer detection
- Update any relevant docstrings

#### Task 4.2: Verify all tests pass
- Run full test suite
- Ensure no regressions

#### Task 4.3: Move feature file
- Move this file to `docs/features/completed/`

## Progress

- [x] Solution analysis and selection
- [ ] Milestone 1: Add connection monitoring infrastructure
- [ ] Milestone 2: Implement monitoring logic and Slack updates
- [ ] Milestone 3: Testing and edge cases
- [ ] Milestone 4: Acceptance Criteria
