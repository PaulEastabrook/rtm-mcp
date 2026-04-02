"""Tests for shared task lookup and disambiguation."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from rtm_mcp.lookup import find_task, resolve_task_ids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_getlist_response(
    taskseries_list: list[dict] | dict,
    list_id: str = "1",
) -> dict[str, Any]:
    """Build a rtm.tasks.getList-style response."""
    return {
        "stat": "ok",
        "tasks": {
            "list": {
                "id": list_id,
                "taskseries": taskseries_list,
            }
        },
    }


def _ts(
    ts_id: str = "10",
    task_id: str = "100",
    name: str = "Test Task",
    modified: str = "2026-01-01T00:00:00Z",
    completed: str = "",
    tags: list[str] | None = None,
    due: str = "",
) -> dict[str, Any]:
    """Build a minimal taskseries dict."""
    tag_data: Any = []
    if tags:
        tag_data = {"tag": tags if len(tags) > 1 else tags[0]}
    return {
        "id": ts_id,
        "created": "2026-01-01T00:00:00Z",
        "modified": modified,
        "name": name,
        "source": "api",
        "url": "",
        "location_id": "",
        "parent_task_id": "",
        "tags": tag_data,
        "participants": [],
        "notes": [],
        "task": {
            "id": task_id,
            "due": due,
            "has_due_time": "0",
            "added": "2026-01-01T00:00:00Z",
            "completed": completed,
            "deleted": "",
            "priority": "N",
            "postponed": "0",
            "estimate": "",
            "start": "",
            "has_start_time": "0",
        },
    }


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.call = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# find_task tests
# ---------------------------------------------------------------------------

class TestFindTask:

    @pytest.mark.asyncio
    async def test_single_exact_match(self, mock_client):
        """Single exact match is returned directly."""
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Buy milk"),
            _ts(name="Buy eggs", ts_id="20", task_id="200"),
        ])
        result = await find_task(mock_client, "Buy milk")
        assert result is not None
        assert result["name"] == "Buy milk"

    @pytest.mark.asyncio
    async def test_exact_match_case_insensitive(self, mock_client):
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Buy Milk"),
        ])
        result = await find_task(mock_client, "buy milk")
        assert result is not None
        assert result["name"] == "Buy Milk"

    @pytest.mark.asyncio
    async def test_partial_match_when_no_exact(self, mock_client):
        """Partial match kicks in when no exact match exists."""
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Buy milk at the store"),
        ])
        result = await find_task(mock_client, "Buy milk")
        assert result is not None
        assert result["name"] == "Buy milk at the store"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self, mock_client):
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Buy eggs"),
        ])
        result = await find_task(mock_client, "Weekly review")
        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_exact_matches_prefers_most_recent(self, mock_client):
        """When multiple tasks share the same name, the most recently modified wins."""
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Weekly GTD review", ts_id="10", task_id="100",
                modified="2014-03-15T00:00:00Z"),
            _ts(name="Weekly GTD review", ts_id="20", task_id="200",
                modified="2026-04-02T10:30:00Z"),
        ])
        result = await find_task(mock_client, "Weekly GTD review")
        assert result is not None
        assert result["taskseries_id"] == "20"  # the newer one

    @pytest.mark.asyncio
    async def test_multiple_partial_matches_prefers_most_recent(self, mock_client):
        """Multiple partial matches also prefer the most recently modified."""
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Review project Alpha", ts_id="10", task_id="100",
                modified="2020-01-01T00:00:00Z"),
            _ts(name="Review project Beta", ts_id="20", task_id="200",
                modified="2026-04-01T00:00:00Z"),
        ])
        result = await find_task(mock_client, "Review project")
        assert result is not None
        assert result["taskseries_id"] == "20"

    @pytest.mark.asyncio
    async def test_exact_match_preferred_over_partial(self, mock_client):
        """An exact match beats a partial match even if the partial is more recent."""
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Buy milk at store", ts_id="10", task_id="100",
                modified="2026-04-02T00:00:00Z"),
            _ts(name="Buy milk", ts_id="20", task_id="200",
                modified="2020-01-01T00:00:00Z"),
        ])
        result = await find_task(mock_client, "Buy milk")
        assert result is not None
        assert result["taskseries_id"] == "20"  # exact match wins

    @pytest.mark.asyncio
    async def test_filters_incomplete_by_default(self, mock_client):
        """By default, calls getList with status:incomplete filter."""
        mock_client.call.return_value = _make_getlist_response([])
        await find_task(mock_client, "anything")
        mock_client.call.assert_called_once_with(
            "rtm.tasks.getList", filter="status:incomplete"
        )

    @pytest.mark.asyncio
    async def test_include_completed_removes_filter(self, mock_client):
        """include_completed=True calls getList without filter."""
        mock_client.call.return_value = _make_getlist_response([])
        await find_task(mock_client, "anything", include_completed=True)
        mock_client.call.assert_called_once_with("rtm.tasks.getList")

    @pytest.mark.asyncio
    async def test_empty_task_list(self, mock_client):
        mock_client.call.return_value = {"stat": "ok", "tasks": {}}
        result = await find_task(mock_client, "anything")
        assert result is None


# ---------------------------------------------------------------------------
# resolve_task_ids tests
# ---------------------------------------------------------------------------

class TestResolveTaskIds:

    @pytest.mark.asyncio
    async def test_with_explicit_ids(self, mock_client):
        """When all three IDs are provided, returns them directly."""
        result = await resolve_task_ids(
            mock_client, None, "100", "10", "1"
        )
        assert result == {"task_id": "100", "taskseries_id": "10", "list_id": "1"}
        mock_client.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_ids_override_task_name(self, mock_client):
        """When task_id is provided alongside task_name, IDs win."""
        result = await resolve_task_ids(
            mock_client, "Buy milk", "100", "10", "1"
        )
        assert result == {"task_id": "100", "taskseries_id": "10", "list_id": "1"}
        mock_client.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_ids_returns_error(self, mock_client):
        result = await resolve_task_ids(
            mock_client, None, "100", None, "1"
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_name_search_found(self, mock_client):
        mock_client.call.return_value = _make_getlist_response([
            _ts(name="Buy milk", ts_id="10", task_id="100"),
        ])
        result = await resolve_task_ids(
            mock_client, "Buy milk", None, None, None
        )
        assert result == {"task_id": "100", "taskseries_id": "10", "list_id": "1"}

    @pytest.mark.asyncio
    async def test_name_search_not_found(self, mock_client):
        mock_client.call.return_value = _make_getlist_response([])
        result = await resolve_task_ids(
            mock_client, "Nonexistent task", None, None, None
        )
        assert "error" in result
        assert "Nonexistent task" in result["error"]

    @pytest.mark.asyncio
    async def test_include_completed_passed_through(self, mock_client):
        """include_completed flag is forwarded to find_task."""
        mock_client.call.return_value = _make_getlist_response([])
        await resolve_task_ids(
            mock_client, "Some task", None, None, None,
            include_completed=True,
        )
        mock_client.call.assert_called_once_with("rtm.tasks.getList")
