"""Pure (no-IO) builder for `gtd_surface_queue` — the AI-surface eligibility read.

Replaces `ai-surface-scan-questions.ms` + `ai-surface-scan-activity.ms` (one tool, a `surface`
scope parameter) and does the work those scripts left to the caller: parses each item's body
frontmatter, and derives the two signals the scan actually branches on (`auto_close_due`,
`response_detected`).

**Not a port — built to the consumer's need.** `agents/ai-surface-scan.md` §§ 3b/3c issue one
`get_task_notes` PER eligible item and parse the YAML themselves, immediately upstream of the
decisions that YAML drives. There is no output-parity oracle (designed change D1): the scripts
carried the library-wide defect classes recorded in `references/milkscript-api-surface.md`.

Three things the live estate settled (measured 2026-07-25, Paul's production account):

1. **Absent frontmatter is the common case, not the edge case.** 11 of 77 eligible `AI_Questions`
   items carry a frontmatter block; 7 of 52 `AI_Activity` items carry `auto_close_at`. Items
   published before v2.8.0 through the old composition path have none. So a row NEVER drops for
   want of metadata — it returns with null fields and `metadata_parse_error` set, and the 45
   `AI_Activity` items that can never auto-close are visible rather than silently absent.

2. **`response_detected` is INCLUSION-based, and that diverges from the brief.** The brief
   specified detection by *exclusion* against `note-shape-catalogue.md` § 2 — a note whose title
   type is not a system type. Measured against the live lists that rule is unusable: all 44
   notes on eligible items whose titles do not parse as `YYYY-MM-DD — TYPE — …` are
   engine-authored (13 frontmatter delimiters, 21 bare `AI-LINK`, 10 one-off engine run logs),
   and the parsed-but-off-catalogue types (`Q`, `Q-BODY`, `Q-UPDATE`, `UPDATE`, `QUESTION`, `A`,
   `META QUESTION` — 50 notes) are engine-authored too. Exclusion would fire on essentially
   every item. Zero Paul-typed free-text notes exist on the eligible set; where Paul HAS
   answered, the engine transcribed it as a typed `ANSWER` / `RESPONSE` / `REPLY` / `DECISION`
   note. A false positive costs a wrong resolve; a false negative costs one scan's delay — so
   precision wins. The exclusion signal is not discarded: it is reported, quarantined, as
   `unrecognised_notes` for the agent to judge.

3. **Completed-but-not-terminally-tagged items must be in scope.** `ai-surface-scan.md` § 3b.2
   names "closure-with-response" (Paul answered and completed in one action) as a detection
   path; the `.ms` eligibility was `status:incomplete`, which makes that path unreachable. The
   tool layer widens the read to completed items lacking the terminal lifecycle tag — measured
   cost: 3 rows on `AI_Questions`, 4 on `AI_Activity`.

The boundary, stated once and repeated in the tool description: **the server detects that a
response EXISTS; the agent decides what it MEANS.** Intent parsing against
`expected_response_shape` stays agent-side.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from .gtd_writes import (
    AI_ACTIVITY_LIST,
    AI_ACTIVITY_TAG,
    AUTO_CLOSED,
    CLAUDE_QUESTION,
    Q_ACKNOWLEDGED,
    Q_ANSWERED,
    Q_PROCESSED,
    SURFACE_TYPE_TAG,
)
from .parsers import extract_note_body
from .project_plan import _permalink

#: The `surface` scope vocabulary (advertised as an advisory enum; asserted equal in
#: test_tool_schemas). `both` is load-bearing — the scan processes both lists per run.
VALID_SURFACES = frozenset({"questions", "activity", "both"})

#: Eligibility filters. Verbatim from the two `.ms` headers EXCEPT the status clause, which is
#: widened so the closure-with-response path (§ 3b.2) is reachable — see the module header.
QUESTIONS_FILTER = (
    "list:AI_Questions AND tag:claude_question AND (status:incomplete OR status:completed) "
    "AND NOT tag:test AND NOT tag:q_processed"
)
ACTIVITY_FILTER = (
    "list:AI_Activity AND tag:ai_activity AND (status:incomplete OR status:completed) "
    "AND NOT tag:test AND NOT tag:q_acknowledged AND NOT tag:auto_closed"
)

#: `note-shape-catalogue.md` § 2, codified. The server is standalone and cannot read the
#: marketplace markdown at runtime, so the vocabulary is a constant here exactly as the engage
#: verdict grammar is in `engage_commit.py` — codification before validation. The CATALOGUE
#: remains the authority; a change there is a lockstep change here.
CATALOGUE_NOTE_TYPES = frozenset(
    {
        "INCEPTION",
        "CONTEXT",
        "DECISION",
        "PROGRESS",
        "COMPLETION",
        "CASCADE",
        "STATE",
        "SESSION",
        "BLOCKER",
        "SOURCE",
        "SOURCE-DRAFT",
        "AI ANALYSIS",
        "CONTRIB",
        "CONTRIB-UPDATE",
        "CHAT",
        "PREP",
        "OUTCOME",
        "OUTPUT",
        "OUTPUTS",
        "DEPENDS-ON",
        "AI-LINK",
        "COMMIT",
        "ORDER",
        "STEER",
        "TMPL-CHILD",
    }
)

#: Engine-authored note types seen on the AI-surface lists that are NOT registered in the
#: catalogue. `QUESTION`/`ALERT`/`NOTIFICATION`/`SURFACE`/`ACTIVITY_REPORT` are written TODAY by
#: this server's own `gtd_surface_create` (the body-note title is `<date> — <ITEM_TYPE> — …`);
#: the single-letter and `Q-*` forms are the pre-v2.8.0 composition path. All are live on the
#: lists now (measured 2026-07-25). Registering these in `note-shape-catalogue.md` § 2 is a
#: gtd-side follow-up — `validate-note.py` would reject the server's own writes today.
SURFACE_NOTE_TYPES = frozenset(
    {
        "QUESTION",
        "ALERT",
        "NOTIFICATION",
        "SURFACE",
        "ACTIVITY_REPORT",
        "Q",
        "A",
        "N",
        "S",
        "AR",
        "Q-BODY",
        "Q-UPDATE",
        "UPDATE",
        "META QUESTION",
    }
)

SYSTEM_NOTE_TYPES = CATALOGUE_NOTE_TYPES | SURFACE_NOTE_TYPES

#: A note carrying one of these types records Paul's answer. Observed live on every item that
#: has ever reached `#q_answered` / `#q_processed`; `DECISION` is also a catalogue journalling
#: type, and on a surface item a decision IS the response, so the response test runs first.
RESPONSE_NOTE_TYPES = frozenset({"ANSWER", "RESPONSE", "REPLY", "DECISION"})

#: `response_detected` evidence paths — a closed vocabulary so the agent can branch on it.
RESPONSE_PATHS = frozenset({"q_answered_tag", "completed_unresolved", "response_note"})

_FRONTMATTER_FENCE = "---"
#: The frontmatter block opens within the first few lines: line 1 when the note was written with
#: an empty title (the pre-v2.8.0 path), line 2 when it carries the standard title line.
_FENCE_SEARCH_LINES = 3

#: The note-title TYPE extractor used for classification. Self-contained rather than reusing
#: `gtd_reads.parse_note_type`, for two measured reasons:
#:  * that helper's TYPE token is `[A-Z][A-Z /-]*` and its separator alternation admits a
#:    bare hyphen, so non-greedy matching splits a HYPHENATED type at its own hyphen: `AI-LINK` parses
#:    as type `AI`, and likewise `DEPENDS-ON`, `SOURCE-DRAFT`, `CONTRIB-UPDATE`, `TMPL-CHILD`.
#:    Requiring the separator to carry surrounding WHITESPACE (which `note-shape-catalogue.md`
#:    § 1 mandates) disambiguates it. Pre-existing and out of scope to change here — it would
#:    alter `gtd_item_context` output — flagged in the v2.9.0 debrief.
#:  * § 1's TYPE token excludes the UNDERSCORE, yet this server's own `gtd_surface_create`
#:    writes `<date> — ACTIVITY_REPORT — <summary>` for the fifth item type. That title fails
#:    § 1 outright (`note_shape.check_title` rejects it, so with RTM_STRICT_NOTES=shape the
#:    write would be BLOCKED). Classification must reflect what is actually on the lists.
_TYPE_RE = re.compile(
    r"^\s*\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?\s+[—–-]\s+([A-Z][A-Z _/-]*?)\s+[—–-]\s"  # noqa: RUF001
)

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s*(.*)$")


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #


def _unquote(value: str) -> str:
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def _scalar(value: str) -> str | None:
    """A frontmatter scalar; the literal `null` (as `surface_body` writes it) becomes None."""
    v = _unquote(value)
    return None if v in ("", "null", "~") else v


def find_frontmatter(body: str) -> tuple[list[str], str]:
    """The lines INSIDE the frontmatter fences, plus an error code (`""` when clean).

    Errors are `frontmatter_absent` (no opening fence near the top of the note) and
    `frontmatter_unterminated` (an opening fence with no closing one) — distinct because the
    first is the ordinary pre-v2.8.0 item and the second is a corrupted write.
    """
    lines = (body or "").split("\n")
    start = -1
    for i, ln in enumerate(lines[:_FENCE_SEARCH_LINES]):
        if ln.strip() == _FRONTMATTER_FENCE:
            start = i
            break
    if start < 0:
        return [], "frontmatter_absent"
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == _FRONTMATTER_FENCE:
            return lines[start + 1 : j], ""
    return [], "frontmatter_unterminated"


def _parse_entities(block: list[str]) -> list[dict[str, Any]]:
    """The `entities:` sub-block — one dict per `- entity_type: …` item, nested keys flattened
    into `entity_rtm` as `surface_body` writes them."""
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    in_rtm = False
    for raw in block:
        item = _LIST_ITEM_RE.match(raw)
        if item and ":" in item.group(1):
            cur = {"entity_rtm": {}}
            out.append(cur)
            in_rtm = False
            raw = item.group(1)
        if cur is None:
            continue
        m = _KEY_RE.match(raw.strip())
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key == "entity_rtm":
            in_rtm = True
            continue
        if in_rtm and key in ("task_id", "taskseries_id", "list_id"):
            cur["entity_rtm"][key] = _unquote(val)
        else:
            in_rtm = False
            cur[key] = _unquote(val)
    return out


def parse_frontmatter(body: str) -> tuple[dict[str, Any], str]:
    """`(fields, error)` from a surface item's body note.

    Deliberately a focused parser for the shape `gtd_writes.surface_body` writes, not a general
    YAML reader: the server has no YAML dependency, and a general parser would silently accept
    shapes the writer never emits.
    """
    block, err = find_frontmatter(body)
    if err:
        return {}, err

    fields: dict[str, Any] = {}
    key: str | None = None
    sub: list[str] = []

    def _flush() -> None:
        if key is None:
            return
        if key == "entities":
            fields["entities"] = _parse_entities(sub)
        elif key == "expected_response_options":
            fields[key] = [_unquote(m.group(1)) for m in (_LIST_ITEM_RE.match(s) for s in sub) if m]
        else:
            fields[key] = "\n".join(s.strip() for s in sub).strip() or None

    for raw in block:
        if raw.startswith((" ", "\t", "-")) or not raw.strip():
            if key is not None:
                sub.append(raw)
            continue
        _flush()
        m = _KEY_RE.match(raw)
        if not m:
            key, sub = None, []
            continue
        name, sub = m.group(1), []
        val = m.group(2).strip()
        if val and val != "|":
            fields[name] = _scalar(val)
            key = None
        else:
            key = name
    _flush()

    if not fields.get("item_id"):
        return fields, "frontmatter_incomplete"
    return fields, ""


# --------------------------------------------------------------------------- #
# Timestamps
# --------------------------------------------------------------------------- #


def parse_timestamp(value: str | None) -> datetime | None:
    """A tolerant UTC-aware parse of the timestamp forms this estate actually carries: RTM's
    ISO-8601 `…Z`, the frontmatter's `YYYY-MM-DD HH:MM`, and a bare `YYYY-MM-DD` (start of day).
    Anything else is None — never a guess and never a raise."""
    v = (value or "").strip()
    if not v:
        return None
    txt = v.replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        try:
            dt = datetime.fromisoformat(v[:10])
        except ValueError:
            return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Note classification
# --------------------------------------------------------------------------- #


def classify_note(title: str) -> str:
    """`"response" | "system" | "unrecognised"` for one note title.

    Recognises three shapes: the standard `YYYY-MM-DD — TYPE — summary` grammar; a bare type
    line (`AI-LINK`, written without the date prefix — 21 live instances); and the frontmatter
    fence itself, which is a delimiter that has never been a human note title.
    """
    text = (title or "").strip()
    if not text:
        return "system"
    if text == _FRONTMATTER_FENCE:
        return "system"
    match = _TYPE_RE.match(text)
    note_type = match.group(1).strip() if match else ""
    if not note_type:
        bare = text.upper()
        if bare in RESPONSE_NOTE_TYPES:
            return "response"
        return "system" if bare in SYSTEM_NOTE_TYPES else "unrecognised"
    if note_type in RESPONSE_NOTE_TYPES:
        return "response"
    return "system" if note_type in SYSTEM_NOTE_TYPES else "unrecognised"


def _note_title(note: dict[str, Any]) -> str:
    """The stored title — RTM has no title field, so it is line 1 of the body (the same storage
    reality the CHAT / ORDER / TMPL-CHILD grammars rely on)."""
    body = extract_note_body(note) or ""
    return body.split("\n", 1)[0].strip()


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #


def _item_type(tags: list[str]) -> str:
    return next((k for k, v in SURFACE_TYPE_TAG.items() if v in tags), "")


def build_row(
    task: dict[str, Any],
    *,
    surface: str,
    by_id: dict[str, dict[str, Any]],
    today: str,
    timezone: str | None,
) -> dict[str, Any]:
    """One queue row: identity + parsed frontmatter + the two derived signals."""
    tags = list(task.get("tags") or [])
    notes = list(task.get("notes") or [])

    meta: dict[str, Any] = {}
    meta_error = "frontmatter_absent"
    meta_note_id = ""
    for n in sorted(notes, key=lambda n: str(n.get("created") or "")):
        fields, err = parse_frontmatter(extract_note_body(n) or "")
        if not err:
            meta, meta_error, meta_note_id = fields, "", str(n.get("id") or "")
            break
        if err != "frontmatter_absent":
            meta, meta_error, meta_note_id = fields, err, str(n.get("id") or "")

    asked_at = meta.get("asked_at") if isinstance(meta.get("asked_at"), str) else None
    auto_close = meta.get("auto_close_at") if isinstance(meta.get("auto_close_at"), str) else None

    # The response baseline: `asked_at` where the item carries it, else the item's own creation
    # (the body note lands at creation, so "after creation" is the same discriminator).
    baseline = parse_timestamp(asked_at) or parse_timestamp(task.get("created"))

    completed = task.get("completed") or None
    terminal = Q_PROCESSED if surface == "questions" else Q_ACKNOWLEDGED
    evidence: list[dict[str, Any]] = []
    unrecognised: list[dict[str, Any]] = []

    if Q_ANSWERED in tags:
        evidence.append({"path": "q_answered_tag", "detail": f"#{Q_ANSWERED} is set"})
    if completed and terminal not in tags and AUTO_CLOSED not in tags:
        evidence.append(
            {
                "path": "completed_unresolved",
                "detail": f"completed without #{terminal} — closure-with-response",
            }
        )
    for n in notes:
        note_id = str(n.get("id") or "")
        if note_id and note_id == meta_note_id:
            continue
        created = parse_timestamp(n.get("created"))
        if baseline and created and created <= baseline:
            continue
        title = _note_title(n)
        kind = classify_note(title)
        if kind == "response":
            evidence.append(
                {
                    "path": "response_note",
                    "detail": title[:160],
                    "note_id": note_id,
                    "created": n.get("created") or "",
                }
            )
        elif kind == "unrecognised":
            unrecognised.append(
                {"note_id": note_id, "title": title[:160], "created": n.get("created") or ""}
            )

    close_date = _iso_date(auto_close)
    return {
        "task_id": str(task.get("id") or ""),
        "taskseries_id": str(task.get("taskseries_id") or ""),
        "list_id": str(task.get("list_id") or ""),
        "surface": surface,
        "name": task.get("name") or "",
        "tags": tags,
        "notes_count": len(notes),
        "created": task.get("created") or "",
        "modified": task.get("modified") or "",
        "completed": completed or "",
        "deep_link": _permalink(str(task.get("id")), by_id, task.get("list_id")),
        # Parsed frontmatter — null / [] when absent, never dropped.
        "item_id": meta.get("item_id"),
        "item_type": meta.get("item_type") or (_item_type(tags) or None),
        "entities": meta.get("entities") or [],
        "expected_response_shape": meta.get("expected_response_shape"),
        "expected_response_options": meta.get("expected_response_options") or [],
        "asked_by": meta.get("asked_by"),
        "asked_at": asked_at,
        "auto_close_at": auto_close,
        "related_artefact": meta.get("related_artefact"),
        "metadata_parse_error": meta_error or None,
        # Derived signals.
        "auto_close_due": bool(close_date and close_date <= (_iso_date(today) or close_date)),
        "response_detected": bool(evidence),
        "response_evidence": evidence,
        "unrecognised_notes": unrecognised,
    }


def build_surface_queue(
    questions: list[dict[str, Any]] | None,
    activity: list[dict[str, Any]] | None,
    *,
    surface: str,
    today: str,
    timezone: str | None,
) -> dict[str, Any]:
    """The queue bundle.

    Two named collections rather than one merged list: the sort keys genuinely differ (questions
    oldest-MODIFIED first — longest-waiting gets attention; activity oldest-CREATED first —
    auto-closure candidates surface first) and the scan makes two separate passes.
    """
    out: dict[str, Any] = {"surface": surface, "current_date": today}

    if surface in ("questions", "both"):
        rows = _rows(questions or [], surface="questions", today=today, timezone=timezone)
        rows.sort(key=lambda r: (r["modified"] or "", r["name"].lower()))
        out["questions"] = rows
        out["questions_count"] = len(rows)
        out["questions_response_detected_count"] = sum(1 for r in rows if r["response_detected"])
    if surface in ("activity", "both"):
        rows = _rows(activity or [], surface="activity", today=today, timezone=timezone)
        rows.sort(key=lambda r: (r["created"] or "", r["name"].lower()))
        out["activity"] = rows
        out["activity_count"] = len(rows)
        out["activity_auto_close_due_count"] = sum(1 for r in rows if r["auto_close_due"])
        out["activity_response_detected_count"] = sum(1 for r in rows if r["response_detected"])

    total = len(out.get("questions", [])) + len(out.get("activity", []))
    out["count"] = total
    out["metadata_missing_count"] = sum(
        1
        for r in (*out.get("questions", []), *out.get("activity", []))
        if r["metadata_parse_error"]
    )
    return out


def _rows(
    tasks: list[dict[str, Any]], *, surface: str, today: str, timezone: str | None
) -> list[dict[str, Any]]:
    by_id = {str(t.get("id") or ""): t for t in tasks}
    return [
        build_row(t, surface=surface, by_id=by_id, today=today, timezone=timezone)
        for t in tasks
        if not t.get("deleted")
    ]


__all__ = [
    "ACTIVITY_FILTER",
    "AI_ACTIVITY_LIST",
    "AI_ACTIVITY_TAG",
    "CATALOGUE_NOTE_TYPES",
    "CLAUDE_QUESTION",
    "QUESTIONS_FILTER",
    "RESPONSE_NOTE_TYPES",
    "RESPONSE_PATHS",
    "SURFACE_NOTE_TYPES",
    "SYSTEM_NOTE_TYPES",
    "VALID_SURFACES",
    "build_row",
    "build_surface_queue",
    "classify_note",
    "find_frontmatter",
    "parse_frontmatter",
    "parse_timestamp",
]
