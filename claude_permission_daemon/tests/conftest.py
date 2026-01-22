"""Pytest configuration and fixtures for claude_permission_daemon tests."""

import asyncio
import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_config_content() -> str:
    """Provide sample valid TOML config content."""
    return """
[daemon]
socket_path = "/tmp/test-claude-permissions.sock"
idle_timeout = 30
request_timeout = 120

[slack]
bot_token = "xoxb-test-token-12345"
app_token = "xapp-test-token-67890"
channel = "U12345678"

[swayidle]
binary = "/usr/bin/swayidle"
"""


@pytest.fixture
def config_file(temp_dir: Path, sample_config_content: str) -> Path:
    """Create a temporary config file with sample content."""
    config_path = temp_dir / "config.toml"
    config_path.write_text(sample_config_content)
    return config_path


@pytest.fixture
def minimal_config_content() -> str:
    """Provide minimal valid TOML config (only required fields)."""
    return """
[slack]
bot_token = "xoxb-minimal-token"
app_token = "xapp-minimal-token"
channel = "C12345678"
"""


@pytest.fixture
def minimal_config_file(temp_dir: Path, minimal_config_content: str) -> Path:
    """Create a temporary config file with minimal content."""
    config_path = temp_dir / "config.toml"
    config_path.write_text(minimal_config_content)
    return config_path
