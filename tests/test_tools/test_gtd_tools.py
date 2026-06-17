"""Tests for GTD domain tools (gtd_project_plan) via mocked RTM client."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

LIST_ID = "49657585"
PROJECT_ID = "1195689993"
AREA_ID = "957240854"


class FakeMCP:
    def __init__(self):
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class FakeContext:
    pass


def _ts(ts_id, task_id, name, parent="", priority="N", tags=None,
        completed="", due="", notes=None):
    return {
        "id": ts_id, "name": name, "created": "2026-01-01T00:00:00Z",
        "modified": "2026-01-01T00:00:00Z", "url": "", "location_id": "",
        "parent_task_id": parent,
        "tags": {"tag": tags} if tags else [],
        "notes": {"note": notes} if notes else [],
        "task": {
            "id": task_id, "due": due, "has_due_time": "0", "completed": completed,
            "deleted": "", "priority": priority, "postponed": "0", "estimate": "",
            "start": "", "has_start_time": "0",
        },
    }


def _getlist(taskseries_list, list_id=LIST_ID):
    return {"stat": "ok", "tasks": {"list": {"id": list_id, "taskseries": taskseries_list}}}


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.call = AsyncMock()
    client.record_transaction = MagicMock()
    type(client).timeline_id = PropertyMock(return_value="tl_test")
    client.config = MagicMock(strict_tags=False)
    return client


@pytest.fixture
def gtd_tools(mock_client):
    mcp = FakeMCP()
    from rtm_mcp.tools.gtd import register_gtd_tools

    async def get_client():
        return mock_client

    register_gtd_tools(mcp, get_client)
    return mcp.tools, mock_client


def _project_tree():
    return _getlist([
        _ts("tsP", PROJECT_ID, "Sam's university open days", parent=AREA_ID,
            tags=["personal", "project"], notes=[
                {"id": "n", "created": "2026-04-05T00:00:00Z", "title": "", "$t": "INCEPTION"}]),
        _ts("ts1", "c1", "Attend webinar", parent=PROJECT_ID, priority="1", due="2026-07-03",
            tags=["action"]),
        _ts("ts2", "c2", "Done thing", parent=PROJECT_ID, completed="2026-06-15T00:00:00Z",
            tags=["action"]),
    ])


class TestGtdProjectPlan:
    @pytest.mark.asyncio
    async def test_by_project_id(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        result = await tools["gtd_project_plan"](FakeContext(), project_id=PROJECT_ID)
        data = result["data"]
        assert data["header"]["schema"] == "project-plan-seed/3"
        assert data["header"]["projectId"] == PROJECT_ID
        assert data["header"]["rowCount"] == 2
        c1 = next(r for r in data["rows"] if r["id"] == "c1")
        assert c1["priority"] == "High"
        assert c1["permalink"].endswith(f"/{LIST_ID}/{AREA_ID}/{PROJECT_ID}/c1")

    @pytest.mark.asyncio
    async def test_read_only_call_surface(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        await tools["gtd_project_plan"](FakeContext(), project_id=PROJECT_ID)

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # exactly one read; no writes/timeline

    @pytest.mark.asyncio
    async def test_by_project_name(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        result = await tools["gtd_project_plan"](
            FakeContext(), project_name="university open days")
        assert result["data"]["header"]["projectId"] == PROJECT_ID

    @pytest.mark.asyncio
    async def test_name_disambiguation(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([
            _ts("tsA", "a1", "Alpha", parent=AREA_ID, tags=["project"]),
            _ts("tsB", "a2", "Alpha", parent=AREA_ID, tags=["project"]),
        ]))

        result = await tools["gtd_project_plan"](FakeContext(), project_name="Alpha")
        data = result["data"]
        assert "header" not in data
        assert {c["id"] for c in data["candidates"]} == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_project_id_not_found(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([
            _ts("tsX", "x1", "Something else", tags=["action"]),
        ]))

        result = await tools["gtd_project_plan"](FakeContext(), project_id="doesnotexist")
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_requires_exactly_one_identifier(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        neither = await tools["gtd_project_plan"](FakeContext())
        assert "error" in neither["data"]

        both = await tools["gtd_project_plan"](
            FakeContext(), project_id=PROJECT_ID, project_name="x")
        assert "error" in both["data"]

    @pytest.mark.asyncio
    async def test_include_completed_toggles_filter(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        await tools["gtd_project_plan"](
            FakeContext(), project_id=PROJECT_ID, include_completed=False)
        call = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.getList")
        assert call.kwargs["filter"] == "status:incomplete"
