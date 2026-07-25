"""Pure-builder tests for `surface_queue` — the AI-surface eligibility read.

The highest-value assertions in this file are the `response_detected` ones. It is the signal the
scan branches on to spend an expensive processing pass and then RESOLVE an item, so a false
positive is a wrong resolve on work Paul never answered. The negative case — an item carrying
only system notes must NOT trip it — is pinned across every engine note shape observed live on
2026-07-25, because detection-by-exclusion (the shape originally specified) fires on all of them.
"""

from rtm_mcp.surface_queue import (
    RESPONSE_NOTE_TYPES,
    SYSTEM_NOTE_TYPES,
    VALID_SURFACES,
    build_row,
    build_surface_queue,
    classify_note,
    find_frontmatter,
    parse_frontmatter,
    parse_timestamp,
)

FRONTMATTER_BODY = """2026-07-20 — QUESTION — EM hire kick-off
---
item_id: 2026-07-20-em-hire-kick-off
item_type: question
list: AI_Questions
entities:
  - entity_type: action
    entity_url: https://www.rememberthemilk.com/app/#all/111
    entity_rtm:
      task_id: "111"
      taskseries_id: "222"
      list_id: "333"
    relationship: subject
expected_response_shape: pick-one
expected_response_options:
  - "Bill"
  - "Izabela"
priority: P1
asked_by: dependency-graph-proposal
asked_at: 2026-07-20 09:00
context_summary: |
  Needs a named point of contact.
related_artefact: null
auto_close_at: null
---

## Question
Who picks this up?
"""


def _note(note_id, body, created="2026-07-20T09:00:00Z"):
    return {"id": note_id, "$t": body, "created": created}


def _item(**over):
    task = {
        "id": "900",
        "taskseries_id": "901",
        "list_id": "51542311",
        "name": "EM hire kick-off",
        "tags": ["claude_question", "q_question", "q_pending"],
        "notes": [_note("1", FRONTMATTER_BODY)],
        "created": "2026-07-20T09:00:00Z",
        "modified": "2026-07-20T09:00:00Z",
        "completed": None,
    }
    task.update(over)
    return task


def _row(task, surface="questions", today="2026-07-25"):
    return build_row(
        task, surface=surface, by_id={str(task["id"]): task}, today=today, timezone="Europe/London"
    )


class TestFrontmatter:
    def test_parses_every_field_the_scan_needs(self):
        fields, err = parse_frontmatter(FRONTMATTER_BODY)
        assert err == ""
        assert fields["item_id"] == "2026-07-20-em-hire-kick-off"
        assert fields["item_type"] == "question"
        assert fields["expected_response_shape"] == "pick-one"
        assert fields["expected_response_options"] == ["Bill", "Izabela"]
        assert fields["asked_by"] == "dependency-graph-proposal"
        assert fields["asked_at"] == "2026-07-20 09:00"
        assert fields["context_summary"] == "Needs a named point of contact."

    def test_entities_keep_the_rtm_id_triple(self):
        fields, _ = parse_frontmatter(FRONTMATTER_BODY)
        assert fields["entities"] == [
            {
                "entity_rtm": {"task_id": "111", "taskseries_id": "222", "list_id": "333"},
                "entity_type": "action",
                "entity_url": "https://www.rememberthemilk.com/app/#all/111",
                "relationship": "subject",
            }
        ]

    def test_literal_null_becomes_none_not_the_string(self):
        fields, _ = parse_frontmatter(FRONTMATTER_BODY)
        assert fields["auto_close_at"] is None
        assert fields["related_artefact"] is None

    def test_fence_on_line_one_is_found(self):
        """The pre-v2.8.0 path wrote the body note with an empty title, so line 1 is `---`."""
        lines, err = find_frontmatter("---\nitem_id: x\n---\nbody")
        assert err == "" and lines == ["item_id: x"]

    def test_absent_and_unterminated_are_distinct_errors(self):
        assert find_frontmatter("2026-07-20 — CONTEXT — no frontmatter here")[1] == (
            "frontmatter_absent"
        )
        assert find_frontmatter("---\nitem_id: x\nno closing fence")[1] == (
            "frontmatter_unterminated"
        )

    def test_a_prose_dash_rule_deep_in_the_body_is_not_a_fence(self):
        assert find_frontmatter("title\nnarrative\nmore\n---\nitem_id: x\n---")[1] == (
            "frontmatter_absent"
        )


class TestMalformedMetadataNeverDropsTheRow:
    def test_absent_frontmatter_returns_a_usable_row(self):
        """66 of 77 live AI_Questions items are in exactly this state."""
        task = _item(notes=[_note("1", "2026-07-20 — CONTEXT — why this is here")])
        row = _row(task)
        assert row["metadata_parse_error"] == "frontmatter_absent"
        assert row["task_id"] == "900" and row["name"] == "EM hire kick-off"
        assert row["item_id"] is None
        assert row["entities"] == [] and row["expected_response_options"] == []
        # item_type still resolves from the tag when the frontmatter cannot supply it.
        assert row["item_type"] == "question"

    def test_unterminated_frontmatter_returns_a_usable_row(self):
        task = _item(notes=[_note("1", "---\nitem_id: x\nnever closed")])
        row = _row(task)
        assert row["metadata_parse_error"] == "frontmatter_unterminated"
        assert row["task_id"] == "900"

    def test_frontmatter_without_item_id_is_incomplete_not_clean(self):
        task = _item(notes=[_note("1", "---\nitem_type: question\n---")])
        assert _row(task)["metadata_parse_error"] == "frontmatter_incomplete"

    def test_metadata_missing_count_surfaces_the_scale(self):
        bare = _item(id="1", notes=[])
        good = _item(id="2")
        out = build_surface_queue(
            [bare, good], [], surface="questions", today="2026-07-25", timezone=None
        )
        assert out["metadata_missing_count"] == 1
        assert out["questions_count"] == 2


class TestAutoCloseDue:
    def _activity(self, auto_close):
        body = f"---\nitem_id: x\nitem_type: notification\nauto_close_at: {auto_close}\n---"
        return _item(tags=["ai_activity", "q_notification", "q_open"], notes=[_note("1", body)])

    def test_due_when_at_or_before_today(self):
        assert _row(self._activity("2026-07-25"), surface="activity")["auto_close_due"] is True
        assert _row(self._activity("2026-07-24"), surface="activity")["auto_close_due"] is True

    def test_not_due_the_day_before_it_falls(self):
        assert _row(self._activity("2026-07-26"), surface="activity")["auto_close_due"] is False

    def test_absent_auto_close_at_is_false_never_an_error(self):
        row = _row(self._activity("null"), surface="activity")
        assert row["auto_close_due"] is False and row["auto_close_at"] is None

    def test_bst_boundary_uses_the_account_date_not_utc(self):
        """`today` is the caller's account-tz date. A BST item auto-closing on 25 Jul is due on
        the 25th in London even though the UTC instant of local midnight is 24 Jul 23:00Z."""
        row = build_row(
            self._activity("2026-07-25"),
            surface="activity",
            by_id={},
            today="2026-07-25",
            timezone="Europe/London",
        )
        assert row["auto_close_due"] is True


class TestResponseDetected:
    """All three inclusion paths, plus the negative that matters most."""

    def test_path_q_answered_tag(self):
        row = _row(_item(tags=["claude_question", "q_answered"]))
        assert row["response_detected"] is True
        assert [e["path"] for e in row["response_evidence"]] == ["q_answered_tag"]

    def test_path_completed_without_the_terminal_tag(self):
        row = _row(_item(completed="2026-07-24T10:00:00Z"))
        assert row["response_detected"] is True
        assert "completed_unresolved" in [e["path"] for e in row["response_evidence"]]

    def test_path_response_note_after_asked_at(self):
        task = _item(
            notes=[
                _note("1", FRONTMATTER_BODY),
                _note("2", "2026-07-22 — ANSWER — Bill", created="2026-07-22T11:00:00Z"),
            ]
        )
        row = _row(task)
        assert row["response_detected"] is True
        evidence = [e for e in row["response_evidence"] if e["path"] == "response_note"]
        assert evidence and evidence[0]["note_id"] == "2"

    def test_every_response_class_type_counts(self):
        for note_type in sorted(RESPONSE_NOTE_TYPES):
            task = _item(
                notes=[
                    _note("1", FRONTMATTER_BODY),
                    _note("2", f"2026-07-22 — {note_type} — x", created="2026-07-22T11:00:00Z"),
                ]
            )
            assert _row(task)["response_detected"] is True, note_type

    def test_system_notes_only_does_NOT_trip_it(self):
        """The negative case. Every one of these shapes is live on the eligible set; an
        exclusion-based rule fires on all of them."""
        task = _item(
            notes=[
                _note("1", FRONTMATTER_BODY),
                _note("2", "2026-07-21 — CONTEXT — re-walk", created="2026-07-21T09:00:00Z"),
                _note("3", "2026-07-22 — CONTRIB — chase queue", created="2026-07-22T09:00:00Z"),
                _note("4", "2026-07-23 — UPDATE — snapshot", created="2026-07-23T09:00:00Z"),
                _note("5", "AI-LINK", created="2026-07-23T10:00:00Z"),
                _note("6", "2026-07-24 — OUTCOME — closing", created="2026-07-24T09:00:00Z"),
                _note("7", "2026-07-24 — Q-UPDATE — depth", created="2026-07-24T10:00:00Z"),
            ]
        )
        row = _row(task)
        assert row["response_detected"] is False
        assert row["response_evidence"] == []
        assert row["unrecognised_notes"] == []

    def test_the_items_own_frontmatter_note_is_never_evidence(self):
        assert _row(_item())["response_detected"] is False

    def test_a_note_before_asked_at_is_ignored(self):
        task = _item(
            notes=[
                _note("1", FRONTMATTER_BODY),
                _note("2", "2026-07-19 — ANSWER — stale", created="2026-07-19T08:00:00Z"),
            ]
        )
        assert _row(task)["response_detected"] is False

    def test_unknown_note_is_quarantined_not_asserted(self):
        """The exclusion signal is preserved for the agent but never sets the boolean."""
        task = _item(
            notes=[
                _note("1", FRONTMATTER_BODY),
                _note("2", "Paul: go with Bill", created="2026-07-22T11:00:00Z"),
            ]
        )
        row = _row(task)
        assert row["response_detected"] is False
        assert [n["note_id"] for n in row["unrecognised_notes"]] == ["2"]

    def test_baseline_falls_back_to_item_creation_when_asked_at_is_absent(self):
        task = _item(
            notes=[
                _note("1", "2026-07-20 — CONTEXT — why", created="2026-07-20T09:00:00Z"),
                _note("2", "2026-07-22 — REPLY — do it", created="2026-07-22T09:00:00Z"),
            ]
        )
        row = _row(task)
        assert row["metadata_parse_error"] == "frontmatter_absent"
        assert row["response_detected"] is True


class TestNoteClassification:
    def test_catalogue_and_surface_types_are_system(self):
        # DECISION is in both sets by design — on a surface item a decision IS the response,
        # so the response test runs first. Every other system type must classify as system.
        assert {"DECISION"} == SYSTEM_NOTE_TYPES & RESPONSE_NOTE_TYPES
        for note_type in sorted(SYSTEM_NOTE_TYPES - RESPONSE_NOTE_TYPES):
            assert classify_note(f"2026-07-25 — {note_type} — x") == "system", note_type

    def test_hyphenated_and_underscored_types_survive_the_split(self):
        """`AI-LINK` must not parse as type `AI` (the gtd_reads.parse_note_type defect), and
        `ACTIVITY_REPORT` — which this server writes — must not fall through as unknown."""
        for note_type in (
            "AI-LINK",
            "DEPENDS-ON",
            "SOURCE-DRAFT",
            "CONTRIB-UPDATE",
            "TMPL-CHILD",
            "ACTIVITY_REPORT",
            "AI ANALYSIS",
        ):
            assert classify_note(f"2026-07-25 — {note_type} — x") == "system", note_type

    def test_bare_type_line_and_fence_are_system(self):
        assert classify_note("AI-LINK") == "system"
        assert classify_note("---") == "system"
        assert classify_note("") == "system"

    def test_free_prose_is_unrecognised(self):
        assert classify_note("ai-surface-scan run (07:20 UTC)") == "unrecognised"


class TestTimestamps:
    def test_parses_the_three_live_forms(self):
        assert parse_timestamp("2026-07-25T09:00:00Z") is not None
        assert parse_timestamp("2026-07-25 09:00") is not None
        assert parse_timestamp("2026-07-25") is not None

    def test_unparseable_is_none_never_a_raise(self):
        assert parse_timestamp("last Tuesday") is None
        assert parse_timestamp("") is None
        assert parse_timestamp(None) is None


class TestBundle:
    def test_both_returns_two_separately_sorted_collections(self):
        q_old = _item(id="1", name="old", modified="2026-07-01T00:00:00Z")
        q_new = _item(id="2", name="new", modified="2026-07-24T00:00:00Z")
        a_old = _item(id="3", name="a-old", created="2026-07-01T00:00:00Z", tags=["ai_activity"])
        a_new = _item(id="4", name="a-new", created="2026-07-24T00:00:00Z", tags=["ai_activity"])
        out = build_surface_queue(
            [q_new, q_old], [a_new, a_old], surface="both", today="2026-07-25", timezone=None
        )
        assert [r["task_id"] for r in out["questions"]] == ["1", "2"]  # oldest MODIFIED first
        assert [r["task_id"] for r in out["activity"]] == ["3", "4"]  # oldest CREATED first
        assert out["count"] == 4

    def test_single_surface_omits_the_other_collection(self):
        out = build_surface_queue(
            [_item()], [], surface="questions", today="2026-07-25", timezone=None
        )
        assert "questions" in out and "activity" not in out

    def test_valid_surfaces_vocabulary(self):
        assert {"questions", "activity", "both"} == VALID_SURFACES
