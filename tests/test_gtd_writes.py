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
