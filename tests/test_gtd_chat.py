"""Tests for the pure gtd_chat helpers (CHAT note grammar, mode footer, turn/thread parsing)."""

import re

from rtm_mcp.gtd_chat import (
    AI_CHAT,
    AI_CHAT_REQUESTED,
    append_mode_footer,
    build_thread,
    format_chat_title,
    local_stamp,
    parse_body,
    parse_chat_title,
    parse_turn,
)

STAMP = "2026-06-28 14:30"


def _note(note_id, title, body, created):
    return {"id": note_id, "title": title, "$t": body, "created": created}


class TestTitleGrammar:
    def test_format_and_parse_round_trip(self):
        title = format_chat_title(STAMP, "me", "Sam's open days")
        assert title == "2026-06-28 14:30 — CHAT — me — Sam's open days"
        parsed = parse_chat_title(title)
        assert parsed == {"stamp": STAMP, "role": "me", "scope": "Sam's open days"}

    def test_parse_ai_role(self):
        parsed = parse_chat_title(format_chat_title(STAMP, "ai", "Attend webinar"))
        assert parsed is not None
        assert parsed["role"] == "ai"
        assert parsed["scope"] == "Attend webinar"

    def test_non_chat_title_returns_none(self):
        assert parse_chat_title("INCEPTION") is None
        assert parse_chat_title("2026-06-28 14:30 — COMMIT — me — x") is None
        assert parse_chat_title("") is None
        # Wrong role token is not a CHAT turn.
        assert parse_chat_title("2026-06-28 14:30 — CHAT — bot — x") is None


class TestModeFooter:
    def test_append_and_parse_round_trip(self):
        body = append_mode_footer("Please progress this", "act")
        assert body == "Please progress this\n\nMode: act"
        text, mode = parse_body(body)
        assert text == "Please progress this"
        assert mode == "act"

    def test_no_mode_is_passthrough(self):
        assert append_mode_footer("hello", None) == "hello"
        text, mode = parse_body("hello")
        assert text == "hello"
        assert mode is None

    def test_footer_only_on_final_line(self):
        # A "Mode:" inside the message (not the final line) is not a footer.
        text, mode = parse_body("Mode: act is what I want\n\nactually do it")
        assert mode is None
        assert text == "Mode: act is what I want\n\nactually do it"

    def test_discuss_footer(self):
        text, mode = parse_body(append_mode_footer("just thinking", "discuss"))
        assert text == "just thinking"
        assert mode == "discuss"


class TestParseTurn:
    def test_chat_note_with_mode(self):
        note = _note(
            "n1",
            format_chat_title(STAMP, "me", "scope"),
            append_mode_footer("do it", "act"),
            "2026-06-28T13:30:00Z",
        )
        turn = parse_turn(note)
        assert turn == {
            "note_id": "n1",
            "role": "me",
            "scope": "scope",
            "text": "do it",
            "created": "2026-06-28T13:30:00Z",
            "mode": "act",
        }

    def test_chat_note_without_mode_omits_key(self):
        note = _note("n2", format_chat_title(STAMP, "ai", "scope"), "here you go", "t")
        turn = parse_turn(note)
        assert turn is not None
        assert "mode" not in turn
        assert turn["text"] == "here you go"

    def test_body_key_variant(self):
        # Worker-authored notes may carry the body under "body" rather than "$t".
        note = {
            "id": "n3",
            "title": format_chat_title(STAMP, "ai", "s"),
            "body": "via body key",
            "created": "t",
        }
        turn = parse_turn(note)
        assert turn is not None
        assert turn["text"] == "via body key"

    def test_non_chat_note_returns_none(self):
        assert parse_turn(_note("n", "INCEPTION", "x", "t")) is None


class TestBuildThread:
    def _notes(self):
        return [
            _note("a", format_chat_title(STAMP, "me", "s"), "first", "2026-06-28T10:00:00Z"),
            _note("doc", "DEPENDS-ON", "not a chat", "2026-06-28T11:00:00Z"),
            _note("b", format_chat_title(STAMP, "ai", "s"), "second", "2026-06-28T12:00:00Z"),
        ]

    def test_filters_non_chat_and_sorts_oldest_first(self):
        turns = build_thread(self._notes())
        assert [t["note_id"] for t in turns] == ["a", "b"]
        assert [t["role"] for t in turns] == ["me", "ai"]

    def test_out_of_order_input_is_sorted(self):
        notes = list(reversed(self._notes()))
        turns = build_thread(notes)
        assert [t["created"] for t in turns] == [
            "2026-06-28T10:00:00Z",
            "2026-06-28T12:00:00Z",
        ]

    def test_since_filter(self):
        turns = build_thread(self._notes(), since="2026-06-28T11:30:00Z")
        assert [t["note_id"] for t in turns] == ["b"]

    def test_empty_thread(self):
        assert build_thread([]) == []
        assert build_thread([_note("x", "INCEPTION", "y", "t")]) == []

    def test_single_note_normalised_to_list(self):
        # RTM returns a single note as a dict, not a list.
        single = _note("a", format_chat_title(STAMP, "me", "s"), "only", "t")
        turns = build_thread(single)
        assert len(turns) == 1
        assert turns[0]["note_id"] == "a"


class TestLocalStamp:
    def test_shape(self):
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", local_stamp("Europe/London"))

    def test_tz_fallback_does_not_raise(self):
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", local_stamp("Not/AZone"))
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", local_stamp(None))


def test_tag_constants_are_bare_names():
    assert AI_CHAT_REQUESTED == "ai_chat_requested"
    assert AI_CHAT == "ai_chat"
