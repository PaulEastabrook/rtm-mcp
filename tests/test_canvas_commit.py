"""Tests for canvas_commit — closed classifier→tag mapping + pure commit validators."""

from rtm_mcp.canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    classifiers_to_tags,
    collect_commit_tags,
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

    def test_empty_ops_no_tags(self):
        assert collect_commit_tags({}) == set()


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

    def test_smart_list_target_rejected_only_with_adds(self):
        with_adds = _validate({"adds": [{"type": "action", "text": "x"}]}, processed=False)
        assert "smart_list_target" in _reasons(with_adds)
        # no adds → the creation target is irrelevant, not rejected
        no_adds = _validate({"edits": {"c1": {"priority": "1"}}}, processed=False)
        assert "smart_list_target" not in _reasons(no_adds)
