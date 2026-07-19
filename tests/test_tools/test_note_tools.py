"""Tests for note MCP tools via mocked RTM client."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_getlist_response(
    taskseries_list: list[dict] | dict,
    list_id: str = "1",
) -> dict[str, Any]:
    return {
        "stat": "ok",
        "tasks": {"list": {"id": list_id, "taskseries": taskseries_list}},
    }


def _ts(
    ts_id: str = "10",
    task_id: str = "100",
    name: str = "Test Task",
    notes: Any = None,
) -> dict[str, Any]:
    return {
        "id": ts_id,
        "created": "2026-01-01T00:00:00Z",
        "modified": "2026-01-01T00:00:00Z",
        "name": name,
        "source": "api",
        "url": "",
        "location_id": "",
        "parent_task_id": "",
        "tags": [],
        "participants": [],
        "notes": notes if notes is not None else [],
        "task": {
            "id": task_id,
            "due": "",
            "has_due_time": "0",
            "added": "2026-01-01T00:00:00Z",
            "completed": "",
            "deleted": "",
            "priority": "N",
            "postponed": "0",
            "estimate": "",
            "start": "",
            "has_start_time": "0",
        },
    }


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


@pytest.fixture
def note_tools(mock_client):
    mcp = FakeMCP()
    from rtm_mcp.tools.notes import register_note_tools

    async def get_client():
        return mock_client

    register_note_tools(mcp, get_client)
    return mcp.tools, mock_client


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.call = AsyncMock()
    client.record_transaction = MagicMock()
    type(client).timeline_id = PropertyMock(return_value="tl_test")
    return client


# ---------------------------------------------------------------------------
# Tests: add_note
# ---------------------------------------------------------------------------


class TestAddNote:
    @pytest.mark.asyncio
    async def test_add_note_by_ids(self, note_tools):
        tools, client = note_tools
        add_resp = {
            "stat": "ok",
            "transaction": {"id": "tx1", "undoable": "1"},
            "note": {
                "id": "n1",
                "title": "My Title",
                "$t": "Note body",
                "created": "2026-01-01T00:00:00Z",
            },
        }
        client.call = AsyncMock(return_value=add_resp)

        result = await tools["add_note"](
            FakeContext(),
            note_text="Note body",
            note_title="My Title",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert result["data"]["note"]["id"] == "n1"
        assert result["data"]["note"]["body"] == "Note body"
        assert result["data"]["note"]["title"] == "My Title"
        assert result["metadata"]["transaction_id"] == "tx1"

    @pytest.mark.asyncio
    async def test_add_note_by_name(self, note_tools):
        tools, client = note_tools
        find_resp = _make_getlist_response([_ts(name="Buy milk")])
        add_resp = {
            "stat": "ok",
            "transaction": {"id": "tx2", "undoable": "1"},
            "note": {"id": "n2", "$t": "Remember oat milk", "created": "2026-01-01"},
        }
        client.call = AsyncMock(side_effect=[find_resp, add_resp])

        result = await tools["add_note"](
            FakeContext(),
            note_text="Remember oat milk",
            task_name="Buy milk",
        )
        assert result["data"]["message"] == "Note added"

    @pytest.mark.asyncio
    async def test_add_note_task_not_found(self, note_tools):
        tools, client = note_tools
        client.call = AsyncMock(return_value=_make_getlist_response([]))

        result = await tools["add_note"](
            FakeContext(),
            note_text="body",
            task_name="Nonexistent",
        )
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_add_note_missing_ids(self, note_tools):
        tools, _client = note_tools
        result = await tools["add_note"](
            FakeContext(),
            note_text="body",
            task_id="100",
        )
        assert "error" in result["data"]


# ---------------------------------------------------------------------------
# Tests: edit_note
# ---------------------------------------------------------------------------


class TestEditNote:
    @pytest.mark.asyncio
    async def test_edit_note(self, note_tools):
        tools, client = note_tools
        edit_resp = {
            "stat": "ok",
            "transaction": {"id": "tx3", "undoable": "1"},
            "note": {"id": "n1", "title": "Updated", "$t": "New body", "modified": "2026-01-02"},
        }
        client.call = AsyncMock(return_value=edit_resp)

        result = await tools["edit_note"](
            FakeContext(),
            note_id="n1",
            note_text="New body",
            note_title="Updated",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert result["data"]["note"]["body"] == "New body"
        assert result["data"]["message"] == "Note updated"

    @pytest.mark.asyncio
    async def test_edit_note_body_field_fallback(self, note_tools):
        """RTM may return 'body' instead of '$t'."""
        tools, client = note_tools
        edit_resp = {
            "stat": "ok",
            "transaction": {"id": "tx4", "undoable": "1"},
            "note": {"id": "n1", "body": "Fallback body", "modified": "2026-01-02"},
        }
        client.call = AsyncMock(return_value=edit_resp)

        result = await tools["edit_note"](
            FakeContext(),
            note_id="n1",
            note_text="Fallback body",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert result["data"]["note"]["body"] == "Fallback body"


# ---------------------------------------------------------------------------
# Tests: delete_note
# ---------------------------------------------------------------------------


class TestDeleteNote:
    @pytest.mark.asyncio
    async def test_delete_note(self, note_tools):
        tools, client = note_tools
        del_resp = {
            "stat": "ok",
            "transaction": {"id": "tx5", "undoable": "1"},
        }
        client.call = AsyncMock(return_value=del_resp)

        result = await tools["delete_note"](
            FakeContext(),
            note_id="n1",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert result["data"]["message"] == "Note deleted"
        assert result["metadata"]["transaction_id"] == "tx5"

    @pytest.mark.asyncio
    async def test_delete_note_task_not_found(self, note_tools):
        tools, client = note_tools
        client.call = AsyncMock(return_value=_make_getlist_response([]))

        result = await tools["delete_note"](
            FakeContext(),
            note_id="n1",
            task_name="Missing",
        )
        assert "error" in result["data"]


# ---------------------------------------------------------------------------
# Tests: get_task_notes
# ---------------------------------------------------------------------------


class TestGetTaskNotes:
    @pytest.mark.asyncio
    async def test_get_notes_by_name(self, note_tools):
        tools, client = note_tools
        notes_data = [
            {"id": "n1", "title": "Note 1", "$t": "Body 1", "created": "2026-01-01"},
            {"id": "n2", "title": "", "$t": "Body 2", "created": "2026-01-02"},
        ]
        resp = _make_getlist_response([_ts(name="My Task", notes={"note": notes_data})])
        client.call = AsyncMock(return_value=resp)

        result = await tools["get_task_notes"](FakeContext(), task_name="My Task")
        assert result["data"]["count"] == 2
        assert result["data"]["notes"][0]["body"] == "Body 1"
        assert result["data"]["task_name"] == "My Task"

    @pytest.mark.asyncio
    async def test_get_notes_by_ids(self, note_tools):
        tools, client = note_tools
        notes_data = {"id": "n1", "title": "Solo", "$t": "Content", "created": "2026-01-01"}
        resp = _make_getlist_response([_ts(notes={"note": notes_data})])
        client.call = AsyncMock(return_value=resp)

        result = await tools["get_task_notes"](
            FakeContext(),
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_get_notes_empty(self, note_tools):
        tools, client = note_tools
        resp = _make_getlist_response([_ts(notes=[])])
        client.call = AsyncMock(return_value=resp)

        result = await tools["get_task_notes"](FakeContext(), task_name="Test Task")
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_get_notes_task_not_found(self, note_tools):
        tools, client = note_tools
        client.call = AsyncMock(return_value=_make_getlist_response([]))

        result = await tools["get_task_notes"](FakeContext(), task_name="Nope")
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_get_notes_missing_ids(self, note_tools):
        tools, _client = note_tools
        result = await tools["get_task_notes"](FakeContext(), task_id="100")
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_get_notes_single_note_as_dict(self, note_tools):
        """RTM returns a single note as dict, not a list."""
        tools, client = note_tools
        # RTM wraps notes under {"note": {...}} for single, {"note": [...]} for multiple
        single_note = {"note": {"id": "n1", "title": "T", "$t": "B", "created": "2026-01-01"}}
        resp = _make_getlist_response([_ts(notes=single_note)])
        client.call = AsyncMock(return_value=resp)

        result = await tools["get_task_notes"](FakeContext(), task_name="Test Task")
        assert result["data"]["count"] == 1


class TestGetTaskNotesCompletedByName:
    @pytest.mark.asyncio
    async def test_name_lookup_spans_completed_tasks(self, note_tools):
        # Regression: the name path used to search incomplete-only, so a
        # completed task's notes were readable by IDs but "not found" by name.
        tools, client = note_tools
        notes_data = {"id": "n1", "title": "", "$t": "Done note", "created": "2026-01-01"}
        ts = _ts(name="Shipped Task", notes={"note": notes_data})
        ts["task"]["completed"] = "2026-06-01T10:00:00Z"
        resp = _make_getlist_response([ts])
        client.call = AsyncMock(return_value=resp)

        result = await tools["get_task_notes"](FakeContext(), task_name="Shipped Task")
        assert result["data"]["count"] == 1
        # include_completed lookup ⇒ the getList carries no status filter.
        lookup_call = client.call.call_args_list[0]
        assert lookup_call.args[0] == "rtm.tasks.getList"
        assert "filter" not in lookup_call.kwargs


# ---------------------------------------------------------------------------
# Tests: the note-shape write-boundary gate (RTM_STRICT_NOTES)
# ---------------------------------------------------------------------------


class TestNoteShapeGate:
    """Three paths per the write-gate contract: accept, reject, flag-off inert.

    The gate rejects BEFORE the task lookup, so a rejection costs zero API calls —
    asserted explicitly (a gate that still hits RTM is not a write boundary).
    """

    @staticmethod
    def _shape_mode(client, mode="shape"):
        client.config = MagicMock(strict_notes=mode)

    @pytest.fixture
    def add_resp(self):
        return {
            "stat": "ok",
            "transaction": {"id": "tx1", "undoable": "1"},
            "note": {"id": "n1", "title": "t", "$t": "body", "created": "2026-01-01"},
        }

    @pytest.mark.asyncio
    async def test_well_formed_title_is_accepted(self, note_tools, add_resp):
        tools, client = note_tools
        self._shape_mode(client)
        client.call = AsyncMock(return_value=add_resp)

        result = await tools["add_note"](
            FakeContext(),
            note_text="body",
            note_title="2026-07-19 — OUTPUT — brief drafted",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert "error" not in result["data"]
        assert client.call.await_count == 1

    @pytest.mark.asyncio
    async def test_malformed_title_is_rejected_without_writing(self, note_tools):
        tools, client = note_tools
        self._shape_mode(client)
        client.call = AsyncMock()

        result = await tools["add_note"](
            FakeContext(),
            note_text="body",
            note_title="just a heading",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        error = result["data"]["error"]
        assert error["code"] == "note_shape_rejected"
        assert error["details"]["rejected_title"] == "just a heading"
        client.call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_gate_off_allows_a_malformed_title(self, note_tools, add_resp):
        """Flags-off must reproduce pre-gate behaviour exactly — the reversibility
        guarantee that makes the bake-in stage safe."""
        tools, client = note_tools
        self._shape_mode(client, "off")
        client.call = AsyncMock(return_value=add_resp)

        result = await tools["add_note"](
            FakeContext(),
            note_text="body",
            note_title="just a heading",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert "error" not in result["data"]
        assert client.call.await_count == 1

    @pytest.mark.asyncio
    async def test_warn_mode_logs_but_writes(self, note_tools, add_resp, caplog):
        tools, client = note_tools
        self._shape_mode(client, "warn")
        client.call = AsyncMock(return_value=add_resp)

        with caplog.at_level("INFO"):
            result = await tools["add_note"](
                FakeContext(),
                note_text="body",
                note_title="just a heading",
                task_id="100",
                taskseries_id="10",
                list_id="1",
            )
        assert "error" not in result["data"]
        assert client.call.await_count == 1
        assert "strict_notes(warn)" in caplog.text

    @pytest.mark.asyncio
    async def test_title_in_body_is_gated_when_no_title_given(self, note_tools):
        """RTM stores the body as `title\\ntext`, so an inline-grammar author is
        still judged — otherwise the gate would be trivially bypassable."""
        tools, client = note_tools
        self._shape_mode(client)
        client.call = AsyncMock()

        result = await tools["add_note"](
            FakeContext(),
            note_text="not a title line\nthen the body",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert result["data"]["error"]["code"] == "note_shape_rejected"
        client.call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_edit_note_gates_a_title_change(self, note_tools):
        tools, client = note_tools
        self._shape_mode(client)
        client.call = AsyncMock()

        result = await tools["edit_note"](
            FakeContext(),
            note_id="n1",
            note_text="new body",
            note_title="rewritten heading",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert result["data"]["error"]["code"] == "note_shape_rejected"
        client.call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_legacy_body_only_edit_is_never_blocked(self, note_tools):
        """THE legacy-safety invariant (hand-off brief § 4). A note whose title
        predates the grammar must stay editable: an edit that supplies no
        note_title is a body-only edit and is not judged, even in shape mode.
        Without this, the gate would strand every pre-grammar note."""
        tools, client = note_tools
        self._shape_mode(client)
        client.call = AsyncMock(
            return_value={
                "stat": "ok",
                "transaction": {"id": "tx1", "undoable": "1"},
                "note": {"id": "n1", "title": "", "$t": "corrected", "modified": "2026-07-19"},
            }
        )

        result = await tools["edit_note"](
            FakeContext(),
            note_id="n1",
            note_text="Some ancient untitled note\ncorrected body text",
            task_id="100",
            taskseries_id="10",
            list_id="1",
        )
        assert "error" not in result["data"]
        assert client.call.await_count == 1
