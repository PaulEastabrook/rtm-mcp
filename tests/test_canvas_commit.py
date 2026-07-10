"""Tests for canvas_commit — closed classifier→tag mapping + pure commit validators."""

from rtm_mcp.canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    AI_PROGRESS_DEFERRED,
    OVERLAY_REFRESH,
    classifiers_to_tags,
    collect_commit_tags,
    execute_progress_tags,
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
