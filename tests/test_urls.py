"""Tests for RTM web UI URL construction and parent chain walking."""

from unittest.mock import AsyncMock

import pytest

from rtm_mcp.urls import (
    build_list_url,
    build_task_url,
    resolve_task_url,
    walk_parent_chain,
)


# ---------------------------------------------------------------------------
# build_list_url
# ---------------------------------------------------------------------------

class TestBuildListUrl:
    def test_basic(self):
        url = build_list_url("49657585")
        assert url == "https://www.rememberthemilk.com/app/#list/49657585"

    def test_different_id(self):
        url = build_list_url("12345")
        assert url == "https://www.rememberthemilk.com/app/#list/12345"


# ---------------------------------------------------------------------------
# build_task_url
# ---------------------------------------------------------------------------

class TestBuildTaskUrl:
    def test_single_segment(self):
        url = build_task_url("100", ["200"])
        assert url == "https://www.rememberthemilk.com/app/#list/100/200"

    def test_two_segments(self):
        url = build_task_url("100", ["200", "300"])
        assert url == "https://www.rememberthemilk.com/app/#list/100/200/300"

    def test_three_segments(self):
        url = build_task_url("49657585", ["400591040", "1159504180", "1195101122"])
        assert url == (
            "https://www.rememberthemilk.com/app/"
            "#list/49657585/400591040/1159504180/1195101122"
        )


# ---------------------------------------------------------------------------
# walk_parent_chain
# ---------------------------------------------------------------------------

def _task(task_id, name, parent_task_id=None, taskseries_id=None):
    """Helper to create a minimal task dict."""
    return {
        "id": task_id,
        "taskseries_id": taskseries_id or f"ts_{task_id}",
        "list_id": "1",
        "name": name,
        "parent_task_id": parent_task_id,
    }


class TestWalkParentChain:
    def test_no_parent(self):
        target = _task("100", "Root task")
        chain, warning = walk_parent_chain(target, [target])
        assert len(chain) == 1
        assert chain[0]["id"] == "100"
        assert warning is None

    def test_single_parent(self):
        parent = _task("100", "Focus area")
        child = _task("200", "Project", parent_task_id="100")
        all_tasks = [parent, child]

        chain, warning = walk_parent_chain(child, all_tasks)
        assert len(chain) == 2
        assert chain[0]["id"] == "100"
        assert chain[1]["id"] == "200"
        assert warning is None

    def test_three_levels(self):
        focus = _task("100", "Focus area")
        project = _task("200", "Project", parent_task_id="100")
        action = _task("300", "Action", parent_task_id="200")
        all_tasks = [focus, project, action]

        chain, warning = walk_parent_chain(action, all_tasks)
        assert len(chain) == 3
        assert [t["id"] for t in chain] == ["100", "200", "300"]
        assert warning is None

    def test_missing_parent(self):
        child = _task("200", "Orphan task", parent_task_id="999")
        chain, warning = walk_parent_chain(child, [child])
        assert len(chain) == 1
        assert chain[0]["id"] == "200"
        assert "999" in warning
        assert "not found" in warning

    def test_cycle_detection(self):
        a = _task("100", "Task A", parent_task_id="200")
        b = _task("200", "Task B", parent_task_id="100")
        all_tasks = [a, b]

        chain, warning = walk_parent_chain(a, all_tasks)
        assert "Cycle" in warning
        # Chain should contain at most 2 items (stopped at cycle)
        assert len(chain) <= 2

    def test_target_not_in_all_tasks(self):
        """Target task doesn't need to be in all_tasks for walking to work."""
        target = _task("300", "Action", parent_task_id="200")
        parent = _task("200", "Project", parent_task_id="100")
        grandparent = _task("100", "Focus")
        # target not included in all_tasks but that's fine —
        # by_task_id only used for parent lookup
        all_tasks = [grandparent, parent, target]

        chain, warning = walk_parent_chain(target, all_tasks)
        assert len(chain) == 3
        assert warning is None


# ---------------------------------------------------------------------------
# resolve_task_url
# ---------------------------------------------------------------------------

class TestResolveTaskUrl:
    @pytest.mark.asyncio
    async def test_full_hierarchy(self):
        client = AsyncMock()

        # getList returns tasks with 3-level hierarchy
        focus = {
            "id": "100", "taskseries": [{
                "id": "ts_100", "name": "Finance", "parent_task_id": "",
                "tags": [], "notes": [], "url": "", "location_id": "",
                "created": "", "modified": "",
                "task": [{"id": "100", "due": "", "has_due_time": "0",
                          "start": "", "has_start_time": "0",
                          "completed": "", "deleted": "", "priority": "N",
                          "postponed": "0", "estimate": ""}],
            }],
        }
        project = {
            "id": "100", "taskseries": [{
                "id": "ts_200", "name": "LW Dormancy", "parent_task_id": "100",
                "tags": [], "notes": [], "url": "", "location_id": "",
                "created": "", "modified": "",
                "task": [{"id": "200", "due": "", "has_due_time": "0",
                          "start": "", "has_start_time": "0",
                          "completed": "", "deleted": "", "priority": "N",
                          "postponed": "0", "estimate": ""}],
            }],
        }
        action = {
            "id": "100", "taskseries": [{
                "id": "ts_300", "name": "Message Simon", "parent_task_id": "200",
                "tags": [], "notes": [], "url": "", "location_id": "",
                "created": "", "modified": "",
                "task": [{"id": "300", "due": "", "has_due_time": "0",
                          "start": "", "has_start_time": "0",
                          "completed": "", "deleted": "", "priority": "N",
                          "postponed": "0", "estimate": ""}],
            }],
        }

        # lists.getList returns list info
        lists_response = {"lists": {"list": [
            {"id": "100", "name": "Processed", "deleted": "0",
             "locked": "0", "archived": "0", "position": "0",
             "smart": "0"},
        ]}}

        async def mock_call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return {"tasks": {"list": [focus, project, action]}}
            if method == "rtm.lists.getList":
                return lists_response
            return {}

        client.call = AsyncMock(side_effect=mock_call)

        result = await resolve_task_url(client, "300", "ts_300", "100")

        assert "url" in result
        assert result["task_name"] == "Message Simon"
        assert result["list_name"] == "Processed"
        assert result["list_id"] == "100"
        assert len(result["hierarchy"]) == 3
        assert result["hierarchy"][0] == {"name": "Finance", "level": 1}
        assert result["hierarchy"][1] == {"name": "LW Dormancy", "level": 2}
        assert result["hierarchy"][2] == {"name": "Message Simon", "level": 3}
        # URL should contain list_id and 3 segments
        assert "#list/100/" in result["url"]
        assert "warning" not in result

    @pytest.mark.asyncio
    async def test_top_level_task(self):
        client = AsyncMock()

        task_list = {
            "id": "5", "taskseries": [{
                "id": "ts_10", "name": "Solo task", "parent_task_id": "",
                "tags": [], "notes": [], "url": "", "location_id": "",
                "created": "", "modified": "",
                "task": [{"id": "10", "due": "", "has_due_time": "0",
                          "start": "", "has_start_time": "0",
                          "completed": "", "deleted": "", "priority": "N",
                          "postponed": "0", "estimate": ""}],
            }],
        }
        lists_response = {"lists": {"list": [
            {"id": "5", "name": "Inbox", "deleted": "0",
             "locked": "1", "archived": "0", "position": "0",
             "smart": "0"},
        ]}}

        async def mock_call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return {"tasks": {"list": [task_list]}}
            if method == "rtm.lists.getList":
                return lists_response
            return {}

        client.call = AsyncMock(side_effect=mock_call)

        result = await resolve_task_url(client, "10", "ts_10", "5")

        assert result["url"] == "https://www.rememberthemilk.com/app/#list/5/10"
        assert result["task_name"] == "Solo task"
        assert result["list_name"] == "Inbox"
        assert len(result["hierarchy"]) == 1

    @pytest.mark.asyncio
    async def test_task_not_found(self):
        client = AsyncMock()

        async def mock_call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return {"tasks": {"list": []}}
            return {}

        client.call = AsyncMock(side_effect=mock_call)

        result = await resolve_task_url(client, "999", "ts_999", "1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_parent_includes_warning(self):
        client = AsyncMock()

        task_list = {
            "id": "1", "taskseries": [{
                "id": "ts_200", "name": "Orphan", "parent_task_id": "999",
                "tags": [], "notes": [], "url": "", "location_id": "",
                "created": "", "modified": "",
                "task": [{"id": "200", "due": "", "has_due_time": "0",
                          "start": "", "has_start_time": "0",
                          "completed": "", "deleted": "", "priority": "N",
                          "postponed": "0", "estimate": ""}],
            }],
        }
        lists_response = {"lists": {"list": [
            {"id": "1", "name": "Processed", "deleted": "0",
             "locked": "0", "archived": "0", "position": "0",
             "smart": "0"},
        ]}}

        async def mock_call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return {"tasks": {"list": [task_list]}}
            if method == "rtm.lists.getList":
                return lists_response
            return {}

        client.call = AsyncMock(side_effect=mock_call)

        result = await resolve_task_url(client, "200", "ts_200", "1")
        assert "url" in result
        assert "warning" in result
        assert "999" in result["warning"]
