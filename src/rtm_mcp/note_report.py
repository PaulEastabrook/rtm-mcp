"""Note-shape hygiene as a read — the builder behind `gtd_note_report`.

Retires the surviving half of gtd's `validate-note.py`, whose `notes-audit` agent shelled out
**one subprocess per note**. Twelve of its sixteen checks were already redundant by 2026-08-02:
the server *constructs* those shapes rather than validating them, so there is nothing left for a
post-hoc check to catch. What remains is the audit half — judging notes that already exist,
including every note written before the gates went on and every note Paul typed into the RTM app
— and that is a read, over one broad `getList`, not 490 subprocesses.

**The checks are the write gate's own, run in reverse.** `note_shape.check_title` /
`check_type` / `check_contract` are the same functions `add_note` is gated by, so the audit and
the gate can never disagree about what conformant means — the alternative is two grammars kept
in step by hand, which is the drift `note_types.py` exists to prevent. The one check with no
write-side twin is the FILING path (`gtd_writes.check_filing_path`), which the OUTPUT-note
grammar owns.

**The free-text rule is normative and survives the port** (`note_shape`'s module docstring):

    no date prefix          →  Paul typed it in the RTM app. INFORMATIONAL, never a finding.
    date-prefixed, bad TYPE →  agent-written. THAT is the finding.

The data separates cleanly — agent-written notes always carry the `YYYY-MM-DD — TYPE —` prefix —
and getting this backwards would bury the real findings under Paul's own prose. `free_text` is
counted and returned so the split is visible rather than merely asserted.

Pure (no IO): the caller supplies the parsed tasks.
"""

from __future__ import annotations

from typing import Any

from .gtd_chat import (
    _COMPANION_MARKER_RE,
    _filing_payloads,
    is_bare_path,
    is_legacy_unfiled,
)
from .gtd_writes import check_filing_path
from .note_shape import check_contract, check_title, check_type
from .parsers import extract_note_body
from .project_plan import _norm_date, _permalink

#: Every finding class, so "what can this report say?" is answered by a constant rather than by
#: reading the loop. `free_text` is deliberately NOT here — it is the informational bucket.
FINDING_CLASSES = ("shape", "vocabulary", "chat_title", "order_contract", "filing_path")


def _filing_findings(body: str) -> str | None:
    """Judge the `FILING:` lines of a note body. Returns a reason, or None.

    Deliberately shape-only and OUTPUT-agnostic: any note carrying a FILING line is making a
    machine-readable claim, and a malformed path breaks the same readers wherever it sits.
    Whether the *artefact* exists is `gtd_note_filing_gaps`' question, not this one's — this
    read is RTM-only and must stay answerable with no vault.

    **This is the class that owns "the payload is a sentence, not a path"** (the eleventh
    dialect — see `gtd_chat.is_bare_path`). It reported `filing_path: 0` on the live estate while
    `linked_missing` was reporting a whole sentence as a missing artefact: the boundary was drawn
    correctly and the check was simply not strict enough to fire.

    Consumes `gtd_chat._filing_payloads` — the same line-walker `parse_filings` uses — rather
    than a second walk, so the two-line labelled-continuation form is handled identically here
    and there. A third parser is what this programme keeps refusing to write.

    The legacy `(unfiled)` form is skipped: `gtd_note_filing_gaps.legacy_unfiled` owns it, and
    duplicating a known migration backlog across two reports is noise, not coverage.
    """
    bad: list[str] = []
    for raw in _filing_payloads(body):
        if not raw or is_legacy_unfiled(raw):
            continue
        path = _COMPANION_MARKER_RE.sub("", raw).strip()
        err = check_filing_path(path)
        if err:
            bad.append(f"'{path}': {err}")
        elif not is_bare_path(path):
            bad.append(
                f"'{path}': the FILING payload is a sentence, not a bare vault-relative path "
                "(it does not end in a file extension). Put the path alone on the line; any "
                "commentary belongs in the note body."
            )
    return "; ".join(bad) if bad else None


def build_note_report(
    parsed: list[dict[str, Any]], *, timezone: str | None = None, max_rows: int = 200
) -> dict[str, Any]:
    """Classify every note on *parsed* against the write gate's own grammar.

    *max_rows* caps each class's ``rows``; ``count`` is always the true total and ``truncated``
    says when the sample is short — a silently capped report reads as full coverage.
    """
    by_id = {str(t.get("id") or ""): t for t in parsed}
    buckets: dict[str, list[dict[str, Any]]] = {c: [] for c in FINDING_CLASSES}
    free_text = 0
    scanned = 0

    for task in parsed:
        for note in task.get("notes") or []:
            scanned += 1
            raw = extract_note_body(note) or ""
            explicit = (note.get("title") or "").strip()
            title, rest = (explicit, raw) if explicit else _split_first_line(raw)

            shape = check_title(title)
            if shape is not None:
                # THE FREE-TEXT RULE. A note with no date prefix is Paul's own; reporting it
                # would bury the agent-written findings under his prose.
                if not _date_prefixed(title):
                    free_text += 1
                    continue
                buckets["shape"].append(_row(task, note, title, shape, timezone, by_id))
                continue

            vocab = check_type(title)
            if vocab is not None:
                buckets["vocabulary"].append(_row(task, note, title, vocab, timezone, by_id))
                continue

            contract = check_contract(title, rest)
            if contract is not None:
                kind, reason = contract
                buckets[kind].append(_row(task, note, title, reason, timezone, by_id))

            filing = _filing_findings(rest)
            if filing is not None:
                buckets["filing_path"].append(_row(task, note, title, filing, timezone, by_id))

    findings = {
        name: {
            "count": len(rows),
            "rows": rows[:max_rows],
            "truncated": len(rows) > max_rows,
        }
        for name, rows in buckets.items()
    }
    return {
        "notes_scanned": scanned,
        "free_text_count": free_text,
        "finding_count": sum(len(r) for r in buckets.values()),
        "findings": findings,
        "free_text_rule": (
            "A note with no date prefix was typed by Paul in the RTM app and is never a "
            "finding — it is counted in free_text_count and excluded from findings."
        ),
    }


def _split_first_line(raw: str) -> tuple[str, str]:
    """RTM stores a note as `title\\ntext` and returns an empty title, so line 1 IS the title."""
    first, _, rest = (raw or "").partition("\n")
    return first, rest


def _date_prefixed(title: str) -> bool:
    """Whether the title opens with a `YYYY-MM-DD` stamp — the agent-vs-human discriminator.

    Deliberately looser than `note_shape._TITLE_RE`: a title that is *trying* to be conformant
    and failing is agent-written and must be reported, which is exactly the case the strict
    regex rejects.
    """
    head = (title or "").strip()[:10]
    return len(head) == 10 and head[4] == "-" and head[7] == "-" and head.replace("-", "").isdigit()


def _row(
    task: dict[str, Any],
    note: dict[str, Any],
    title: str,
    reason: str,
    timezone: str | None,
    by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task_id": str(task.get("id") or ""),
        "task_name": task.get("name") or "",
        "note_id": str(note.get("id") or ""),
        "note_title": title,
        "reason": reason,
        "created": _norm_date(note.get("created"), timezone),
        "deep_link": _permalink(str(task.get("id") or ""), by_id, task.get("list_id")),
    }
