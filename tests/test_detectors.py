"""Faithful-port unit tests for the detector builders (ports of the *-candidates.ms scripts).

Each test pins the selection + fields the corresponding MilkScript produces, so a divergence from
the reference logic fails here.
"""

from __future__ import annotations

from typing import Any

from rtm_mcp import detectors as d

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


def _note(title: str, body: str = "") -> dict[str, Any]:
    return {"id": "n", "title": title, "$t": body}


# --------------------------------------------------------------------------- #
# reassessment
# --------------------------------------------------------------------------- #


def test_reassessment_selects_and_tags_contrib_prep():
    contrib = [_t(id="1", name="A", tags=["ai_contrib_drafted"], modified="2026-07-01T00:00:00Z")]
    prep = [_t(id="2", name="B", tags=["ai_prep_drafted"], modified="2026-07-02T00:00:00Z")]
    out = d.build_reassessment_candidates(contrib, prep, today=TODAY)
    assert out["count"] == 2
    by = {c["id"]: c for c in out["candidates"]}
    assert by["1"]["tag_set"] == ["CONTRIB"]
    assert by["2"]["tag_set"] == ["PREP"]
    # sorted oldest-modified first
    assert [c["id"] for c in out["candidates"]] == ["1", "2"]


def test_reassessment_skips_personal_without_optin():
    contrib = [
        _t(
            id="1",
            name="P",
            tags=["ai_contrib_drafted", "personal"],
            modified="2026-07-01T00:00:00Z",
        )
    ]
    out = d.build_reassessment_candidates(contrib, [], today=TODAY)
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "personal life-context, not opted in"


def test_reassessment_skips_recently_modified():
    contrib = [
        _t(id="1", name="Fresh", tags=["ai_contrib_drafted"], modified="2026-07-23T00:00:00Z")
    ]
    out = d.build_reassessment_candidates(contrib, [], stale_threshold_days=1, today=TODAY)
    assert out["count"] == 0
    assert "stale threshold" in out["skipped"][0]["reason"]


def test_reassessment_dedups_by_id():
    row = _t(
        id="1",
        name="Both",
        tags=["ai_contrib_drafted", "ai_prep_drafted"],
        modified="2026-07-01T00:00:00Z",
    )
    out = d.build_reassessment_candidates([row], [row], today=TODAY)
    assert out["count"] == 1
    assert out["candidates"][0]["tag_set"] == ["CONTRIB", "PREP"]


# --------------------------------------------------------------------------- #
# unblock
# --------------------------------------------------------------------------- #


def test_unblock_source_classes_and_dedup_precedence():
    shared = _t(
        id="1",
        name="Shared",
        tags=["ai_deferred_pending_unblock", "waiting_for"],
        due="2026-07-01T00:00:00Z",
    )
    class_results = {
        "ai_deferred_pending_unblock": [shared],
        "waiting_for_overdue": [shared],
        "blocker_note_active": [],
        "depends_on_active": [],
        "speculative_stale": [],
    }
    out = d.build_unblock_candidates(class_results, today=TODAY)
    assert out["count"] == 1
    assert out["candidates"][0]["source_class"] == "ai_deferred_pending_unblock"  # precedence


def test_unblock_blocker_note_requires_active_title():
    active = _t(
        id="1",
        name="Blocked",
        tags=["action"],
        notes=[_note("2026-07-01 — BLOCKER — waiting on X")],
    )
    resolved = _t(
        id="2", name="Clear", tags=["action"], notes=[_note("2026-07-01 — BLOCKER-RESOLVED — done")]
    )
    class_results = {
        "ai_deferred_pending_unblock": [],
        "waiting_for_overdue": [],
        "blocker_note_active": [active, resolved],
        "depends_on_active": [],
        "speculative_stale": [],
    }
    out = d.build_unblock_candidates(class_results, today=TODAY)
    assert [c["id"] for c in out["candidates"]] == ["1"]


def test_unblock_disqualifying_tag_skipped():
    row = _t(id="1", name="X", tags=["ai_deferred_pending_unblock", "someday"])
    class_results = {"ai_deferred_pending_unblock": [row]}
    out = d.build_unblock_candidates(class_results, today=TODAY)
    assert out["count"] == 0
    assert out["skipped"][0]["reason"] == "disqualifying tag"


def test_unblock_cap_applied_last():
    rows = [_t(id=str(i), name=f"n{i}", tags=["ai_deferred_pending_unblock"]) for i in range(5)]
    out = d.build_unblock_candidates(
        {"ai_deferred_pending_unblock": rows}, max_candidates=2, today=TODAY
    )
    assert out["count"] == 2


def test_unblock_speculative_stale_gate():
    fresh = _t(id="1", name="fresh", tags=["ai_speculative"], modified="2026-07-23T00:00:00Z")
    stale = _t(id="2", name="stale", tags=["ai_speculative"], modified="2026-07-01T00:00:00Z")
    cr = {"speculative_stale": [fresh, stale]}
    out = d.build_unblock_candidates(cr, stale_speculative_days=14, today=TODAY)
    assert [c["id"] for c in out["candidates"]] == ["2"]


# --------------------------------------------------------------------------- #
# decision / deliverable / research (shared lexical skeleton)
# --------------------------------------------------------------------------- #


def test_decision_matches_and_anti_pattern():
    tasks = [
        _t(id="1", name="Decide between A and B", tags=["action"]),
        _t(id="2", name="Decide whether to email Bob", tags=["action"]),  # decision + anti (email)
        _t(id="3", name="Buy milk", tags=["action"]),  # no match, silent
    ]
    out = d.build_decision_candidates(tasks, today=TODAY)
    assert [c["id"] for c in out["candidates"]] == ["1"]
    assert any(s["reason"].startswith("matched anti-pattern") for s in out["skipped"])


def test_decision_personal_optin_tag():
    tasks = [_t(id="1", name="Decide on X", tags=["action", "personal"])]
    assert d.build_decision_candidates(tasks, today=TODAY)["count"] == 0
    tasks2 = [_t(id="1", name="Decide on X", tags=["action", "personal", "ai_decide_optin"])]
    assert d.build_decision_candidates(tasks2, today=TODAY)["count"] == 1


def test_deliverable_matches_draft_shapes():
    tasks = [
        _t(id="1", name="Draft the spec", tags=["action"]),
        _t(id="2", name="Research the market", tags=["action"]),  # anti + non-match
    ]
    out = d.build_deliverable_candidates(tasks, today=TODAY)
    assert [c["id"] for c in out["candidates"]] == ["1"]


def test_research_default_horizon_active():
    # research defaults horizon_days=2 → the date filter is active; an undated item is out.
    tasks = [_t(id="1", name="Investigate the options", tags=["action"])]
    assert d.build_research_candidates(tasks, today=TODAY)["count"] == 0
    # horizon_days=0 disables it
    assert d.build_research_candidates(tasks, horizon_days=0, today=TODAY)["count"] == 1


def test_lexical_exclude_drafted():
    tasks = [_t(id="1", name="Decide on X", tags=["action", "ai_contrib_drafted"])]
    assert d.build_decision_candidates(tasks, today=TODAY)["count"] == 0
    assert d.build_decision_candidates(tasks, exclude_drafted=False, today=TODAY)["count"] == 1


def test_lexical_sorted_by_effective_date():
    tasks = [
        _t(id="1", name="Decide A", tags=["action"], due="2026-08-02T00:00:00Z"),
        _t(id="2", name="Decide B", tags=["action"], due="2026-07-25T00:00:00Z"),
        _t(id="3", name="Decide C", tags=["action"]),  # no date → last
    ]
    out = d.build_decision_candidates(tasks, today=TODAY)
    assert [c["id"] for c in out["candidates"]] == ["2", "1", "3"]
    assert out["candidates"][-1]["date"] == ""


# --------------------------------------------------------------------------- #
# calendar-prep
# --------------------------------------------------------------------------- #


def test_calendar_prep_horizon_window_and_time():
    tasks = [
        _t(id="1", name="Board meeting", tags=["calendar_entry"], due="2026-07-24T09:30:00Z"),
        _t(id="2", name="Far off", tags=["calendar_entry"], due="2026-09-01T09:00:00Z"),
    ]
    out = d.build_calendar_prep_candidates(tasks, today=TODAY)
    assert [c["id"] for c in out["candidates"]] == ["1"]
    assert out["candidates"][0]["time"] == "09:30"


def test_calendar_prep_zero_treated_as_two():
    out = d.build_calendar_prep_candidates([], horizon_days=0, today=TODAY)
    assert out["horizon_days"] == 2


# --------------------------------------------------------------------------- #
# capture
# --------------------------------------------------------------------------- #


def test_capture_window_and_status_and_desc_sort():
    incomplete = [
        [_t(id="1", name="new", tags=["ai_contrib_drafted"], modified="2026-07-22T00:00:00Z")]
    ]
    completed = [
        [
            _t(
                id="2",
                name="done",
                tags=["ai_prep_drafted"],
                completed="2026-07-20T00:00:00Z",
                modified="2026-07-20T00:00:00Z",
            )
        ]
    ]
    out = d.build_capture_candidates(incomplete, completed, window_days=7, today=TODAY)
    assert out["count"] == 2
    # newest-modified first
    assert [c["id"] for c in out["candidates"]] == ["1", "2"]
    by = {c["id"]: c for c in out["candidates"]}
    assert by["2"]["status"] == "completed"


def test_capture_window_cutoff():
    incomplete = [
        [_t(id="1", name="old", tags=["ai_contrib_drafted"], modified="2026-07-01T00:00:00Z")]
    ]
    out = d.build_capture_candidates(incomplete, [], window_days=7, today=TODAY)
    assert out["count"] == 0


# --------------------------------------------------------------------------- #
# topic-cluster
# --------------------------------------------------------------------------- #


def test_topic_cluster_threshold_and_projects():
    rows = [
        _t(id=str(i), name=f"n{i}", tags=["action", "acme"], parent_task_id=str(i % 3))
        for i in range(5)
    ]
    out = d.build_topic_clusters(rows, threshold=5)
    assert out["count"] == 1
    c = out["clusters"][0]
    assert c["anchor"] == "acme"
    assert c["anchor_type"] == "person"  # all-lowercase 3-12
    assert c["item_count"] == 5
    assert c["distinct_projects"] == 3


def test_topic_cluster_requires_two_projects():
    rows = [_t(id=str(i), name="n", tags=["action", "acme"], parent_task_id="p") for i in range(6)]
    assert d.build_topic_clusters(rows, threshold=5)["count"] == 0  # only 1 project


def test_topic_cluster_trivial_tags_never_anchor():
    rows = [
        _t(id=str(i), name="n", tags=["action", "work"], parent_task_id=str(i)) for i in range(6)
    ]
    assert d.build_topic_clusters(rows, threshold=5)["count"] == 0  # 'work'/'action' trivial


def test_topic_cluster_workflow_state_gate():
    rows = [
        _t(id=str(i), name="n", tags=["acme"], parent_task_id=str(i)) for i in range(6)
    ]  # no workflow state
    assert d.build_topic_clusters(rows, threshold=5)["count"] == 0


# --------------------------------------------------------------------------- #
# health-check
# --------------------------------------------------------------------------- #


def test_health_stuck_project():
    tasks = [_t(id="p", name="Proj", tags=["project"])]
    out = d.build_health_check(tasks, today=TODAY)
    assert out["issues"][0]["category"] == "stuck_project"


def test_health_project_with_next_action_ok():
    tasks = [
        _t(id="p", name="Proj", tags=["project"]),
        _t(id="c", name="Do it", tags=["action"], parent_task_id="p"),
    ]
    cats = [i["category"] for i in d.build_health_check(tasks, today=TODAY)["issues"]]
    assert "stuck_project" not in cats


def test_health_missing_context_and_state_subtask_only():
    tasks = [_t(id="c", name="Orphan", tags=[], parent_task_id="p")]
    cats = {i["category"] for i in d.build_health_check(tasks, today=TODAY)["issues"]}
    assert "missing_life_context" in cats
    assert "missing_workflow_state" in cats


def test_health_stale_waiting_for_not_subtask_gated():
    tasks = [_t(id="w", name="Waiting", tags=["waiting_for"], modified="2026-07-01T00:00:00Z")]
    cats = {i["category"] for i in d.build_health_check(tasks, today=TODAY)["issues"]}
    assert "stale_waiting_for" in cats


def test_health_action_with_due_date():
    tasks = [_t(id="a", name="Timed", tags=["action"], due="2026-07-30T00:00:00Z")]
    cats = {i["category"] for i in d.build_health_check(tasks, today=TODAY)["issues"]}
    assert "action_with_due_date" in cats
