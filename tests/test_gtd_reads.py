"""Unit tests for the collection/context read builders (gtd_query / inbox / waiting / context)."""

from __future__ import annotations

from typing import Any

from rtm_mcp import gtd_reads as g

TODAY = "2026-07-23"


def _t(**k: Any) -> dict[str, Any]:
    return {
        "id": k.get("id", "1"),
        "taskseries_id": k.get("taskseries_id", "s1"),
        "list_id": k.get("list_id", "L1"),
        "name": k.get("name", ""),
        "due": k.get("due"),
        "start": k.get("start"),
        "completed": k.get("completed"),
        "priority": k.get("priority", "N"),
        "tags": k.get("tags", []),
        "notes": k.get("notes", []),
        "parent_task_id": k.get("parent_task_id"),
        "modified": k.get("modified"),
    }


def _note(title: str, created: str = "2026-07-20T00:00:00Z", body: str = "b") -> dict[str, Any]:
    return {"id": "n" + title[:4], "title": title, "$t": body, "created": created}


# --------------------------------------------------------------------------- #
# parse_note_type / classify_gtd_type
# --------------------------------------------------------------------------- #


def test_parse_note_type_grammar():
    assert g.parse_note_type("2026-07-20 — STATE — snap") == ("2026-07-20", "STATE", "snap")
    assert g.parse_note_type("2026-07-20 14:30 — CHAT — me — hi")[1] == "CHAT"
    assert g.parse_note_type("freeform note") == ("", "", "freeform note")


def test_classify_gtd_type_precedence():
    assert g.classify_gtd_type(["project", "action"]) == "project"
    assert g.classify_gtd_type(["waiting_for"]) == "waiting_for"
    assert g.classify_gtd_type(["action"]) == "action"


# --------------------------------------------------------------------------- #
# gtd_query
# --------------------------------------------------------------------------- #


def test_query_next_actions_attributes_context():
    tasks = [
        _t(id="1", name="Call plumber", tags=["action", "location_home"]),
        _t(id="2", name="Reply email", tags=["action", "conversation_email"]),
        _t(id="3", name="Anything", tags=["action"]),  # default → using_device
    ]
    out = g.build_query_next_actions(tasks, context=None, timezone=None)
    ctxs = {r["id"]: r["context"] for r in out["rows"]}
    assert ctxs == {"1": "location_home", "2": "conversation_email", "3": "using_device"}


def test_query_next_actions_context_filter():
    tasks = [
        _t(id="1", name="Home", tags=["action", "location_home"]),
        _t(id="2", name="Office", tags=["action", "location_office"]),
    ]
    out = g.build_query_next_actions(tasks, context="location_home", timezone=None)
    assert [r["id"] for r in out["rows"]] == ["1"]


def test_query_todays_field_sorted():
    tasks = [
        _t(id="1", name="Later", due="2026-07-23T00:00:00Z"),
        _t(id="2", name="Overdue", due="2026-07-20T00:00:00Z"),
    ]
    out = g.build_query_todays_field(tasks, timezone=None)
    assert [r["id"] for r in out["rows"]] == ["2", "1"]


def test_query_focus_projects_attribution():
    tasks = [
        _t(id="f", name="Area", tags=["focus"]),
        _t(id="p1", name="Proj1", tags=["project"], parent_task_id="f"),
        _t(id="p2", name="Loose", tags=["project"]),
    ]
    out = g.build_query_focus_projects(tasks, focus_id=None, timezone=None)
    by = {r["id"]: r for r in out["rows"]}
    assert by["p1"]["focus"] == "Area"
    assert by["p2"]["focus"] == "(unfiled)"


def test_query_focus_projects_scoped():
    tasks = [
        _t(id="f", name="Area", tags=["focus"]),
        _t(id="p1", name="Proj1", tags=["project"], parent_task_id="f"),
        _t(id="p2", name="Other", tags=["project"], parent_task_id="g"),
    ]
    out = g.build_query_focus_projects(tasks, focus_id="f", timezone=None)
    assert [r["id"] for r in out["rows"]] == ["p1"]


# --------------------------------------------------------------------------- #
# gtd_inbox_state
# --------------------------------------------------------------------------- #


def test_inbox_state_three_signals():
    tasks = [
        _t(id="1", name="raw"),
        _t(id="2", name="reviewing", tags=["ai_review"]),
        _t(id="3", name="approved", tags=["ai_approved"]),
    ]
    out = g.build_inbox_state(tasks, timezone=None)
    assert out["depth"] == 3
    assert out["unprocessed_count"] == 1
    assert out["awaiting_review_count"] == 1
    assert out["approved_unapplied_count"] == 1


# --------------------------------------------------------------------------- #
# gtd_waiting_for_queue
# --------------------------------------------------------------------------- #


def test_waiting_for_staleness_and_sort():
    tasks = [
        _t(
            id="1",
            name="Fresh",
            tags=["waiting_for"],
            modified="2026-07-22T00:00:00Z",
            due="2026-07-30T00:00:00Z",
        ),
        _t(
            id="2",
            name="Stale",
            tags=["waiting_for"],
            modified="2026-07-01T00:00:00Z",
            due="2026-08-01T00:00:00Z",
        ),
    ]
    out = g.build_waiting_for_queue(tasks, today=TODAY, timezone=None)
    assert out["stale_count"] == 1
    # stale first
    assert [r["id"] for r in out["rows"]] == ["2", "1"]
    by = {r["id"]: r for r in out["rows"]}
    assert by["2"]["stale"] is True and by["1"]["stale"] is False


# --------------------------------------------------------------------------- #
# gtd_context
# --------------------------------------------------------------------------- #


def test_resolve_task_ref_by_id_name_and_miss():
    tasks = [_t(id="10", name="Alpha"), _t(id="11", name="Beta")]
    assert g.resolve_task_ref(tasks, "10")["task"]["id"] == "10"
    assert g.resolve_task_ref(tasks, "alpha")["task"]["id"] == "10"
    assert g.resolve_task_ref(tasks, "nope") == {}


def test_resolve_task_ref_ambiguous_candidates():
    tasks = [_t(id="1", name="Review the doc"), _t(id="2", name="Review the deck")]
    res = g.resolve_task_ref(tasks, "review")
    assert "candidates" in res and len(res["candidates"]) == 2


def test_context_bundle_state_first_and_relations():
    parent = _t(
        id="p", name="Project", tags=["project"], notes=[_note("2026-07-10 — STATE — proj snap")]
    )
    task = _t(
        id="t",
        name="Action",
        tags=["action"],
        parent_task_id="p",
        notes=[
            _note("2026-07-01 — PROGRESS — did a thing", created="2026-07-01T00:00:00Z"),
            _note("2026-07-15 — STATE — latest", created="2026-07-15T00:00:00Z"),
        ],
    )
    sibling = _t(id="s", name="Sibling", tags=["action"], parent_task_id="p")
    parsed = [parent, task, sibling]
    out = g.build_context(parsed, task, depth="medium", timezone=None)
    assert out["task"]["gtd_type"] == "action"
    # STATE note ordered first
    assert out["notes"][0]["type"] == "STATE"
    # medium → siblings + ancestors present
    assert [s["id"] for s in out["siblings"]] == ["s"]
    assert any(a["id"] == "p" for a in out["ancestors"])


def test_context_shallow_omits_relations():
    task = _t(id="t", name="A", tags=["action"], parent_task_id="p")
    parsed = [
        _t(id="p", name="P", tags=["project"]),
        task,
        _t(id="s", name="Sib", parent_task_id="p"),
    ]
    out = g.build_context(parsed, task, depth="shallow", timezone=None)
    assert out["siblings"] == []
    assert out["ancestors"] == []


def test_context_deep_includes_bodies():
    task = _t(id="t", name="A", tags=["action"], notes=[_note("2026-07-01 — DECISION — chose X")])
    out = g.build_context([task], task, depth="deep", timezone=None)
    assert out["notes"][0]["body"] == "b"  # full bodies at deep
    shallow = g.build_context([task], task, depth="shallow", timezone=None)
    assert shallow["notes"][0]["body"] == ""
