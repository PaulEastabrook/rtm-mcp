"""Pure-grammar tests for the Phase 1 write tools (gtd_writes.py).

Covers the seven Tier-1 canonical vocabularies, structural tag materialisation, the hard-gated
Definition of Ready, the note title/block grammar, and every validator rejection path.
"""

from __future__ import annotations

from rtm_mcp import gtd_writes as w


def _reasons(rejections) -> set[str]:
    return {r["reason"] for r in rejections}


# --------------------------------------------------------------------------- #
# Tier-1 vocabularies (D1)
# --------------------------------------------------------------------------- #


def test_life_contexts_include_client():
    # `client` IS canonical (a Work-domain refinement) even though gtd's DoR axis omits it.
    assert sorted(w.LIFE_CONTEXTS) == ["client", "leanworking", "personal", "work"]


def test_item_kinds_exclude_project():
    # project has its own governed tool (gtd_create_project) with a richer DoR.
    assert sorted(w.ITEM_KINDS) == ["action", "calendar_entry", "waiting_for"]
    assert "project" not in w.ITEM_KINDS


def test_workflow_states_are_the_five():
    assert sorted(w.WORKFLOW_STATES) == ["action", "focus", "project", "someday", "waiting_for"]
    # calendar_entry is a Special Tag, NOT a workflow state
    assert "calendar_entry" not in w.WORKFLOW_STATES


def test_energy_and_moscow_vocabularies():
    assert sorted(w.ENERGY_LEVELS) == ["high_energy", "low_energy"]
    assert sorted(w.MOSCOW_BANDS) == ["could", "must", "should"]
    assert w.MOSCOW_TO_PRIORITY == {"must": "1", "should": "2", "could": "3"}


def test_journal_note_types_exclude_side_effect_types():
    for t in ("DEPENDS-ON", "OUTPUT", "CHAT", "ORDER", "TMPL-CHILD", "CONTRIB"):
        assert t not in w.JOURNAL_NOTE_TYPES
    assert "STATE" in w.JOURNAL_NOTE_TYPES and "PROGRESS" in w.JOURNAL_NOTE_TYPES


# --------------------------------------------------------------------------- #
# Tag materialisation
# --------------------------------------------------------------------------- #


def test_calendar_entry_carries_action_plus_calendar_tag():
    tags = w.item_tags("calendar_entry", "work")
    assert "action" in tags and "calendar_entry" in tags


def test_action_defaults_context_and_stamps_marker():
    tags = w.item_tags("action", "work")
    assert "using_device" in tags  # documented default
    assert "ai_conversation" in tags
    assert "action" in tags


def test_waiting_for_gets_no_context_or_energy():
    tags = w.item_tags("waiting_for", "personal")
    assert not (set(tags) & set(w.ACTION_CONTEXTS))
    assert not (set(tags) & set(w.ENERGY_LEVELS))
    assert "waiting_for" in tags


def test_extra_tags_are_merged_and_sorted():
    tags = w.item_tags("action", "work", extra_tags=["quick_win", " "])
    assert "quick_win" in tags
    assert tags == sorted(tags)


def test_collect_item_tags_matches_item_tags():
    kw = {"action_context": "location_home", "energy": "low_energy"}
    assert w.collect_item_tags("action", "work", **kw) == set(w.item_tags("action", "work", **kw))


# --------------------------------------------------------------------------- #
# Definition of Ready (hard-gated)
# --------------------------------------------------------------------------- #


def test_dor_action_requires_estimate_energy_priority():
    assert set(w.check_dor("action", {"life_context": "work"})) == {
        "estimate",
        "energy",
        "priority",
    }


def test_dor_action_satisfied():
    supplied = {
        "life_context": "work",
        "estimate": "30 minutes",
        "energy": "low_energy",
        "priority": "must",
    }
    assert w.check_dor("action", supplied) == []


def test_dor_waiting_for_requires_due():
    assert w.check_dor("waiting_for", {"life_context": "work", "priority": "must"}) == ["due"]


def test_dor_calendar_entry_requires_due():
    assert w.check_dor("calendar_entry", {"life_context": "work", "priority": "could"}) == ["due"]


def test_relational_axis_is_advisory_only_for_actions():
    assert w.ADVISORY_AXES["action"] == ("relational",)
    assert "relational" not in w.REQUIRED_AXES["action"]


# --------------------------------------------------------------------------- #
# Note grammar
# --------------------------------------------------------------------------- #


def test_note_title_em_dash_form():
    assert w.format_note_title("PROGRESS", "did a thing", date="2026-07-23") == (
        "2026-07-23 — PROGRESS — did a thing"
    )
    assert w.format_note_title("STATE", "snap", date="2026-07-23", time="09:05").startswith(
        "2026-07-23 09:05 — STATE — "
    )


def test_block_order_valid_and_invalid():
    good = "narrative\n--- Sources ---\n- a\n--- AI Context ---\nk: v"
    assert w.check_block_order(good) is None
    bad = "narrative\n--- AI Context ---\nk: v\n--- Sources ---\n- a"
    assert w.check_block_order(bad) is not None
    assert w.check_block_order("just narrative") is None
    assert w.check_block_order(None) is None


def test_state_body_marker_is_idempotent():
    once = w.state_body("the state", date="2026-07-23")
    assert once.startswith("Snapshot as of: 2026-07-23")
    assert w.state_body(once, date="2026-07-23") == once


# --------------------------------------------------------------------------- #
# Validators
# --------------------------------------------------------------------------- #


def _create(**over):
    base = dict(
        kind="action",
        name="Do it",
        life_context="work",
        action_context=None,
        energy="low_energy",
        comms=None,
        priority="must",
        estimate="30 minutes",
        due=None,
        processed_ok=True,
    )
    base.update(over)
    return w.validate_create_item(**base)


def test_create_valid_has_no_rejections():
    out = _create()
    assert out["rejections"] == [] and out["missing"] == []


def test_create_rejects_off_enum_values():
    assert "invalid_input" in _reasons(_create(kind="epic")["rejections"])
    assert "invalid_life" in _reasons(_create(life_context="urgent")["rejections"])
    assert "invalid_input" in _reasons(_create(energy="medium")["rejections"])
    assert "invalid_input" in _reasons(_create(comms="carrier_pigeon")["rejections"])
    assert "invalid_input" in _reasons(_create(action_context="location_moon")["rejections"])
    assert "invalid_input" in _reasons(_create(priority="wont")["rejections"])


def test_create_rejects_missing_name():
    assert "missing_name" in _reasons(_create(name="  ")["rejections"])


def test_create_rejects_dor_gap():
    out = _create(estimate=None, energy=None)
    assert "dor_not_met" in _reasons(out["rejections"])
    assert set(out["missing"]) == {"estimate", "energy"}


def test_create_rejects_smart_processed_list():
    assert "smart_list_target" in _reasons(_create(processed_ok=False)["rejections"])


def test_add_note_rejections():
    assert "invalid_note_type" in _reasons(
        w.validate_add_note(note_type="DEPENDS-ON", summary="s", body="")
    )
    assert "missing_parameter" in _reasons(
        w.validate_add_note(note_type="PROGRESS", summary=" ", body="")
    )
    bad = "n\n--- AI Context ---\nx\n--- Sources ---\ny"
    assert "invalid_block_order" in _reasons(
        w.validate_add_note(note_type="PROGRESS", summary="s", body=bad)
    )
    assert w.validate_add_note(note_type="STATE", summary="s", body="fine") == []


def test_capture_requires_text():
    assert "missing_parameter" in _reasons(w.validate_capture(text="  "))
    assert w.validate_capture(text="something") == []


def test_transition_rejects_empty_and_overlap():
    assert "missing_parameter" in _reasons(
        w.validate_transition(add_tags=[], remove_tags=[], existing=[])
    )
    assert "invalid_input" in _reasons(
        w.validate_transition(add_tags=["someday"], remove_tags=["someday"], existing=[])
    )


def test_transition_rejects_two_workflow_states():
    out = w.validate_transition(add_tags=["someday"], remove_tags=[], existing=["action"])
    assert "invalid_input" in _reasons(out)


def test_transition_allows_swapping_workflow_state():
    out = w.validate_transition(add_tags=["someday"], remove_tags=["action"], existing=["action"])
    assert out == []


def test_transition_rejects_two_life_contexts():
    out = w.validate_transition(add_tags=["personal"], remove_tags=[], existing=["work"])
    assert "invalid_input" in _reasons(out)


def test_collect_transition_tags_includes_signals():
    got = w.collect_transition_tags(["someday"])
    assert {"someday", "ai_conversation", "ai_overlay_refresh_needed"} <= got


# --------------------------------------------------------------------------- #
# Phase 2 — completion / dependency / series guard
# --------------------------------------------------------------------------- #


def test_completion_events_guards():
    # waiting_for_resolved only for a waiting-for
    assert w.completion_events(["action"], has_outcome_note=False, decided=False) == ["completed"]
    assert "waiting_for_resolved" in w.completion_events(
        ["waiting_for"], has_outcome_note=False, decided=False
    )
    # calendar_entry_completed only when NO outcome note was filed this cycle
    assert "calendar_entry_completed" in w.completion_events(
        ["calendar_entry"], has_outcome_note=False, decided=False
    )
    assert "calendar_entry_completed" not in w.completion_events(
        ["calendar_entry"], has_outcome_note=True, decided=False
    )
    # decided only when decision-shaped
    assert "decided" in w.completion_events(["action"], has_outcome_note=False, decided=True)
    # #test items fan out nothing at all
    assert w.completion_events(["test", "waiting_for"], has_outcome_note=False, decided=False) == []


def test_fanout_events_are_events_not_tags():
    """They are progression-fanout `event:` arguments — no RTM tag by these names exists."""
    assert {
        "completed",
        "decided",
        "waiting_for_resolved",
        "calendar_entry_completed",
    } == w.FANOUT_EVENTS
    assert not (w.FANOUT_EVENTS & w.WORKFLOW_STATES)


def test_output_approval_transition_first_only():
    assert w.output_approval_transition(["ai_output_review_needed"]) == (
        ["ai_output_approved"],
        ["ai_output_review_needed"],
    )
    # already approved → no tag change (the event already fired)
    assert w.output_approval_transition(["ai_output_approved"]) == ([], [])
    assert w.output_approval_transition(["action"]) == ([], [])


def test_validate_complete_calendar_needs_outcome():
    assert "missing_parameter" in _reasons(
        w.validate_complete(kind_tags=["calendar_entry"], completion="x", outcome="")
    )
    assert w.validate_complete(kind_tags=["calendar_entry"], completion="", outcome="y") == []
    assert "missing_parameter" in _reasons(
        w.validate_complete(kind_tags=["action"], completion="", outcome="")
    )
    assert w.validate_complete(kind_tags=["action"], completion="done", outcome="") == []


def test_depends_on_note_carries_every_required_field():
    body = w.depends_on_note(
        upstream_name="Draft the spec",
        upstream_ids={"task_id": "1", "taskseries_id": "2", "list_id": "3"},
        upstream_type="action",
        why="payload",
        captured_at="2026-07-23",
    )
    for required in ("Depends on:", "task_id:", "taskseries_id:", "list_id:", "Status:"):
        assert required in body
    assert 'task_id: "1"' in body
    assert "Status: active" in body


def test_depends_on_statuses_use_resolved_not_superseded():
    # journaling-lifecycle + five runtime call sites write `resolved`; the catalogue's
    # `superseded` is stale.
    assert {"active", "resolved", "obsolete"} == w.DEPENDS_ON_STATUSES
    assert "superseded" not in w.DEPENDS_ON_STATUSES


def test_upstream_types_include_project_and_external():
    assert {"project", "external"} <= w.UPSTREAM_TYPES


def test_validate_link_dependency_rejections():
    assert "invalid_input" in _reasons(
        w.validate_link_dependency(upstream_type="nonsense", why="w", same_task=False)
    )
    assert "missing_parameter" in _reasons(
        w.validate_link_dependency(upstream_type="action", why=" ", same_task=False)
    )
    assert "self_dep" in _reasons(
        w.validate_link_dependency(upstream_type="action", why="w", same_task=True)
    )


def test_inbox_close_body_lists_derived_and_source():
    body = w.inbox_close_body(
        [{"type": "action", "name": "Do it", "url": "http://x"}],
        source_name="raw capture",
        source_url="http://s",
    )
    assert "DERIVED ITEMS CREATED:" in body
    assert '1. [action] "Do it" — RTM URL: http://x' in body
    assert 'SOURCE: Inbox_Stuff item "raw capture"' in body


# ---- series guard -------------------------------------------------------- #


def _row(i, series, due="", completed=None, repeating=False):
    return {
        "id": i,
        "taskseries_id": series,
        "due": due,
        "completed": completed,
        "is_repeating": repeating,
    }


def test_series_guard_one_off_is_identity():
    rows = [_row("9", "z")]
    assert w.collapse_write({"9": "must"}, rows) == {"9": "must"}
    assert w.divergent_band_proposals({"9": "must"}, rows) == []


def test_series_guard_collapses_to_nearest_active():
    rows = [_row("2", "s", due="2026-09-01"), _row("1", "s", due="2026-08-01")]
    # a write aimed at the LATER occurrence is redirected to the soonest-due open one
    assert w.collapse_write({"2": "must"}, rows) == {"1": "must"}


def test_series_guard_gate_single_repeating_occurrence():
    # one open occurrence, but is_repeating → still collapsible
    rows = [_row("1", "s", due="2026-08-01", repeating=True)]
    assert "s" in w.collapsible_series(rows)
    # a single non-repeating occurrence is NOT collapsible
    assert w.collapsible_series([_row("1", "s", due="2026-08-01")]) == {}


def test_series_guard_completed_rows_excluded():
    rows = [_row("1", "s", completed="2026-01-01"), _row("2", "s", due="2026-08-01")]
    assert w.collapsible_series(rows) == {}  # only one OPEN occurrence, not repeating


def test_series_guard_undated_sorts_after_dated():
    rows = [_row("2", "s"), _row("1", "s", due="2026-08-01")]
    assert w.nearest_active(rows)["id"] == "1"


def test_series_guard_divergence_surfaced_not_resolved():
    rows = [_row("1", "s", due="2026-08-01"), _row("2", "s", due="2026-09-01")]
    conflicts = w.divergent_band_proposals({"1": "must", "2": "could"}, rows)
    assert len(conflicts) == 1
    assert conflicts[0]["nearest_active_id"] == "1"
    assert conflicts[0]["chosen_band"] == "must"
    # band aliases normalise, so these do NOT diverge
    assert w.divergent_band_proposals({"1": "high", "2": "1"}, rows) == []


def test_validate_set_properties():
    assert "missing_parameter" in _reasons(
        w.validate_set_properties(priority=None, energy=None, has_any=False)
    )
    assert "invalid_input" in _reasons(
        w.validate_set_properties(priority="wont", energy=None, has_any=True)
    )
    assert w.validate_set_properties(priority="must", energy="low_energy", has_any=True) == []


# --------------------------------------------------------------------------- #
# Phase 3 — process-op verdict grammars
# --------------------------------------------------------------------------- #


def test_process_batch_cap_and_split():
    assert w.PROCESS_BATCH_CAP == 50
    head, tail = w.split_batch(list(range(60)))
    assert len(head) == 50 and len(tail) == 10
    assert w.split_batch([1, 2]) == ([1, 2], [])


def test_process_vocabularies():
    assert sorted(w.INBOX_VERBS) == ["complete", "leave", "move", "tag"]
    assert sorted(w.CHASE_VERDICTS) == ["complete", "convert_to_action", "leave", "retickle"]
    assert sorted(w.CONSOLIDATE_MOVES) == ["complete", "link_dependency", "promote", "reparent"]


def test_validate_inbox_zero_paths():
    assert w.validate_inbox_zero([{"item_ref": "1", "verb": "complete"}]) == []
    assert "missing_parameter" in _reasons(w.validate_inbox_zero([]))
    assert "invalid_input" in _reasons(w.validate_inbox_zero([{"item_ref": "1", "verb": "x"}]))
    assert "missing_parameter" in _reasons(w.validate_inbox_zero([{"verb": "complete"}]))
    # verb-specific args
    assert "missing_parameter" in _reasons(
        w.validate_inbox_zero([{"item_ref": "1", "verb": "tag"}])
    )
    assert "missing_parameter" in _reasons(
        w.validate_inbox_zero([{"item_ref": "1", "verb": "move"}])
    )
    assert (
        w.validate_inbox_zero([{"item_ref": "1", "verb": "move", "args": {"list_name": "P"}}]) == []
    )


def test_validate_chase_sweep_paths():
    assert w.validate_chase_sweep([{"waiting_for_ref": "1", "verdict": "complete"}]) == []
    assert "invalid_input" in _reasons(
        w.validate_chase_sweep([{"waiting_for_ref": "1", "verdict": "nudge"}])
    )
    # retickle must carry the new chase date
    assert "missing_parameter" in _reasons(
        w.validate_chase_sweep([{"waiting_for_ref": "1", "verdict": "retickle"}])
    )
    assert (
        w.validate_chase_sweep(
            [{"waiting_for_ref": "1", "verdict": "retickle", "new_due": "friday"}]
        )
        == []
    )


def test_validate_consolidate_paths():
    assert w.validate_consolidate([{"move_type": "complete", "task_ref": "1"}]) == []
    assert "invalid_input" in _reasons(w.validate_consolidate([{"move_type": "merge"}]))
    assert "missing_parameter" in _reasons(
        w.validate_consolidate([{"move_type": "reparent", "task_ref": "1"}])
    )
    assert "missing_parameter" in _reasons(w.validate_consolidate([{"move_type": "promote"}]))
    assert "self_dep" in _reasons(
        w.validate_consolidate(
            [
                {
                    "move_type": "link_dependency",
                    "dependent_ref": "1",
                    "upstream_ref": "1",
                    "why": "w",
                }
            ]
        )
    )
    assert "missing_parameter" in _reasons(
        w.validate_consolidate(
            [{"move_type": "link_dependency", "dependent_ref": "1", "upstream_ref": "2"}]
        )
    )  # no why
    assert (
        w.validate_consolidate(
            [
                {
                    "move_type": "link_dependency",
                    "dependent_ref": "1",
                    "upstream_ref": "2",
                    "why": "w",
                }
            ]
        )
        == []
    )
