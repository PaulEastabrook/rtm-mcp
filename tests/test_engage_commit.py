"""Tests for the server-side engage verdict grammar (src/rtm_mcp/engage_commit.py).

Mirrors the chat-side scripts/test_validate_engage_verdict.py contract case-for-case: the enum, the
per-kind base legality, the two flag guards (deadline § 3.1, blocked § 3.2), closest-legal
suggestions, the pre-triage suggestion, the date-phrase resolution, and the strict-tag gate input.
"""

from rtm_mcp.canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    OVERLAY_REFRESH,
)
from rtm_mcp.engage_commit import (
    CALENDAR_ENTRY_TAG,
    SOMEDAY_TAG,
    STEER_MAX_LEN,
    STEER_VERBS,
    VERDICT_FAMILY,
    base_verdict,
    collect_engage_tags,
    date_phrase_for,
    is_legal,
    make_steer_note,
    sanitize_steer,
    steer_note_text,
    suggest_verdict,
    validate,
    verdict_arg,
)


class TestEnumAndParsing:
    def test_enum_has_all_twelve_verdicts_with_families(self):
        assert VERDICT_FAMILY["do_now"] == "progress"
        assert VERDICT_FAMILY["next_actions"] == "defer"
        assert VERDICT_FAMILY["keep"] == "guard"
        assert VERDICT_FAMILY["drop"] == "guard"
        # progress / defer / guard partition — the full enum from grammar § 1
        assert set(VERDICT_FAMILY) == {
            "do_now",
            "draft",
            "nudge",
            "to_calendar",
            "next_actions",
            "today",
            "defer_start",
            "bump",
            "resurface",
            "someday",
            "keep",
            "drop",
        }

    def test_base_verdict_strips_arg(self):
        assert base_verdict("defer_start:next friday") == "defer_start"
        assert base_verdict("bump:+3d") == "bump"
        assert base_verdict("today") == "today"

    def test_verdict_arg(self):
        assert verdict_arg("defer_start:next friday") == "next friday"
        assert verdict_arg("bump:+3d") == "+3d"
        assert verdict_arg("today") == ""


class TestBaseLegality:
    def test_action_legal_set(self):
        for v in ("do_now", "draft", "to_calendar", "next_actions", "today", "defer_start", "bump"):
            assert is_legal(v, "action", False, False), v
        # resurface base-illegal for action (needs the blocked guard)
        assert not is_legal("resurface", "action", False, False)

    def test_waiting_for_edges(self):
        assert is_legal("nudge", "waiting_for", False, False)
        assert is_legal("today", "waiting_for", False, False)
        assert is_legal("bump", "waiting_for", False, False)
        # a waiting-for is not done, and its date is a chase tickle → not cleared
        assert not is_legal("do_now", "waiting_for", False, False)
        assert not is_legal("draft", "waiting_for", False, False)
        assert not is_legal("next_actions", "waiting_for", False, False)
        assert not is_legal("defer_start", "waiting_for", False, False)

    def test_calendar_entry_edges(self):
        assert is_legal("do_now", "calendar_entry", False, False)
        assert is_legal("today", "calendar_entry", False, False)
        # already on the hard landscape
        assert not is_legal("to_calendar", "calendar_entry", False, False)
        assert not is_legal("next_actions", "calendar_entry", False, False)

    def test_project_only_structural(self):
        for v in ("someday", "keep", "drop"):
            assert is_legal(v, "project", False, False), v
        for v in ("do_now", "today", "bump", "next_actions", "resurface"):
            assert not is_legal(v, "project", False, False), v


class TestFlagGuards:
    def test_deadline_guard_restricts_set(self):
        # § 3.1 — a hard deadline allows only do_now/to_calendar/keep/drop
        for v in ("do_now", "to_calendar", "keep", "drop"):
            assert is_legal(v, "action", True, False), v
        for v in ("next_actions", "today", "defer_start", "bump", "someday", "resurface"):
            assert not is_legal(v, "action", True, False), v

    def test_blocked_guard_enables_resurface(self):
        assert is_legal("resurface", "action", False, True)
        # base defer verdicts remain legal on a blocked item
        assert is_legal("next_actions", "action", False, True)

    def test_deadline_precedes_blocked(self):
        # both flags set → deadline guard wins → resurface illegal
        assert not is_legal("resurface", "action", True, True)
        assert is_legal("keep", "action", True, True)


class TestSuggestPreTriage:
    def test_suggested_verdicts(self):
        assert suggest_verdict("action", True, False) == "keep"  # deadline
        assert suggest_verdict("action", False, True) == "resurface"  # blocked
        assert suggest_verdict("waiting_for", False, False) == "nudge"
        assert suggest_verdict("action", False, False) == "next_actions"  # soft action
        assert suggest_verdict("calendar_entry", False, False) == "keep"
        assert suggest_verdict("project", False, False) == "keep"

    def test_suggested_is_always_legal(self):
        for kind in ("action", "waiting_for", "calendar_entry", "project"):
            for hd in (False, True):
                for bl in (False, True):
                    s = suggest_verdict(kind, hd, bl)
                    assert is_legal(s, kind, hd, bl), (kind, hd, bl, s)


class TestValidateBatch:
    def test_all_legal_ok(self):
        r = validate(
            [
                {"id": "1", "verdict": "next_actions", "kind": "action"},
                {"id": "2", "verdict": "nudge", "kind": "waiting_for"},
                {"id": "3", "verdict": "keep", "kind": "action", "has_deadline": True},
            ]
        )
        assert r["ok"] is True
        assert r["errors"] == []

    def test_off_enum_rejected_with_suggestion(self):
        r = validate([{"id": "1", "verdict": "nope", "kind": "action"}])
        assert r["ok"] is False
        assert r["errors"][0]["reason"] == "off-enum"

    def test_type_illegal_rejected_with_closest_legal(self):
        # deferring a hard deadline is type-illegal → suggest keep
        r = validate(
            [{"id": "1", "verdict": "next_actions", "kind": "action", "has_deadline": True}]
        )
        assert r["ok"] is False
        assert r["errors"][0]["reason"] == "type-illegal"
        assert r["errors"][0]["suggestion"] == "keep"

    def test_unknown_kind_rejected(self):
        r = validate([{"id": "1", "verdict": "today", "kind": "widget"}])
        assert r["ok"] is False
        assert r["errors"][0]["reason"] == "unknown-kind"

    def test_arg_verdict_validated_on_bare_verb(self):
        r = validate([{"id": "1", "verdict": "defer_start:next friday", "kind": "action"}])
        assert r["ok"] is True


class TestDatePhrase:
    def test_today(self):
        assert date_phrase_for("today", "", None) == "today"

    def test_bump_days(self):
        assert date_phrase_for("bump", "+3d", None) == "in 3 days"
        assert date_phrase_for("bump", "", None) == "in 1 days"  # postpone parity default

    def test_defer_start_uses_phrase(self):
        assert date_phrase_for("defer_start", "next monday", None) == "next monday"
        assert date_phrase_for("defer_start", "", "in a week") == "in a week"
        assert date_phrase_for("defer_start", "", None) == "today"

    def test_non_date_verdicts_return_none(self):
        for v in ("next_actions", "resurface", "someday", "keep", "drop", "do_now", "draft"):
            assert date_phrase_for(v, "", None) is None


class TestCollectTags:
    def test_tag_union_per_verdict(self):
        tags = collect_engage_tags(
            [
                {"id": "1", "verdict": "someday"},
                {"id": "2", "verdict": "to_calendar"},
                {"id": "3", "verdict": "draft"},
                {"id": "4", "verdict": "today"},
            ]
        )
        assert AI_CONVERSATION in tags
        assert SOMEDAY_TAG in tags
        assert OVERLAY_REFRESH in tags  # from someday
        assert CALENDAR_ENTRY_TAG in tags
        assert AI_PROGRESS in tags
        assert AI_DEFERRED in tags  # draft may be blocked

    def test_no_op_verdicts_write_no_tag(self):
        assert collect_engage_tags([{"id": "1", "verdict": "keep"}]) == set()
        assert collect_engage_tags([{"id": "1", "verdict": "do_now"}]) == set()
        assert collect_engage_tags([{"id": "1", "verdict": "drop"}]) == set()

    def test_date_verdict_stamps_conversation_only(self):
        assert collect_engage_tags([{"id": "1", "verdict": "next_actions"}]) == {AI_CONVERSATION}
        assert collect_engage_tags([{"id": "1", "verdict": "resurface"}]) == {
            AI_CONVERSATION,
            OVERLAY_REFRESH,
        }


class TestProgressSteer:
    def test_only_progress_verbs_consume_the_note(self):
        assert STEER_VERBS == ("draft", "do_now", "nudge")

    def test_sanitize_passes_clean_text(self):
        clean, warning = sanitize_steer("chase Roshni re the course")
        assert clean == "chase Roshni re the course"
        assert warning is None

    def test_sanitize_none_and_empty_are_noops(self):
        assert sanitize_steer(None) == (None, None)
        assert sanitize_steer("   ") == (None, None)
        assert sanitize_steer("") == (None, None)

    def test_sanitize_non_string_dropped_with_warning(self):
        assert sanitize_steer(42) == (None, "note_not_string")
        assert sanitize_steer({"x": 1}) == (None, "note_not_string")
        assert sanitize_steer(["a"]) == (None, "note_not_string")

    def test_sanitize_strips_control_chars_and_collapses_whitespace(self):
        clean, warning = sanitize_steer("chase\tBob\n\n  now\x00")
        assert clean == "chase Bob now"
        assert warning is None

    def test_sanitize_truncates_oversize_with_warning(self):
        clean, warning = sanitize_steer("x" * (STEER_MAX_LEN + 50))
        assert len(clean) == STEER_MAX_LEN
        assert warning == "note_truncated"

    def test_make_steer_note_title_and_pure_body(self):
        title, text = make_steer_note("2026-07-18 14:30", "draft", "chase Roshni")
        assert title == "2026-07-18 14:30 — STEER — draft"
        assert text == "chase Roshni"  # body is pure — no marker pollution

    def test_steer_note_text_round_trips(self):
        title, text = make_steer_note("2026-07-18 14:30", "draft", "chase Roshni")
        body = f"{title}\n{text}"
        assert steer_note_text(body) == "chase Roshni"

    def test_steer_note_text_multiline_body(self):
        body = "2026-07-18 14:30 — STEER — do_now\nline one\nline two"
        assert steer_note_text(body) == "line one\nline two"

    def test_steer_note_text_rejects_non_steer_notes(self):
        assert steer_note_text("COMMIT\nsome audit body") is None
        assert steer_note_text("2026-07-18 14:30 — CHAT — me — scope\nhi") is None
        assert steer_note_text("") is None
        assert steer_note_text("just a plain note") is None
