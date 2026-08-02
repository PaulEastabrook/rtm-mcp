"""The note-shape audit read (v6.4.0, `gtd_note_report`).

Two properties carry this file. **The free-text rule** — a note with no date prefix is Paul's
own and is never a finding — because inverting it buries every real finding under his prose.
And **the audit uses the write gate's own functions**, so the two cannot drift; that is asserted
by object identity, not by comparing two lists that happen to agree today.
"""

from rtm_mcp import note_shape
from rtm_mcp.note_report import FINDING_CLASSES, build_note_report


def _note(nid, title, body=""):
    return {
        "id": nid,
        "title": "",
        "$t": title if not body else f"{title}\n{body}",
        "created": "2026-07-20T00:00:00Z",
    }


def _task(tid, notes):
    return {
        "id": tid,
        "taskseries_id": f"ts{tid}",
        "list_id": "1",
        "name": f"Task {tid}",
        "parent_task_id": "",
        "tags": ["work", "action"],
        "notes": notes,
        "completed": "",
    }


def _report(*notes):
    return build_note_report([_task("1", list(notes))])


class TestTheFreeTextRule:
    """Normative (`note_shape`'s module docstring), and the reason the audit is usable at all."""

    def test_a_note_with_no_date_prefix_is_never_a_finding(self):
        out = _report(_note("n1", "Just something Paul typed into the RTM app"))
        assert out["finding_count"] == 0
        assert out["free_text_count"] == 1

    def test_a_date_prefixed_note_with_a_bad_type_IS_the_finding(self):
        out = _report(_note("n2", "2026-07-20 — WIDGET — invented"))
        assert out["findings"]["vocabulary"]["count"] == 1
        assert out["free_text_count"] == 0

    def test_a_date_prefixed_note_that_fails_to_parse_is_a_shape_finding(self):
        """Deliberately looser than the strict title regex: a title *trying* to be conformant
        and failing is agent-written, which is exactly the case the strict regex rejects."""
        out = _report(_note("n3", "2026-07-20 - NOTYPE no em-dashes here"))
        assert out["findings"]["shape"]["count"] == 1
        assert out["free_text_count"] == 0

    def test_the_rule_is_stated_in_the_payload(self):
        assert "never a finding" in _report()["free_text_rule"]


class TestTheContractTier:
    def test_a_malformed_chat_title_is_reported(self):
        out = _report(_note("n4", "2026-07-20 — CHAT — no role or time"))
        assert out["findings"]["chat_title"]["count"] == 1

    def test_a_well_formed_chat_title_is_clean(self):
        out = _report(_note("n5", "2026-07-20 09:30 — CHAT — me — Proj", "hello"))
        assert out["finding_count"] == 0

    def test_a_non_conformant_order_note_is_reported(self):
        out = _report(_note("n6", "2026-07-20 09:30 — ORDER — 2 items", '{"schema":"nope"}'))
        assert out["findings"]["order_contract"]["count"] == 1

    def test_a_conformant_order_note_is_clean(self):
        from rtm_mcp.order_note import make

        title, body = make(["1", "2"], "board-commit", "2026-07-20T09:30:00Z", "2026-07-20 09:30")
        out = _report(_note("n7", title, body))
        assert out["finding_count"] == 0


class TestFilingPathShape:
    def test_an_absolute_filing_path_is_reported(self):
        out = _report(_note("n8", "2026-07-20 — OUTPUT — x", "n\n\nFILING: /abs/a.md"))
        assert out["findings"]["filing_path"]["count"] == 1

    def test_a_sentence_on_a_filing_line_is_reported(self):
        """v6.5.1 — this class's whole purpose, and it reported ZERO on the live estate while
        `gtd_note_filing_gaps.linked_missing` was reporting the same sentence as a missing
        artefact. The boundary was drawn correctly; the check was not strict enough to fire."""
        observed = (
            "work/…/principal-engineer-role-rr-draft-v0.1.md (companion metadata: "
            "principal-engineer-role-rr-draft-v0.1.meta.md) — filed alongside the sibling docs."
        )
        out = _report(_note("n11", "2026-07-20 — OUTPUT — x", f"n\n\nFILING: {observed}"))
        rows = out["findings"]["filing_path"]["rows"]
        assert len(rows) == 1 and "sentence, not a bare vault-relative path" in rows[0]["reason"]

    def test_a_real_path_with_spaces_is_NOT_reported(self):
        """The load-bearing regression, quoting a real live filename."""
        real = "work/hiring/Simon Meek - Flexible working application form (signed).docx"
        out = _report(_note("n12", "2026-07-20 — OUTPUT — x", f"n\n\nFILING: {real}"))
        assert out["findings"]["filing_path"]["count"] == 0

    def test_the_legacy_unfiled_form_is_left_to_its_own_class(self):
        """`gtd_note_filing_gaps.legacy_unfiled` owns it; duplicating a known migration backlog
        across two reports is noise, not coverage."""
        out = _report(_note("n13", "2026-07-20 — OUTPUT — x", "n\n\nFILING: work/a.md (unfiled)"))
        assert out["findings"]["filing_path"]["count"] == 0

    def test_the_companion_marker_and_the_continuation_form_are_tolerated(self):
        """The two-line labelled form is a legal catalogue § 3 shape, not a malformed path — a
        dangling FILING line belongs to the two-line parser, not to this check."""
        out = _report(
            _note("n9", "2026-07-20 — OUTPUT — x", "n\n\nFILING: work/a.md (+ .meta.md)"),
            _note("n10", "2026-07-20 — OUTPUT — y", "n\n\nFILING: —\nwork/b.md"),
        )
        assert out["findings"]["filing_path"]["count"] == 0


class TestTheAuditCannotDriftFromTheGate:
    def test_it_uses_the_gates_own_functions(self):
        """Object identity, not value equality: a copy-pasted second grammar would pass a
        value comparison happily on the day it was written and drift the week after."""
        import rtm_mcp.note_report as nr

        assert nr.check_title is note_shape.check_title
        assert nr.check_type is note_shape.check_type
        assert nr.check_contract is note_shape.check_contract

    def test_every_class_is_reachable(self):
        """Guard-the-guard: a class that can never fire is a check that has gone dead."""
        from rtm_mcp.order_note import make

        title, _ = make(["1"], "board-commit", "2026-07-20T09:30:00Z", "2026-07-20 09:30")
        out = _report(
            _note("a", "2026-07-20 - broken"),
            _note("b", "2026-07-20 — WIDGET — invented"),
            _note("c", "2026-07-20 — CHAT — bad"),
            _note("d", title, "not json"),
            _note("e", "2026-07-20 — OUTPUT — x", "n\n\nFILING: /abs.md"),
        )
        dead = [c for c in FINDING_CLASSES if out["findings"][c]["count"] == 0]
        assert dead == [], f"unreachable classes: {dead}"


class TestTruncationIsAnnounced:
    def test_rows_are_capped_but_the_count_stays_true(self):
        notes = [_note(str(i), f"2026-07-20 — WIDGET — n{i}") for i in range(5)]
        out = build_note_report([_task("1", notes)], max_rows=2)
        vocab = out["findings"]["vocabulary"]
        assert vocab["count"] == 5 and len(vocab["rows"]) == 2 and vocab["truncated"] is True
