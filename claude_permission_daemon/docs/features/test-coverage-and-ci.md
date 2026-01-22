# Test Coverage and CI

You must read, understand, and follow all instructions in `./README.md` when planning and implementing this feature.

## Overview

Add additional test coverage for the daemon module and create a GitHub Actions workflow to run tests on push and workflow_dispatch.

## Requirements

### 1. Additional Test Coverage

The current test suite has 106 tests with 60% overall coverage. The `daemon.py` module has 0% coverage because it contains the main orchestration logic that's harder to unit test. Add tests to cover:

- Daemon initialization and configuration
- Component wiring (idle monitor, socket server, slack handler callbacks)
- Permission request handling flow
- Slack action handling
- Idle state change handling (race condition logic)
- Shutdown behavior

Target: Improve overall coverage to at least 75%.

### 2. GitHub Actions Workflow

Create `.github/workflows/test.yml` that:

- Runs on push to any branch
- Runs on pull requests to main
- Runs on workflow_dispatch (manual trigger)
- Uses Python 3.14
- Installs dependencies
- Runs pytest with coverage reporting
- Fails if tests fail

## Deliverables

1. New test file `tests/test_daemon.py` with unit tests for daemon orchestration
2. `.github/workflows/test.yml` workflow file
3. Updated coverage metrics in feature documentation

---

# Implementation Plan

## Status: IN PROGRESS

Commit message prefix format: `TestCI - {Milestone}.{Task}: {summary}`

## Milestones and Tasks

### Milestone 1: Daemon Unit Tests

**Goal**: Add comprehensive unit tests for `daemon.py` module.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 1.1 | Test Daemon initialization | Tests for `__init__`, verify state manager and component initialization |
| 1.2 | Test Daemon start/stop | Tests for `start()` and `stop()` with mocked components |
| 1.3 | Test permission request handling | Tests for `_handle_permission_request()` - active user passthrough, idle user Slack flow, Slack failure fallback |
| 1.4 | Test Slack action handling | Tests for `_handle_slack_action()` - approve, deny, unknown request |
| 1.5 | Test idle state change handling | Tests for `_on_idle_change()` - race condition logic when user returns |
| 1.6 | Test helper functions | Tests for `setup_logging()`, `parse_args()` |

**Exit Criteria**: All tests pass, daemon.py coverage significantly improved.

### Milestone 2: GitHub Actions Workflow

**Goal**: Create CI workflow for automated testing.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 2.1 | Create workflow file | `.github/workflows/test.yml` with Python 3.14, pytest, coverage |
| 2.2 | Verify workflow syntax | Validate YAML syntax and workflow configuration |

**Exit Criteria**: Workflow file created and committed.

### Milestone 3: Acceptance Criteria

**Goal**: Final validation and documentation.

| Task | Description | Deliverables |
|------|-------------|--------------|
| 3.1 | Verify coverage improvement | Run coverage report, confirm >= 75% overall |
| 3.2 | Full test suite pass | All tests passing |
| 3.3 | Move feature to completed | Move this file to `docs/features/completed/` |

**Exit Criteria**: Feature complete, coverage target met, all tests passing.

---

## Progress Log

### Milestone 1: Daemon Unit Tests

**Status**: NOT STARTED

- [ ] Task 1.1: Test Daemon initialization
- [ ] Task 1.2: Test Daemon start/stop
- [ ] Task 1.3: Test permission request handling
- [ ] Task 1.4: Test Slack action handling
- [ ] Task 1.5: Test idle state change handling
- [ ] Task 1.6: Test helper functions

### Milestone 2: GitHub Actions Workflow

**Status**: NOT STARTED

- [ ] Task 2.1: Create workflow file
- [ ] Task 2.2: Verify workflow syntax

### Milestone 3: Acceptance Criteria

**Status**: NOT STARTED

- [ ] Task 3.1: Verify coverage improvement
- [ ] Task 3.2: Full test suite pass
- [ ] Task 3.3: Move feature to completed
