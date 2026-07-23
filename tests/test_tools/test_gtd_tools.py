"""Tests for GTD domain tools (gtd_project_plan) via mocked RTM client."""

import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

LIST_ID = "49657585"
PROJECT_ID = "1195689993"
AREA_ID = "957240854"


class FakeMCP:
    def __init__(self):
        self.tools: dict[str, Any] = {}

    def tool(self, *_args, **_kwargs):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class FakeContext:
    pass


def _ts(
    ts_id,
    task_id,
    name,
    parent="",
    priority="N",
    tags=None,
    completed="",
    due="",
    notes=None,
    rrule="",
):
    ts = {
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
    if rrule:
        ts["rrule"] = {"$t": rrule, "every": "1"}
    return ts


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
    # Cached system-list set (Phase 2 create-path optimisation) — the governed writes resolve
    # Processed / Inbox_Stuff through this instead of a per-write rtm.lists.getList.
    _lf = {
        "deleted": False,
        "locked": False,
        "archived": False,
        "position": 0,
        "filter": "",
        "sort_order": 0,
    }
    client.get_lists_cached = AsyncMock(
        return_value=[
            {"id": LIST_ID, "name": "Processed", "smart": False, **_lf},
            {"id": "51526642", "name": "Inbox_Stuff", "smart": False, **_lf},
        ]
    )
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
        assert data["header"]["schema"] == "project-plan-seed/3.1"
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
    async def test_seed_item_and_frame_redacted(self, gtd_tools):
        """The #redacted curtain surfaces on each seed item AND on the frame (the project's own
        tag), so the board can lock a redacted item and render a redacted project's locked screen."""
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts(
                        "tsP",
                        PROJECT_ID,
                        "Proj",
                        parent=AREA_ID,
                        tags=["personal", "project", "redacted"],
                    ),
                    _ts("ts1", "c1", "Secret item", parent=PROJECT_ID, tags=["action", "redacted"]),
                    _ts("ts2", "c2", "Open item", parent=PROJECT_ID, tags=["action"]),
                ]
            )
        )

        data = (await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID))["data"]
        assert data["frame"]["redacted"] is True  # project itself is redacted
        by_id = {it["id"]: it for it in data["seed"]}
        assert by_id["c1"]["redacted"] is True
        assert by_id["c2"]["redacted"] is False  # always present, not just when true

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
        assert "strict_tag_rejected" in reasons
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
    async def test_execute_off_clears_progression_directive(self, gtd_tools):
        """ "off" removes the progression-directive tags present on the item (the inverse of the
        set-paths) via a single removeTags, and writes no addTags."""
        tools, client = gtd_tools
        tree = _commit_tree_c1_tags(
            ["action", "ai_progress_requested", "ai_deferred_pending_unblock"]
        )
        client.call = AsyncMock(side_effect=_commit_dispatch(tree, _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "off"}
        )
        removetags = next(
            c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.removeTags"
        )
        cleared = set(removetags.kwargs["tags"].split(","))
        assert cleared == {"ai_progress_requested", "ai_deferred_pending_unblock"}
        # off never ADDS a progression tag (the only addTags is the project overlay-refresh mark)
        addtags = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags"]
        assert all("ai_progress" not in c.kwargs["tags"] for c in addtags)

    @pytest.mark.asyncio
    async def test_execute_off_idempotent_no_directive(self, gtd_tools):
        """ "off" on an item carrying no progression directive is a clean no-op — no removeTags."""
        tools, client = gtd_tools
        # c1 carries only its workflow tag — no progression directive present
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "off"}
        )
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert "rtm.tasks.removeTags" not in methods
        assert "rtm.tasks.addTags" not in methods

    @pytest.mark.asyncio
    async def test_execute_now_then_off_leaves_no_directive(self, gtd_tools):
        """Inverse round-trip: set now, then off → the item carries no progression directive."""
        tools, client = gtd_tools
        # after a `now` commit the item carries #ai_progress_requested; a follow-up `off` clears it
        tree = _commit_tree_c1_tags(["action", "ai_progress_requested"])
        client.call = AsyncMock(side_effect=_commit_dispatch(tree, _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "off"}
        )
        removetags = next(
            c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.removeTags"
        )
        assert removetags.kwargs["tags"] == "ai_progress_requested"
        # the only addTags is the project overlay-refresh mark, never a progression tag
        addtags = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags"]
        assert all("ai_progress" not in c.kwargs["tags"] for c in addtags)

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
        assert {r["reason"] for r in rejected} == {"strict_tag_rejected"}
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


class TestGtdCommitScope:
    """Commit `scope` (audit-note placement axis) + the project-entity verb carve-out."""

    def _commit_notes(self, client):
        return [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add"]

    @pytest.mark.asyncio
    async def test_default_scope_is_plan_commit_note_on_project(self, gtd_tools):
        """No scope → the pre-scope behaviour: a bare-titled COMMIT note on the project."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, edits={"c1": {"priority": "1"}}
        )
        note = next(c for c in self._commit_notes(client) if c.kwargs.get("note_title") == "COMMIT")
        assert note.kwargs["task_id"] == PROJECT_ID

    @pytest.mark.asyncio
    async def test_unknown_scope_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, edits={"c1": {"priority": "1"}}, scope="bogus"
        )
        assert result["data"]["applied"] == []
        assert {r["reason"] for r in result["data"]["rejected"]} == {"invalid_scope"}
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)  # nothing written — not even the read

    @pytest.mark.asyncio
    async def test_item_scope_note_on_referenced_item(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, edits={"c1": {"priority": "1"}}, scope="item"
        )
        note = next(
            c for c in self._commit_notes(client) if c.kwargs.get("note_title") == "COMMIT (item)"
        )
        assert note.kwargs["task_id"] == "c1"  # on the item, not the project
        assert note.kwargs["taskseries_id"] == "ts1"

    @pytest.mark.asyncio
    async def test_instant_scope_note_on_referenced_item(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={"c1": "now"}, scope="instant"
        )
        note = next(
            c
            for c in self._commit_notes(client)
            if c.kwargs.get("note_title") == "COMMIT (instant)"
        )
        assert note.kwargs["task_id"] == "c1"

    @pytest.mark.asyncio
    async def test_project_scope_note_distinct_from_plan_commit(self, gtd_tools):
        """project scope → an audit note on the project, distinctly titled so it never reads as a
        plan-wide COMMIT event."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            edits={PROJECT_ID: {"text": "Renamed project"}},
            scope="project",
        )
        titles = {c.kwargs.get("note_title") for c in self._commit_notes(client)}
        assert "COMMIT (project)" in titles
        assert "COMMIT" not in titles  # not the plan-scope title
        note = next(
            c
            for c in self._commit_notes(client)
            if c.kwargs.get("note_title") == "COMMIT (project)"
        )
        assert note.kwargs["task_id"] == PROJECT_ID

    @pytest.mark.asyncio
    async def test_project_rename_via_edits(self, gtd_tools):
        """The project itself is an accepted edits target (rename) — carved out of the child gate."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            edits={PROJECT_ID: {"text": "Renamed project"}},
            scope="project",
        )
        assert "rejected" not in result["data"]
        setname = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.setName")
        assert setname.kwargs["task_id"] == PROJECT_ID
        assert setname.kwargs["name"] == "Renamed project"

    @pytest.mark.asyncio
    async def test_project_complete_requires_confirm(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        # without confirmation → destructive rejection, nothing written
        rej = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, completes=[PROJECT_ID], scope="project"
        )
        assert {r["reason"] for r in rej["data"]["rejected"]} == {"destructive_unconfirmed"}
        assert not ({c.args[0] for c in client.call.call_args_list if c.args} & WRITE_METHODS)

        # with confirmation → the project is completed
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))
        ok = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            completes=[PROJECT_ID],
            confirm_destructive=True,
            scope="project",
        )
        assert "rejected" not in ok["data"]
        comp = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.complete")
        assert comp.kwargs["task_id"] == PROJECT_ID

    @pytest.mark.asyncio
    async def test_project_delete_soft(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        ok = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            removes=[PROJECT_ID],
            confirm_destructive=True,
            scope="project",
        )
        assert "rejected" not in ok["data"]
        rem = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.delete")
        assert rem.kwargs["task_id"] == PROJECT_ID

    @pytest.mark.asyncio
    async def test_carve_out_is_project_id_only(self, gtd_tools):
        """An arbitrary non-child id is still rejected — the carve-out is project_id-only."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            edits={"not-a-child": {"text": "x"}},
            scope="item",
        )
        reasons = {r["reason"] for r in result["data"]["rejected"]}
        assert "cross_project" in reasons
        assert result["data"]["applied"] == []
        assert not ({c.args[0] for c in client.call.call_args_list if c.args} & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_project_note_via_notes_lands_on_project(self, gtd_tools):
        """v1.27.0: notes[project_id] is carved out — a content note on the project task, in
        addition to the scope:project COMMIT (project) audit note (two notes on the project)."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            notes={PROJECT_ID: {"type": "JOURNAL", "text": "Kicked off"}},
            scope="project",
        )
        assert "rejected" not in result["data"]
        proj_notes = [
            c
            for c in client.call.call_args_list
            if c.args[0] == "rtm.tasks.notes.add" and c.kwargs.get("task_id") == PROJECT_ID
        ]
        titles = {c.kwargs.get("note_title") for c in proj_notes}
        assert "JOURNAL" in titles  # the user's content note
        assert "COMMIT (project)" in titles  # the per-scope audit note — both land on the project
        content = next(c for c in proj_notes if c.kwargs.get("note_title") == "JOURNAL")
        assert content.kwargs["note_text"] == "Kicked off"

    @pytest.mark.asyncio
    async def test_execute_on_project_id_still_rejected(self, gtd_tools):
        """execute stays child-only — project_id is not a valid execute target."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, execute={PROJECT_ID: "now"}
        )
        assert "cross_project" in {r["reason"] for r in result["data"]["rejected"]}
        assert not ({c.args[0] for c in client.call.call_args_list if c.args} & WRITE_METHODS)


class TestGtdOrderNoteDC4:
    """DC-4: durable reorder via the ORDER note — the commit writes it, the thin plan-graph
    honours it (single source of truth: RTM; the manual-order pin is pure derivation)."""

    @pytest.mark.asyncio
    async def test_commit_with_order_writes_conformant_order_note(self, gtd_tools):
        from rtm_mcp import order_note

        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, order=["c2", "c1"]
        )
        data = result["data"]
        assert "rejected" not in data
        assert data["order_persisted"] == "order-note"  # the mechanism, not True

        notes = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add"]
        order_writes = [
            c for c in notes if order_note.TITLE_RX.match(c.kwargs.get("note_title", ""))
        ]
        assert len(order_writes) == 1
        w = order_writes[0]
        assert w.kwargs["task_id"] == PROJECT_ID  # on the project task, not an item
        p = order_note.parse(w.kwargs["note_title"], w.kwargs["note_text"])
        assert p["valid"], p["errors"]
        assert p["order"] == ["c2", "c1"]
        assert p["source"] == "board-commit"
        # the note write records its transaction (batch_undo reverts it with the commit)
        assert any(op["op"] == "order-note" and op["transaction_id"] for op in data["applied"])
        # an order-only commit is a real commit: the COMMIT audit note still lands
        assert any(c.kwargs.get("note_title") == "COMMIT" for c in notes)

    @pytest.mark.asyncio
    async def test_order_note_written_before_overlay_refresh_stamp(self, gtd_tools):
        """A finalise fired off #ai_overlay_refresh_needed must never read a commit whose ORDER
        note hasn't landed — the note write strictly precedes the stamp."""
        from rtm_mcp import order_note

        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            order=["c1", "c2"],
            edits={"c1": {"priority": "1"}},
        )
        calls = client.call.call_args_list
        note_idx = next(
            i
            for i, c in enumerate(calls)
            if c.args[0] == "rtm.tasks.notes.add"
            and order_note.TITLE_RX.match(c.kwargs.get("note_title", ""))
        )
        stamp_idx = next(
            i
            for i, c in enumerate(calls)
            if c.args[0] == "rtm.tasks.addTags"
            and c.kwargs.get("tags") == "ai_overlay_refresh_needed"
        )
        assert note_idx < stamp_idx

    @pytest.mark.asyncio
    async def test_commit_without_order_writes_no_order_note(self, gtd_tools):
        from rtm_mcp import order_note

        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, edits={"c1": {"priority": "1"}}
        )
        assert result["data"]["order_persisted"] is False
        notes = [c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add"]
        assert not any(order_note.TITLE_RX.match(c.kwargs.get("note_title", "")) for c in notes)

    @pytest.mark.asyncio
    async def test_order_only_commit_stamps_overlay_refresh(self, gtd_tools):
        """An order-only commit is non-empty (the ORDER note landed) → the overlay-refresh mark
        is stamped as for any other commit; the finalise drain derives the pin from the note."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(), project_id=PROJECT_ID, order=["c2", "c1"]
        )
        stamped = [
            c
            for c in client.call.call_args_list
            if c.args[0] == "rtm.tasks.addTags"
            and c.kwargs.get("tags") == "ai_overlay_refresh_needed"
        ]
        assert len(stamped) == 1

    @pytest.mark.asyncio
    async def test_canvas_seed_honours_latest_order_note(self, gtd_tools):
        """The thin plan-graph derives the manual-order bias from the latest valid ORDER note on
        the project, so the board seed shows the dragged order immediately on reload."""
        from rtm_mcp import order_note

        tools, client = gtd_tools
        title, body = order_note.make(
            ["c2", "c1"], "board-commit", "2026-07-05T09:41:12Z", "2026-07-05 10:41"
        )
        tree = _getlist(
            [
                _ts(
                    "tsP",
                    PROJECT_ID,
                    "Test Project",
                    parent=AREA_ID,
                    tags=["personal", "project"],
                    # RTM storage reality: the title is the body's first line.
                    notes=[
                        {
                            "id": "n9",
                            "created": "2026-07-05T09:41:12Z",
                            "title": "",
                            "$t": f"{title}\n{body}",
                        }
                    ],
                ),
                _ts("ts1", "c1", "First by default", parent=PROJECT_ID, tags=["action"]),
                _ts("ts2", "c2", "Dragged first", parent=PROJECT_ID, tags=["action"]),
            ]
        )
        client.call = AsyncMock(return_value=tree)

        result = await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID)
        ids = [it["id"] for it in result["data"]["seed"]]
        assert ids == ["c2", "c1"]  # the pinned order, not input order
        # still read-only: the ORDER-note derivation adds no call
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]

    @pytest.mark.asyncio
    async def test_canvas_ignores_invalid_order_note(self, gtd_tools):
        """Fail closed: a corrupted ORDER note is ignored (no bias) — the seed falls back to the
        default thin order and always renders."""
        tools, client = gtd_tools
        corrupt = "2026-07-05 10:41 — ORDER — 2 items\n{not json"
        tree = _getlist(
            [
                _ts(
                    "tsP",
                    PROJECT_ID,
                    "Test Project",
                    parent=AREA_ID,
                    tags=["personal", "project"],
                    notes=[
                        {
                            "id": "n9",
                            "created": "2026-07-05T09:41:12Z",
                            "title": "",
                            "$t": corrupt,
                        }
                    ],
                ),
                _ts("ts1", "c1", "First by default", parent=PROJECT_ID, tags=["action"]),
                _ts("ts2", "c2", "Would be dragged first", parent=PROJECT_ID, tags=["action"]),
            ]
        )
        client.call = AsyncMock(return_value=tree)

        result = await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID)
        ids = [it["id"] for it in result["data"]["seed"]]
        assert ids == ["c1", "c2"]  # default input order — the invalid note biased nothing

    @pytest.mark.asyncio
    async def test_canvas_pin_never_violates_topology(self, gtd_tools):
        """The ORDER note biases cosmetic tiering only: a consumer pinned ahead of its producer
        is clamped — the DAG wins (identical semantics to gtd's enriched engine)."""
        from rtm_mcp import order_note

        tools, client = gtd_tools
        # pin the consumer (222) ahead of its producer (111)
        title, body = order_note.make(
            ["222", "111"], "board-commit", "2026-07-05T09:41:12Z", "2026-07-05 10:41"
        )
        depends = (
            "2026-07-05 — DEPENDS-ON — needs the producer\n"
            'Upstream RTM IDs:\n  task_id: "111"\n  list_id: "49657585"\n'
            "Status: active\n"
        )
        tree = _getlist(
            [
                _ts(
                    "tsP",
                    PROJECT_ID,
                    "Test Project",
                    parent=AREA_ID,
                    tags=["personal", "project"],
                    notes=[
                        {
                            "id": "n9",
                            "created": "2026-07-05T09:41:12Z",
                            "title": "",
                            "$t": f"{title}\n{body}",
                        }
                    ],
                ),
                # numeric ids: DEPENDS-ON upstream ids are matched by a digits-only regex
                _ts("ts1", "111", "Producer", parent=PROJECT_ID, tags=["action"]),
                _ts(
                    "ts2",
                    "222",
                    "Consumer",
                    parent=PROJECT_ID,
                    tags=["action"],
                    notes=[
                        {"id": "nd", "created": "2026-07-05T00:00:00Z", "title": "", "$t": depends}
                    ],
                ),
            ]
        )
        client.call = AsyncMock(return_value=tree)

        result = await tools["gtd_project_canvas"](FakeContext(), project_id=PROJECT_ID)
        ids = [it["id"] for it in result["data"]["seed"]]
        assert ids.index("111") < ids.index("222")  # producer first — the pin was clamped


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
        assert "strict_tag_rejected" in {r.get("reason") for r in data["rejected"]}
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
            "chat_count",
            "chat_review_count",
            "waiting_count",
            "redacted",
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
        # conversation counts: no #ai_chat items in this fixture.
        assert row["chat_count"] == 0
        assert row["chat_review_count"] == 0

    @pytest.mark.asyncio
    async def test_project_chat_counts(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsA", AREA_ID, "Sam — University", tags=["personal", "focus"]),
                _ts("tsP", PROJECT_ID, "Open days", parent=AREA_ID, tags=["personal", "project"]),
                _ts("ts1", "101", "Chatting", parent=PROJECT_ID, tags=["action", "ai_chat"]),
                _ts(
                    "ts2",
                    "102",
                    "Awaiting review",
                    parent=PROJECT_ID,
                    tags=["action", "ai_chat", "ai_output_review_needed"],
                ),
            ]
        )
        client.call = AsyncMock(return_value=tree)

        data = (await tools["gtd_project_index"](FakeContext()))["data"]
        row = next(r for r in data["projects"] if r["project_id"] == PROJECT_ID)
        assert row["chat_count"] == 2  # both items have #ai_chat
        assert row["chat_review_count"] == 1  # one awaits review

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
            "redacted": False,
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
            "estimate",
            "contexts",
            "energy",
            "exec",
            "redacted",
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

    @pytest.mark.asyncio
    async def test_project_action_and_focus_redacted(self, gtd_tools):
        # Redaction surfaces at every level the navigator renders: the focus row and the project row
        # from their own #redacted tag; the action row is server-derived and CASCADES — an action
        # under a redacted project / focus is shielded even without its own tag.
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts(
                        "tsArea",
                        AREA_ID,
                        "Hive Mind",
                        tags=["personal", "focus", "redacted"],
                    ),
                    _ts(
                        "tsP",
                        PROJECT_ID,
                        "Open days",
                        parent=AREA_ID,
                        tags=["personal", "project", "redacted"],
                    ),
                    _ts("ts1", "101", "Secret", parent=PROJECT_ID, tags=["action", "redacted"]),
                    _ts("ts2", "102", "Open", parent=PROJECT_ID, tags=["action"]),
                ]
            )
        )

        data = (await tools["gtd_project_index"](FakeContext()))["data"]
        focus = next(f for f in data["foci"] if f["focus_id"] == AREA_ID)
        assert focus["redacted"] is True
        proj = next(r for r in data["projects"] if r["project_id"] == PROJECT_ID)
        assert proj["redacted"] is True
        by_id = {a["action_id"]: a for a in data["actions"]}
        assert by_id["101"]["redacted"] is True  # own tag
        assert by_id["102"]["redacted"] is True  # cascade from the redacted project + focus


# ── gtd_set_redaction ────────────────────────────────────────────────────────


def _redaction_tree(tags=None):
    """A getList tree carrying the target task c1 (taskseries ts1) under the project."""
    return _getlist(
        [
            _ts("tsP", PROJECT_ID, "Sam's university open days", parent=AREA_ID, tags=["project"]),
            _ts("ts1", "c1", "Attend webinar", parent=PROJECT_ID, tags=tags),
        ]
    )


def _redaction_dispatch(tree):
    """side_effect: tree for reads, a transaction for the tag write."""

    async def _call(method, **kwargs):
        if method == "rtm.tasks.getList":
            return tree
        return {"transaction": {"id": f"tx_{method.rsplit('.', 1)[-1]}", "undoable": "1"}}

    return _call


class TestGtdSetRedaction:
    @pytest.mark.asyncio
    async def test_add_path_tags_and_records(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree()))

        result = await tools["gtd_set_redaction"](FakeContext(), task_id="c1", redacted=True)

        add = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert add.kwargs["tags"] == "redacted"
        assert add.kwargs["task_id"] == "c1"
        assert add.kwargs["taskseries_id"] == "ts1"  # triple resolved internally
        assert add.kwargs["list_id"] == LIST_ID
        assert result["data"] == {"task_id": "c1", "redacted": True}
        assert result["metadata"]["transaction_id"] == "tx_addTags"
        client.record_transaction.assert_called()  # undoable via batch_undo

    @pytest.mark.asyncio
    async def test_remove_path(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree(tags=["redacted"])))

        result = await tools["gtd_set_redaction"](FakeContext(), task_id="c1", redacted=False)

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert "rtm.tasks.removeTags" in methods
        assert "rtm.tasks.addTags" not in methods  # never gated, never added
        rem = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.removeTags")
        assert rem.kwargs["tags"] == "redacted"
        assert result["data"] == {"task_id": "c1", "redacted": False}

    @pytest.mark.asyncio
    async def test_unknown_task_id_errors_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree()))

        result = await tools["gtd_set_redaction"](FakeContext(), task_id="nope", redacted=True)

        assert "error" in result["data"]
        assert "not found" in result["data"]["error"]["message"]
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # one read, nothing written

    @pytest.mark.asyncio
    async def test_strict_tag_rejection_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True, vault_root=None)
        client.get_account_tags = AsyncMock(return_value=set())  # #redacted not provisioned
        client.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree()))

        result = await tools["gtd_set_redaction"](FakeContext(), task_id="c1", redacted=True)

        assert result["data"]["error"]["details"]["strict_tag_mode"] is True
        assert "redacted" in result["data"]["error"]["details"]["rejected_tags"]
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert "rtm.tasks.addTags" not in methods  # nothing written

    @pytest.mark.asyncio
    async def test_round_trips_on_a_focus_shaped_task(self, gtd_tools):
        # An Area of Focus is just a task (parent of #project tasks) — gtd_set_redaction resolves by
        # id regardless of shape, so redacting a whole focus is the same one governed write.
        tools, client = gtd_tools
        focus_tree = _getlist([_ts("tsArea", AREA_ID, "Hive Mind", tags=["work", "focus"])])
        client.call = AsyncMock(side_effect=_redaction_dispatch(focus_tree))

        add = await tools["gtd_set_redaction"](FakeContext(), task_id=AREA_ID, redacted=True)
        assert add["data"] == {"task_id": AREA_ID, "redacted": True}
        addc = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert addc.kwargs["task_id"] == AREA_ID and addc.kwargs["tags"] == "redacted"

        client.call = AsyncMock(side_effect=_redaction_dispatch(focus_tree))
        rem = await tools["gtd_set_redaction"](FakeContext(), task_id=AREA_ID, redacted=False)
        assert rem["data"] == {"task_id": AREA_ID, "redacted": False}
        remc = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.removeTags")
        assert remc.kwargs["task_id"] == AREA_ID and remc.kwargs["tags"] == "redacted"

    @pytest.mark.asyncio
    async def test_add_path_writes_audit_note(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree()))

        await tools["gtd_set_redaction"](FakeContext(), task_id="c1", redacted=True)

        note = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add")
        assert note.kwargs["note_title"] == "REDACTION"
        assert "drawn" in note.kwargs["note_text"]
        assert note.kwargs["task_id"] == "c1"  # on the target item
        assert (
            "ai_conversation" not in note.kwargs["note_text"]
        )  # a viewing change, not an AI write

    @pytest.mark.asyncio
    async def test_remove_path_writes_audit_note(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree(tags=["redacted"])))

        await tools["gtd_set_redaction"](FakeContext(), task_id="c1", redacted=False)

        note = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add")
        assert note.kwargs["note_title"] == "REDACTION"
        assert "lifted" in note.kwargs["note_text"]

    @pytest.mark.asyncio
    async def test_strict_tag_rejection_writes_no_audit_note(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True, vault_root=None)
        client.get_account_tags = AsyncMock(return_value=set())  # #redacted not provisioned
        client.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree()))

        await tools["gtd_set_redaction"](FakeContext(), task_id="c1", redacted=True)

        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert "rtm.tasks.notes.add" not in methods  # nothing written, not even the audit note


# ── gtd_chat_post / gtd_chat_thread ──────────────────────────────────────────

CHAT_TITLE_RE = r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — CHAT — (me|ai) — Attend webinar$"


def _chat_target_tree(tags=None, notes=None):
    """A getList tree carrying the chat target task c1 (taskseries ts1) under the project."""
    return _getlist(
        [
            _ts("tsP", PROJECT_ID, "Sam's university open days", parent=AREA_ID, tags=["project"]),
            _ts("ts1", "c1", "Attend webinar", parent=PROJECT_ID, tags=tags, notes=notes),
        ]
    )


def _chat_dispatch(tree, note_id="n_new"):
    """side_effect for client.call: tree for reads, a note dict for notes.add, tx for tag ops."""

    async def _call(method, **kwargs):
        if method == "rtm.tasks.getList":
            return tree
        if method == "rtm.tasks.notes.add":
            return {
                "transaction": {"id": "txnote", "undoable": "1"},
                "note": {"id": note_id, "created": "2026-06-28T14:30:00Z"},
            }
        return {"transaction": {"id": f"tx_{method.rsplit('.', 1)[-1]}", "undoable": "1"}}

    return _call


class TestGtdChatPost:
    @pytest.mark.asyncio
    async def test_me_turn_posts_note_and_adds_tags(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        result = await tools["gtd_chat_post"](
            FakeContext(), task_id="c1", text="please progress", role="me"
        )

        add = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add")
        assert re.match(CHAT_TITLE_RE, add.kwargs["note_title"])  # scope defaults to task name
        assert "— me —" in add.kwargs["note_title"]
        assert add.kwargs["note_text"] == "please progress"

        tag = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.addTags")
        assert tag.kwargs["tags"] == "ai_chat_requested,ai_chat"
        assert tag.kwargs["task_id"] == "c1"

        data = result["data"]
        assert data["role"] == "me"
        assert data["tag_changes"] == ["+ai_chat_requested", "+ai_chat"]
        assert data["note"]["id"] == "n_new"
        assert data["errors"] == []
        client.record_transaction.assert_called()  # transactions recorded for batch_undo

    @pytest.mark.asyncio
    async def test_ai_turn_removes_requested_tag(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        result = await tools["gtd_chat_post"](
            FakeContext(), task_id="c1", text="here is your answer", role="ai"
        )

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert "rtm.tasks.removeTags" in methods
        assert "rtm.tasks.addTags" not in methods  # ai turn never adds
        rem = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.removeTags")
        assert rem.kwargs["tags"] == "ai_chat_requested"
        assert result["data"]["tag_changes"] == ["-ai_chat_requested"]

    @pytest.mark.asyncio
    async def test_task_id_resolves_series_and_list(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        await tools["gtd_chat_post"](FakeContext(), task_id="c1", text="x", role="me")

        add = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add")
        assert add.kwargs["task_id"] == "c1"
        assert add.kwargs["taskseries_id"] == "ts1"
        assert add.kwargs["list_id"] == LIST_ID

    @pytest.mark.asyncio
    async def test_mode_footer_round_trips_into_thread(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        await tools["gtd_chat_post"](
            FakeContext(), task_id="c1", text="do it", role="me", mode="act"
        )
        add = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.notes.add")
        title, body = add.kwargs["note_title"], add.kwargs["note_text"]
        assert body == "do it\n\nMode: act"

        # Feed the authored note back through the read tool in the shape real getList returns —
        # title field empty, the grammar title as the body's first line (title\nmessage). The mode
        # still round-trips.
        note = {
            "id": "n1",
            "title": "",
            "$t": f"{title}\n{body}",
            "created": "2026-06-28T14:30:00Z",
        }
        client.call = AsyncMock(return_value=_chat_target_tree(notes=[note]))
        thread = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        turn = thread["data"]["turns"][0]
        assert turn["mode"] == "act"
        assert turn["text"] == "do it"

    @pytest.mark.asyncio
    async def test_invalid_role_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        result = await tools["gtd_chat_post"](FakeContext(), task_id="c1", text="x", role="bot")
        assert "error" in result["data"]
        client.call.assert_not_called()  # rejected before any read/write

    @pytest.mark.asyncio
    async def test_invalid_mode_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        result = await tools["gtd_chat_post"](
            FakeContext(), task_id="c1", text="x", role="me", mode="ponder"
        )
        assert "error" in result["data"]
        client.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_not_found(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        result = await tools["gtd_chat_post"](FakeContext(), task_id="nope", text="x", role="me")
        assert "error" in result["data"]
        assert "not found among active tasks" in result["data"]["error"]["message"]
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        # incomplete miss → a second read against completed to distinguish; nothing written.
        assert methods == ["rtm.tasks.getList", "rtm.tasks.getList"]

    @pytest.mark.asyncio
    async def test_completed_task_rejected_read_only(self, gtd_tools):
        # A me-turn to a COMPLETED task is refused with a clear read-only error (the worker only
        # drains incomplete items), after a second lookup — nothing written.
        tools, client = gtd_tools
        completed_tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Project", parent=AREA_ID, tags=["project"]),
                _ts(
                    "ts1",
                    "cdone",
                    "Done item",
                    parent=PROJECT_ID,
                    tags=["action", "ai_chat"],
                    completed="2026-07-01T00:00:00Z",
                ),
            ]
        )

        async def _call(method, **kwargs):
            if method == "rtm.tasks.getList":
                # completed read returns the task; incomplete read does not.
                return completed_tree if "completed" in kwargs.get("filter", "") else _getlist([])
            return {"transaction": {"id": "tx", "undoable": "1"}}

        client.call = AsyncMock(side_effect=_call)

        result = await tools["gtd_chat_post"](FakeContext(), task_id="cdone", text="x", role="me")
        assert "completed" in result["data"]["error"]["message"]
        assert "read-only" in result["data"]["error"]["message"]
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList", "rtm.tasks.getList"]  # two reads, no write

    @pytest.mark.asyncio
    async def test_strict_tag_rejection_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True, vault_root=None)
        client.get_account_tags = AsyncMock(return_value={"ai_chat"})  # missing ai_chat_requested
        client.call = AsyncMock(side_effect=_chat_dispatch(_chat_target_tree()))

        result = await tools["gtd_chat_post"](FakeContext(), task_id="c1", text="x", role="me")

        assert result["data"]["error"]["details"]["strict_tag_mode"] is True
        assert "ai_chat_requested" in result["data"]["error"]["details"]["rejected_tags"]
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert "rtm.tasks.notes.add" not in methods  # nothing written
        assert "rtm.tasks.addTags" not in methods


class TestGtdChatThread:
    def _thread_notes(self):
        # Real getList shape: title field empty; the grammar title is the body's first line.
        return [
            {
                "id": "a",
                "title": "",
                "$t": "2026-06-28 10:00 — CHAT — me — Attend webinar\nfirst",
                "created": "2026-06-28T10:00:00Z",
            },
            {
                "id": "doc",
                "title": "",
                "$t": "DEPENDS-ON\nnot a chat",
                "created": "2026-06-28T11:00:00Z",
            },
            {
                "id": "b",
                "title": "",
                "$t": "2026-06-28 12:00 — CHAT — ai — Attend webinar\nsecond",
                "created": "2026-06-28T12:00:00Z",
            },
        ]

    @pytest.mark.asyncio
    async def test_returns_only_chat_turns_oldest_first(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_chat_target_tree(notes=self._thread_notes()))

        result = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        turns = result["data"]["turns"]
        assert [t["note_id"] for t in turns] == ["a", "b"]
        assert [t["role"] for t in turns] == ["me", "ai"]
        assert result["data"]["task_id"] == "c1"

    @pytest.mark.asyncio
    async def test_reads_completed_task_thread(self, gtd_tools):
        # A prior conversation stays viewable after the task is completed: the read spans
        # incomplete + completed, returns the turns, and `requested` is False (no pending worker).
        tools, client = gtd_tools
        completed_tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Project", parent=AREA_ID, tags=["project"]),
                _ts(
                    "ts1",
                    "c1",
                    "Attend webinar",
                    parent=PROJECT_ID,
                    tags=["action", "ai_chat"],
                    completed="2026-07-01T00:00:00Z",
                    notes=self._thread_notes(),
                ),
            ]
        )
        client.call = AsyncMock(return_value=completed_tree)

        result = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        assert [t["note_id"] for t in result["data"]["turns"]] == ["a", "b"]
        assert result["data"]["requested"] is False
        # the resolve read spans incomplete + completed.
        call = next(c for c in client.call.call_args_list if c.args[0] == "rtm.tasks.getList")
        assert call.kwargs["filter"] == "status:incomplete OR status:completed"

    @pytest.mark.asyncio
    async def test_since_filters(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_chat_target_tree(notes=self._thread_notes()))

        result = await tools["gtd_chat_thread"](
            FakeContext(), task_id="c1", since="2026-06-28T11:30:00Z"
        )
        assert [t["note_id"] for t in result["data"]["turns"]] == ["b"]

    @pytest.mark.asyncio
    async def test_requested_reflects_tag(self, gtd_tools):
        tools, client = gtd_tools

        client.call = AsyncMock(
            return_value=_chat_target_tree(tags=["action", "ai_chat_requested"])
        )
        on = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        assert on["data"]["requested"] is True

        client.call = AsyncMock(return_value=_chat_target_tree(tags=["action"]))
        off = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        assert off["data"]["requested"] is False

    @pytest.mark.asyncio
    async def test_no_chat_notes_returns_empty(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_chat_target_tree())

        result = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        assert result["data"]["turns"] == []

    @pytest.mark.asyncio
    async def test_turns_carry_server_derived_attachments(self, gtd_tools):
        # Stage 2 (board-chat enrichment § 2.8): an OUTPUT note's FILING path (labelled
        # continuation form) attaches to the ai turn created at-or-after it, verbatim; a LINK:
        # trailer parses into links[] and stays in text. The me turn carries empty arrays.
        tools, client = gtd_tools
        vault_path = "work/turner-and-townsend/reporting-capability-guidance/output/brief.md"
        notes = [
            *self._thread_notes(),
            {
                "id": "out1",
                "title": "",
                "$t": (
                    "2026-06-28 — OUTPUT — Commissioning brief drafted\n"
                    "Drafted the brief.\n\n"
                    "FILING: filed in the project output folder with companion metadata —\n"
                    f"{vault_path} (+ .meta.md)"
                ),
                "created": "2026-06-28T11:55:00Z",
            },
        ]
        notes[2]["$t"] = (
            "2026-06-28 12:00 — CHAT — ai — Attend webinar\n"
            "Drafted it.\n\nLINK: https://x.test/page — Confluence page"
        )
        client.call = AsyncMock(return_value=_chat_target_tree(notes=notes))

        result = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        me, ai = result["data"]["turns"]
        assert me["files"] == [] and me["links"] == []
        assert ai["files"] == [
            {"path": vault_path, "label": "Commissioning brief drafted", "note_id": "out1"}
        ]
        assert ai["links"] == [{"url": "https://x.test/page", "label": "Confluence page"}]
        assert "LINK: https://x.test/page — Confluence page" in ai["text"]  # retained in text

    @pytest.mark.asyncio
    async def test_output_after_last_ai_turn_stays_unattached(self, gtd_tools):
        # Conservative correlation: a filing with no ai turn after it attaches to nothing.
        tools, client = gtd_tools
        notes = [
            *self._thread_notes(),
            {
                "id": "late",
                "title": "",
                "$t": "2026-06-28 — OUTPUT — Filed later\nFILING: personal/later.md (+ .meta.md)",
                "created": "2026-06-28T13:00:00Z",
            },
        ]
        client.call = AsyncMock(return_value=_chat_target_tree(notes=notes))

        result = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        assert all(t["files"] == [] for t in result["data"]["turns"])

    @pytest.mark.asyncio
    async def test_read_only_call_surface(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_chat_target_tree(notes=self._thread_notes()))

        await tools["gtd_chat_thread"](FakeContext(), task_id="c1")

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # one read; no writes/timeline
        client.record_transaction.assert_not_called()

    def _project_scope_tree(self):
        """A project-scope thread (CHAT notes on the PROJECT task) whose artefacts were filed
        against descendants: an open child, a COMPLETED child, and a grandchild (3-level)."""

        def _out(note_id, created, path, summary):
            return {
                "id": note_id,
                "title": "",
                "$t": f"2026-06-28 — OUTPUT — {summary}\nFILING: {path} (+ .meta.md)",
                "created": created,
            }

        project_notes = [
            {
                "id": "m1",
                "title": "",
                "$t": "2026-06-28 10:00 — CHAT — me — Project\nwhat outputs?",
                "created": "2026-06-28T10:00:00Z",
            },
            {
                "id": "a1",
                "title": "",
                "$t": "2026-06-28 12:00 — CHAT — ai — Project\nfour packs",
                "created": "2026-06-28T12:00:00Z",
            },
        ]
        return _getlist(
            [
                _ts(
                    "tsP",
                    PROJECT_ID,
                    "Hire an Engineering Manager",
                    parent=AREA_ID,
                    tags=["project"],
                    notes=project_notes,
                ),
                _ts(
                    "ts1",
                    "c1",
                    "Draft the job spec",
                    parent=PROJECT_ID,
                    tags=["action"],
                    notes=[
                        _out("o1", "2026-06-28T11:00:00Z", "work/hire/output/spec.docx", "Spec")
                    ],
                ),
                _ts(
                    "ts2",
                    "c2",
                    "Draft the ALR",
                    parent=PROJECT_ID,
                    tags=["action"],
                    completed="2026-06-20T00:00:00Z",
                    notes=[_out("o2", "2026-06-28T11:10:00Z", "work/hire/output/alr.xlsx", "ALR")],
                ),
                _ts(
                    "ts3",
                    "g1",
                    "Collect referee details",
                    parent="c1",
                    tags=["action"],
                    notes=[_out("o3", "2026-06-28T11:20:00Z", "work/hire/output/refs.md", "Refs")],
                ),
            ]
        )

    @pytest.mark.asyncio
    async def test_project_scope_aggregates_descendant_filings(self, gtd_tools):
        # Stage 2b: a #project target's files[] aggregate OUTPUT/FILING notes from the whole
        # descendant tree — open child, COMPLETED child, and grandchild — each entry carrying
        # item_id/item_name provenance, on the ai turn created at-or-after the filing. Still ONE
        # read, no write.
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=self._project_scope_tree())

        result = await tools["gtd_chat_thread"](FakeContext(), task_id=PROJECT_ID)
        me, ai = result["data"]["turns"]
        assert me["files"] == []
        assert ai["files"] == [
            {
                "path": "work/hire/output/spec.docx",
                "label": "Spec",
                "note_id": "o1",
                "item_id": "c1",
                "item_name": "Draft the job spec",
            },
            {
                "path": "work/hire/output/alr.xlsx",
                "label": "ALR",
                "note_id": "o2",
                "item_id": "c2",
                "item_name": "Draft the ALR",
            },
            {
                "path": "work/hire/output/refs.md",
                "label": "Refs",
                "note_id": "o3",
                "item_id": "g1",
                "item_name": "Collect referee details",
            },
        ]
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # the broad read already carries the children
        client.record_transaction.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_project_target_with_subtask_stays_same_task(self, gtd_tools):
        # The gate is the #project tag, not subtask presence: an item target's files[] never
        # scan its own subtasks' notes.
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts(
                    "ts1",
                    "c1",
                    "Parent action",
                    parent="",
                    tags=["action"],
                    notes=[
                        {
                            "id": "m1",
                            "title": "",
                            "$t": "2026-06-28 10:00 — CHAT — me — Parent action\ngo",
                            "created": "2026-06-28T10:00:00Z",
                        },
                        {
                            "id": "a1",
                            "title": "",
                            "$t": "2026-06-28 12:00 — CHAT — ai — Parent action\ndone",
                            "created": "2026-06-28T12:00:00Z",
                        },
                    ],
                ),
                _ts(
                    "ts2",
                    "c2",
                    "Subtask",
                    parent="c1",
                    tags=["action"],
                    notes=[
                        {
                            "id": "o1",
                            "title": "",
                            "$t": "2026-06-28 — OUTPUT — Filed\nFILING: work/x/output/y.md (+ .meta.md)",
                            "created": "2026-06-28T11:00:00Z",
                        }
                    ],
                ),
            ]
        )
        client.call = AsyncMock(return_value=tree)

        result = await tools["gtd_chat_thread"](FakeContext(), task_id="c1")
        assert all(t["files"] == [] for t in result["data"]["turns"])


def _inflight_tree():
    """Two projects, each with an incomplete #ai_chat item (different statuses), plus an excluded
    #test chat item — the cross-project shape gtd_chat_inflight rolls up."""
    chat_note = {
        "id": "n1",
        "title": "",  # real getList: title empty, grammar in the body's first line
        "$t": "2026-06-29 10:00 — CHAT — me — Alpha\nkick it off",
        "created": "2026-06-29T10:00:00Z",
    }
    return _getlist(
        [
            _ts("tsA", "pA", "Alpha", parent=AREA_ID, tags=["project"]),
            _ts(
                "ts1",
                "iA",
                "Draft the thing",
                parent="pA",
                tags=["action", "ai_chat", "ai_chat_requested"],
                notes=[chat_note],
            ),
            _ts("tsB", "pB", "Beta", parent=AREA_ID, tags=["project"]),
            _ts(
                "ts2",
                "iB",
                "Review the output",
                parent="pB",
                tags=["action", "ai_chat", "ai_output_review_needed"],
            ),
            _ts("tsT", "iT", "Test item", parent="pA", tags=["action", "ai_chat", "test"]),
        ]
    )


class TestGtdChatInflight:
    @pytest.mark.asyncio
    async def test_cross_project_rollup(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_inflight_tree())

        data = (await tools["gtd_chat_inflight"](FakeContext()))["data"]
        by_id = {i["task_id"]: i for i in data["items"]}
        assert set(by_id) == {"iA", "iB"}  # #test item excluded
        assert data["count"] == 2

        assert by_id["iA"]["status"] == "in_flight"
        assert by_id["iA"]["scope"] == "item"
        assert by_id["iA"]["project_id"] == "pA"
        assert by_id["iA"]["project_name"] == "Alpha"
        assert by_id["iA"]["last_activity"] == "2026-06-29T10:00:00Z"

        assert by_id["iB"]["status"] == "awaiting_review"
        assert by_id["iB"]["project_id"] == "pB"
        assert by_id["iB"]["project_name"] == "Beta"

    @pytest.mark.asyncio
    async def test_empty_portfolio(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([]))

        data = (await tools["gtd_chat_inflight"](FakeContext()))["data"]
        assert data == {"items": [], "count": 0}

    @pytest.mark.asyncio
    async def test_read_only_call_surface(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_inflight_tree())

        await tools["gtd_chat_inflight"](FakeContext())

        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # one read; no writes/timeline/settings
        client.record_transaction.assert_not_called()


class TestGtdChatPostNoteFailure:
    @pytest.mark.asyncio
    async def test_note_write_failure_skips_signal_tags(self, gtd_tools):
        # Regression: a failed chat-note write used to still stamp
        # #ai_chat_requested — a drain signal with no turn to answer.
        tools, client = gtd_tools
        tree = _chat_target_tree()

        async def _call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return tree
            if method == "rtm.tasks.notes.add":
                raise RuntimeError("RTM 500")
            return {"transaction": {"id": "tx", "undoable": "1"}}

        client.call = AsyncMock(side_effect=_call)

        result = await tools["gtd_chat_post"](
            FakeContext(), task_id="c1", text="please progress", role="me"
        )

        data = result["data"]
        assert "error" in data
        assert data["errors"]  # underlying failure surfaced
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert "rtm.tasks.addTags" not in methods
        assert "rtm.tasks.removeTags" not in methods

    @pytest.mark.asyncio
    async def test_ai_turn_note_failure_keeps_requested_tag(self, gtd_tools):
        # An ai turn whose note write failed must NOT remove #ai_chat_requested —
        # the turn was not actually answered.
        tools, client = gtd_tools
        tree = _chat_target_tree()

        async def _call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return tree
            if method == "rtm.tasks.notes.add":
                raise RuntimeError("RTM 500")
            return {"transaction": {"id": "tx", "undoable": "1"}}

        client.call = AsyncMock(side_effect=_call)

        result = await tools["gtd_chat_post"](FakeContext(), task_id="c1", text="answer", role="ai")
        assert "error" in result["data"]
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert "rtm.tasks.removeTags" not in methods


class TestGtdCreateProjectDuplicateIds:
    @pytest.mark.asyncio
    async def test_duplicate_in_draft_ids_rejected_no_writes(self, gtd_tools):
        # Regression: an explicit id colliding with another item's positional
        # index passed validation and silently dropped an item at apply time.
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_create_dispatch(_create_account()))

        result = await tools["gtd_create_project"](
            FakeContext(),
            frame={"life": "personal", "focus": "Personal", "name": "P"},
            items=[
                {"id": "1", "type": "action", "text": "A"},
                {"type": "action", "text": "B"},  # positional id "1" — collides
            ],
        )
        data = result["data"]
        assert data["created"] == []
        assert "duplicate_id" in {r.get("reason") for r in data["rejected"]}
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert not (methods & WRITE_METHODS)


# ── repeating-templated-project token stamping (Wave B) ──────────────────────

_DEP_BODY = (
    "2026-06-15 — DEPENDS-ON — Task B needs Task A\n"
    "Depends on: Task A\n"
    "Upstream RTM IDs:\n"
    '  task_id: "201"\n'
    '  taskseries_id: "tsA"\n'
    '  list_id: "49657585"\n'
    "Status: active\n"
    "Captured by: progression-fanout"
)


def _tmpl_body(slug):
    return f'2026-07-05 — TMPL-CHILD — {slug}\n{{"schema": "tmpl-child/1", "template_child_id": "{slug}"}}'


def _dep_note(body=_DEP_BODY):
    return {"id": "nDep", "created": "2026-06-15T00:00:00Z", "title": "", "$t": body}


def _tmpl_note(nid, slug):
    return {"id": nid, "created": "2026-07-05T00:00:00Z", "title": "", "$t": _tmpl_body(slug)}


def _repeating_tree(rrule="FREQ=WEEKLY", a_notes=None, b_notes=None, extra=None):
    series = [
        _ts("tsRP", "rp", "Weekly review", tags=["work", "project"], rrule=rrule),
        _ts("tsA", "201", "Task A", parent="rp", tags=["action"], notes=a_notes),
        _ts(
            "tsB",
            "202",
            "Task B",
            parent="rp",
            tags=["action"],
            notes=b_notes if b_notes is not None else [_dep_note()],
        ),
    ]
    if extra:
        series.extend(extra)
    return _getlist(series)


def _stamp_dispatch(tree):
    async def _call(method, **kwargs):
        if method == "rtm.tasks.getList":
            return tree
        if method == "rtm.tasks.notes.add":
            return {"transaction": {"id": "txadd", "undoable": "1"}, "note": {"id": "n_new"}}
        return {"transaction": {"id": f"tx_{method.rsplit('.', 1)[-1]}", "undoable": "1"}}

    return _call


class TestGtdStampTokens:
    @pytest.mark.asyncio
    async def test_backfill_stamps_and_authors_dep_lines(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_stamp_dispatch(_repeating_tree()))

        result = await tools["gtd_stamp_tokens"](FakeContext(), project_id="rp")
        data = result["data"]
        entry = data["projects"][0]
        assert entry["project_id"] == "rp"
        assert entry["skipped_reason"] is None
        stamped = {s["child_id"]: s["slug"] for s in entry["stamped"]}
        assert set(stamped) == {"201", "202"}  # both open children stamped
        # The dep line on 202 carries 201's freshly assigned slug (token-space).
        assert len(entry["dep_lines"]) == 1
        dl = entry["dep_lines"][0]
        assert dl["child_id"] == "202"
        assert dl["upstream_slug"] == stamped["201"]

        calls = client.call.call_args_list
        adds = [c for c in calls if c.args and c.args[0] == "rtm.tasks.notes.add"]
        edits = [c for c in calls if c.args and c.args[0] == "rtm.tasks.notes.edit"]
        # 2 TMPL-CHILD notes + 1 audit note; 1 DEPENDS-ON re-author.
        assert len(adds) == 3
        assert len(edits) == 1
        assert any("TMPL-CHILD" in c.kwargs.get("note_title", "") for c in adds)
        assert any(c.kwargs.get("note_title") == "TMPL-STAMP" for c in adds)
        # The edited DEPENDS-ON note text carries the token line.
        assert "Template-child-id:" in edits[0].kwargs["note_text"]

    @pytest.mark.asyncio
    async def test_idempotent_second_run_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        tree = _repeating_tree(
            a_notes=[_tmpl_note("nA", "aaaaaaaa")],
            b_notes=[
                _tmpl_note("nB", "bbbbbbbb"),
                _dep_note(_DEP_BODY + '\nTemplate-child-id: "aaaaaaaa"'),
            ],
        )
        client.call = AsyncMock(side_effect=_stamp_dispatch(tree))

        result = await tools["gtd_stamp_tokens"](FakeContext(), project_id="rp")
        data = result["data"]
        assert data["applied"] == []
        entry = data["projects"][0]
        assert entry["stamped"] == []
        assert entry["dep_lines"] == []
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert "rtm.tasks.notes.add" not in methods
        assert "rtm.tasks.notes.edit" not in methods

    @pytest.mark.asyncio
    async def test_not_repeating_project_skipped(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_stamp_dispatch(_repeating_tree(rrule="")))

        result = await tools["gtd_stamp_tokens"](FakeContext(), project_id="rp")
        entry = result["data"]["projects"][0]
        assert entry["skipped_reason"] == "not_repeating"
        assert entry["stamped"] == []
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert methods == {"rtm.tasks.getList"}  # nothing written

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_stamp_dispatch(_repeating_tree()))

        result = await tools["gtd_stamp_tokens"](FakeContext(), project_id="rp", dry_run=True)
        data = result["data"]
        assert data["dry_run"] is True
        assert data["applied"] == []
        entry = data["projects"][0]
        assert len(entry["stamped"]) == 2  # plan is computed
        assert len(entry["dep_lines"]) == 1
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # no writes

    @pytest.mark.asyncio
    async def test_project_id_not_found(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_stamp_dispatch(_repeating_tree()))

        result = await tools["gtd_stamp_tokens"](FakeContext(), project_id="nope")
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_sweep_selects_only_repeating_projects(self, gtd_tools):
        tools, client = gtd_tools
        # A second, one-off project (no rrule) must NOT be swept.
        oneoff = [
            _ts("tsO", "op", "One-off project", tags=["work", "project"]),
            _ts("tsOc", "301", "Child", parent="op", tags=["action"]),
        ]
        client.call = AsyncMock(side_effect=_stamp_dispatch(_repeating_tree(extra=oneoff)))

        result = await tools["gtd_stamp_tokens"](FakeContext())  # no project_id → sweep
        ids = {p["project_id"] for p in result["data"]["projects"]}
        assert ids == {"rp"}  # only the repeating project

    @pytest.mark.asyncio
    async def test_read_getlist_then_writes(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_stamp_dispatch(_repeating_tree()))

        await tools["gtd_stamp_tokens"](FakeContext(), project_id="rp")
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods[0] == "rtm.tasks.getList"  # one read first
        assert methods.count("rtm.tasks.getList") == 1


def _commit_tree_repeating():
    return _getlist(
        [
            _ts(
                "tsP",
                PROJECT_ID,
                "Recurring Project",
                parent=AREA_ID,
                tags=["personal", "project"],
                rrule="FREQ=WEEKLY",
            ),
            _ts("ts1", "c1", "Existing", parent=PROJECT_ID, tags=["action"]),
        ]
    )


class TestGtdApplyCanvasCommitRepeatingAdds:
    @pytest.mark.asyncio
    async def test_add_to_repeating_project_stamps_tmpl_child(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree_repeating(), _lists()))

        result = await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            adds=[{"type": "action", "text": "New child"}],
        )
        assert result["data"]["errors"] == []
        adds = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.notes.add"
        ]
        assert any("TMPL-CHILD" in c.kwargs.get("note_title", "") for c in adds)

    @pytest.mark.asyncio
    async def test_add_to_oneoff_project_stamps_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_commit_dispatch(_commit_tree(), _lists()))

        await tools["gtd_apply_canvas_commit"](
            FakeContext(),
            project_id=PROJECT_ID,
            adds=[{"type": "action", "text": "New child"}],
        )
        adds = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.notes.add"
        ]
        assert not any("TMPL-CHILD" in c.kwargs.get("note_title", "") for c in adds)


# ── Engage renegotiation surface (gtd_engage_seed / gtd_apply_engage_commit) ──────────────────


def _ets(ts_id, task_id, name, due="", tags=None, has_due_time="0", parent="", notes=None):
    """A taskseries dict with a configurable has_due_time (the base _ts hardcodes '0')."""
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
            "has_due_time": has_due_time,
            "completed": "",
            "deleted": "",
            "priority": "N",
            "postponed": "0",
            "estimate": "",
            "start": "",
            "has_start_time": "0",
        },
    }


def _engage_tree():
    """Overdue items across kinds + a blocked pair under a project."""
    return _getlist(
        [
            _ets("tsArea", "areaX", "Area", tags=["focus"]),
            _ets("tsP", "P", "Project", parent="areaX", tags=["personal", "project"]),
            _ets("ts1", "a1", "Soft action", due="2020-01-01", tags=["action"]),
            _ets(
                "tsHd",
                "hd",
                "Hard deadline",
                due="2020-01-01T09:00:00Z",
                has_due_time="1",
                tags=["action"],
            ),
            _ets("tsWf", "wf", "Waiting on Bob", due="2020-01-01", tags=["waiting_for"]),
            _ets("ts201", "201", "Upstream", parent="P", due="2020-01-01", tags=["action"]),
            _ets(
                "ts202",
                "202",
                "Downstream",
                parent="P",
                due="2020-01-01",
                tags=["action"],
                notes=[
                    {
                        "id": "n",
                        "created": "2026-06-01T00:00:00Z",
                        "title": "",
                        "$t": 'DEPENDS-ON\nUpstream RTM IDs:\n  task_id: "201"\n'
                        '  list_id: "' + LIST_ID + '"\nStatus: active\n',
                    }
                ],
            ),
        ]
    )


def _engage_dispatch(tree, parse_iso="2026-07-16T00:00:00Z"):
    async def _call(method, **kwargs):
        if method == "rtm.tasks.getList":
            return tree
        if method == "rtm.time.parse":
            return {"time": {"$t": parse_iso} if parse_iso else {}}
        return {"transaction": {"id": f"tx_{method.rsplit('.', 1)[-1]}", "undoable": "1"}}

    return _call


class TestGtdEngageSeed:
    @pytest.mark.asyncio
    async def test_read_only_call_surface(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        await tools["gtd_engage_seed"](FakeContext())
        methods = [c.args[0] for c in client.call.call_args_list if c.args]
        assert methods == ["rtm.tasks.getList"]  # no write, no timeline
        assert client.record_transaction.call_count == 0

    @pytest.mark.asyncio
    async def test_flags_and_suggestions(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        data = (await tools["gtd_engage_seed"](FakeContext()))["data"]
        by = {r["id"]: r for r in data["items"]}
        assert set(by) == {"a1", "hd", "wf", "201", "202"}
        assert by["hd"]["has_deadline"] is True and by["hd"]["suggested"] == "keep"
        assert by["a1"]["has_deadline"] is False and by["a1"]["suggested"] == "next_actions"
        assert by["wf"]["kind"] == "waiting_for" and by["wf"]["suggested"] == "nudge"
        assert by["202"]["blocked"] is True and by["202"]["suggested"] == "resurface"
        assert by["201"]["blocked"] is False
        assert data["current_date"]  # today stamped


_PHASE0_ARGS: dict[str, dict[str, Any]] = {
    "gtd_reassessment_candidates": {},
    "gtd_unblock_candidates": {},
    "gtd_decision_candidates": {},
    "gtd_deliverable_candidates": {},
    "gtd_research_candidates": {},
    "gtd_calendar_prep_candidates": {},
    "gtd_capture_candidates": {},
    "gtd_topic_clusters": {},
    "gtd_health_check": {},
    "gtd_query": {},
    "gtd_inbox_state": {},
    "gtd_waiting_for_queue": {},
    "gtd_context": {"task_ref": "Alpha"},
}


INBOX_ID = "51526642"


def _write_lists():
    """Both lists the Phase-1 write tools resolve."""
    base = {
        "deleted": "0",
        "locked": "0",
        "archived": "0",
        "position": "0",
        "filter": "",
        "sort_order": "0",
    }
    return {
        "lists": {
            "list": [
                {"id": LIST_ID, "name": "Processed", "smart": "0", **base},
                {"id": INBOX_ID, "name": "Inbox_Stuff", "smart": "0", **base},
            ]
        }
    }


def _write_account():
    """A project with one child — the parent a create/transition targets."""
    return _getlist(
        [
            _ts("tsP", PROJECT_ID, "Some Project", parent=AREA_ID, tags=["work", "project"]),
            _ts("ts1", "1001", "Existing action", parent=PROJECT_ID, tags=["work", "action"]),
        ]
    )


def _write_dispatch(tree, *, parsed_time="2026-08-01T09:00:00Z", new_id="new1"):
    """Route reads to the tree/lists, rtm.tasks.add to a fresh id, parse to a fixed ISO."""
    calls = {"n": 0}

    async def dispatch(method, **kwargs):
        if method == "rtm.tasks.getList":
            return tree
        if method == "rtm.lists.getList":
            return _write_lists()
        if method == "rtm.time.parse":
            return {"time": {"$t": parsed_time}} if parsed_time else {"time": {}}
        if method == "rtm.tasks.add":
            calls["n"] += 1
            return {
                "transaction": {"id": f"tx_add{calls['n']}", "undoable": "1"},
                "list": {
                    "id": kwargs.get("list_id") or LIST_ID,
                    "taskseries": {
                        "id": f"ts_{new_id}",
                        "name": kwargs.get("name", ""),
                        "created": "2026-07-23T00:00:00Z",
                        "modified": "2026-07-23T00:00:00Z",
                        "tags": [],
                        "notes": [],
                        "parent_task_id": kwargs.get("parent_task_id", ""),
                        "task": {
                            "id": new_id,
                            "due": "",
                            "completed": "",
                            "priority": "N",
                            "postponed": "0",
                            "estimate": "",
                            "start": "",
                            "has_due_time": "0",
                            "has_start_time": "0",
                            "deleted": "",
                        },
                    },
                },
            }
        return {"transaction": {"id": f"tx_{method.rsplit('.', 1)[-1]}", "undoable": "1"}}

    return dispatch


def _methods(client):
    return [c.args[0] for c in client.call.call_args_list if c.args]


def _kw_for(client, method):
    return [c.kwargs for c in client.call.call_args_list if c.args and c.args[0] == method]


class TestGtdCreateItem:
    @pytest.mark.asyncio
    async def test_creates_action_with_materialised_tags_and_true_post_state(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))

        res = await tools["gtd_create_item"](
            FakeContext(),
            parent_ref=PROJECT_ID,
            kind="action",
            name="Write the thing",
            life_context="work",
            priority="must",
            energy="low_energy",
            estimate="30 minutes",
        )
        data = res["data"]
        assert "rejected" not in data
        # TRUE post-state: the real id triple RTM returned
        assert data["task_id"] == "new1" and data["taskseries_id"] == "ts_new1"
        assert data["ready"] is True and data["deep_link"].startswith("http")
        # structural tags materialised from typed facets
        assert {"action", "work", "using_device", "low_energy", "ai_conversation"} <= set(
            data["tags"]
        )
        # created under the parent, name verbatim, SmartAdd disabled
        add = _kw_for(client, "rtm.tasks.add")[0]
        assert add["parent_task_id"] == PROJECT_ID and add["parse"] == "0"
        assert add["name"] == "Write the thing"
        # MoSCoW must -> RTM priority 1
        assert _kw_for(client, "rtm.tasks.setPriority")[0]["priority"] == "1"
        # durable orchestration signal on the nearest #project ancestor
        stamps = [
            k
            for k in _kw_for(client, "rtm.tasks.addTags")
            if k["tags"] == "ai_overlay_refresh_needed"
        ]
        assert stamps and stamps[0]["task_id"] == PROJECT_ID
        assert client.record_transaction.called

    @pytest.mark.asyncio
    async def test_create_path_issues_no_list_read(self, gtd_tools):
        """Phase 2 create-path optimisation: Processed resolves through the client's cached
        system-list set, so a governed create no longer pays an rtm.lists.getList per write."""
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        await tools["gtd_create_item"](
            FakeContext(),
            parent_ref=PROJECT_ID,
            kind="action",
            name="X",
            life_context="work",
            priority="must",
            energy="low_energy",
            estimate="5 minutes",
        )
        assert "rtm.lists.getList" not in _methods(client)
        # exactly one task read (the parent resolution) before the writes
        assert _methods(client).count("rtm.tasks.getList") == 1
        assert _methods(client)[0] == "rtm.tasks.getList"

    @pytest.mark.asyncio
    async def test_calendar_entry_carries_action_and_calendar_tag(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_create_item"](
            FakeContext(),
            parent_ref=PROJECT_ID,
            kind="calendar_entry",
            name="Board meeting",
            life_context="work",
            priority="should",
            due="1 August",
        )
        tags = set(res["data"]["tags"])
        assert {"action", "calendar_entry"} <= tags

    @pytest.mark.asyncio
    async def test_dor_gap_rejects_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_create_item"](
            FakeContext(),
            parent_ref=PROJECT_ID,
            kind="action",
            name="Half-baked",
            life_context="work",
            priority="must",  # no estimate, no energy
        )
        data = res["data"]
        assert "dor_not_met" in {r["reason"] for r in data["rejected"]}
        assert set(data["missing"]) == {"estimate", "energy"}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_off_enum_rejects_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_create_item"](
            FakeContext(),
            parent_ref=PROJECT_ID,
            kind="action",
            name="X",
            life_context="urgent",
            priority="must",
            energy="low_energy",
            estimate="5 minutes",
        )
        assert "invalid_life" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_unresolvable_due_rejects_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account(), parsed_time=None))
        res = await tools["gtd_create_item"](
            FakeContext(),
            parent_ref=PROJECT_ID,
            kind="waiting_for",
            name="Waiting for Bob",
            life_context="work",
            priority="must",
            due="the 32nd of Smarch",
        )
        assert "bad_date" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_unknown_parent_errors_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_create_item"](
            FakeContext(),
            parent_ref="no-such-parent",
            kind="action",
            name="X",
            life_context="work",
            priority="must",
            energy="low_energy",
            estimate="5 minutes",
        )
        assert res["data"]["error"]["code"] == "task_not_found"
        assert not (set(_methods(client)) & WRITE_METHODS)


class TestGtdAddNote:
    @pytest.mark.asyncio
    async def test_writes_conforming_title(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_add_note"](
            FakeContext(),
            task_ref="1001",
            note_type="PROGRESS",
            summary="did a thing",
            body="narrative",
        )
        title = res["data"]["note_title"]
        assert " — PROGRESS — did a thing" in title
        note = _kw_for(client, "rtm.tasks.notes.add")[0]
        assert note["task_id"] == "1001" and note["note_title"] == title
        assert client.record_transaction.called

    @pytest.mark.asyncio
    async def test_state_note_gets_snapshot_marker(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        await tools["gtd_add_note"](
            FakeContext(), task_ref="1001", note_type="STATE", summary="snap", body="where we are"
        )
        note = _kw_for(client, "rtm.tasks.notes.add")[0]
        assert note["note_text"].startswith("Snapshot as of: ")
        # latest-wins: the prior STATE note is never deleted
        assert "rtm.tasks.notes.delete" not in _methods(client)

    @pytest.mark.asyncio
    async def test_side_effect_note_type_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_add_note"](
            FakeContext(), task_ref="1001", note_type="DEPENDS-ON", summary="x", body=""
        )
        assert "invalid_note_type" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_bad_block_order_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_add_note"](
            FakeContext(),
            task_ref="1001",
            note_type="PROGRESS",
            summary="x",
            body="n\n--- AI Context ---\nk: v\n--- Sources ---\n- a",
        )
        assert "invalid_block_order" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)


class TestGtdCapture:
    @pytest.mark.asyncio
    async def test_captures_raw_with_source_note_and_no_classification(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_capture"](FakeContext(), text="Remember the thing")
        data = res["data"]
        assert data["list_name"] == "Inbox_Stuff" and data["task_id"] == "new1"
        # staged RAW: pipeline provenance only, no life-context / workflow-state tag
        assert data["tags"] == ["ai_conversation"]
        add = _kw_for(client, "rtm.tasks.add")[0]
        assert add["list_id"] == INBOX_ID and add["parse"] == "0"
        src = _kw_for(client, "rtm.tasks.notes.add")[0]
        assert " — SOURCE — conversational capture" in src["note_title"]
        assert src["note_text"] == "Remember the thing"

    @pytest.mark.asyncio
    async def test_pre_analysis_adds_ai_analysis_note_and_review_tag(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_capture"](
            FakeContext(),
            text="Batch remediation",
            source_type="consumer remediation",
            pre_analysis="proposed: do X",
        )
        assert set(res["data"]["tags"]) == {"ai_conversation", "ai_review"}
        titles = [k["note_title"] for k in _kw_for(client, "rtm.tasks.notes.add")]
        assert any(" — AI ANALYSIS — proposed disposition" in t for t in titles)
        assert any(" — SOURCE — consumer remediation" in t for t in titles)

    @pytest.mark.asyncio
    async def test_empty_text_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_capture"](FakeContext(), text="   ")
        assert "missing_parameter" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)


class TestGtdTransitionState:
    @pytest.mark.asyncio
    async def test_applies_transition_and_stamps_signal(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_transition_state"](
            FakeContext(), task_ref="1001", add_tags=["someday"], remove_tags=["action"]
        )
        data = res["data"]
        assert data["signal_stamped"] == "ai_overlay_refresh_needed"
        assert "someday" in data["tags"] and "action" not in data["tags"]
        assert _kw_for(client, "rtm.tasks.removeTags")[0]["tags"] == "action"
        stamps = [
            k
            for k in _kw_for(client, "rtm.tasks.addTags")
            if k["tags"] == "ai_overlay_refresh_needed"
        ]
        assert stamps and stamps[0]["task_id"] == PROJECT_ID  # nearest #project ancestor
        assert client.record_transaction.called

    @pytest.mark.asyncio
    async def test_double_workflow_state_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_transition_state"](
            FakeContext(),
            task_ref="1001",
            add_tags=["someday"],  # existing already has `action`
        )
        assert "invalid_input" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_empty_transition_rejected_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_transition_state"](FakeContext(), task_ref="1001")
        assert "missing_parameter" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_strict_tag_rejection_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(return_value={"action", "ai_conversation"})
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_transition_state"](
            FakeContext(), task_ref="1001", add_tags=["brand_new_tag"], remove_tags=["action"]
        )
        assert "strict_tag_rejected" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)


class TestGtdPhase2Writes:
    """Completion, dependency, properties, bulk — incl. the all-or-nothing bulk guarantee."""

    @pytest.mark.asyncio
    async def test_complete_action_note_before_complete(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_complete_action"](
            FakeContext(), task_ref="1001", completion="did it", cascade="project impact"
        )
        data = res["data"]
        assert data["completed"] is True and data["note_type"] == "COMPLETION"
        methods = _methods(client)
        # ordering invariant: the note is written BEFORE the completion
        assert methods.index("rtm.tasks.notes.add") < methods.index("rtm.tasks.complete")
        # CASCADE lands on the parent project
        casc = [k for k in _kw_for(client, "rtm.tasks.notes.add") if "CASCADE" in k["note_title"]]
        assert casc and casc[0]["task_id"] == PROJECT_ID
        assert data["signal_stamped"] == "ai_overlay_refresh_needed"
        assert client.record_transaction.called

    @pytest.mark.asyncio
    async def test_complete_action_returns_events_and_stamps_no_event_tags(self, gtd_tools):
        """The four fan-out signals are EVENT names, not tags — returned, never stamped."""
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts(
                    "tsW",
                    "2001",
                    "Waiting for Bob",
                    parent=PROJECT_ID,
                    tags=["work", "waiting_for"],
                ),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_complete_action"](
            FakeContext(), task_ref="2001", completion="arrived"
        )
        events = res["data"]["fanout_events"]
        assert events == ["completed", "waiting_for_resolved"]
        written_tags = " ".join(k.get("tags", "") for k in _kw_for(client, "rtm.tasks.addTags"))
        for ev in ("completed", "waiting_for_resolved", "calendar_entry_completed", "decided"):
            assert ev not in written_tags.split(",")

    @pytest.mark.asyncio
    async def test_complete_calendar_entry_requires_outcome(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts(
                    "tsC",
                    "3001",
                    "Board meeting",
                    parent=PROJECT_ID,
                    tags=["work", "action", "calendar_entry"],
                ),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_complete_action"](
            FakeContext(), task_ref="3001", completion="went well"
        )
        assert "missing_parameter" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)
        # with an outcome it writes an OUTCOME note instead of COMPLETION
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        ok = await tools["gtd_complete_action"](
            FakeContext(), task_ref="3001", outcome="Decisions: ship it"
        )
        assert ok["data"]["note_type"] == "OUTCOME"

    @pytest.mark.asyncio
    async def test_complete_resolves_review_to_approved(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts(
                    "tsA",
                    "4001",
                    "Drafted thing",
                    parent=PROJECT_ID,
                    tags=["work", "action", "ai_output_review_needed"],
                ),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_complete_action"](FakeContext(), task_ref="4001", completion="done")
        assert res["data"]["approval_transition"] is True
        assert any(
            "ai_output_approved" in k.get("tags", "") for k in _kw_for(client, "rtm.tasks.addTags")
        )
        assert any(
            "ai_output_review_needed" in k.get("tags", "")
            for k in _kw_for(client, "rtm.tasks.removeTags")
        )

    @pytest.mark.asyncio
    async def test_close_inbox_item_lists_derived_and_completes(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsI", "5001", "raw capture", tags=["ai_conversation"]),
                _ts("tsD", "5002", "Derived action", tags=["work", "action"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_close_inbox_item"](
            FakeContext(), inbox_item_ref="5001", derived_refs=["5002"]
        )
        data = res["data"]
        assert data["completed"] is True and data["derived_count"] == 1
        assert data["note_title"].endswith("— COMPLETION — Processed into GTD system")
        note = _kw_for(client, "rtm.tasks.notes.add")[0]
        assert "Derived action" in note["note_text"] and "SOURCE:" in note["note_text"]
        # completed, never deleted — it stays as the audit record
        assert "rtm.tasks.delete" not in _methods(client)

    @pytest.mark.asyncio
    async def test_close_inbox_refuses_when_derived_missing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            side_effect=_write_dispatch(_getlist([_ts("tsI", "5001", "raw capture")]))
        )
        res = await tools["gtd_close_inbox_item"](
            FakeContext(), inbox_item_ref="5001", derived_refs=["nope"]
        )
        assert "task_not_found" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_set_properties_series_guard_redirects(self, gtd_tools):
        """priority/estimate are taskseries-level — the write redirects to nearest-active."""
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts(
                    "tsR",
                    "6002",
                    "Recurring",
                    parent=PROJECT_ID,
                    tags=["work", "action"],
                    due="2026-09-01T00:00:00Z",
                ),
                _ts(
                    "tsR",
                    "6001",
                    "Recurring",
                    parent=PROJECT_ID,
                    tags=["work", "action"],
                    due="2026-08-01T00:00:00Z",
                ),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_set_properties"](FakeContext(), task_ref="6002", priority="must")
        data = res["data"]
        assert data["series_collapsed"] is True
        assert data["written_to_task_id"] == "6001"  # soonest-due open occurrence
        assert _kw_for(client, "rtm.tasks.setPriority")[0]["task_id"] == "6001"

    @pytest.mark.asyncio
    async def test_set_properties_one_off_not_redirected(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_set_properties"](FakeContext(), task_ref="1001", priority="should")
        assert res["data"]["series_collapsed"] is False
        assert _kw_for(client, "rtm.tasks.setPriority")[0]["priority"] == "2"

    @pytest.mark.asyncio
    async def test_set_properties_bad_date_rejects_without_writing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account(), parsed_time=None))
        res = await tools["gtd_set_properties"](
            FakeContext(), task_ref="1001", due="the 32nd of Smarch"
        )
        assert "bad_date" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_link_dependency_writes_conforming_note(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("tsA", "7001", "Send it", parent=PROJECT_ID, tags=["work", "action"]),
                _ts("tsB", "7002", "Draft it", parent=PROJECT_ID, tags=["work", "action"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_link_dependency"](
            FakeContext(), dependent_ref="7001", upstream_ref="7002", why="payload"
        )
        data = res["data"]
        assert data["dependent_id"] == "7001" and data["upstream_id"] == "7002"
        note = _kw_for(client, "rtm.tasks.notes.add")[0]
        # the note lands on the DEPENDENT, not the upstream
        assert note["task_id"] == "7001"
        for required in ("Depends on:", "task_id:", "taskseries_id:", "list_id:", "Status:"):
            assert required in note["note_text"]
        assert "Status: active" in note["note_text"]

    @pytest.mark.asyncio
    async def test_link_dependency_self_dep_rejected(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_write_dispatch(_write_account()))
        res = await tools["gtd_link_dependency"](
            FakeContext(), dependent_ref="1001", upstream_ref="1001", why="x"
        )
        assert "self_dep" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_batch_transition_applies_and_stamps_per_item(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("t1", "8001", "A", parent=PROJECT_ID, tags=["work", "action"]),
                _ts("t2", "8002", "B", parent=PROJECT_ID, tags=["work", "action"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_batch_transition"](
            FakeContext(), items=["8001", "8002"], add_tags=["someday"], remove_tags=["action"]
        )
        data = res["data"]
        assert data["applied_count"] == 2 and data["requested_count"] == 2
        assert all(r["signal_stamped"] == "ai_overlay_refresh_needed" for r in data["results"])
        assert len(_kw_for(client, "rtm.tasks.addTags")) >= 3  # 2 items + the project stamp

    @pytest.mark.asyncio
    async def test_batch_transition_all_or_nothing(self, gtd_tools):
        """D9: ONE invalid item ⇒ zero applied, nothing written."""
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("t1", "8001", "A", parent=PROJECT_ID, tags=["work", "action"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_batch_transition"](
            FakeContext(),
            items=["8001", "does-not-exist"],
            add_tags=["someday"],
            remove_tags=["action"],
        )
        data = res["data"]
        assert data["applied_count"] == 0 and data["results"] == []
        assert "task_not_found" in {r["reason"] for r in data["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_batch_transition_invalid_cardinality_blocks_whole_batch(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("t1", "8001", "A", parent=PROJECT_ID, tags=["work", "action"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        # adding `someday` without removing `action` would leave two workflow states
        res = await tools["gtd_batch_transition"](
            FakeContext(), items=["8001"], add_tags=["someday"]
        )
        assert res["data"]["applied_count"] == 0
        assert not (set(_methods(client)) & WRITE_METHODS)


class TestGtdPhase3ProcessOps:
    """Apply-a-reviewed-set: whole-set atomicity, once-per-project signal, bounded input."""

    @pytest.mark.asyncio
    async def test_inbox_zero_applies_mixed_verbs(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("i1", "9001", "raw one"),
                _ts("i2", "9002", "raw two"),
                _ts("i3", "9003", "raw three"),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_inbox_zero"](
            FakeContext(),
            dispositions=[
                {"item_ref": "9001", "verb": "tag", "args": {"tags": ["note"]}},
                {"item_ref": "9002", "verb": "complete"},
                {"item_ref": "9003", "verb": "leave"},
            ],
        )
        data = res["data"]
        assert data["applied_count"] == 2  # `leave` is a counted no-op
        assert data["requested_count"] == 3 and data["remaining"] == []
        assert "completed" in data["fanout_events"]
        assert any(
            k["tags"].startswith("note") or "note" in k["tags"]
            for k in _kw_for(client, "rtm.tasks.addTags")
        )
        assert client.record_transaction.called

    @pytest.mark.asyncio
    async def test_inbox_zero_one_bad_item_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            side_effect=_write_dispatch(_getlist([_ts("i1", "9001", "raw one")]))
        )
        res = await tools["gtd_inbox_zero"](
            FakeContext(),
            dispositions=[
                {"item_ref": "9001", "verb": "complete"},
                {"item_ref": "9001", "verb": "nuke"},  # illegal verb
            ],
        )
        assert res["data"]["applied_count"] == 0
        assert "invalid_input" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_inbox_zero_unresolvable_ref_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            side_effect=_write_dispatch(_getlist([_ts("i1", "9001", "raw one")]))
        )
        res = await tools["gtd_inbox_zero"](
            FakeContext(),
            dispositions=[
                {"item_ref": "9001", "verb": "complete"},
                {"item_ref": "nope", "verb": "complete"},
            ],
        )
        assert res["data"]["applied_count"] == 0
        assert "task_not_found" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_bounded_input_returns_remaining(self, gtd_tools):
        """More than the cap ⇒ apply the first N, hand the tail back for a follow-up call."""
        from rtm_mcp.gtd_writes import PROCESS_BATCH_CAP

        tools, client = gtd_tools
        n = PROCESS_BATCH_CAP + 3
        tree = _getlist([_ts(f"i{i}", str(9000 + i), f"raw {i}") for i in range(n)])
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_inbox_zero"](
            FakeContext(),
            dispositions=[{"item_ref": str(9000 + i), "verb": "leave"} for i in range(n)],
        )
        data = res["data"]
        assert data["requested_count"] == n
        assert len(data["results"]) == PROCESS_BATCH_CAP
        assert len(data["remaining"]) == 3

    @pytest.mark.asyncio
    async def test_chase_sweep_verdict_writes(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("w1", "9101", "Waiting A", parent=PROJECT_ID, tags=["work", "waiting_for"]),
                _ts("w2", "9102", "Waiting B", parent=PROJECT_ID, tags=["work", "waiting_for"]),
                _ts("w3", "9103", "Waiting C", parent=PROJECT_ID, tags=["work", "waiting_for"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_chase_sweep"](
            FakeContext(),
            verdicts=[
                {"waiting_for_ref": "9101", "verdict": "retickle", "new_due": "next monday"},
                {"waiting_for_ref": "9102", "verdict": "convert_to_action"},
                {"waiting_for_ref": "9103", "verdict": "complete"},
            ],
        )
        data = res["data"]
        assert data["applied_count"] == 3
        # retickle uses the parse_time result, not the caller's text
        due = _kw_for(client, "rtm.tasks.setDueDate")
        assert any(k["due"] == "2026-08-01T09:00:00Z" for k in due)
        # convert_to_action swaps the workflow state AND clears the tickle
        assert any("waiting_for" in k["tags"] for k in _kw_for(client, "rtm.tasks.removeTags"))
        assert any(k["due"] == "" for k in due)
        assert {"completed", "waiting_for_resolved"} <= set(data["fanout_events"])

    @pytest.mark.asyncio
    async def test_chase_sweep_bad_date_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist([_ts("w1", "9101", "Waiting A", tags=["work", "waiting_for"])])
        client.call = AsyncMock(side_effect=_write_dispatch(tree, parsed_time=None))
        res = await tools["gtd_chase_sweep"](
            FakeContext(),
            verdicts=[
                {"waiting_for_ref": "9101", "verdict": "retickle", "new_due": "the 32nd of Smarch"},
            ],
        )
        assert res["data"]["applied_count"] == 0
        assert "bad_date" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_signal_stamped_once_per_project_not_per_item(self, gtd_tools):
        """Phase 2 § 2a lesson: consolidated signal — one stamp per affected project."""
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("w1", "9101", "A", parent=PROJECT_ID, tags=["work", "waiting_for"]),
                _ts("w2", "9102", "B", parent=PROJECT_ID, tags=["work", "waiting_for"]),
                _ts("w3", "9103", "C", parent=PROJECT_ID, tags=["work", "waiting_for"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_chase_sweep"](
            FakeContext(),
            verdicts=[
                {"waiting_for_ref": r, "verdict": "complete"} for r in ("9101", "9102", "9103")
            ],
        )
        assert res["data"]["projects_signalled"] == [PROJECT_ID]
        stamps = [
            k
            for k in _kw_for(client, "rtm.tasks.addTags")
            if k.get("tags") == "ai_overlay_refresh_needed"
        ]
        assert len(stamps) == 1  # three items, ONE stamp

    @pytest.mark.asyncio
    async def test_no_fanout_event_is_written_as_a_tag(self, gtd_tools):
        """The Phase 2 guard, re-asserted for the process ops."""
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("w1", "9101", "A", parent=PROJECT_ID, tags=["work", "waiting_for"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_chase_sweep"](
            FakeContext(), verdicts=[{"waiting_for_ref": "9101", "verdict": "complete"}]
        )
        assert "completed" in res["data"]["fanout_events"]
        written = set()
        for k in _kw_for(client, "rtm.tasks.addTags"):
            written |= set(k.get("tags", "").split(","))
        for ev in ("completed", "waiting_for_resolved", "calendar_entry_completed", "decided"):
            assert ev not in written

    @pytest.mark.asyncio
    async def test_consolidate_reparent_and_link(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("a1", "9201", "Orphan", tags=["work", "action"]),
                _ts("a2", "9202", "Consumer", parent=PROJECT_ID, tags=["work", "action"]),
                _ts("a3", "9203", "Producer", parent=PROJECT_ID, tags=["work", "action"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        res = await tools["gtd_consolidate_apply"](
            FakeContext(),
            moves=[
                {"move_type": "reparent", "task_ref": "9201", "new_parent_ref": PROJECT_ID},
                {
                    "move_type": "link_dependency",
                    "dependent_ref": "9202",
                    "upstream_ref": "9203",
                    "why": "payload",
                },
            ],
        )
        data = res["data"]
        assert data["applied_count"] == 2
        rep = _kw_for(client, "rtm.tasks.setParentTask")[0]
        assert rep["task_id"] == "9201" and rep["parent_task_id"] == PROJECT_ID
        note = _kw_for(client, "rtm.tasks.notes.add")[0]
        assert note["task_id"] == "9202"  # the DEPENDENT
        for required in ("Depends on:", "task_id:", "taskseries_id:", "list_id:", "Status:"):
            assert required in note["note_text"]

    @pytest.mark.asyncio
    async def test_consolidate_self_dep_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            side_effect=_write_dispatch(_getlist([_ts("a1", "9201", "X", tags=["work", "action"])]))
        )
        res = await tools["gtd_consolidate_apply"](
            FakeContext(),
            moves=[
                {
                    "move_type": "link_dependency",
                    "dependent_ref": "9201",
                    "upstream_ref": "9201",
                    "why": "w",
                },
            ],
        )
        assert res["data"]["applied_count"] == 0
        assert "self_dep" in {r["reason"] for r in res["data"]["rejected"]}
        assert not (set(_methods(client)) & WRITE_METHODS)

    @pytest.mark.asyncio
    async def test_consolidate_promote_lifts_to_top_level(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ts("tsP", PROJECT_ID, "Proj", parent=AREA_ID, tags=["work", "project"]),
                _ts("a1", "9201", "Child", parent=PROJECT_ID, tags=["work", "action"]),
            ]
        )
        client.call = AsyncMock(side_effect=_write_dispatch(tree))
        await tools["gtd_consolidate_apply"](
            FakeContext(),
            moves=[
                {"move_type": "promote", "task_ref": "9201"},
            ],
        )
        assert _kw_for(client, "rtm.tasks.setParentTask")[0]["parent_task_id"] == ""


class TestGtdPhase0Reads:
    """Phase 0 typed read tools — read-only call surface + representative output shapes."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", sorted(_PHASE0_ARGS))
    async def test_read_only_call_surface(self, gtd_tools, tool_name):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([_ts("s", "10", "Alpha", tags=["action"])]))
        await tools[tool_name](FakeContext(), **_PHASE0_ARGS[tool_name])
        methods = {c.args[0] for c in client.call.call_args_list if c.args}
        assert methods == {"rtm.tasks.getList"}  # no write, no timeline
        assert client.record_transaction.call_count == 0

    @pytest.mark.asyncio
    async def test_decision_candidates_shape(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("t1", "1", "Decide between A and B", tags=["action"]),
                    _ts("t2", "2", "Buy milk", tags=["action"]),
                ]
            )
        )
        data = (await tools["gtd_decision_candidates"](FakeContext()))["data"]
        assert data["count"] == 1
        row = data["candidates"][0]
        assert row["name"] == "Decide between A and B"
        assert row["deep_link"].startswith("http") and row["kind"] == "action"

    @pytest.mark.asyncio
    async def test_health_check_shape(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([_ts("tp", "p", "Proj", tags=["project"])]))
        data = (await tools["gtd_health_check"](FakeContext()))["data"]
        assert data["issues"][0]["category"] == "stuck_project"
        assert data["current_date"]

    @pytest.mark.asyncio
    async def test_topic_clusters_shape(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts(f"ts{i}", str(i), f"n{i}", parent=str(i % 3), tags=["action", "acme"])
                    for i in range(5)
                ]
            )
        )
        data = (await tools["gtd_topic_clusters"](FakeContext(), threshold=5))["data"]
        assert data["count"] == 1 and data["clusters"][0]["anchor"] == "acme"

    @pytest.mark.asyncio
    async def test_query_bad_perspective_typed_error(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(return_value=_getlist([]))
        res = await tools["gtd_query"](FakeContext(), perspective="nonsense")
        assert res["data"]["error"]["code"] == "invalid_input"

    @pytest.mark.asyncio
    async def test_query_todays_field_shape(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [_ts("t1", "1", "Overdue thing", tags=["action"], due="2026-07-20T00:00:00Z")]
            )
        )
        data = (await tools["gtd_query"](FakeContext(), perspective="todays_field"))["data"]
        assert data["perspective"] == "todays_field" and data["count"] == 1

    @pytest.mark.asyncio
    async def test_inbox_state_shape(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist(
                [
                    _ts("t1", "1", "raw"),
                    _ts("t2", "2", "reviewing", tags=["ai_review"]),
                    _ts("t3", "3", "approved", tags=["ai_approved"]),
                ]
            )
        )
        data = (await tools["gtd_inbox_state"](FakeContext()))["data"]
        assert data["depth"] == 3
        assert data["unprocessed_count"] == 1
        assert data["awaiting_review_count"] == 1
        assert data["approved_unapplied_count"] == 1

    @pytest.mark.asyncio
    async def test_context_miss_typed_error(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(
            return_value=_getlist([_ts("t1", "1", "Something", tags=["action"])])
        )
        res = await tools["gtd_context"](FakeContext(), task_ref="does-not-exist")
        assert res["data"]["error"]["code"] == "task_not_found"

    @pytest.mark.asyncio
    async def test_context_bundle_shape(self, gtd_tools):
        tools, client = gtd_tools
        note = {
            "id": "n1",
            "created": "2026-07-15T00:00:00Z",
            "title": "2026-07-15 — STATE — snap",
            "$t": "b",
        }
        client.call = AsyncMock(
            return_value=_getlist([_ts("t1", "1", "My Task", tags=["action"], notes=[note])])
        )
        data = (await tools["gtd_context"](FakeContext(), task_ref="1", depth="shallow"))["data"]
        assert data["task"]["gtd_type"] == "action"
        assert data["notes"][0]["type"] == "STATE"


class TestGtdApplyEngageCommit:
    @pytest.mark.asyncio
    async def test_next_actions_clears_due(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "next_actions"}]
        )
        assert res["data"]["errors"] == []
        due_calls = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.setDueDate"
        ]
        assert due_calls and due_calls[0].kwargs["due"] == ""  # cleared
        # #ai_conversation stamped
        tag_calls = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.addTags"
        ]
        assert any("ai_conversation" in c.kwargs.get("tags", "") for c in tag_calls)

    @pytest.mark.asyncio
    async def test_today_sets_due_via_parse_time(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "today"}]
        )
        assert res["data"]["errors"] == []
        assert any(c.args[0] == "rtm.time.parse" for c in client.call.call_args_list if c.args)
        due = next(
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.setDueDate"
        )
        assert due.kwargs["due"] == "2026-07-16T00:00:00Z"  # the parse_time result, not client text

    @pytest.mark.asyncio
    async def test_someday_adds_tag_and_overlay_refresh_on_project(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "202", "verdict": "someday"}]
        )
        assert res["data"]["errors"] == []
        addtags = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.addTags"
        ]
        # someday tag on the item, overlay-refresh mark on the nearest #project ancestor (P)
        assert any("someday" in c.kwargs.get("tags", "") for c in addtags)
        assert any(
            c.kwargs.get("tags") == "ai_overlay_refresh_needed" and c.kwargs.get("task_id") == "P"
            for c in addtags
        )

    @pytest.mark.asyncio
    async def test_resurface_clears_due_and_signals(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "202", "verdict": "resurface"}]
        )
        assert res["data"]["errors"] == []
        due = next(
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.setDueDate"
        )
        assert due.kwargs["due"] == ""
        assert any(
            c.kwargs.get("tags") == "ai_overlay_refresh_needed"
            for c in client.call.call_args_list
            if c.args and c.args[0] == "rtm.tasks.addTags"
        )

    @pytest.mark.asyncio
    async def test_draft_adds_progress_tag(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "draft"}]
        )
        assert res["data"]["errors"] == []
        addtags = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.addTags"
        ]
        assert any("ai_progress_requested" in c.kwargs.get("tags", "") for c in addtags)

    @pytest.mark.asyncio
    async def test_keep_is_no_op(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "hd", "verdict": "keep"}]
        )
        assert res["data"]["errors"] == []
        writes = [c for c in client.call.call_args_list if c.args and c.args[0] in WRITE_METHODS]
        assert writes == []  # keep writes nothing

    @pytest.mark.asyncio
    async def test_drop_requires_confirm(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "drop"}]
        )
        assert res["data"]["applied"] == []
        assert any(r["reason"] == "destructive_unconfirmed" for r in res["data"]["rejected"])
        assert not any(c.args[0] in WRITE_METHODS for c in client.call.call_args_list if c.args)

    @pytest.mark.asyncio
    async def test_acl_rejects_deferring_a_hard_deadline(self, gtd_tools):
        # ACL: re-derived has_deadline (has_due_time) makes next_actions type-illegal — nothing written
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "hd", "verdict": "next_actions"}]
        )
        assert res["data"]["applied"] == []
        rej = res["data"]["rejected"][0]
        assert rej["reason"] == "type_illegal" and rej["suggestion"] == "keep"
        assert not any(c.args[0] in WRITE_METHODS for c in client.call.call_args_list if c.args)

    @pytest.mark.asyncio
    async def test_acl_rejects_off_enum(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "obliterate"}]
        )
        assert res["data"]["applied"] == []
        assert res["data"]["rejected"][0]["reason"] == "off_enum"
        assert not any(c.args[0] in WRITE_METHODS for c in client.call.call_args_list if c.args)

    @pytest.mark.asyncio
    async def test_acl_rejects_hallucinated_date(self, gtd_tools):
        # parse_time returns no $t → bad_date → whole batch rejected, nothing written
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree(), parse_iso=""))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(),
            items=[{"id": "a1", "verdict": "defer_start", "date_phrase": "the 32nd of Neveruary"}],
        )
        assert res["data"]["applied"] == []
        assert res["data"]["rejected"][0]["reason"] == "bad_date"
        assert not any(c.args[0] in WRITE_METHODS for c in client.call.call_args_list if c.args)

    @pytest.mark.asyncio
    async def test_not_found_rejects_batch(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(),
            items=[{"id": "a1", "verdict": "next_actions"}, {"id": "ghost", "verdict": "keep"}],
        )
        assert res["data"]["applied"] == []
        # v2.0.0: the bare `not_found` reason was reconciled onto the registry's
        # resolution code — one spelling for "this id is not a task in the account".
        assert any(r["reason"] == "task_not_found" for r in res["data"]["rejected"])
        assert not any(c.args[0] in WRITE_METHODS for c in client.call.call_args_list if c.args)

    @pytest.mark.asyncio
    async def test_records_transactions_for_undo(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "next_actions"}]
        )
        assert client.record_transaction.call_count >= 1

    @pytest.mark.asyncio
    async def test_strict_tag_rejection_writes_nothing(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))
        client.config = MagicMock(strict_tags=True, vault_root=None)
        # #someday is absent from the account → the gate rejects the someday commit
        client.get_account_tags = AsyncMock(return_value={"ai_conversation"})

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "someday"}]
        )
        assert res["data"]["applied"] == []
        assert any(r["reason"] == "strict_tag_rejected" for r in res["data"]["rejected"])
        assert not any(c.args[0] in WRITE_METHODS for c in client.call.call_args_list if c.args)

    # ── PROGRESS steer note (the per-item `note` — Tier 1) ──────────────────────────────────────

    @staticmethod
    def _steer_notes(client):
        return [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.notes.add"
        ]

    @pytest.mark.asyncio
    async def test_draft_with_note_attaches_steer_note(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(),
            items=[{"id": "a1", "verdict": "draft", "note": "chase Roshni re course"}],
        )
        assert res["data"]["errors"] == []
        notes = self._steer_notes(client)
        assert len(notes) == 1
        assert "— STEER — draft" in notes[0].kwargs["note_title"]
        assert notes[0].kwargs["note_text"] == "chase Roshni re course"  # pure body
        # the drafting signal still fired
        addtags = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.addTags"
        ]
        assert any("ai_progress_requested" in c.kwargs.get("tags", "") for c in addtags)
        # note write recorded a transaction (reversed by batch_undo with the verdict write)
        assert client.record_transaction.call_count >= 2

    @pytest.mark.asyncio
    async def test_do_now_with_note_attaches_note_to_self_no_progress_tag(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "do_now", "note": "just do it"}]
        )
        assert res["data"]["errors"] == []
        notes = self._steer_notes(client)
        assert len(notes) == 1
        assert "— STEER — do_now" in notes[0].kwargs["note_title"]
        # do_now has no durable tag write
        assert not any(
            c.args[0] == "rtm.tasks.addTags" for c in client.call.call_args_list if c.args
        )

    @pytest.mark.asyncio
    async def test_nudge_with_note_retickles_and_attaches_steer(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "wf", "verdict": "nudge", "note": "chase Bob"}]
        )
        assert res["data"]["errors"] == []
        due = next(
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.setDueDate"
        )
        assert due.kwargs["due"] == "2026-07-16T00:00:00Z"  # re-tickled to today
        notes = self._steer_notes(client)
        assert len(notes) == 1 and "— STEER — nudge" in notes[0].kwargs["note_title"]

    @pytest.mark.asyncio
    async def test_note_ignored_on_defer_and_guard_verdicts(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(),
            items=[
                {"id": "a1", "verdict": "today", "note": "should be ignored"},
                {"id": "hd", "verdict": "keep", "note": "also ignored"},
            ],
        )
        assert res["data"]["errors"] == []
        assert self._steer_notes(client) == []  # no note written for defer/guard verdicts

    @pytest.mark.asyncio
    async def test_oversize_note_truncated_with_warning(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "draft", "note": "x" * 700}]
        )
        assert res["data"]["errors"] == []
        notes = self._steer_notes(client)
        assert len(notes) == 1 and len(notes[0].kwargs["note_text"]) == 500
        assert any(w["warning"] == "note_truncated" for w in res["data"]["warnings"])

    @pytest.mark.asyncio
    async def test_non_string_note_dropped_gracefully(self, gtd_tools):
        tools, client = gtd_tools
        client.call = AsyncMock(side_effect=_engage_dispatch(_engage_tree()))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "draft", "note": {"not": "a string"}}]
        )
        assert res["data"]["errors"] == []
        assert self._steer_notes(client) == []  # note dropped
        assert any(w["warning"] == "note_not_string" for w in res["data"]["warnings"])
        # the verdict write still committed
        addtags = [
            c for c in client.call.call_args_list if c.args and c.args[0] == "rtm.tasks.addTags"
        ]
        assert any("ai_progress_requested" in c.kwargs.get("tags", "") for c in addtags)

    @pytest.mark.asyncio
    async def test_idempotent_recommit_does_not_duplicate_note(self, gtd_tools):
        tools, client = gtd_tools
        tree = _getlist(
            [
                _ets(
                    "ts1",
                    "a1",
                    "Soft action",
                    due="2020-01-01",
                    tags=["action"],
                    notes=[
                        {
                            "id": "s1",
                            "created": "2026-07-01T00:00:00Z",
                            "title": "",
                            "$t": "2026-07-01 09:00 — STEER — draft\nchase Bob",
                        }
                    ],
                ),
            ]
        )
        client.call = AsyncMock(side_effect=_engage_dispatch(tree))

        res = await tools["gtd_apply_engage_commit"](
            FakeContext(), items=[{"id": "a1", "verdict": "draft", "note": "chase Bob"}]
        )
        assert res["data"]["errors"] == []
        assert self._steer_notes(client) == []  # identical steer already present → skipped
        assert any("skipped, duplicate" in a["op"] for a in res["data"]["applied"])
