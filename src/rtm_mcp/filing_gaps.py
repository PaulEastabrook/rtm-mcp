"""Output-filing reconciliation — the read behind `gtd_note_filing_gaps`.

**This server is the only process that can see both sides.** agent-memory-mcp holds no RTM
token; RTM holds no vault. So the join between an OUTPUT note and the artefact it claims lives
here, and computing it in code rather than having an agent eye two tool outputs is the whole
point: a reconciliation an LLM performs by reading notes is a fresh error opportunity per run;
computed identically every time, it is a fact.

Seven finding classes, each with rows rather than only a count. The baselines are the
2026-08-01 reconciliation's, across 104 OUTPUT notes and 171 companion-tracked artefacts:

======================  ====================================================  ===============
class                   what it is                                            baseline
======================  ====================================================  ===============
`linked_missing`        an OUTPUT note's `FILING:` path resolves to nothing    4
`filed_unlinked`        a tracked artefact no OUTPUT note references           97 of 126
`companion_missing`     an artefact that resolves but carries no companion     11 of 40 sampled
`join_unpopulated`      a companion with no / mismatched `source_action`       0 of 40 populated
`prose_path`            an OUTPUT note with no machine-readable FILING line    67 of 104
`register_defect`       duplicate registers, or a non-conformant title         1 dup, 4 titles
`legacy_unfiled`        pre-v6.4.0 `FILING: <path> (unfiled)`                  3 (all fixtures)
======================  ====================================================  ===============

`legacy_unfiled` (v6.5.0) is a **migration backlog with a natural end state**, which is why it
is its own class rather than folded into a neighbour. It is not `linked_missing` — nothing is
missing, nothing was ever filed — and it is not `prose_path`, because the note DOES carry a
FILING line. Filing it under a description that does not fit is how vocabularies rot.

The two root causes those numbers share are worth restating, because they explain why five of
the six classes exist at all. **The join key is a location** — `FILING: work/…/x.md` records
where a file *was*, so the 18 July vault reorganisation invalidated four pointers that were
correct when written, with nothing watching. And **filing and journalling were two unbound
acts**, so 77% of the time the second was skipped. v6.4.0's gate closes the second going
forward; this read is how the standing backlog stays visible rather than assumed gone.

**An absent vault produces a PARTIAL result, never a clean one.** Every class that needs the
vault is NAMED in ``gaps[]`` and emitted as ``null`` rather than ``0`` — the `gtd_engine_report`
precedent. A reconciliation that says "zero drift" because nothing was mounted is worse than one
that refuses to answer.

Pure (no IO of its own beyond the vault listing handed in) and RTM-free: the caller supplies the
parsed tasks and the walked artefacts, so the builder is deterministic and testable.
"""

from __future__ import annotations

from typing import Any

from .filing_gate import SOURCE_ACTION_FIELD
from .gtd_chat import legacy_unfiled_paths, parse_output_note
from .gtd_reads import parse_note_type
from .gtd_writes import LEGACY_OUTPUTS_PREFIX, is_outputs_register
from .note_shape import effective_title
from .parsers import extract_note_body
from .project_plan import _norm_date, _permalink

#: Default per-class row cap. Generous, because the baseline population is large (97 orphans on
#: one class alone) and a report that silently shows a tenth of its own findings is misleading in
#: exactly the way this tool exists to fix. `truncated` is emitted regardless.
FILING_GAPS_DEFAULT_ROWS = 200

#: Every class this read can report. Named as a constant so the "which are underivable without a
#: vault?" question is answered by set arithmetic rather than by a second hand-maintained list.
FINDING_CLASSES = (
    "linked_missing",
    "filed_unlinked",
    "companion_missing",
    "join_unpopulated",
    "prose_path",
    "register_defect",
    "legacy_unfiled",
)

#: The classes that need the vault. `prose_path`, `register_defect` and `legacy_unfiled` are
#: RTM-only, which is why a vault-less run still returns something useful rather than nothing.
VAULT_DEPENDENT = ("linked_missing", "filed_unlinked", "companion_missing", "join_unpopulated")

#: A note that mentions a path in prose rather than on a `FILING:` line. Ten mutually
#: incompatible dialects were counted live, so this does NOT try to parse them — it detects that
#: a path is *probably* being described and reports the note for a human. Detecting is the
#: server's job; interpreting ten dialects is not.
_PROSE_HINTS = ("filed", "filing", "saved to", "output/", "outputs/", ".md", ".xlsx", ".pdf")


def _rows_for(notes: list[dict[str, Any]] | None) -> list[tuple[dict[str, Any], str, str]]:
    """``(note, effective_title, body_after_title)`` for each note — the shape every scan needs."""
    out = []
    for n in notes or []:
        raw = extract_note_body(n) or ""
        title = effective_title(n.get("title") or "", raw)
        _, _, rest = raw.partition("\n")
        out.append((n, title, rest))
    return out


def build_filing_gaps(
    parsed: list[dict[str, Any]],
    *,
    artefacts: list[dict[str, Any]] | None,
    timezone: str | None = None,
    max_rows: int = 200,
) -> dict[str, Any]:
    """Reconcile RTM's OUTPUT notes against the vault's tracked artefacts.

    *artefacts* is `companion.walk_artefacts`' output — ``None`` when no vault resolved, which
    is what drives the partial result. *max_rows* caps each class's ``rows`` list; the count is
    always the true total and ``truncated`` says when the sample is short, because a silently
    capped report reads as complete coverage.
    """
    by_id = {str(t.get("id") or ""): t for t in parsed}
    have_vault = artefacts is not None
    tracked = {a["path"]: a for a in (artefacts or [])}

    linked: list[dict[str, Any]] = []
    prose: list[dict[str, Any]] = []
    companion_missing: list[dict[str, Any]] = []
    join_gaps: list[dict[str, Any]] = []
    register_defects: list[dict[str, Any]] = []
    legacy_unfiled: list[dict[str, Any]] = []
    referenced: set[str] = set()

    for task in parsed:
        tid = str(task.get("id") or "")
        for note, title, rest in _rows_for(task.get("notes")):
            _, note_type, _ = parse_note_type(title)
            if note_type == "OUTPUT":
                # The pre-v6.4.0 declaration of absence, reported BEFORE the prose fallback:
                # nothing is missing, nothing was ever filed. Classifying it `linked_missing`
                # sends a reader hunting a file that was never meant to exist — and it is not
                # `prose_path` either, since the note DOES carry a FILING line.
                for stale in legacy_unfiled_paths(rest):
                    legacy_unfiled.append(
                        _note_row(
                            task,
                            note,
                            title,
                            timezone,
                            by_id,
                            path=stale,
                            detail="pre-v6.4.0 `FILING: <path> (unfiled)` — a declaration that "
                            "nothing was filed, written before `unfiled=True` existed. Re-file "
                            "the artefact and journal it, or re-journal with unfiled=True.",
                        )
                    )
                rec = parse_output_note(note)
                paths = rec["paths"] if rec else []
                if not paths:
                    # A note carrying ONLY a legacy-unfiled line has been classified already;
                    # falling through would double-report it as prose.
                    if not legacy_unfiled_paths(rest) and _looks_like_prose_path(rest):
                        prose.append(_note_row(task, note, title, timezone, by_id))
                    continue
                for path in paths:
                    referenced.add(path)
                    if not have_vault:
                        continue
                    entry = tracked.get(path)
                    if entry is None:
                        linked.append(_note_row(task, note, title, timezone, by_id, path=path))
                    elif entry.get("meta") is None:
                        companion_missing.append(
                            _note_row(task, note, title, timezone, by_id, path=path)
                        )
                    else:
                        gap = _join_gap(entry["meta"], tid)
                        if gap:
                            join_gaps.append(
                                _note_row(task, note, title, timezone, by_id, path=path, detail=gap)
                            )
            elif is_outputs_register(title):
                defect = _register_defect(title)
                if defect:
                    register_defects.append(
                        _note_row(task, note, title, timezone, by_id, detail=defect)
                    )
        register_defects.extend(_duplicate_registers(task, timezone, by_id))

    # TRACKED artefacts only — `meta is not None`. The class means "the file store says this is
    # filed, and nothing journalled it", so an untracked file is a different finding and is
    # counted separately as `untracked_unlinked_count`.
    #
    # The filter was missing at v6.4.0 and the first live run showed why it matters: 2,704 rows
    # against a measured baseline of 97, because `walk_artefacts` enumerates every file in the
    # vault — `.auto-memory/` caches, `.bak` files, Syncthing sync-conflict artefacts. A class
    # whose whole value is that its findings are real was ~96% noise, which is worse than not
    # reporting it. The two sets also overlapped, contradicting the disjointness the comment
    # below asserts; with the filter they are disjoint by construction, as intended.
    filed_unlinked = (
        [
            {"path": p, "companion": True}
            for p, a in sorted(tracked.items())
            if p not in referenced and a.get("meta") is not None
        ]
        if have_vault
        else []
    )
    # An untracked artefact is reported ONCE. It is `companion_missing` when an OUTPUT note
    # points at it (the note is the actionable end) and `filed_unlinked` otherwise — the two
    # sets are disjoint by construction, so a total across classes never double-counts.
    orphan_untracked = (
        [
            {"path": p, "companion": False}
            for p, a in sorted(tracked.items())
            if p not in referenced and a.get("meta") is None
        ]
        if have_vault
        else []
    )

    findings = {
        "linked_missing": linked,
        "filed_unlinked": filed_unlinked,
        "companion_missing": companion_missing,
        "join_unpopulated": join_gaps,
        "prose_path": prose,
        "register_defect": register_defects,
        "legacy_unfiled": legacy_unfiled,
    }
    out: dict[str, Any] = {
        "vault_present": have_vault,
        "artefacts_scanned": len(tracked) if have_vault else None,
        "output_notes_scanned": sum(
            1
            for t in parsed
            for _, ti, _ in _rows_for(t.get("notes"))
            if parse_note_type(ti)[1] == "OUTPUT"
        ),
        "untracked_unlinked_count": len(orphan_untracked) if have_vault else None,
        "findings": {},
        "gaps": [] if have_vault else list(VAULT_DEPENDENT),
    }
    for name in FINDING_CLASSES:
        rows = findings[name]
        derivable = have_vault or name not in VAULT_DEPENDENT
        out["findings"][name] = {
            # NEVER 0 when underivable — a zero would read as "clean" (the `gtd_engine_report`
            # rule). `gaps[]` names it; this says the same thing structurally.
            "count": len(rows) if derivable else None,
            "rows": rows[:max_rows] if derivable else [],
            "truncated": derivable and len(rows) > max_rows,
        }
    return out


def _looks_like_prose_path(body: str) -> bool:
    low = (body or "").lower()
    return any(h in low for h in _PROSE_HINTS)


def _join_gap(meta: dict[str, Any], task_id: str) -> str | None:
    raw = meta.get(SOURCE_ACTION_FIELD)
    values = [str(v).strip() for v in (raw if isinstance(raw, list) else [raw]) if v]
    if not values:
        return f"companion carries no `{SOURCE_ACTION_FIELD}`"
    if task_id and not any(task_id in v for v in values):
        return f"`{SOURCE_ACTION_FIELD}` ({', '.join(values)}) does not name task {task_id}"
    return None


def _register_defect(title: str) -> str | None:
    """A register title that is not the catalogue form is a finding, not a failure."""
    _, note_type, summary = parse_note_type(title)
    if note_type != "OUTPUTS":
        return (
            f"register title '{title}' uses the legacy '{LEGACY_OUTPUTS_PREFIX} <name>' form; "
            "the catalogue form is 'YYYY-MM-DD — OUTPUTS — <project name>'"
        )
    if not summary:
        return "register title carries no project name"
    return None


def _duplicate_registers(
    task: dict[str, Any], timezone: str | None, by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    regs = [(n, ti) for n, ti, _ in _rows_for(task.get("notes")) if is_outputs_register(ti)]
    if len(regs) < 2:
        return []
    return [
        _note_row(
            task,
            n,
            ti,
            timezone,
            by_id,
            detail=f"{len(regs)} OUTPUTS registers on this project — the latest wins on read; "
            "the others are stale and must be merged or removed by hand",
        )
        for n, ti in regs
    ]


def _note_row(
    task: dict[str, Any],
    note: dict[str, Any],
    title: str,
    timezone: str | None,
    by_id: dict[str, dict[str, Any]],
    *,
    path: str = "",
    detail: str = "",
) -> dict[str, Any]:
    row = {
        "task_id": str(task.get("id") or ""),
        "task_name": task.get("name") or "",
        "note_id": str(note.get("id") or ""),
        "note_title": title,
        "created": _norm_date(note.get("created"), timezone),
        "deep_link": _permalink(str(task.get("id") or ""), by_id, task.get("list_id")),
    }
    if path:
        row["path"] = path
    if detail:
        row["detail"] = detail
    return row
