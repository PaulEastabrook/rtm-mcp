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


# ── canvas tools ───────────────────────────────────────────────────────────

def _lists(processed_smart="0"):
    return {"lists": {"list": [
        {"id": LIST_ID, "name": "Processed", "smart": processed_smart,
         "deleted": "0", "locked": "0", "archived": "0", "position": "0",
         "filter": "", "sort_order": "0"},
    ]}}


def _commit_tree():
    return _getlist([
        _ts("tsP", PROJECT_ID, "Test Project", parent=AREA_ID, tags=["personal", "project"]),
        _ts("ts1", "c1", "Edit me", parent=PROJECT_ID, priority="N",
            tags=["action", "using_device"]),
        _ts("ts2", "c2", "Complete me", parent=PROJECT_ID, priority="N", tags=["action"]),
    ])


def _add_result():
    return {
        "transaction": {"id": "txadd", "undoable": "1"},
        "list": {"id": LIST_ID, "taskseries": [_ts("tsNew", "new1", "New action", parent="")]},
    }


def _commit_dispatch(tree, lists):
    """side_effect for client.call: route by RTM method to the right canned response."""
    async def _call(method, **kwargs):
        if method == "rtm.tasks.getList":
            return tree
        if method == "rtm.lists.getList":
            return lists
        if method == "rtm.tasks.add":
            return _add_result()
        return {"transaction": {"id": f"tx_{method.rsplit('.', 1)[-1]}", "undoable": "1"}}
    return _call


WRITE_METHODS = {
    "rtm.tasks.add", "rtm.tasks.setTags", "rtm.tasks.addTags", "rtm.tasks.setPriority",
    "rtm.tasks.setDueDate", "rtm.tasks.setName", "rtm.tasks.setParentTask",
    "rtm.tasks.complete", "rtm.tasks.delete", "rtm.tasks.notes.add",
}


class TestGtdProjectCanvas:
    @pytest.mark.asyncio
    async def test_returns_seed_shape(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        result = await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID)
        data = result["data"]
        assert data["mode"] == "existing"
        assert data["frame"]["name"] == "Sam's university open days"
        assert data["frame"]["life"] == "personal"
        ids = {it["id"] for it in data["seed"]}
        assert ids == {"c1", "c2"}

    @pytest.mark.asyncio
    async def test_read_only_call_surface(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID)

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # no writes, no timeline

    @pytest.mark.asyncio
    async def test_completed_history_placed_last(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        result = await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID)
        seed = result["data"]["seed"]
        c2 = next(it for it in seed if it["id"] == "c2")
        assert c2.get("hx") == 1
        assert seed[-1]["id"] == "c2"  # history after open items

    @pytest.mark.asyncio
    async def test_by_name(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        result = await tools["gtd_project_canvas"](
            FakeContext(), project_name="university open days")
        assert result["data"]["frame"]["name"] == "Sam's university open days"

    @pytest.mark.asyncio
    async def test_ambiguous_name_returns_candidates(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([
            _ts("tsA", "a1", "Alpha", parent=AREA_ID, tags=["project"]),
            _ts("tsB", "a2", "Alpha", parent=AREA_ID, tags=["project"]),
        ]))

        result = await tools["gtd_project_canvas"](FakeContext(), project_name="Alpha")
        assert {c["id"] for c in result["data"]["candidates"]} == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_not_found(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([
            _ts("tsX", "x1", "Something", tags=["action"]),
        ]))

        result = await tools["gtd_project_canvas"](FakeContext(), project_id="nope")
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_lean_caps_notes(self, gtd_tools):
        tools, client = gtd_tools
        many = [{"id": f"n{i}", "created": "2026-01-01T00:00:00Z", "title": "",
                 "$t": f"note {i}"} for i in range(5)]
        client.call = AsyncMock(return_value=_getlist([
            _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["personal", "project"]),
            _ts("ts1", "c1", "Busy", parent=PROJECT_ID, tags=["action"], notes=many),
        ]))

        result = await tools["gtd_project_canvas"](
            FakeContext(), project_id=PROJECT_ID, lean=True, note_cap=2)
        c1 = next(it for it in result["data"]["seed"] if it["id"] == "c1")
        assert len(c1["notes"]) == 2
        assert c1["nc"] == 5  # honest true total


class TestGtdApplyCanvasCommit:
    @pytest.mark.asyncio
    async def test_staged_commit_applies(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID,
            adds=[{"type": "action", "text": "New action",
                   "classifiers": {"context": "using_device", "priority": "2"}}],
            edits={"c1": {"priority": "1"}},
            completes=["c2"],
            execute={"c1": "later"},
            confirm_destructive=True,
        )
        data = result["data"]
        assert "rejected" not in data
        assert data["order_persisted"] is False
        assert len(data["applied"]) >= 5

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        for m in ("rtm.tasks.add", "rtm.tasks.setParentTask", "rtm.tasks.complete",
                  "rtm.tasks.addTags", "rtm.tasks.notes.add"):
            assert m in methods

        # execute writes the durable progression tag
        addtags = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert "ai_progress_requested" in addtags.kwargs["tags"]
        # a COMMIT audit note is written
        notes = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add"]
        assert any(c.kwargs.get("note_title") == "COMMIT" for c in notes)

    @pytest.mark.asyncio
    async def test_rejects_non_canonical_tag_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(return_value={"action"})  # missing using_device etc.
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID,
            adds=[{"type": "action", "text": "x", "classifiers": {"context": "using_device"}}],
        )
        reasons = {r["reason"] for r in result["data"]["rejected"]}
        assert "non_canonical_tag" in reasons
        assert result["data"]["applied"] == []
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_rejects_smart_list_target(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists("1")))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID,
            adds=[{"type": "action", "text": "x"}],
        )
        reasons = {r["reason"] for r in result["data"]["rejected"]}
        assert "smart_list_target" in reasons
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_rejects_cross_project_id(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID,
            edits={"intruder": {"priority": "1"}},
        )
        reasons = {r["reason"] for r in result["data"]["rejected"]}
        assert "cross_project" in reasons
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_rejects_destructive_without_confirm(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID,
            completes=["c2"], confirm_destructive=False,
        )
        reasons = {r["reason"] for r in result["data"]["rejected"]}
        assert "destructive_unconfirmed" in reasons
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)
