"""Unit tests for the collection/context read builders (today / next-actions / focus-projects / inbox / waiting / context)."""

from __future__ import annotations

from typing import Any

from rtm_mcp import contribution, note_shape, note_types, surface_queue
from rtm_mcp import gtd_reads as g

TODAY = "2026-07-23"


def _t(**k: Any) -> dict[str, Any]:
    return {
        "id": k.get("id", "1"),
        "taskseries_id": k.get("taskseries_id", "s1"),
        "list_id": k.get("list_id", "L1"),
        "name": k.get("name", ""),
        "due": k.get("due"),
        "start": k.get("start"),
        "completed": k.get("completed"),
        "priority": k.get("priority", "N"),
        "tags": k.get("tags", []),
        "notes": k.get("notes", []),
        "parent_task_id": k.get("parent_task_id"),
        "modified": k.get("modified"),
    }


def _note(title: str, created: str = "2026-07-20T00:00:00Z", body: str = "b") -> dict[str, Any]:
    return {"id": "n" + title[:4], "title": title, "$t": body, "created": created}


# --------------------------------------------------------------------------- #
# parse_note_type / classify_gtd_type
# --------------------------------------------------------------------------- #


def test_parse_note_type_grammar():
    assert g.parse_note_type("2026-07-20 — STATE — snap") == ("2026-07-20", "STATE", "snap")
    assert g.parse_note_type("2026-07-20 14:30 — CHAT — me — hi")[1] == "CHAT"
    assert g.parse_note_type("freeform note") == ("", "", "freeform note")


class TestHyphenatedTypesAreOneToken:
    """A TYPE containing a hyphen must not be split at its own hyphen.

    The defect this pins: `_NOTE_TITLE_RE` accepted a plain hyphen as the separator AND allowed
    zero whitespace around it, so the non-greedy TYPE group terminated at the type's own hyphen —
    `AI-LINK` parsed as type `AI`, summary `LINK — …`. It produced a **wrong answer rather than an
    error**, which is why it went unnoticed while two sibling parsers had already defended against it.
    """

    #: Every write-authorised type carrying an internal hyphen. Derived, not hand-listed — a new
    #: hyphenated type joins this test automatically.
    HYPHENATED = sorted(t for t in note_types.WRITE_AUTHORISED_NOTE_TYPES if "-" in t)

    def test_the_sample_set_is_not_empty(self):
        """Guard-the-guard: if no write-authorised type contained a hyphen, every assertion below
        would pass vacuously against the very regex that had the bug."""
        assert len(self.HYPHENATED) >= 6
        assert "AI-LINK" in self.HYPHENATED

    def test_every_hyphenated_type_parses_whole(self):
        for ntype in self.HYPHENATED:
            date, parsed, summary = g.parse_note_type(f"2026-08-01 — {ntype} — a summary")
            assert parsed == ntype, f"{ntype} split to {parsed!r}"
            assert date == "2026-08-01"
            assert summary == "a summary"

    def test_the_exact_regression(self):
        """The reported case, spelled out — RTM 1220420600."""
        assert g.parse_note_type("2026-08-01 — AI-LINK — see also")[1] == "AI-LINK"

    def test_all_three_read_parsers_agree(self):
        """The invariant that would have caught this: three modules parse the same grammar, so a
        divergence between them is the defect. Reaching for the private regexes is deliberate —
        the agreement is the contract, and it has no public surface."""
        for ntype in self.HYPHENATED:
            title = f"2026-08-01 — {ntype} — a summary"
            reads = g._NOTE_TITLE_RE.match(title)
            contrib = contribution._TITLE_RE.match(title)
            surface = surface_queue._TYPE_RE.match(title)
            assert reads and contrib and surface, f"{ntype} unparsed by one of the three"
            assert reads.group(2) == contrib.group(2) == surface.group(1) == ntype

    def test_the_spaced_hyphen_separator_still_works(self):
        """The loosening the guard protects is retained — a plain hyphen IS a legal separator on the
        read path, so tightening must not have been achieved by simply banning it."""
        assert g.parse_note_type("2026-08-01 - PROGRESS - moved on")[1] == "PROGRESS"
        assert g.parse_note_type("2026-08-01 - AI-LINK - see also")[1] == "AI-LINK"

    def test_the_write_gate_is_safe_for_a_different_reason(self):
        """`note_shape` keeps `\\s*` and is correct: its separator class is em/en-dash only, so a
        type's hyphen can never be read as one. Pinned so nobody 'harmonises' the four grammars onto
        a single form and reintroduces the defect from the other direction."""
        assert note_shape.check_title("2026-08-01 — AI-LINK — see also") is None
        assert "-" not in note_shape._DASH  # the plain hyphen is NOT a write-gate separator


def test_classify_gtd_type_precedence():
    assert g.classify_gtd_type(["project", "action"]) == "project"
    assert g.classify_gtd_type(["waiting_for"]) == "waiting_for"
    assert g.classify_gtd_type(["action"]) == "action"


# --------------------------------------------------------------------------- #
# gtd_query
# --------------------------------------------------------------------------- #


def test_query_next_actions_attributes_context():
    tasks = [
        _t(id="1", name="Call plumber", tags=["action", "location_home"]),
        _t(id="2", name="Reply email", tags=["action", "conversation_email"]),
        _t(id="3", name="Anything", tags=["action"]),  # default → using_device
    ]
    out = g.build_query_next_actions(tasks, context=None, timezone=None)
    ctxs = {r["id"]: r["context"] for r in out["rows"]}
    assert ctxs == {"1": "location_home", "2": "conversation_email", "3": "using_device"}


def test_query_next_actions_context_filter():
    tasks = [
        _t(id="1", name="Home", tags=["action", "location_home"]),
        _t(id="2", name="Office", tags=["action", "location_office"]),
    ]
    out = g.build_query_next_actions(tasks, context="location_home", timezone=None)
    assert [r["id"] for r in out["rows"]] == ["1"]


def test_query_todays_field_sorted():
    tasks = [
        _t(id="1", name="Later", due="2026-07-23T00:00:00Z"),
        _t(id="2", name="Overdue", due="2026-07-20T00:00:00Z"),
    ]
    out = g.build_query_todays_field(tasks, timezone=None)
    assert [r["id"] for r in out["rows"]] == ["2", "1"]


def test_query_focus_projects_attribution():
    tasks = [
        _t(id="f", name="Area", tags=["focus"]),
        _t(id="p1", name="Proj1", tags=["project"], parent_task_id="f"),
        _t(id="p2", name="Loose", tags=["project"]),
    ]
    out = g.build_query_focus_projects(tasks, focus_id=None, timezone=None)
    by = {r["id"]: r for r in out["rows"]}
    assert by["p1"]["focus"] == "Area"
    assert by["p2"]["focus"] == "(unfiled)"


def test_query_focus_projects_scoped():
    tasks = [
        _t(id="f", name="Area", tags=["focus"]),
        _t(id="p1", name="Proj1", tags=["project"], parent_task_id="f"),
        _t(id="p2", name="Other", tags=["project"], parent_task_id="g"),
    ]
    out = g.build_query_focus_projects(tasks, focus_id="f", timezone=None)
    assert [r["id"] for r in out["rows"]] == ["p1"]


# --------------------------------------------------------------------------- #
# gtd_inbox_state
# --------------------------------------------------------------------------- #


def test_inbox_state_three_signals():
    tasks = [
        _t(id="1", name="raw"),
        _t(id="2", name="reviewing", tags=["ai_review"]),
        _t(id="3", name="approved", tags=["ai_approved"]),
    ]
    out = g.build_inbox_state(tasks, timezone=None)
    assert out["depth"] == 3
    assert out["unprocessed_count"] == 1
    assert out["awaiting_review_count"] == 1
    assert out["approved_unapplied_count"] == 1


# --------------------------------------------------------------------------- #
# gtd_waiting_for_queue
# --------------------------------------------------------------------------- #


def test_waiting_for_staleness_and_sort():
    tasks = [
        _t(
            id="1",
            name="Fresh",
            tags=["waiting_for"],
            modified="2026-07-22T00:00:00Z",
            due="2026-07-30T00:00:00Z",
        ),
        _t(
            id="2",
            name="Stale",
            tags=["waiting_for"],
            modified="2026-07-01T00:00:00Z",
            due="2026-08-01T00:00:00Z",
        ),
    ]
    out = g.build_waiting_for_queue(tasks, today=TODAY, timezone=None)
    assert out["stale_count"] == 1
    # stale first
    assert [r["id"] for r in out["rows"]] == ["2", "1"]
    by = {r["id"]: r for r in out["rows"]}
    assert by["2"]["stale"] is True and by["1"]["stale"] is False


# --------------------------------------------------------------------------- #
# gtd_item_context
# --------------------------------------------------------------------------- #


def test_resolve_task_ref_by_id_name_and_miss():
    tasks = [_t(id="10", name="Alpha"), _t(id="11", name="Beta")]
    assert g.resolve_task_ref(tasks, "10")["task"]["id"] == "10"
    assert g.resolve_task_ref(tasks, "alpha")["task"]["id"] == "10"
    assert g.resolve_task_ref(tasks, "nope") == {}


def test_resolve_task_ref_ambiguous_candidates():
    tasks = [_t(id="1", name="Review the doc"), _t(id="2", name="Review the deck")]
    res = g.resolve_task_ref(tasks, "review")
    assert "candidates" in res and len(res["candidates"]) == 2


def test_context_bundle_state_first_and_relations():
    parent = _t(
        id="p", name="Project", tags=["project"], notes=[_note("2026-07-10 — STATE — proj snap")]
    )
    task = _t(
        id="t",
        name="Action",
        tags=["action"],
        parent_task_id="p",
        notes=[
            _note("2026-07-01 — PROGRESS — did a thing", created="2026-07-01T00:00:00Z"),
            _note("2026-07-15 — STATE — latest", created="2026-07-15T00:00:00Z"),
        ],
    )
    sibling = _t(id="s", name="Sibling", tags=["action"], parent_task_id="p")
    parsed = [parent, task, sibling]
    out = g.build_context(parsed, task, depth="medium", timezone=None)
    assert out["task"]["gtd_type"] == "action"
    # STATE note ordered first
    assert out["notes"][0]["type"] == "STATE"
    # medium → siblings + ancestors present
    assert [s["id"] for s in out["siblings"]] == ["s"]
    assert any(a["id"] == "p" for a in out["ancestors"])


def test_context_shallow_omits_relations():
    task = _t(id="t", name="A", tags=["action"], parent_task_id="p")
    parsed = [
        _t(id="p", name="P", tags=["project"]),
        task,
        _t(id="s", name="Sib", parent_task_id="p"),
    ]
    out = g.build_context(parsed, task, depth="shallow", timezone=None)
    assert out["siblings"] == []
    assert out["ancestors"] == []


def test_context_deep_includes_bodies():
    task = _t(id="t", name="A", tags=["action"], notes=[_note("2026-07-01 — DECISION — chose X")])
    out = g.build_context([task], task, depth="deep", timezone=None)
    assert out["notes"][0]["body"] == "b"  # full bodies at deep
    shallow = g.build_context([task], task, depth="shallow", timezone=None)
    assert shallow["notes"][0]["body"] == ""
