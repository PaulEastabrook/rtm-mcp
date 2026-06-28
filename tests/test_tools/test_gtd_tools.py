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


def _ts(ts_id, task_id, name, parent="", priority="N", tags=None, completed="", due="", notes=None):
    return {
        "id": ts_id,
        "name": name,
        "created": "2026-01-01T00:00:00Z",
        "modified": "2026-01-01T00:00:00Z",
        "url": "",
        "location_id": "",
        "parent_task_id": parent,
        "tags": {"tag": tags} if tags else [],
        "notes": {"note": notes} if notes else [],
        "task": {
            "id": task_id,
            "due": due,
            "has_due_time": "0",
            "completed": completed,
            "deleted": "",
            "priority": priority,
            "postponed": "0",
            "estimate": "",
            "start": "",
            "has_start_time": "0",
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
    client.config = MagicMock(strict_tags=False, vault_root=None)
    # Realistic account tz (cached settings read in the real client; here a plain stub so the
    # envelope's date localisation runs — get_timezone never routes through client.call).
    client.get_timezone = AsyncMock(return_value="Europe/London")
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
    return _getlist(
        [
            _ts(
                "tsP",
                PROJECT_ID,
                "Sam's university open days",
                parent=AREA_ID,
                tags=["personal", "project"],
                notes=[
                    {"id": "n", "created": "2026-04-05T00:00:00Z", "title": "", "$t": "INCEPTION"}
                ],
            ),
            _ts(
                "ts1",
                "c1",
                "Attend webinar",
                parent=PROJECT_ID,
                priority="1",
                due="2026-07-03",
                tags=["action"],
            ),
            _ts(
                "ts2",
                "c2",
                "Done thing",
                parent=PROJECT_ID,
                completed="2026-06-15T00:00:00Z",
                tags=["action"],
            ),
        ]
    )


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

        result = await tools["gtd_project_plan"](FakeContext(), project_name="university open days")
        assert result["data"]["header"]["projectId"] == PROJECT_ID

    @pytest.mark.asyncio
    async def test_name_disambiguation(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsA", "a1", "Alpha", parent=AREA_ID, tags=["project"]),
                    _ts("tsB", "a2", "Alpha", parent=AREA_ID, tags=["project"]),
                ]
            )
        )

        result = await tools["gtd_project_plan"](FakeContext(), project_name="Alpha")
        data = result["data"]
        assert "header" not in data
        assert {c["id"] for c in data["candidates"]} == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_project_id_not_found(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsX", "x1", "Something else", tags=["action"]),
                ]
            )
        )

        result = await tools["gtd_project_plan"](FakeContext(), project_id="doesnotexist")
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_requires_exactly_one_identifier(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        neither = await tools["gtd_project_plan"](FakeContext())
        assert "error" in neither["data"]

        both = await tools["gtd_project_plan"](
            FakeContext(), project_id=PROJECT_ID, project_name="x"
        )
        assert "error" in both["data"]

    @pytest.mark.asyncio
    async def test_include_completed_toggles_filter(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_project_tree())

        await tools["gtd_project_plan"](
            FakeContext(), project_id=PROJECT_ID, include_completed=False
        )
        call = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.getList")
        assert call.kwargs["filter"] == "status:incomplete"


# ── canvas tools ───────────────────────────────────────────────────────────


def _lists(processed_smart="0"):
    return {
        "lists": {
            "list": [
                {
                    "id": LIST_ID,
                    "name": "Processed",
                    "smart": processed_smart,
                    "deleted": "0",
                    "locked": "0",
                    "archived": "0",
                    "position": "0",
                    "filter": "",
                    "sort_order": "0",
                },
            ]
        }
    }


def _commit_tree():
    return _getlist(
        [
            _ts("tsP", PROJECT_ID, "Test Project", parent=AREA_ID, tags=["personal", "project"]),
            _ts(
                "ts1",
                "c1",
                "Edit me",
                parent=PROJECT_ID,
                priority="N",
                tags=["action", "using_device"],
            ),
            _ts("ts2", "c2", "Complete me", parent=PROJECT_ID, priority="N", tags=["action"]),
        ]
    )


def _commit_tree_c1_tags(c1_tags):
    """A commit tree where c1 carries the given tags (e.g. a stale progression sibling)."""
    return _getlist(
        [
            _ts("tsP", PROJECT_ID, "Test Project", parent=AREA_ID, tags=["personal", "project"]),
            _ts("ts1", "c1", "Edit me", parent=PROJECT_ID, priority="N", tags=c1_tags),
            _ts("ts2", "c2", "Complete me", parent=PROJECT_ID, priority="N", tags=["action"]),
        ]
    )


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
    "rtm.tasks.add",
    "rtm.tasks.setTags",
    "rtm.tasks.addTags",
    "rtm.tasks.removeTags",
    "rtm.tasks.setPriority",
    "rtm.tasks.setDueDate",
    "rtm.tasks.setName",
    "rtm.tasks.setParentTask",
    "rtm.tasks.complete",
    "rtm.tasks.delete",
    "rtm.tasks.notes.add",
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
            FakeContext(), project_name="university open days"
        )
        assert result["data"]["frame"]["name"] == "Sam's university open days"

    @pytest.mark.asyncio
    async def test_ambiguous_name_returns_candidates(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsA", "a1", "Alpha", parent=AREA_ID, tags=["project"]),
                    _ts("tsB", "a2", "Alpha", parent=AREA_ID, tags=["project"]),
                ]
            )
        )

        result = await tools["gtd_project_canvas"](FakeContext(), project_name="Alpha")
        assert {c["id"] for c in result["data"]["candidates"]} == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_not_found(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsX", "x1", "Something", tags=["action"]),
                ]
            )
        )

        result = await tools["gtd_project_canvas"](FakeContext(), project_id="nope")
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_lean_caps_notes(self, gtd_tools):
        tools, client = gtd_tools
        many = [
            {"id": f"n{i}", "created": "2026-01-01T00:00:00Z", "title": "", "$t": f"note {i}"}
            for i in range(5)
        ]
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["personal", "project"]),
                    _ts("ts1", "c1", "Busy", parent=PROJECT_ID, tags=["action"], notes=many),
                ]
            )
        )

        result = await tools["gtd_project_canvas"](
            FakeContext(), project_id=PROJECT_ID, lean=True, note_cap=2
        )
        c1 = next(it for it in result["data"]["seed"] if it["id"] == "c1")
        assert len(c1["notes"]) == 2
        assert c1["nc"] == 5  # honest true total

    @pytest.mark.asyncio
    async def test_seed_emits_prog_from_progression_tags(self, gtd_tools):
        """The execute tri-state round-trips: seed rows carry `prog` derived from the durable tags
        (now/later), or omit it when neither is present, so the pill reflects committed state."""
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["personal", "project"]),
                    _ts(
                        "ts1",
                        "c1",
                        "Now item",
                        parent=PROJECT_ID,
                        tags=["action", "ai_progress_requested"],
                    ),
                    _ts(
                        "ts2",
                        "c2",
                        "Later item",
                        parent=PROJECT_ID,
                        tags=["action", "ai_progress_deferred"],
                    ),
                    _ts("ts3", "c3", "Plain item", parent=PROJECT_ID, tags=["action"]),
                ]
            )
        )

        data = (await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID))["data"]
        by_id = {it["id"]: it for it in data["seed"]}
        assert by_id["c1"]["prog"] == "now"
        assert by_id["c2"]["prog"] == "later"
        assert "prog" not in by_id["c3"]

    @pytest.mark.asyncio
    async def test_bst_due_renders_local_day(self, gtd_tools):
        """Regression: a BST date-only due arrives from RTM as the prior day's 23:00 UTC
        (2026-06-22 local → 2026-06-21T23:00:00Z). The seed must localise to the account tz and
        show 2026-06-22, not the UTC-truncated 2026-06-21."""
        tools, client = gtd_tools
        client.get_timezone = AsyncMock(return_value="Europe/London")
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["personal", "project"]),
                    _ts(
                        "ts1",
                        "c1",
                        "Waiting for New Again",
                        parent=PROJECT_ID,
                        tags=["waiting_for"],
                        due="2026-06-21T23:00:00Z",
                    ),
                ]
            )
        )

        data = (await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID))["data"]
        c1 = next(it for it in data["seed"] if it["id"] == "c1")
        assert c1["d"] == "2026-06-22"  # account-local day, not the UTC-truncated 2026-06-21

    @pytest.mark.asyncio
    async def test_dates_fall_back_when_timezone_unavailable(self, gtd_tools):
        """If the tz settings read fails (get_timezone → None), date localisation is skipped
        (raw-UTC truncation) rather than raising — the read still succeeds."""
        tools, client = gtd_tools
        client.get_timezone = AsyncMock(return_value=None)
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["personal", "project"]),
                    _ts(
                        "ts1",
                        "c1",
                        "Waiting for New Again",
                        parent=PROJECT_ID,
                        tags=["waiting_for"],
                        due="2026-06-21T23:00:00Z",
                    ),
                ]
            )
        )

        data = (await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID))["data"]
        c1 = next(it for it in data["seed"] if it["id"] == "c1")
        assert c1["d"] == "2026-06-21"  # documented fallback: no tz → raw UTC truncation


def _meta_tree():
    """Project + one open action, each note pointing at a filed artefact (reference / output)."""
    return _getlist(
        [
            _ts(
                "tsP",
                PROJECT_ID,
                "Sam's placement",
                parent=AREA_ID,
                tags=["personal", "project"],
                notes=[
                    {
                        "id": "np",
                        "created": "2026-05-01T00:00:00Z",
                        "title": "",
                        "$t": "REFERENCE: personal/sam/reference/cert.pdf",
                    }
                ],
            ),
            _ts(
                "ts1",
                "c1",
                "Draft decision",
                parent=PROJECT_ID,
                tags=["action"],
                notes=[
                    {
                        "id": "n1",
                        "created": "2026-05-04T00:00:00Z",
                        "title": "",
                        "$t": "OUTPUT: personal/sam/output/decision-x.md",
                    }
                ],
            ),
        ]
    )


def _build_vault(root):
    """Materialise a tmp AI Memory vault with the marker + two filed artefacts + companions."""
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "_index.md").write_text("# index\n")
    out = root / "personal" / "sam" / "output"
    ref = root / "personal" / "sam" / "reference"
    out.mkdir(parents=True)
    ref.mkdir(parents=True)
    (out / "decision-x.md").write_text("# decision\n")
    (out / "decision-x.meta.md").write_text(
        "---\n"
        'schema_version: "1.0.0"\n'
        'title: "Decision X"\n'
        "type: decision-record\n"
        "status: review-needed\n"
        "date_created: 2026-05-04\n"
        "authors:\n"
        '  - "Paul Eastabrook (directing)"\n'
        "  - Claude\n"
        "tags:\n"
        "  - sam\n"
        "  - placement\n"
        "---\nbody\n"
    )
    (ref / "cert.pdf").write_text("%PDF stub\n")
    (ref / "cert.meta.md").write_text(
        '---\ntitle: "TT Employers Liability Certificate"\ntype: reference\nstatus: final\n---\nbody\n'
    )
    return str(root)


class TestGtdProjectCanvasCompanionMeta:
    @pytest.mark.asyncio
    async def test_row_and_frame_files_gain_meta(self, gtd_tools, tmp_path):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=False, vault_root=_build_vault(tmp_path))
        client.call = AsyncMock(return_value=_meta_tree())

        data = (await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID))["data"]

        c1 = next(it for it in data["seed"] if it["id"] == "c1")
        f = c1["files"][0]
        assert f["meta"]["type"] == "decision-record"
        assert f["meta"]["status"] == "review-needed"
        assert f["meta"]["title"] == "Decision X"
        assert f["meta"]["authors"] == ["Paul Eastabrook (directing)", "Claude"]
        assert f["meta"]["tags"] == ["sam", "placement"]
        # n/ext/kind/path unchanged — backward-compatible
        assert (f["n"], f["ext"], f["kind"]) == ("decision-x.md", "md", "output")

        frame_file = data["frame"]["files"][0]
        assert frame_file["kind"] == "reference"
        assert frame_file["meta"]["type"] == "reference"
        assert frame_file["meta"]["title"] == "TT Employers Liability Certificate"

    @pytest.mark.asyncio
    async def test_read_only_with_vault(self, gtd_tools, tmp_path):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=False, vault_root=_build_vault(tmp_path))
        client.call = AsyncMock(return_value=_meta_tree())

        await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID)

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # vault reads are FS-only; no extra API calls

    @pytest.mark.asyncio
    async def test_no_meta_when_vault_absent(self, gtd_tools, tmp_path):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=False, vault_root=str(tmp_path / "nope"))
        client.call = AsyncMock(return_value=_meta_tree())

        data = (await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID))["data"]
        c1 = next(it for it in data["seed"] if it["id"] == "c1")
        assert c1["files"] and "meta" not in c1["files"][0]  # file objects present, no meta
        assert "meta" not in data["frame"]["files"][0]


class TestGtdApplyCanvasCommit:
    @pytest.mark.asyncio
    async def test_staged_commit_applies(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            adds=[
                {
                    "type": "action",
                    "text": "New action",
                    "classifiers": {"context": "using_device", "priority": "2"},
                }
            ],
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
        for m in (
            "rtm.tasks.add",
            "rtm.tasks.setParentTask",
            "rtm.tasks.complete",
            "rtm.tasks.addTags",
            "rtm.tasks.notes.add",
        ):
            assert m in methods

        # execute "later" writes the durable DEFERRED progression tag, not the immediate one
        addtags = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert "ai_progress_deferred" in addtags.kwargs["tags"]
        assert "ai_progress_requested" not in addtags.kwargs["tags"]
        # a COMMIT audit note is written
        notes = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add"]
        assert any(c.kwargs.get("note_title") == "COMMIT" for c in notes)

    @pytest.mark.asyncio
    async def test_accepts_json_string_ops(self, gtd_tools):
        """Defensive path: complex ops arriving as JSON strings (the Cowork serialisation) are
        coerced and applied — a populated add creates the child carrying #ai_conversation, and a
        stringified destructive op applies under confirm_destructive."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            adds='[{"type": "action", "text": "New action", '
            '"classifiers": {"context": "using_device"}}]',
            completes='["c2"]',
            confirm_destructive=True,
        )
        data = result["data"]
        assert "rejected" not in data
        assert any(op["op"].startswith("add:") for op in data["applied"])

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert "rtm.tasks.add" in methods  # adds string coerced and created
        assert "rtm.tasks.complete" in methods  # completes string coerced and applied
        # created item carries the journaling tag
        settags = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.setTags")
        assert "ai_conversation" in settags.kwargs["tags"]

    @pytest.mark.asyncio
    async def test_rejects_non_canonical_tag_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(return_value={"action"})  # missing using_device etc.
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
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
            FakeContext(),
            project_id=PROJECT_ID,
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
            FakeContext(),
            project_id=PROJECT_ID,
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
            FakeContext(),
            project_id=PROJECT_ID,
            completes=["c2"],
            confirm_destructive=False,
        )
        reasons = {r["reason"] for r in result["data"]["rejected"]}
        assert "destructive_unconfirmed" in reasons
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_execute_now_writes_requested_no_stale_drop(self, gtd_tools):
        """now/quick write #ai_progress_requested; with no stale sibling present, no removeTags."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "now"}
        )
        addtags = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert "ai_progress_requested" in addtags.kwargs["tags"]
        assert "ai_progress_deferred" not in addtags.kwargs["tags"]
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert "rtm.tasks.removeTags" not in methods  # nothing stale to drop

    @pytest.mark.asyncio
    async def test_execute_later_to_now_drops_stale_deferred(self, gtd_tools):
        """An item previously deferred, now set to now: writes requested and drops the stale
        deferred sibling so it never carries both."""
        tools, client = gtd_tools
        tree = _commit_tree_c1_tags(["action", "ai_progress_deferred"])
        client.call = AsyncMock(side_effect=_commit_dispatch(tree, _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "now"}
        )
        addtags = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert "ai_progress_requested" in addtags.kwargs["tags"]
        removetags = next(
            c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.removeTags"
        )
        assert removetags.kwargs["tags"] == "ai_progress_deferred"

    @pytest.mark.asyncio
    async def test_execute_now_to_later_drops_stale_requested(self, gtd_tools):
        """An item previously requested, now deferred: writes deferred and drops the stale
        requested sibling."""
        tools, client = gtd_tools
        tree = _commit_tree_c1_tags(["action", "ai_progress_requested"])
        client.call = AsyncMock(side_effect=_commit_dispatch(tree, _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "later"}
        )
        addtags = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert "ai_progress_deferred" in addtags.kwargs["tags"]
        removetags = next(
            c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.removeTags"
        )
        assert removetags.kwargs["tags"] == "ai_progress_requested"

    @pytest.mark.asyncio
    async def test_later_rejected_when_deferred_tag_missing(self, gtd_tools):
        """Dependency: until #ai_progress_deferred is provisioned in RTM, a `later` commit fails
        the strict-tag existence gate with a clear, recoverable error — no silent drop, no write."""
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(
            return_value={"ai_progress_requested", "ai_deferred_pending_unblock", "ai_conversation"}
        )
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "later"}
        )
        rejected = result["data"]["rejected"]
        assert {r["reason"] for r in rejected} == {"non_canonical_tag"}
        assert any("ai_progress_deferred" in r.get("rejected_tags", []) for r in rejected)
        assert result["data"]["applied"] == []
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_now_allowed_when_deferred_tag_missing(self, gtd_tools):
        """Backward-compat: a now/quick-only commit does NOT require the new deferred tag to exist,
        so it still applies even before #ai_progress_deferred is provisioned."""
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(
            return_value={
                "ai_progress_requested",
                "ai_deferred_pending_unblock",
                "ai_conversation",
                "ai_overlay_refresh_needed",  # provisioned (Piece 0b); ai_progress_deferred absent
            }  # note: ai_progress_deferred deliberately absent
        )
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "now"}
        )
        assert "rejected" not in result["data"]
        addtags = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert "ai_progress_requested" in addtags.kwargs["tags"]

    @pytest.mark.asyncio
    async def test_successful_commit_stamps_overlay_refresh_mark(self, gtd_tools):
        """Piece 0b: any successful commit stamps #ai_overlay_refresh_needed on the project (so the
        gtd-side finalise engine refreshes the persisted overlay even for a non-execute commit)."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, edits={"c1": {"priority": "1"}}
        )
        stamp = [
            c
            for c in client.call.call_args_list
            if c.args[0] == "rtm.tasks.addTags"
            and c.kwargs.get("tags") == "ai_overlay_refresh_needed"
        ]
        assert len(stamp) == 1
        assert stamp[0].kwargs["task_id"] == PROJECT_ID  # stamped on the project, not an item

    @pytest.mark.asyncio
    async def test_zero_apply_commit_does_not_stamp_overlay_refresh(self, gtd_tools):
        """A commit that applied nothing made no plan change → no overlay-refresh stamp."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](FakeContext(), project_id=PROJECT_ID)
        assert result["data"]["applied"] == []
        stamped = any(
            c.args[0] == "rtm.tasks.addTags" and c.kwargs.get("tags") == "ai_overlay_refresh_needed"
            for c in client.call.call_args_list
        )
        assert not stamped


# ── gtd_create_project ───────────────────────────────────────────────────────


def _create_account():
    """Account read for create: an Area of Focus (AREA_ID, 'Personal') that already has a project
    under it, so resolve_focus can find the area by name."""
    return _getlist(
        [
            _ts("tsArea", AREA_ID, "Personal", parent=""),
            _ts(
                "tsExisting",
                "p_existing",
                "Existing project",
                parent=AREA_ID,
                tags=["personal", "project"],
            ),
        ]
    )


def _create_dispatch(account):
    """side_effect for client.call: the account read, then DISTINCT ids per rtm.tasks.add (new1,
    new2, ...) so the in-draft→new-id mapping and DEPENDS-ON notes can be verified; a generic
    transaction for every other write."""
    counter = {"n": 0}

    async def _call(method, **kwargs):
        if method == "rtm.tasks.getList":
            return account
        if method == "rtm.tasks.add":
            counter["n"] += 1
            i = counter["n"]
            return {
                "transaction": {"id": f"txadd{i}", "undoable": "1"},
                "list": {
                    "id": LIST_ID,
                    "taskseries": [
                        _ts(
                            f"tsNew{i}",
                            f"new{i}",
                            kwargs.get("name", ""),
                            parent=kwargs.get("parent_task_id", ""),
                        )
                    ],
                },
            }
        return {"transaction": {"id": f"tx_{method.rsplit('.', 1)[-1]}", "undoable": "1"}}

    return _call


class TestGtdCreateProject:
    @pytest.mark.asyncio
    async def test_creates_project_and_children_in_dep_order(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={
                "life": "personal",
                "focus": "Personal",
                "name": "New Project",
                "outcome": "Win",
            },
            items=[
                {"id": "c", "type": "action", "text": "Consumer", "deps": ["p"]},
                {"id": "p", "type": "action", "text": "Producer"},
            ],
        )
        data = result["data"]
        assert "rejected" not in data
        # project = first add (new1); children created producer-first (new2=p, new3=c)
        assert data["project_id"] == "new1"
        assert data["created"] == ["new2", "new3"]
        assert data["url"].endswith(f"/{LIST_ID}/{AREA_ID}/new1")

        adds = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.add"]
        assert adds[0].kwargs["parent_task_id"] == AREA_ID  # project under the area
        assert all(a.kwargs["parent_task_id"] == "new1" for a in adds[1:])  # children under project
        assert [a.kwargs["name"] for a in adds[1:]] == ["Producer", "Consumer"]  # dep order

        proj_tags = next(
            c
            for c in client.call.call_args_list
            if c.args[0] == "rtm.tasks.setTags" and c.kwargs.get("task_id") == "new1"
        )
        assert {"project", "personal", "ai_project_needs_finalise"} <= set(
            proj_tags.kwargs["tags"].split(",")
        )

        dep_note = next(
            c
            for c in client.call.call_args_list
            if c.args[0] == "rtm.tasks.notes.add" and c.kwargs.get("note_title") == "DEPENDS-ON"
        )
        assert dep_note.kwargs["task_id"] == "new3"  # attached to the consumer
        assert 'task_id: "new2"' in dep_note.kwargs["note_text"]  # producer's NEW id

        inception = next(
            c
            for c in client.call.call_args_list
            if c.args[0] == "rtm.tasks.notes.add" and c.kwargs.get("note_title") == "INCEPTION"
        )
        assert inception.kwargs["task_id"] == "new1"
        assert "Win" in inception.kwargs["note_text"]

        assert client.record_transaction.called  # undoable via batch_undo

    @pytest.mark.asyncio
    async def test_done_item_created_then_completed(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "work", "focus": "Personal", "name": "P"},
            items=[{"id": "d", "type": "action", "text": "Already done", "done": True}],
        )
        data = result["data"]
        assert "rejected" not in data
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert "rtm.tasks.complete" in methods
        assert data["completed"] == ["new2"]  # project=new1, the done child=new2

    @pytest.mark.asyncio
    async def test_execute_now_and_blocked_deferred(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Personal", "name": "P"},
            items=[
                {"id": "p", "type": "action", "text": "Producer", "execute": "later"},
                {"id": "c", "type": "action", "text": "Consumer", "deps": ["p"], "execute": "now"},
            ],
        )
        data = result["data"]
        assert "rejected" not in data
        addtags = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags"]
        by_task = {c.kwargs["task_id"]: c.kwargs["tags"] for c in addtags}
        assert "ai_progress_deferred" in by_task["new2"]  # producer 'later'
        assert "ai_progress_requested" in by_task["new3"]  # consumer 'now'
        assert "ai_deferred_pending_unblock" in by_task["new3"]  # but blocked by the open producer
        assert data["progressed"] == {"p": "later", "c": "now"}

    @pytest.mark.asyncio
    async def test_accepts_json_string_params(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame='{"life": "personal", "focus": "Personal", "name": "P"}',
            items='[{"id": "a", "type": "action", "text": "A"}]',
        )
        data = result["data"]
        assert "rejected" not in data
        assert data["created"] == ["new2"]

    @pytest.mark.asyncio
    async def test_ambiguous_focus_returns_candidates_no_writes(self, gtd_tools):
        tools, client = gtd_tools
        account = _getlist(
            [
                _ts("tsA1", "fa1", "Family", parent=""),
                _ts("tsA2", "fa2", "Family", parent=""),
                _ts("tsPa", "pa", "P A", parent="fa1", tags=["project"]),
                _ts("tsPb", "pb", "P B", parent="fa2", tags=["project"]),
            ]
        )
        client.call = AsyncMock(side_effect=_create_dispatch(account))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Family", "name": "P"},
            items=[{"type": "action", "text": "A"}],
        )
        assert {c["id"] for c in result["data"]["candidates"]} == {"fa1", "fa2"}
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_focus_miss_errors_no_writes(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Nonexistent Area", "name": "P"},
            items=[{"type": "action", "text": "A"}],
        )
        assert "error" in result["data"]
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_missing_name_rejected_no_writes(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Personal"},  # no name
            items=[{"type": "action", "text": "A"}],
        )
        data = result["data"]
        assert data["created"] == []
        assert "missing_name" in {r.get("reason") for r in data["rejected"]}
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_rejects_when_finalise_mark_absent_no_writes(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(
            return_value={"personal", "project", "ai_conversation", "action"}
        )  # missing ai_project_needs_finalise
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Personal", "name": "P"},
            items=[{"type": "action", "text": "A"}],
        )
        data = result["data"]
        assert data["created"] == []
        assert "non_canonical_tag" in {r.get("reason") for r in data["rejected"]}
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_now_only_create_backward_compat(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(
            return_value={
                "personal",
                "project",
                "ai_conversation",
                "ai_project_needs_finalise",
                "action",
                "ai_progress_requested",
                "ai_deferred_pending_unblock",
            }  # ai_progress_deferred deliberately absent
        )
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Personal", "name": "P"},
            items=[{"id": "a", "type": "action", "text": "A", "execute": "now"}],
        )
        assert "rejected" not in result["data"]

    @pytest.mark.asyncio
    async def test_reads_account_once_before_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Personal", "name": "P"},
            items=[{"type": "action", "text": "A"}],
        )
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods[0] == "rtm.tasks.getList"
        assert methods.count("rtm.tasks.getList") == 1


def _index_account():
    """A portfolio: AREA_ID area (a #focus) → one active project (two children, one blocked) + a
    someday project under the same area; plus an empty #focus area with no active projects."""
    return _getlist(
        [
            _ts("tsArea", AREA_ID, "Sam — University", tags=["personal", "focus"]),
            _ts("tsEmpty", "areaEmpty", "Line management", tags=["work", "focus"]),
            _ts("tsP", PROJECT_ID, "Open days", parent=AREA_ID, tags=["personal", "project"]),
            _ts(
                "ts1",
                "101",
                "Attend webinar",
                parent=PROJECT_ID,
                due="2026-07-03",
                tags=["action", "quick_win"],  # unblocked quick win → ai_quick
            ),
            _ts(
                "ts2",
                "102",
                "Book travel",
                parent=PROJECT_ID,
                due="2026-06-10",
                tags=["action"],
                notes=[
                    {
                        "id": "n",
                        "created": "2026-06-01T00:00:00Z",
                        "title": "",
                        "$t": 'DEPENDS-ON\n  task_id: "101"\nStatus: active\n',
                    }
                ],
            ),
            _ts(
                "tsSD",
                "sd1",
                "Someday idea",
                parent=AREA_ID,
                tags=["personal", "project", "someday"],
            ),
        ]
    )


class TestGtdProjectIndex:
    @pytest.mark.asyncio
    async def test_returns_projects_foci_actions_object(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_index_account())

        result = await tools["gtd_project_index"](FakeContext())
        data = result["data"]
        assert set(data) == {"projects", "foci", "actions"}
        assert isinstance(data["projects"], list)
        assert isinstance(data["foci"], list)
        assert isinstance(data["actions"], list)

    @pytest.mark.asyncio
    async def test_project_row_field_set(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_index_account())

        data = (await tools["gtd_project_index"](FakeContext()))["data"]
        row = next(r for r in data["projects"] if r["project_id"] == PROJECT_ID)
        assert set(row) == {
            "life",
            "focus",
            "focus_id",
            "project",
            "project_id",
            "priority",
            "open_count",
            "blocked_count",
            "next_tickle",
            "updated",
            "ai_quick",
            "ai_now",
            "ai_later",
        }
        assert row["life"] == "personal"
        assert row["focus"] == "Sam — University"
        assert row["focus_id"] == AREA_ID
        assert row["open_count"] == 2
        assert row["blocked_count"] == 1
        assert row[
            "next_tickle"
        ]  # earliest open due (deterministic; exact value covered in pure test)
        # AI-progressible tallies: 101 is an unblocked #quick_win action; nothing now/later.
        assert row["ai_quick"] == 1
        assert row["ai_now"] == 0
        assert row["ai_later"] == 0

    @pytest.mark.asyncio
    async def test_foci_includes_empty_focus_area(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_index_account())

        data = (await tools["gtd_project_index"](FakeContext()))["data"]
        foci = {f["focus_id"]: f for f in data["foci"]}
        # both #focus areas appear, including the one with no active projects
        assert set(foci) == {AREA_ID, "areaEmpty"}
        assert foci[AREA_ID] == {
            "focus_id": AREA_ID,
            "focus": "Sam — University",
            "life": "personal",
        }
        assert foci["areaEmpty"]["life"] == "work"

    @pytest.mark.asyncio
    async def test_actions_under_active_project(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_index_account())

        data = (await tools["gtd_project_index"](FakeContext()))["data"]
        actions = data["actions"]
        assert {a["action_id"] for a in actions} == {"101", "102"}
        a = next(a for a in actions if a["action_id"] == "101")
        assert set(a) == {
            "action_id",
            "name",
            "project_id",
            "project",
            "focus",
            "life",
            "type",
            "due",
            "priority",
            "blocked",
        }
        assert a["project_id"] == PROJECT_ID
        assert a["project"] == "Open days"
        assert a["focus"] == "Sam — University"
        assert a["life"] == "personal"
        # type + urgency signal: 101 is an #action, has a due, no priority, and is the upstream
        # (not blocked); 102 is blocked by 101.
        assert a["type"] == "action"
        assert a["due"] == "2026-07-03"
        assert a["priority"] == ""
        assert a["blocked"] is False
        assert next(x for x in actions if x["action_id"] == "102")["blocked"] is True

    @pytest.mark.asyncio
    async def test_read_only_call_surface(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_index_account())

        await tools["gtd_project_index"](FakeContext())

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # exactly one read; no writes/timeline
        client.record_transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_include_someday_passthrough(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_index_account())

        default = await tools["gtd_project_index"](FakeContext())
        assert {r["project_id"] for r in default["data"]["projects"]} == {PROJECT_ID}

        with_someday = await tools["gtd_project_index"](FakeContext(), include_someday=True)
        assert {r["project_id"] for r in with_someday["data"]["projects"]} == {PROJECT_ID, "sd1"}
