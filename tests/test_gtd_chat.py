"""Tests for the pure gtd_chat helpers (CHAT note grammar, mode footer, turn/thread parsing)."""

import re

from rtm_mcp.gtd_chat import (
    AI_CHAT,
    AI_CHAT_REQUESTED,
    append_mode_footer,
    build_inflight,
    build_thread,
    format_chat_title,
    local_stamp,
    parse_body,
    parse_chat_title,
    parse_turn,
)

STAMP = "2026-06-28 14:30"


def _note(note_id, title, body, created):
    """A note in the shape real `rtm.tasks.getList` returns: the `title` field is ALWAYS empty; the
    grammar title is the FIRST LINE of the body, the message on the lines after (RTM stores
    `title\\nmessage` in the single body field — there is no separate note-title field)."""
    full = f"{title}\n{body}" if body else title
    return {"id": note_id, "title": "", "$t": full, "created": created}


def _chat_note(note_id, role, created):
    """A realistic CHAT note (title-as-body-first-line) for a task, for last_activity tests."""
    return _note(note_id, format_chat_title(STAMP, role, "scope"), "hi", created)


def _task(task_id, name="Task", parent="", tags=None, notes=None, completed=None):
    """A parsed task in the shape parse_tasks_response emits (subset build_inflight reads)."""
    return {
        "id": task_id,
        "name": name,
        "parent_task_id": parent or None,
        "tags": tags or [],
        "notes": notes or [],
        "completed": completed,
    }


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
        # Worker-authored notes may carry the body under "body" rather than "$t"; the grammar is
        # still the first line of that body.
        note = {
            "id": "n3",
            "title": "",
            "body": f"{format_chat_title(STAMP, 'ai', 's')}\nvia body key",
            "created": "t",
        }
        turn = parse_turn(note)
        assert turn is not None
        assert turn["text"] == "via body key"

    def test_non_chat_note_returns_none(self):
        assert parse_turn(_note("n", "INCEPTION", "x", "t")) is None

    def test_title_in_body_first_line_not_title_field(self):
        # Regression: real getList returns title="" with the grammar as the body's first line. The
        # parser must read the body, never the (always-empty) title field. This shape returned
        # turns:[] before the fix.
        note = {
            "id": "1",
            "title": "",
            "$t": "2026-06-28 22:02 — CHAT — me — project\nhello there",
            "created": "2026-06-28T21:02:20Z",
        }
        turn = parse_turn(note)
        assert turn is not None
        assert turn["role"] == "me"
        assert turn["scope"] == "project"
        assert turn["text"] == "hello there"

    def test_title_field_is_ignored(self):
        # A populated title field must NOT be parsed: only the body's first line counts. Here the
        # title field carries the grammar but the body's first line does not → not a CHAT turn.
        note = {
            "id": "x",
            "title": format_chat_title(STAMP, "me", "scope"),
            "$t": "just a plain message, no grammar",
            "created": "t",
        }
        assert parse_turn(note) is None

    def test_single_line_body_yields_turn_with_empty_text(self):
        # Title only, no message line — a valid turn with empty text (must not be dropped).
        note = {
            "id": "s",
            "title": "",
            "$t": format_chat_title(STAMP, "ai", "scope"),
            "created": "t",
        }
        turn = parse_turn(note)
        assert turn is not None
        assert turn["role"] == "ai"
        assert turn["text"] == ""
        assert "mode" not in turn

    def test_mode_footer_on_realistic_shape(self):
        # The Mode footer (last body line) is stripped from text and surfaced, with the grammar in
        # the body's first line.
        note = {
            "id": "m",
            "title": "",
            "$t": "2026-06-28 22:02 — CHAT — me — project\nprogress this\n\nMode: act",
            "created": "t",
        }
        turn = parse_turn(note)
        assert turn is not None
        assert turn["text"] == "progress this"
        assert turn["mode"] == "act"


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


class TestBuildInflight:
    AREA = "area1"
    PROJ = "proj1"
    PROJ2 = "proj2"

    def _portfolio(self):
        """Two projects under an area; project PROJ has a project-scope thread + three item threads
        (one per status) + several excluded items; PROJ2 has one item thread (cross-project)."""
        return [
            _task(self.AREA, "Focus area", tags=["focus"]),
            _task(self.PROJ, "Alpha", parent=self.AREA, tags=["project", "ai_chat"]),
            _task(self.PROJ2, "Beta", parent=self.AREA, tags=["project"]),
            # PROJ item threads — one per status
            _task(
                "i_flight",
                "Draft it",
                parent=self.PROJ,
                tags=["action", "ai_chat", "ai_chat_requested"],
                notes=[_chat_note("n1", "me", "2026-06-29T10:00:00Z")],
            ),
            _task(
                "i_review",
                "Review it",
                parent=self.PROJ,
                tags=["action", "ai_chat", "ai_output_review_needed"],
            ),
            _task("i_open", "Chatting", parent=self.PROJ, tags=["action", "ai_chat"]),
            # excluded: no #ai_chat / #test / completed
            _task("i_nochat", "No chat", parent=self.PROJ, tags=["action"]),
            _task("i_test", "Test", parent=self.PROJ, tags=["action", "ai_chat", "test"]),
            _task(
                "i_done",
                "Done",
                parent=self.PROJ,
                tags=["action", "ai_chat"],
                completed="2026-06-01T00:00:00Z",
            ),
            # cross-project item thread under PROJ2
            _task("i_beta", "Beta item", parent=self.PROJ2, tags=["action", "ai_chat"]),
        ]

    def _by_id(self):
        return {i["task_id"]: i for i in build_inflight(self._portfolio())["items"]}

    def test_selection_incomplete_ai_chat_not_test(self):
        ids = set(self._by_id())
        assert ids == {self.PROJ, "i_flight", "i_review", "i_open", "i_beta"}
        # excluded: no-chat, #test, completed
        assert {"i_nochat", "i_test", "i_done"}.isdisjoint(ids)

    def test_count_matches_items(self):
        out = build_inflight(self._portfolio())
        assert out["count"] == len(out["items"]) == 5

    def test_status_precedence(self):
        by_id = self._by_id()
        assert by_id["i_flight"]["status"] == "in_flight"
        assert by_id["i_review"]["status"] == "awaiting_review"
        assert by_id["i_open"]["status"] == "open"

    def test_in_flight_wins_over_review(self):
        parsed = [
            _task(self.PROJ, "Alpha", tags=["project"]),
            _task(
                "both",
                "Both signals",
                parent=self.PROJ,
                tags=["action", "ai_chat", "ai_chat_requested", "ai_output_review_needed"],
            ),
        ]
        item = next(i for i in build_inflight(parsed)["items"] if i["task_id"] == "both")
        assert item["status"] == "in_flight"

    def test_scope_project_vs_item(self):
        by_id = self._by_id()
        assert by_id[self.PROJ]["scope"] == "project"
        assert by_id["i_flight"]["scope"] == "item"

    def test_ancestor_project_resolution(self):
        by_id = self._by_id()
        # item → nearest #project ancestor
        assert by_id["i_flight"]["project_id"] == self.PROJ
        assert by_id["i_flight"]["project_name"] == "Alpha"
        # a project task resolves to itself
        assert by_id[self.PROJ]["project_id"] == self.PROJ
        # cross-project item attributes to its own project
        assert by_id["i_beta"]["project_id"] == self.PROJ2
        assert by_id["i_beta"]["project_name"] == "Beta"

    def test_deeply_nested_item_walks_up_to_project(self):
        parsed = [
            _task(self.AREA, "Focus", tags=["focus"]),
            _task(self.PROJ, "Alpha", parent=self.AREA, tags=["project"]),
            _task("mid", "Mid action", parent=self.PROJ, tags=["action"]),
            _task("leaf", "Leaf", parent="mid", tags=["action", "ai_chat"]),
        ]
        item = build_inflight(parsed)["items"][0]
        assert item["task_id"] == "leaf"
        assert item["project_id"] == self.PROJ

    def test_loose_item_without_project_ancestor(self):
        parsed = [_task("loose", "Loose", tags=["action", "ai_chat"])]
        item = build_inflight(parsed)["items"][0]
        assert item["project_id"] == ""
        assert item["project_name"] == ""

    def test_last_activity_is_latest_chat_note(self):
        parsed = [
            _task(self.PROJ, "Alpha", tags=["project"]),
            _task(
                "chatty",
                "Chatty",
                parent=self.PROJ,
                tags=["action", "ai_chat"],
                notes=[
                    _chat_note("n1", "me", "2026-06-29T10:00:00Z"),
                    _chat_note("n2", "ai", "2026-06-29T12:00:00Z"),
                    _note("doc", "INCEPTION", "not a chat", "2026-06-29T23:00:00Z"),  # ignored
                ],
            ),
        ]
        item = build_inflight(parsed)["items"][0]
        assert item["last_activity"] == "2026-06-29T12:00:00Z"

    def test_last_activity_empty_when_no_chat_notes(self):
        by_id = self._by_id()
        assert by_id["i_open"]["last_activity"] == ""  # tagged #ai_chat but no CHAT note yet

    def test_ordering_status_then_recency(self):
        parsed = [
            _task(self.PROJ, "Alpha", tags=["project"]),
            _task("open1", "Open", parent=self.PROJ, tags=["action", "ai_chat"]),
            _task(
                "flight_old",
                "Old flight",
                parent=self.PROJ,
                tags=["action", "ai_chat", "ai_chat_requested"],
                notes=[_chat_note("a", "me", "2026-06-29T09:00:00Z")],
            ),
            _task(
                "flight_new",
                "New flight",
                parent=self.PROJ,
                tags=["action", "ai_chat", "ai_chat_requested"],
                notes=[_chat_note("b", "me", "2026-06-29T18:00:00Z")],
            ),
        ]
        order = [i["task_id"] for i in build_inflight(parsed)["items"]]
        # both in_flight before the open one; within in_flight the more recent activity first
        assert order == ["flight_new", "flight_old", "open1"]

    def test_empty(self):
        assert build_inflight([]) == {"items": [], "count": 0}
        assert build_inflight([_task("x", "No chat", tags=["action"])]) == {"items": [], "count": 0}


class TestLocalStamp:
    def test_shape(self):
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", local_stamp("Europe/London"))

    def test_tz_fallback_does_not_raise(self):
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", local_stamp("Not/AZone"))
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", local_stamp(None))


def test_tag_constants_are_bare_names():
    assert AI_CHAT_REQUESTED == "ai_chat_requested"
    assert AI_CHAT == "ai_chat"
