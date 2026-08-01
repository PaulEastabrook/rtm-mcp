"""Tests for canvas_create — the pure validators + tag collector for gtd_project_create."""

from rtm_mcp.canvas_commit import (
    ADD_KEYS,
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    AI_PROGRESS_DEFERRED,
)
from rtm_mcp.canvas_create import (
    FINALISE_MARK,
    ITEM_KEYS,
    PROJECT_TAG,
    collect_create_tags,
    item_id,
    project_tags,
    validate_create,
)


def _reasons(result):
    return {r["reason"] for r in result["rejections"]}


class TestItemId:
    def test_explicit_id_wins(self):
        assert item_id({"id": "abc"}, 3) == "abc"

    def test_missing_id_falls_back_to_index(self):
        assert item_id({}, 2) == "2"

    def test_empty_id_falls_back_to_index(self):
        assert item_id({"id": ""}, 5) == "5"


class TestProjectTags:
    def test_with_life(self):
        assert project_tags("personal") == ["personal", PROJECT_TAG, AI_CONVERSATION, FINALISE_MARK]

    def test_without_life(self):
        assert project_tags(None) == [PROJECT_TAG, AI_CONVERSATION, FINALISE_MARK]

    def test_finalise_mark_value(self):
        assert FINALISE_MARK == "ai_project_needs_finalise"


class TestCollectCreateTags:
    def test_project_tags_always_present(self):
        tags = collect_create_tags({"life": "work"}, [])
        assert {"work", PROJECT_TAG, AI_CONVERSATION, FINALISE_MARK} <= tags

    def test_item_classifier_tags_included(self):
        tags = collect_create_tags(
            {"life": "personal"},
            [{"type": "action", "classifiers": {"context": "using_device", "quick": True}}],
        )
        assert {"action", "using_device", "quick_win"} <= tags

    def test_later_execute_pulls_deferred_into_gate(self):
        tags = collect_create_tags(
            {"life": "work"}, [{"type": "action", "text": "x", "execute": "later"}]
        )
        assert AI_PROGRESS_DEFERRED in tags
        assert {AI_PROGRESS, AI_DEFERRED, AI_CONVERSATION} <= tags

    def test_now_only_execute_does_not_require_deferred(self):
        # backward-compat: a now/quick-only create must NOT require the new deferred tag to exist
        tags = collect_create_tags(
            {"life": "work"},
            [
                {"type": "action", "text": "a", "execute": "now"},
                {"type": "action", "text": "b", "execute": "quick"},
            ],
        )
        assert AI_PROGRESS_DEFERRED not in tags
        assert AI_PROGRESS in tags

    def test_no_execute_omits_progress_tags(self):
        tags = collect_create_tags({"life": "work"}, [{"type": "action", "text": "a"}])
        assert AI_PROGRESS not in tags
        assert AI_PROGRESS_DEFERRED not in tags


class TestValidateCreate:
    def _ok_frame(self):
        return {"life": "personal", "focus": "Personal", "name": "New Project"}

    def test_clean_create_has_no_rejections(self):
        items = [
            {"id": "p", "type": "action", "text": "Producer"},
            {"id": "c", "type": "action", "text": "Consumer", "deps": ["p"]},
        ]
        assert validate_create(self._ok_frame(), items)["rejections"] == []

    def test_missing_name_rejected(self):
        assert "missing_name" in _reasons(validate_create({"life": "personal"}, []))

    def test_invalid_life_rejected(self):
        frame = {"name": "X", "life": "banana"}
        assert "invalid_life" in _reasons(validate_create(frame, []))

    def test_unknown_add_type_rejected(self):
        items = [{"type": "frobnicate", "text": "x"}]
        assert "unknown_add_type" in _reasons(validate_create(self._ok_frame(), items))

    def test_invalid_execute_rejected(self):
        items = [{"type": "action", "text": "x", "execute": "soon"}]
        assert "invalid_execute" in _reasons(validate_create(self._ok_frame(), items))

    def test_unknown_dep_rejected(self):
        items = [{"id": "a", "type": "action", "text": "x", "deps": ["ghost"]}]
        assert "unknown_dep" in _reasons(validate_create(self._ok_frame(), items))

    def test_dep_by_index_resolves(self):
        # an item with no explicit id is addressable by its index; a dep on "0" is valid
        items = [
            {"type": "action", "text": "first"},
            {"type": "action", "text": "second", "deps": ["0"]},
        ]
        assert validate_create(self._ok_frame(), items)["rejections"] == []


class TestItemTextIsValidatedBeforeAnyWrite:
    """The incident pin: a draft keyed on `name` must be rejected, not half-written.

    `gtd_item_create` keys the name on `name`; both canvas surfaces key it on `text`. A 17-item
    plan authored with `name` produced 17 items with empty names — each refused by RTM with
    *"Task name provided is invalid"*, **after** the project task and its notes were already
    durable. The create's own documentation promises a half-built project never lands; these
    rejections are what makes that true for this failure class."""

    def _ok_frame(self):
        return {"life": "personal", "focus": "Personal", "name": "New Project"}

    def test_missing_text_rejected(self):
        items = [{"type": "action", "name": "keyed on the wrong field"}]
        assert "missing_name" in _reasons(validate_create(self._ok_frame(), items))

    def test_whitespace_only_text_rejected(self):
        items = [{"type": "action", "text": "   \n\t "}]
        assert "missing_name" in _reasons(validate_create(self._ok_frame(), items))

    def test_empty_string_text_rejected(self):
        assert "missing_name" in _reasons(
            validate_create(self._ok_frame(), [{"type": "action", "text": ""}])
        )

    def test_non_string_text_rejected(self):
        assert "missing_name" in _reasons(
            validate_create(self._ok_frame(), [{"type": "action", "text": 42}])
        )

    def test_rejection_carries_the_index_and_names_the_confusion(self):
        items = [
            {"type": "action", "text": "fine"},
            {"type": "action", "name": "wrong key"},
        ]
        rejection = next(
            r for r in validate_create(self._ok_frame(), items)["rejections"] if "index" in r
        )
        assert rejection["index"] == 1
        assert "name" in rejection["detail"] and "text" in rejection["detail"]

    def test_whole_draft_is_rejected_so_nothing_is_written(self):
        """One bad item rejects the create — the atomicity the surface promises."""
        items = [
            {"type": "action", "text": "good"},
            {"type": "action", "text": ""},
            {"type": "action", "text": "also good"},
        ]
        assert validate_create(self._ok_frame(), items)["rejections"] != []


class TestItemKeys:
    def test_item_keys_extend_the_commit_add_keys(self):
        """Create accepts everything a commit add does, plus the five create-only extras."""
        assert ADD_KEYS < ITEM_KEYS
        assert {"id", "deps", "done", "execute", "notes"} == ITEM_KEYS - ADD_KEYS

    def test_every_documented_item_field_is_recognised(self):
        """Guards the receipt against crying wolf on the tool's own advertised shape."""
        documented = {
            "id",
            "type",
            "text",
            "classifiers",
            "chase",
            "calendar_date",
            "due",
            "start",
            "estimate",
            "deps",
            "done",
            "execute",
            "notes",
        }
        assert documented <= ITEM_KEYS


class TestDuplicateAndSelfDeps:
    def _ok_frame(self):
        return {"life": "personal", "focus": "F", "name": "P", "outcome": ""}

    def test_duplicate_explicit_ids_rejected(self):
        items = [
            {"id": "a", "type": "action", "text": "one"},
            {"id": "a", "type": "action", "text": "two"},
        ]
        assert "duplicate_id" in _reasons(validate_create(self._ok_frame(), items))

    def test_explicit_id_colliding_with_positional_index_rejected(self):
        # Item 0 claims explicit id "1"; item 1 (no id) resolves to positional
        # "1" — the apply loop would keep only one of them, silently.
        items = [
            {"id": "1", "type": "action", "text": "A"},
            {"type": "action", "text": "B"},
        ]
        assert "duplicate_id" in _reasons(validate_create(self._ok_frame(), items))

    def test_self_dep_rejected(self):
        items = [{"id": "a", "type": "action", "text": "x", "deps": ["a"]}]
        assert "self_dep" in _reasons(validate_create(self._ok_frame(), items))

    def test_unique_ids_still_pass(self):
        items = [
            {"id": "a", "type": "action", "text": "one"},
            {"type": "action", "text": "two", "deps": ["a"]},
        ]
        assert validate_create(self._ok_frame(), items)["rejections"] == []
