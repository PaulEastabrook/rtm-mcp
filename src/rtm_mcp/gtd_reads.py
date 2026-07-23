"""Pure (no-IO) builders for the four new GTD collection/context read tools.

These are not `.ms` ports — they codify the GTD read semantics documented in the gtd skill
references (list-catalogue, tag-taxonomy, inbox-stuff-pipeline, weekly-review, journaling-lifecycle
note-reading-protocol) as compact, typed projections. The tool layer issues the single
`rtm.tasks.getList` read(s) and passes parsed rows here; no clock/network (the caller passes
`today`, account-tz localised, and `timezone`).
"""

from __future__ import annotations

import re
from typing import Any

from .canvas_seed import _CONTEXT_TAGS, map_kind
from .note_shape import effective_title
from .parsers import extract_note_body
from .project_plan import _ancestor_chain, _norm_date, _permalink

# Canonical closed vocabularies (advertised as advisory enums; asserted equal in test_tool_schemas).
VALID_PERSPECTIVES = frozenset({"next_actions_by_context", "todays_field", "focus_projects"})
VALID_DEPTHS = frozenset({"shallow", "medium", "deep"})

# Comms-mode context tags (the second context axis, alongside the physical _CONTEXT_TAGS).
_COMMS_CONTEXT_TAGS = (
    "conversation_email",
    "conversation_messenger",
    "conversation_phone_call",
    "conversation_video_call",
    "conversation_f2f",
)
_ALL_CONTEXT_TAGS = (*_CONTEXT_TAGS, *_COMMS_CONTEXT_TAGS)

_LIFE_TAGS = ("work", "personal", "leanworking")

# Note-title grammar: `YYYY-MM-DD [HH:MM] — TYPE — summary` (em/en-dash or spaced hyphen).
_NOTE_TITLE_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2})?\s*[—–-]\s*([A-Z][A-Z /-]*?)\s*[—–-]\s*(.*)$"  # noqa: RUF001
)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _deep_link(t: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    return _permalink(str(t.get("id")), by_id, t.get("list_id"))


def _prio(raw: str | None) -> str:
    return raw if raw in ("1", "2", "3") else ""


def parse_note_type(title: str) -> tuple[str, str, str]:
    """`(date, TYPE, summary)` from a note title, else `("", "", title)`. TYPE is upper-case."""
    m = _NOTE_TITLE_RE.match(title or "")
    if not m:
        return "", "", (title or "").strip()
    return m.group(1), m.group(2).strip(), m.group(3).strip()


def classify_gtd_type(tags: list[str]) -> str:
    """GTD workflow-state precedence: project > focus > waiting_for > someday > action."""
    if "project" in tags:
        return "project"
    if "focus" in tags:
        return "focus"
    if "waiting_for" in tags:
        return "waiting_for"
    if "someday" in tags:
        return "someday"
    return "action"


def _row(t: dict[str, Any], by_id: dict[str, dict[str, Any]], timezone: str | None) -> dict:
    return {
        "id": str(t.get("id") or ""),
        "name": t.get("name") or "",
        "kind": map_kind(t.get("tags") or []),
        "priority": _prio(t.get("priority")),
        "due": _norm_date(t.get("due"), timezone),
        "tags": list(t.get("tags") or []),
        "parent_id": t.get("parent_task_id") or None,
        "deep_link": _deep_link(t, by_id),
    }


# --------------------------------------------------------------------------- #
# gtd_query(perspective)
# --------------------------------------------------------------------------- #


def build_query_next_actions(
    tasks: list[dict[str, Any]], *, context: str | None, timezone: str | None
) -> dict[str, Any]:
    """Incomplete #action items, each attributed to its action context (physical or comms). When
    ``context`` is given, only that context's actions are returned; otherwise all, grouped."""
    by_id = {str(t.get("id") or ""): t for t in tasks}
    rows: list[dict[str, Any]] = []
    for t in tasks:
        tags = t.get("tags") or []
        ctx = next((c for c in _ALL_CONTEXT_TAGS if c in tags), "using_device")
        if context and ctx != context:
            continue
        r = _row(t, by_id, timezone)
        r["context"] = ctx
        rows.append(r)
    rows.sort(key=lambda r: (r["context"], r["name"].lower()))
    return {
        "perspective": "next_actions_by_context",
        "context": context or "",
        "rows": rows,
        "count": len(rows),
    }


def build_query_todays_field(
    tasks: list[dict[str, Any]], *, timezone: str | None
) -> dict[str, Any]:
    """Today's field — the getList already filtered to due-today/overdue + the untagged capture
    catch; here we just shape + sort (overdue first, then by due)."""
    by_id = {str(t.get("id") or ""): t for t in tasks}
    rows = [_row(t, by_id, timezone) for t in tasks]
    rows.sort(key=lambda r: (r["due"] or "9999", r["name"].lower()))
    return {"perspective": "todays_field", "rows": rows, "count": len(rows)}


def build_query_focus_projects(
    tasks: list[dict[str, Any]], *, focus_id: str | None, timezone: str | None
) -> dict[str, Any]:
    """Active #project rows attributed to their parent Area of Focus. When ``focus_id`` is given,
    only that focus's projects; otherwise all, grouped by focus."""
    by_id = {str(t.get("id") or ""): t for t in tasks}
    rows: list[dict[str, Any]] = []
    for t in tasks:
        tags = t.get("tags") or []
        if "project" not in tags or "test" in tags or t.get("completed"):
            continue
        pid = str(t.get("parent_task_id") or "")
        if focus_id and pid != focus_id:
            continue
        r = _row(t, by_id, timezone)
        r["focus_id"] = pid
        r["focus"] = (by_id.get(pid, {}).get("name") or "") if pid else "(unfiled)"
        rows.append(r)
    rows.sort(key=lambda r: (r["focus"].lower(), r["name"].lower()))
    return {
        "perspective": "focus_projects",
        "focus_id": focus_id or "",
        "rows": rows,
        "count": len(rows),
    }


# --------------------------------------------------------------------------- #
# gtd_inbox_state — three health counts on Inbox_Stuff (one read)
# --------------------------------------------------------------------------- #


def build_inbox_state(tasks: list[dict[str, Any]], *, timezone: str | None) -> dict[str, Any]:
    """The three inbox-health signals in one shape (all subsets of one Inbox_Stuff read):
    depth (all), unprocessed (no ai_review/ai_approved pipeline tag), awaiting-review (ai_review),
    approved-unapplied (ai_approved)."""
    by_id = {str(t.get("id") or ""): t for t in tasks}
    unprocessed, review, approved = [], [], []
    for t in tasks:
        tags = t.get("tags") or []
        r = _row(t, by_id, timezone)
        if "ai_approved" in tags:
            approved.append(r)
        elif "ai_review" in tags:
            review.append(r)
        else:
            unprocessed.append(r)
    return {
        "depth": len(tasks),
        "unprocessed_count": len(unprocessed),
        "awaiting_review_count": len(review),
        "approved_unapplied_count": len(approved),
        "unprocessed": unprocessed,
        "awaiting_review": review,
        "approved_unapplied": approved,
    }


# --------------------------------------------------------------------------- #
# gtd_waiting_for_queue — the chase queue with staleness
# --------------------------------------------------------------------------- #


def build_waiting_for_queue(
    tasks: list[dict[str, Any]], *, today: str, timezone: str | None
) -> dict[str, Any]:
    """Incomplete #waiting_for items as a chase queue: the due tickle (chase prompt), the age
    since last update, and a ``stale`` flag (updated >14 days ago — weekly-review § 3)."""
    from .detectors import _minus_days

    by_id = {str(t.get("id") or ""): t for t in tasks}
    cutoff = _minus_days(today, 14)
    rows: list[dict[str, Any]] = []
    for t in tasks:
        r = _row(t, by_id, timezone)
        modified = _norm_date(t.get("modified"), timezone)
        r["updated"] = modified
        r["stale"] = bool(modified) and modified < cutoff
        rows.append(r)
    # Stale first, then earliest due tickle.
    rows.sort(key=lambda r: (not r["stale"], r["due"] or "9999", r["name"].lower()))
    return {
        "rows": rows,
        "count": len(rows),
        "stale_count": sum(1 for r in rows if r["stale"]),
        "current_date": today,
    }


# --------------------------------------------------------------------------- #
# gtd_context — the STATE-first note-reading-protocol bundle
# --------------------------------------------------------------------------- #


def resolve_task_ref(parsed: list[dict[str, Any]], task_ref: str) -> dict[str, Any]:
    """Resolve a task by id or name among the fetched tasks. Mirrors resolve_project's shape:
    {"task": <t>} | {"candidates": [...]} | {} (caller builds the typed miss)."""
    by_id = {str(t.get("id") or ""): t for t in parsed}
    ref = (task_ref or "").strip()
    if ref in by_id:
        return {"task": by_id[ref]}
    low = ref.lower()
    exact = [t for t in parsed if (t.get("name") or "").lower() == low]
    matches = exact or [t for t in parsed if low in (t.get("name") or "").lower()]
    if not matches:
        return {}
    if len(matches) > 1:
        return {
            "candidates": [
                {"id": str(t["id"]), "name": t.get("name") or "", "list_id": t.get("list_id") or ""}
                for t in matches[:20]
            ]
        }
    return {"task": matches[0]}


def _ordered_notes(notes: list[dict[str, Any]], *, timezone: str | None, full: bool) -> list[dict]:
    """Notes ordered per the note-reading-protocol: STATE (latest) → INCEPTION → newest others →
    DECISION → the rest. ``full`` keeps every note + body; otherwise non-STATE is capped and bodies
    dropped for a compact bundle."""
    parsed = []
    for n in notes:
        body = extract_note_body(n)
        title = effective_title(n.get("title") or "", body)
        date, ntype, summary = parse_note_type(title)
        parsed.append(
            {
                "id": str(n.get("id") or ""),
                "type": ntype,
                "date": date or _norm_date(n.get("created"), timezone),
                "summary": summary,
                "body": body if full else "",
            }
        )
    parsed.sort(key=lambda p: p["date"], reverse=True)  # newest first baseline

    def bucket(name: str) -> list[dict]:
        return [p for p in parsed if p["type"] == name]

    state = bucket("STATE")
    inception = bucket("INCEPTION")
    decision = bucket("DECISION")
    special = {"STATE", "INCEPTION", "DECISION"}
    others = [p for p in parsed if p["type"] not in special]
    if not full:
        others = others[:3]  # newest 2-3 (protocol step 2)
    ordered = [*state, *inception, *others, *decision]
    # de-dupe by id preserving order (a note could fall in two buckets only if mis-typed)
    seen: set[str] = set()
    out = []
    for p in ordered:
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        out.append(p)
    return out


def build_context(
    parsed: list[dict[str, Any]], task: dict[str, Any], *, depth: str, timezone: str | None
) -> dict[str, Any]:
    """The STATE-first context bundle for one task: the gtd-interpreted task view, its notes
    (STATE-first), siblings, and the parent chain to the Area of Focus. ``depth`` widens the
    bundle: shallow = task + own notes; medium = + parent + immediate siblings; deep = + full
    note bodies + full siblings + the full ancestor chain."""
    by_id = {str(t.get("id") or ""): t for t in parsed}
    tags = task.get("tags") or []
    tid = str(task.get("id") or "")
    pid = str(task.get("parent_task_id") or "")
    full = depth == "deep"
    include_relations = depth in ("medium", "deep")

    task_view = {
        "id": tid,
        "name": task.get("name") or "",
        "list_id": str(task.get("list_id") or ""),
        "taskseries_id": str(task.get("taskseries_id") or ""),
        "gtd_type": classify_gtd_type(tags),
        "kind": map_kind(tags),
        "priority": _prio(task.get("priority")),
        "due": _norm_date(task.get("due"), timezone),
        "start": _norm_date(task.get("start"), timezone),
        "tags": list(tags),
        "parent_id": pid or None,
        "notes_count": len(task.get("notes") or []),
        "deep_link": _deep_link(task, by_id),
    }

    notes = _ordered_notes(task.get("notes") or [], timezone=timezone, full=full)

    siblings: list[dict[str, Any]] = []
    if include_relations and pid:
        sibs = [
            t
            for t in parsed
            if str(t.get("parent_task_id") or "") == pid and str(t.get("id")) != tid
        ]
        if not full:
            sibs = sibs[:8]
        siblings = [
            {
                "id": str(t["id"]),
                "name": t.get("name") or "",
                "gtd_type": classify_gtd_type(t.get("tags") or []),
                "completed": bool(t.get("completed")),
                "deep_link": _deep_link(t, by_id),
            }
            for t in sibs
        ]

    ancestors: list[dict[str, Any]] = []
    if include_relations and pid:
        chain = _ancestor_chain(tid, by_id)[:-1]  # exclude self (last)
        if not full:
            chain = chain[-2:]  # immediate parent(s)
        for aid in chain:
            a = by_id.get(aid)
            if not a:
                ancestors.append({"id": aid, "name": "", "gtd_type": "", "deep_link": ""})
                continue
            latest = _ordered_notes(a.get("notes") or [], timezone=timezone, full=False)
            ancestors.append(
                {
                    "id": aid,
                    "name": a.get("name") or "",
                    "gtd_type": classify_gtd_type(a.get("tags") or []),
                    "deep_link": _deep_link(a, by_id),
                    "latest_note": latest[0]["summary"] if latest else "",
                }
            )

    return {
        "task": task_view,
        "notes": notes,
        "siblings": siblings,
        "ancestors": ancestors,
        "depth": depth,
    }
