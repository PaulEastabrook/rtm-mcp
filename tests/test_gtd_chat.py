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
    parse_filings,
    parse_links,
    parse_output_note,
    parse_turn,
    project_descendants,
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


VAULT_PATH = "work/turner-and-townsend/reporting-capability-guidance/output/2026-05-25-brief.md"


def _output_note(note_id, created, paths=None, summary="Brief drafted", continuation=False):
    """A realistic OUTPUT note (title-as-body-first-line) carrying FILING line(s)."""
    lines = []
    for p in paths if paths is not None else [VAULT_PATH]:
        if continuation:
            lines.append("FILING: filed in the project output folder with companion metadata —")
            lines.append(f"{p} (+ .meta.md)")
        else:
            lines.append(f"FILING: {p} (+ .meta.md)")
    body = "Drafted the brief.\n\n" + "\n".join(lines) + "\n\nStatus: awaiting review."
    return _note(note_id, f"2026-05-25 — OUTPUT — {summary}", body, created)


class TestParseFilings:
    def test_single_line_form(self):
        assert parse_filings(f"prose\nFILING: {VAULT_PATH} (+ .meta.md)\nmore") == [VAULT_PATH]

    def test_labelled_continuation_form(self):
        body = (
            "FILING: filed in the project output folder with companion metadata —\n"
            f"{VAULT_PATH} (+ .meta.md)"
        )
        assert parse_filings(body) == [VAULT_PATH]

    def test_companion_marker_optional(self):
        assert parse_filings(f"FILING: {VAULT_PATH}") == [VAULT_PATH]

    def test_absolute_path_skipped(self):
        # Malformed per the catalogue — the notes-audit owns flagging it; never "repair" here.
        assert parse_filings(f"FILING: /{VAULT_PATH} (+ .meta.md)") == []

    def test_backslashed_path_skipped(self):
        assert parse_filings(r"FILING: work\ttt\output\brief.md (+ .meta.md)") == []

    def test_multiple_filing_lines(self):
        body = f"FILING: {VAULT_PATH} (+ .meta.md)\nFILING: personal/other/report.md (+ .meta.md)"
        assert parse_filings(body) == [VAULT_PATH, "personal/other/report.md"]

    def test_empty_and_no_filing(self):
        assert parse_filings("") == []
        assert parse_filings("just prose\nno filing here") == []


class TestParseOutputNote:
    def test_output_note_with_filing(self):
        out = parse_output_note(_output_note("o1", "2026-05-25T16:55:32Z"))
        assert out == {
            "note_id": "o1",
            "label": "Brief drafted",
            "created": "2026-05-25T16:55:32Z",
            "paths": [VAULT_PATH],
        }

    def test_continuation_form_parses(self):
        out = parse_output_note(_output_note("o2", "t", continuation=True))
        assert out is not None
        assert out["paths"] == [VAULT_PATH]

    def test_timestamped_title_variant(self):
        note = _note("o3", "2026-05-25 16:55 — OUTPUT — Filed", f"FILING: {VAULT_PATH}", "t")
        out = parse_output_note(note)
        assert out is not None
        assert out["label"] == "Filed"

    def test_non_output_note_with_filing_line_ignored(self):
        # Historic FILING-typed notes (and any other type) predate the convention — the grammar is
        # pinned to OUTPUT notes only (catalogue § 3).
        note = _note("f1", "2026-04-06 — FILING — Artefacts filed", f"FILING: {VAULT_PATH}", "t")
        assert parse_output_note(note) is None

    def test_output_note_without_filing_is_none(self):
        assert (
            parse_output_note(_note("o4", "2026-05-25 — OUTPUT — No file", "prose only", "t"))
            is None
        )


class TestParseLinks:
    def test_em_dash_separator(self):
        assert parse_links("LINK: https://x.test/a — Jira issue") == [
            {"url": "https://x.test/a", "label": "Jira issue"}
        ]

    def test_en_dash_separator(self):
        assert parse_links("LINK: https://x.test/a – label") == [  # noqa: RUF001 — en-dash on purpose
            {"url": "https://x.test/a", "label": "label"}
        ]

    def test_spaced_hyphen_separator(self):
        assert parse_links("LINK: https://x.test/a - label") == [
            {"url": "https://x.test/a", "label": "label"}
        ]

    def test_no_separator_gives_empty_label(self):
        assert parse_links("LINK: https://x.test/a") == [{"url": "https://x.test/a", "label": ""}]

    def test_only_line_anchored_uppercase_keyword(self):
        assert parse_links("see LINK: https://x.test/a — inline mention") == []
        assert parse_links("link: https://x.test/a — lowercase") == []

    def test_multiple_links_in_order(self):
        text = "prose\nLINK: https://a.test — A\nLINK: https://b.test — B"
        assert [link["url"] for link in parse_links(text)] == ["https://a.test", "https://b.test"]


class TestBuildThreadAttachments:
    def _thread(self, extra_notes, ai_text="done"):
        notes = [
            _note("m1", format_chat_title(STAMP, "me", "s"), "please", "2026-05-25T10:00:00Z"),
            _note("a1", format_chat_title(STAMP, "ai", "s"), ai_text, "2026-05-25T17:00:00Z"),
        ]
        return build_thread(notes + extra_notes)

    def test_output_before_ai_turn_attaches(self):
        turns = self._thread([_output_note("o1", "2026-05-25T16:55:32Z")])
        ai = turns[-1]
        assert ai["files"] == [{"path": VAULT_PATH, "label": "Brief drafted", "note_id": "o1"}]

    def test_output_created_equal_to_ai_turn_attaches(self):
        turns = self._thread([_output_note("o1", "2026-05-25T17:00:00Z")])
        assert turns[-1]["files"][0]["note_id"] == "o1"

    def test_output_after_last_ai_turn_unattached(self):
        turns = self._thread([_output_note("o1", "2026-05-25T18:00:00Z")])
        assert all(t["files"] == [] for t in turns)

    def test_two_ai_turns_windows_respected(self):
        notes = [
            _note("a1", format_chat_title(STAMP, "ai", "s"), "first", "2026-05-25T12:00:00Z"),
            _note("a2", format_chat_title(STAMP, "ai", "s"), "second", "2026-05-25T18:00:00Z"),
            _output_note("early", "2026-05-25T11:00:00Z"),
            _output_note("mid", "2026-05-25T15:00:00Z", paths=["personal/mid.md"]),
        ]
        turns = build_thread(notes)
        first, second = turns[0], turns[1]
        assert [f["note_id"] for f in first["files"]] == ["early"]
        assert [f["note_id"] for f in second["files"]] == ["mid"]

    def test_files_never_attach_to_me_turns(self):
        turns = self._thread([_output_note("o1", "2026-05-25T09:00:00Z")])
        me = turns[0]
        assert me["role"] == "me" and me["files"] == []
        assert turns[-1]["files"][0]["note_id"] == "o1"  # earliest ai turn >= the filing

    def test_link_trailer_parsed_and_retained_in_text(self):
        ai_text = "Done — see the page.\n\nLINK: https://x.test/page — Confluence page"
        turns = self._thread([], ai_text=ai_text)
        ai = turns[-1]
        assert ai["links"] == [{"url": "https://x.test/page", "label": "Confluence page"}]
        assert "LINK: https://x.test/page — Confluence page" in ai["text"]

    def test_turns_without_attachments_carry_empty_arrays(self):
        turns = self._thread([])
        assert all(t["files"] == [] and t["links"] == [] for t in turns)

    def test_since_filter_keeps_full_thread_correlation(self):
        # The OUTPUT correlates to the ai turn even when `since` filters out the earlier me turn —
        # correlation runs over the full thread, then the filter applies.
        notes = [
            _note("m1", format_chat_title(STAMP, "me", "s"), "go", "2026-05-25T10:00:00Z"),
            _note("a1", format_chat_title(STAMP, "ai", "s"), "done", "2026-05-25T17:00:00Z"),
            _output_note("o1", "2026-05-25T16:55:32Z"),
        ]
        turns = build_thread(notes, since="2026-05-25T12:00:00Z")
        assert [t["note_id"] for t in turns] == ["a1"]
        assert turns[0]["files"][0]["path"] == VAULT_PATH

    def test_item_scope_file_entries_carry_no_provenance_fields(self):
        # Regression guard (stage 2b): with no descendants the entry shape is byte-identical to
        # v1.19.0 — exactly {path, label, note_id}, no item_id/item_name.
        turns = self._thread([_output_note("o1", "2026-05-25T16:55:32Z")])
        entry = turns[-1]["files"][0]
        assert set(entry) == {"path", "label", "note_id"}


class TestProjectDescendants:
    def _tree(self):
        return [
            _task("P", name="Project", tags=["project"]),
            _task("c1", name="Child one", parent="P"),
            _task("c2", name="Child two", parent="P", completed="2026-06-01T00:00:00Z"),
            _task("g1", name="Grandchild", parent="c1"),
            _task("loose", name="Elsewhere"),
            _task("other", name="Other project child", parent="Q"),
        ]

    def test_children_and_grandchildren_breadth_first(self):
        ids = [t["id"] for t in project_descendants(self._tree(), "P")]
        assert ids == ["c1", "c2", "g1"]  # children first, then grandchildren; project excluded

    def test_completed_descendant_included(self):
        # A completed action's filed output is still a project output.
        assert "c2" in [t["id"] for t in project_descendants(self._tree(), "P")]

    def test_deleted_descendant_excluded(self):
        tree = self._tree()
        tree[1]["deleted"] = "2026-06-02T00:00:00Z"
        ids = [t["id"] for t in project_descendants(tree, "P")]
        assert ids == ["c2"]  # c1 gone, and g1 unreachable through it

    def test_cycle_guarded(self):
        tree = [_task("a", parent="b"), _task("b", parent="a")]
        assert [t["id"] for t in project_descendants(tree, "a")] == ["b"]

    def test_no_descendants(self):
        assert project_descendants(self._tree(), "loose") == []


class TestBuildThreadProjectScope:
    """Stage 2b: a #project target's FILING scan covers the descendant tree, with provenance."""

    def _project_notes(self):
        # The project-level thread: me asks "what outputs?", ai replies at 17:00.
        return [
            _note("m1", format_chat_title(STAMP, "me", "P"), "outputs?", "2026-05-25T10:00:00Z"),
            _note("a1", format_chat_title(STAMP, "ai", "P"), "four packs", "2026-05-25T17:00:00Z"),
        ]

    def _child(self, task_id, name, output_notes):
        return _task(task_id, name=name, parent="P", notes=output_notes)

    def test_child_filing_attaches_with_provenance(self):
        child = self._child("c1", "Draft the pack", [_output_note("o1", "2026-05-25T16:00:00Z")])
        turns = build_thread(self._project_notes(), descendants=[child])
        assert turns[-1]["files"] == [
            {
                "path": VAULT_PATH,
                "label": "Brief drafted",
                "note_id": "o1",
                "item_id": "c1",
                "item_name": "Draft the pack",
            }
        ]

    def test_grandchild_filing_included(self):
        # The descendant list is whatever project_descendants yields — a 3-level grandchild's
        # OUTPUT note attaches exactly like a child's.
        tree = [
            _task("P", name="Project", tags=["project"]),
            _task("c1", name="Child", parent="P"),
            _task(
                "g1",
                name="Grandchild",
                parent="c1",
                notes=[_output_note("og", "2026-05-25T15:00:00Z")],
            ),
        ]
        turns = build_thread(self._project_notes(), descendants=project_descendants(tree, "P"))
        assert [f["item_id"] for f in turns[-1]["files"]] == ["g1"]

    def test_child_filing_after_last_ai_turn_unattached(self):
        child = self._child("c1", "Late filer", [_output_note("o1", "2026-05-25T18:00:00Z")])
        turns = build_thread(self._project_notes(), descendants=[child])
        assert all(t["files"] == [] for t in turns)

    def test_two_ai_turn_windows_respected_across_children(self):
        notes = [
            _note("a1", format_chat_title(STAMP, "ai", "P"), "first", "2026-05-25T12:00:00Z"),
            _note("a2", format_chat_title(STAMP, "ai", "P"), "second", "2026-05-25T18:00:00Z"),
        ]
        early = self._child("c1", "Early", [_output_note("oe", "2026-05-25T11:00:00Z")])
        mid = self._child(
            "c2", "Mid", [_output_note("om", "2026-05-25T15:00:00Z", paths=["personal/mid.md"])]
        )
        turns = build_thread(notes, descendants=[early, mid])
        assert [f["item_id"] for f in turns[0]["files"]] == ["c1"]
        assert [f["item_id"] for f in turns[1]["files"]] == ["c2"]

    def test_own_note_filing_keeps_plain_shape_alongside_child_entries(self):
        # An OUTPUT note on the project task itself stays in the v1 shape (no provenance —
        # provenance names the DESCENDANT that filed it); a child entry in the same turn carries it.
        own = _output_note("op", "2026-05-25T16:00:00Z", paths=["personal/own.md"])
        child = self._child("c1", "Child", [_output_note("oc", "2026-05-25T16:30:00Z")])
        turns = build_thread([*self._project_notes(), own], descendants=[child])
        files = turns[-1]["files"]
        assert set(files[0]) == {"path", "label", "note_id"}  # own note scanned first
        assert files[1]["item_id"] == "c1"

    def test_descendant_chat_notes_do_not_become_turns(self):
        # A child action's own CHAT thread is a separate conversation — descendants contribute
        # only OUTPUT/FILING notes, never turns.
        child = self._child("c1", "Child", [_chat_note("cc", "ai", "2026-05-25T16:00:00Z")])
        turns = build_thread(self._project_notes(), descendants=[child])
        assert [t["note_id"] for t in turns] == ["m1", "a1"]


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


class TestInflightNearestProject:
    def test_nested_projects_attribute_to_nearest(self):
        # P1 → P2 → item: the item must attribute to P2 (nearest), not P1
        # (topmost) — the chain is root-first, so the walk must be leaf-first.
        parsed = [
            _task("p1", "Outer project", tags=["project"]),
            _task("p2", "Inner project", parent="p1", tags=["project"]),
            _task("leaf", "Leaf", parent="p2", tags=["action", "ai_chat"]),
        ]
        item = build_inflight(parsed)["items"][0]
        assert item["project_id"] == "p2"
        assert item["project_name"] == "Inner project"

    def test_nested_project_itself_attributes_to_self(self):
        # A project with its own thread resolves to itself, not its parent project.
        parsed = [
            _task("p1", "Outer project", tags=["project"]),
            _task("p2", "Inner project", parent="p1", tags=["project", "ai_chat"]),
        ]
        item = build_inflight(parsed)["items"][0]
        assert item["project_id"] == "p2"
        assert item["scope"] == "project"
