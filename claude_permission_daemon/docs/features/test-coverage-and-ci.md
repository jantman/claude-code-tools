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
