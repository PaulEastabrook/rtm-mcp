"""Tests for canvas_commit — closed classifier→tag mapping + pure commit validators."""

from rtm_mcp.canvas_commit import (
    ADD_KEYS,
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    AI_PROGRESS_DEFERRED,
    CANONICAL_TYPES,
    CLASSIFIER_KEYS,
    OVERLAY_REFRESH,
    VALID_TYPES,
    blank_text_rejection,
    classifiers_to_tags,
    collect_commit_tags,
    execute_progress_tags,
    unknown_keys,
    validate_commit,
)


class TestClassifiersToTags:
    def test_full_action_mapping_excludes_priority(self):
        tags = classifiers_to_tags(
            "action",
            {
                "context": "using_device",
                "comms": "conversation_email",
                "priority": "1",
                "quick": True,
            },
        )
        assert tags == [
            "action",
            "using_device",
            "conversation_email",
            "quick_win",
            AI_CONVERSATION,
        ]

    def test_waiting_for_minimal(self):
        assert classifiers_to_tags("waiting_for", None) == ["waiting_for", AI_CONVERSATION]

    def test_unknown_type_drops_type_tag(self):
        # bogus type yields no workflow tag (validate_commit rejects it separately)
        assert classifiers_to_tags("bogus", {}) == [AI_CONVERSATION]

    def test_noncanonical_context_dropped(self):
        tags = classifiers_to_tags("action", {"context": "made_up_context"})
        assert tags == ["action", AI_CONVERSATION]


class TestEnergyIsCarriedAsATag:
    """v6.2.0 — `energy` was accepted by callers, never read, and never reported.

    The Definition of Ready calls energy REQUIRED for an action, and `gtd_item_create` hard-gates
    it. Both canvas surfaces silently dropped it, so 17 live items landed unrated with no signal.
    It maps here rather than as a sibling key because it *is* a tag — which also means the
    strict-tag existence gate picks it up for free, since both `collect_*_tags` call this."""

    def test_high_energy_becomes_a_tag(self):
        assert "high_energy" in classifiers_to_tags("action", {"energy": "high_energy"})

    def test_low_energy_becomes_a_tag(self):
        assert "low_energy" in classifiers_to_tags("action", {"energy": "low_energy"})

    def test_energy_sits_with_its_classifier_siblings(self):
        tags = classifiers_to_tags(
            "action",
            {"context": "using_device", "comms": "conversation_email", "energy": "high_energy"},
        )
        assert tags == [
            "action",
            "using_device",
            "conversation_email",
            "high_energy",
            AI_CONVERSATION,
        ]

    def test_noncanonical_energy_dropped(self):
        assert classifiers_to_tags("action", {"energy": "medium"}) == ["action", AI_CONVERSATION]

    def test_energy_enters_the_strict_tag_gate(self):
        """The point of routing it through `classifiers_to_tags` rather than a new branch."""
        tags = collect_commit_tags(
            {"adds": [{"type": "action", "classifiers": {"energy": "high_energy"}}]}
        )
        assert "high_energy" in tags


class TestCalendarEntryIsAnAcceptedSynonym:
    """v6.2.0 — the enum divergence that cost a live 17-item plan its entire create.

    The canvas grammar says `calendar`; `gtd_item_create` says `calendar_entry`. Widening is
    additive: renaming either would break every ALREADY-RENDERED artifact board, which holds a
    frozen copy of its template and is a live caller no repo grep can see (CONTRIBUTING § 2.8)."""

    def test_both_spellings_are_valid(self):
        assert {"calendar", "calendar_entry"} <= VALID_TYPES

    def test_both_spellings_map_to_the_same_tag(self):
        assert classifiers_to_tags("calendar", None) == classifiers_to_tags("calendar_entry", None)

    def test_the_tag_is_calendar_entry_either_way(self):
        assert "calendar_entry" in classifiers_to_tags("calendar", None)

    def test_neither_spelling_is_rejected(self):
        for spelling in ("calendar", "calendar_entry"):
            result = validate_commit(
                {"adds": [{"type": spelling, "text": "Book the room"}]},
                set(),
                "p",
                processed_list_ok=True,
                confirm_destructive=False,
            )
            assert result["rejections"] == [], spelling

    def test_only_the_canonical_spelling_is_offered(self):
        """Accepted ≠ advertised — the synonym is a migration affordance, not a second way to say it."""
        assert "calendar_entry" not in CANONICAL_TYPES
        assert "calendar" in CANONICAL_TYPES

    def test_an_unknown_type_names_only_the_canonical_set(self):
        result = validate_commit(
            {"adds": [{"type": "frobnicate", "text": "x"}]},
            set(),
            "p",
            processed_list_ok=True,
            confirm_destructive=False,
        )
        detail = next(
            r["detail"] for r in result["rejections"] if r["reason"] == "unknown_add_type"
        )
        assert "calendar_entry" not in detail


class TestUnknownKeys:
    """The floor of the fix — an unrecognised key is REPORTED, never dropped."""

    def test_all_known_returns_empty(self):
        assert (
            unknown_keys({"context": "using_device", "energy": "high_energy"}, CLASSIFIER_KEYS)
            == []
        )

    def test_unknown_keys_are_returned_sorted(self):
        found = unknown_keys({"zebra": 1, "alpha": 2, "context": "using_device"}, CLASSIFIER_KEYS)
        assert found == ["alpha", "zebra"]

    def test_none_and_non_mapping_are_tolerated(self):
        assert unknown_keys(None, CLASSIFIER_KEYS) == []
        assert unknown_keys("not a dict", CLASSIFIER_KEYS) == []  # type: ignore[arg-type]

    def test_the_two_facets_that_were_lost_are_now_recognised(self):
        assert "energy" in CLASSIFIER_KEYS
        assert "estimate" in ADD_KEYS


class TestBlankTextRejection:
    def test_populated_text_passes(self):
        assert blank_text_rejection("Draft the note", index=0) is None

    def test_whitespace_only_is_rejected(self):
        assert blank_text_rejection("  ", index=0)["reason"] == "missing_name"

    def test_none_is_rejected(self):
        assert blank_text_rejection(None, index=2)["index"] == 2

    def test_detail_names_the_sibling_surfaces_key(self):
        detail = blank_text_rejection("", index=0)["detail"]
        assert "gtd_item_create" in detail and "name" in detail


class TestAddTextIsValidatedBeforeAnyWrite:
    def test_blank_add_text_rejects_the_commit(self):
        result = validate_commit(
            {"adds": [{"type": "action", "name": "keyed on the wrong field"}]},
            set(),
            "p",
            processed_list_ok=True,
            confirm_destructive=False,
        )
        assert "missing_name" in {r["reason"] for r in result["rejections"]}

    def test_a_populated_add_is_untouched(self):
        result = validate_commit(
            {"adds": [{"type": "action", "text": "Draft the note"}]},
            set(),
            "p",
            processed_list_ok=True,
            confirm_destructive=False,
        )
        assert result["rejections"] == []


class TestExecuteProgressTags:
    def test_now_and_quick_request_immediate_progress(self):
        # now/quick write ai_progress_requested; the deferred sibling is the one to drop
        assert execute_progress_tags("now") == (AI_PROGRESS, AI_PROGRESS_DEFERRED)
        assert execute_progress_tags("quick") == (AI_PROGRESS, AI_PROGRESS_DEFERRED)

    def test_later_defers_and_drops_requested(self):
        assert execute_progress_tags("later") == (AI_PROGRESS_DEFERRED, AI_PROGRESS)


class TestCollectCommitTags:
    def test_union_across_ops(self):
        ops = {
            "adds": [{"type": "action", "classifiers": {"context": "using_device"}}],
            "edits": {"x": {"comms": "conversation_phone_call"}},
            "execute": {"y": "later"},
            "notes": {"z": {"type": "CONTEXT", "text": "hi"}},
        }
        tags = collect_commit_tags(ops)
        assert {
            "action",
            "using_device",
            "conversation_phone_call",
            AI_PROGRESS,
            AI_DEFERRED,
            AI_CONVERSATION,
        } <= tags

    def test_later_execute_pulls_deferred_into_gate(self):
        assert AI_PROGRESS_DEFERRED in collect_commit_tags({"execute": {"y": "later"}})

    def test_now_only_execute_does_not_require_deferred(self):
        # backward-compat: a now/quick-only commit must NOT make the new tag a gate requirement
        tags = collect_commit_tags({"execute": {"y": "now", "z": "quick"}})
        assert AI_PROGRESS_DEFERRED not in tags
        assert {AI_PROGRESS, AI_DEFERRED, AI_CONVERSATION} <= tags

    def test_empty_ops_no_tags(self):
        assert collect_commit_tags({}) == set()

    def test_off_only_execute_gates_no_progress_tags(self):
        # "off" only REMOVES tags (never gated), so an off-only commit must not require any of the
        # progression tags to exist — only the unconditional overlay-refresh mark (actionable op).
        tags = collect_commit_tags({"execute": {"y": "off"}})
        assert {AI_PROGRESS, AI_PROGRESS_DEFERRED, AI_DEFERRED, AI_CONVERSATION}.isdisjoint(tags)
        assert OVERLAY_REFRESH in tags

    def test_mixed_off_and_set_still_gates_set_tags(self):
        # a commit mixing off + now still gates the set-mode's tags
        tags = collect_commit_tags({"execute": {"a": "off", "b": "now"}})
        assert {AI_PROGRESS, AI_DEFERRED, AI_CONVERSATION} <= tags


class TestOverlayRefreshGate:
    def test_present_for_each_actionable_op(self):
        # Piece 0b: any non-empty commit will stamp #ai_overlay_refresh_needed, so the gate must
        # include it for every actionable op kind — including completes-only / removes-only, and
        # (since DC-4) order-only, which writes the ORDER note then stamps the mark.
        for ops in (
            {"adds": [{"type": "action", "text": "x"}]},
            {"edits": {"c1": {"priority": "1"}}},
            {"execute": {"c1": "now"}},
            {"notes": {"c1": {"type": "X", "text": "y"}}},
            {"completes": ["c1"]},
            {"removes": ["c1"]},
            {"order": ["c1", "c2"]},
        ):
            assert OVERLAY_REFRESH in collect_commit_tags(ops), ops

    def test_absent_for_empty_ops(self):
        assert OVERLAY_REFRESH not in collect_commit_tags({})


PLAN_IDS = {"c1", "c2"}


def _validate(ops, *, processed=True, confirm=False):
    return validate_commit(
        ops, PLAN_IDS, "P", processed_list_ok=processed, confirm_destructive=confirm
    )


def _reasons(result):
    return {r["reason"] for r in result["rejections"]}


class TestValidateCommit:
    def test_happy_path_no_rejections(self):
        ops = {"edits": {"c1": {"priority": "1"}}, "adds": [{"type": "action", "text": "New"}]}
        assert _validate(ops, processed=True, confirm=False)["rejections"] == []

    def test_cross_project_id_rejected(self):
        ops = {"edits": {"intruder": {"priority": "1"}}}
        assert "cross_project" in _reasons(_validate(ops))

    def test_destructive_without_confirm_rejected(self):
        ops = {"completes": ["c1"]}
        assert "destructive_unconfirmed" in _reasons(_validate(ops, confirm=False))

    def test_destructive_with_confirm_ok(self):
        ops = {"completes": ["c1"]}
        assert "destructive_unconfirmed" not in _reasons(_validate(ops, confirm=True))

    def test_unknown_add_type_rejected(self):
        ops = {"adds": [{"type": "bogus", "text": "x"}]}
        assert "unknown_add_type" in _reasons(_validate(ops))

    def test_invalid_execute_value_rejected(self):
        ops = {"execute": {"c1": "soon"}}
        assert "invalid_execute" in _reasons(_validate(ops))

    def test_off_execute_value_accepted(self):
        # "off" is a valid commit-side execute value (the instant-control clear)
        assert "invalid_execute" not in _reasons(_validate({"execute": {"c1": "off"}}))

    def test_off_execute_stays_child_only(self):
        # execute (incl. "off") is not project-entity carved out — off on the project is rejected
        assert "cross_project" in _reasons(_validate({"execute": {"P": "off"}}))

    def test_smart_list_target_rejected_only_with_adds(self):
        with_adds = _validate({"adds": [{"type": "action", "text": "x"}]}, processed=False)
        assert "smart_list_target" in _reasons(with_adds)
        # no adds → the creation target is irrelevant, not rejected
        no_adds = _validate({"edits": {"c1": {"priority": "1"}}}, processed=False)
        assert "smart_list_target" not in _reasons(no_adds)

    def test_project_entity_verbs_accept_project_id(self):
        # project_id ("P") is a valid target for rename/add-project-note/complete/delete — the
        # carve-out (v1.27.0 added notes).
        ops = {
            "edits": {"P": {"text": "Renamed"}},
            "notes": {"P": {"type": "x", "text": "y"}},
            "completes": ["P"],
            "removes": ["P"],
        }
        assert _reasons(_validate(ops, confirm=True)) == set()

    def test_project_id_still_rejected_for_non_carve_ops(self):
        # execute/order stay child-only — the project is not a valid target there.
        assert "cross_project" in _reasons(_validate({"execute": {"P": "now"}}))
        assert "cross_project" in _reasons(_validate({"order": ["P"]}))
        # notes IS now carved out (v1.27.0) — a note on the project is a valid journal entry
        assert "cross_project" not in _reasons(
            _validate({"notes": {"P": {"type": "x", "text": "y"}}})
        )

    def test_carve_out_is_project_id_only(self):
        # a non-child that is NOT the project is still rejected in the carved-out maps
        assert "cross_project" in _reasons(_validate({"edits": {"intruder": {"text": "x"}}}))
