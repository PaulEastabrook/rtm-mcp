"""Engage-seed builder — the overdue + soft-parked set backing `gtd_engage_seed`.

Pure (no IO). Maps a flat, parsed `rtm.tasks.getList` result into the ground truth the engage
renegotiation sweep (chat funnel + live board) reasons over: one row per dated item at/after its date
(overdue or due-today), each carrying SERVER-DERIVED flags. Vault-free — the same membrane as
`gtd_project_index` / `gtd_project_canvas`: the enriched plan-graph overlay lives in AI Memory and is
the gtd skill's concern, never the server's, so `blocked` is the THIN plan-graph judgement (an open
DEPENDS-ON upstream within the item's own project's rows), identical to `gtd_project_index`'s.

`has_deadline` is derived from the RTM `has_due_time` primitive — a due carrying a specific TIME is
genuinely day/time-specific (the GTD *hard landscape*); a date-only due is a soft parked-date. It is
the load-bearing input to the verdict grammar's deadline guard (`engage_commit` § 3.1).

Redaction is CURTAIN-NOT-VAULT (rtm-mcp v1.30.0 invariant, CLAUDE.md § Redaction surface): the seed
EMITS the `redacted` flag (own #redacted OR a cascade from a redacted #project / #focus ancestor) but
NEVER nulls, strips, or withholds any field/row on it — a shielded overdue row flows its full name and
flags exactly like an unshielded one. Enforcement (the locked placeholder, funnel exclusion, the
askClaude PII shield) is 100% client-side. `test_engage_seed.py` pins this.
"""

from __future__ import annotations

from typing import Any

from .engage_commit import suggest_verdict
from .plan_graph import build_graph
from .project_index import _FOCUS_TAG, _SOMEDAY_TAG
from .project_plan import (
    _PROJECT_TAG,
    _TEST_TAG,
    REDACTED_TAG,
    _norm_date,
    build_envelope,
)


def _kind(tags: list[str]) -> str:
    """The item kind the verdict grammar keys legality on, resolved from the workflow-state tag.
    #project wins (a project task surfaced in the overdue sweep), then waiting-for, then calendar
    entry, else a plain action. Note this returns "calendar_entry" (the grammar kind), NOT
    canvas_seed.map_kind's "calendar" glyph value."""
    if _PROJECT_TAG in tags:
        return "project"
    if "waiting_for" in tags:
        return "waiting_for"
    if "calendar_entry" in tags:
        return "calendar_entry"
    return "action"


def _blocked_map(parsed: list[dict[str, Any]], timezone: str | None) -> dict[str, bool]:
    """id → True for every child the THIN plan-graph judges blocked, across all active projects.
    Built once per project (build_envelope + build_graph, the parity-pinned engines) so a seed row's
    `blocked` is the SAME judgement `gtd_project_index` emits — an open DEPENDS-ON upstream within the
    project's own rows (cross-project / completed upstreams don't count). Default (absent) → False, so
    a loose single-action or a project task with no dependency graph is unblocked."""
    out: dict[str, bool] = {}
    for proj in parsed:
        tags = proj.get("tags") or []
        if _PROJECT_TAG not in tags or _TEST_TAG in tags or proj.get("completed"):
            continue
        env = build_envelope(parsed, proj["id"], timezone=timezone)
        judgement = build_graph(env["header"], env["rows"]).get("judgement", {})
        for rid, j in judgement.items():
            if j.get("blocked"):
                out[rid] = True
    return out


def _redacted_cascade(task: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    """The viewing-curtain flag: the item's own #redacted, OR a cascade from any redacted #project /
    #focus ancestor (so a shielded parent locks the row) — mirroring `project_index.build_actions`.
    A flag only; the row still flows full data (curtain-not-vault)."""
    if REDACTED_TAG in (task.get("tags") or []):
        return True
    cur = str(task.get("parent_task_id") or "")
    seen: set[str] = set()
    for _ in range(10):
        if not cur or cur in seen:
            break
        seen.add(cur)
        anc = by_id.get(cur)
        if not anc:
            break
        atags = anc.get("tags") or []
        if REDACTED_TAG in atags and (_PROJECT_TAG in atags or _FOCUS_TAG in atags):
            return True
        cur = str(anc.get("parent_task_id") or "")
    return False


def build_engage_seed(
    parsed: list[dict[str, Any]],
    *,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Flat parsed tasks → the overdue + soft-parked seed.

    Selection (the overdue-set definition): an incomplete item with a due date localised on-or-before
    `today` (overdue OR due today), NOT #test, NOT #someday (a #someday item is deliberately parked,
    not overdue). All kinds that carry a date are included — action, waiting-for, calendar entry, and
    a #project task with its own due — because the sweep offers a kind-appropriate verdict for each.

    today: the current date `YYYY-MM-DD` in the account timezone (the tool computes it; the builder
        stays clock-free and deterministic). Emitted back as `current_date`.
    timezone: the account IANA zone — every date is localised before the on-or-before comparison and
        truncation (RTM returns UTC, so a BST midnight due would otherwise compare a day early). None
        → raw-UTC truncation (safe fallback, same as build_envelope).

    Each row: {id, name, kind, has_deadline, blocked, postponed, suggested, redacted, due} —
        has_deadline = RTM has_due_time (a timed due = the hard landscape);
        blocked = the thin plan-graph judgement (an open DEPENDS-ON upstream in the project);
        postponed = RTM's postpone count (the bump-fatigue signal);
        suggested = the deterministic pre-triage verdict (engage_commit.suggest_verdict);
        redacted = own #redacted OR a redacted #project/#focus ancestor (a client-side curtain flag —
            the row still carries full data).

    Returns {items: [...], current_date: today, count: n}; items sorted by due → name for
    deterministic output.
    """
    by_id = {t["id"]: t for t in parsed}
    blocked_map = _blocked_map(parsed, timezone)
    rows: list[dict[str, Any]] = []

    for t in parsed:
        tags = t.get("tags") or []
        if t.get("completed") or _TEST_TAG in tags or _SOMEDAY_TAG in tags:
            continue
        due_local = _norm_date(t.get("due"), timezone)
        if not due_local or due_local > today:
            continue

        kind = _kind(tags)
        has_deadline = bool(t.get("has_due_time"))
        blocked = bool(blocked_map.get(t["id"]))
        rows.append(
            {
                "id": t["id"],
                "name": t.get("name") or "",
                "kind": kind,
                "has_deadline": has_deadline,
                "blocked": blocked,
                "postponed": int(t.get("postponed") or 0),
                "suggested": suggest_verdict(kind, has_deadline, blocked),
                # Viewing-curtain flag — the client shields the display; the server never suppresses
                # any field on it (curtain-not-vault, CLAUDE.md § Redaction surface).
                "redacted": _redacted_cascade(t, by_id),
                "due": due_local,
            }
        )

    rows.sort(key=lambda r: (r["due"], r["name"].lower()))
    return {"items": rows, "current_date": today, "count": len(rows)}
