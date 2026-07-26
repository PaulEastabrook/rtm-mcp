"""Test configuration and fixtures."""

import pytest

from rtm_mcp.config import RTMConfig


@pytest.fixture(scope="session")
def _log_sink_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("rtm-mcp-logs")


@pytest.fixture(autouse=True)
def _isolated_log_sink(_log_sink_dir, monkeypatch):
    """Point the v5.1.0 file sink at a throwaway directory for the whole suite.

    `configure_logging()` opens a real `RotatingFileHandler`, so without this every test that
    touches it writes into the operator's live `~/.config/rtm-mcp/logs/` — mixing test noise
    into the one channel a headless run depends on, and the one place someone will look to find
    out what a scheduled worker did at 06:45.
    """
    monkeypatch.setenv("RTM_LOG_DIR", str(_log_sink_dir))


@pytest.fixture
def mock_config() -> RTMConfig:
    """Create a mock RTM config."""
    return RTMConfig(
        api_key="test_api_key",
        shared_secret="test_shared_secret",
        auth_token="test_auth_token",
        bucket_capacity=100,  # Large capacity to prevent waits in tests
    )


@pytest.fixture
def sample_task_response() -> dict:
    """Sample RTM task response."""
    return {
        "stat": "ok",
        "tasks": {
            "list": {
                "id": "123",
                "taskseries": {
                    "id": "456",
                    "name": "Test Task",
                    "created": "2024-01-01T00:00:00Z",
                    "modified": "2024-01-01T00:00:00Z",
                    "tags": {"tag": ["work", "urgent"]},
                    "notes": [],
                    "url": "",
                    "task": {
                        "id": "789",
                        "due": "2024-01-15T00:00:00Z",
                        "has_due_time": "0",
                        "completed": "",
                        "deleted": "",
                        "priority": "1",
                        "postponed": "0",
                        "estimate": "",
                    },
                },
            }
        },
    }


@pytest.fixture
def sample_lists_response() -> dict:
    """Sample RTM lists response."""
    return {
        "stat": "ok",
        "lists": {
            "list": [
                {
                    "id": "1",
                    "name": "Inbox",
                    "deleted": "0",
                    "locked": "1",
                    "archived": "0",
                    "position": "-1",
                    "smart": "0",
                },
                {
                    "id": "2",
                    "name": "Personal",
                    "deleted": "0",
                    "locked": "0",
                    "archived": "0",
                    "position": "0",
                    "smart": "0",
                },
                {
                    "id": "3",
                    "name": "Work",
                    "deleted": "0",
                    "locked": "0",
                    "archived": "0",
                    "position": "1",
                    "smart": "0",
                },
            ]
        },
    }
