"""Pure (no-IO) builders for five GTD portfolio / hygiene reads.

Backs `gtd_dependency_gaps`, `gtd_review_report`, `gtd_item_stale`, `gtd_workload_report` and
`gtd_focus_index`. Grouped because each is a small projection over one broad `rtm.tasks.getList`;
the substantial subsystems get their own modules (`surface_queue`, `engine_report`, `tag_report`).

**Built to intent, not ported (designed change D1).** The five source scripts
(`dependency-graph-detect.ms`, `weekly-review-stats.ms`, `stale-items.ms`, `workload-balance.ms`,
and — for `gtd_focus_index` — no script at all) carry the library-wide defect classes recorded in
`references/milkscript-api-surface.md`, so there is **no output-parity oracle**. Divergences are
deliberate and named at each builder.

Two findings from grounding this against the live account on 2026-07-25 are worth stating up front:

* **`weekly-review-stats.ms` reported 0 completions and 0 additions, always** — a defect class
  outside the MilkScript sweep entirely. It filtered on `completedAfter:"N days ago"` and
  `addedAfter:"N days ago"`. Those operators are real, but RTM does **not** parse the relative
  phrase `"N days ago"` for them: measured live, `completedAfter:"7 days ago"` → **0** while
  `completedWithin:"7 days of today"` → **53**, and `completedAfter:07/18/2026` → 73. The query
  matched nothing and returned it as a finding. `build_review_report` takes the completed cohort
  from the verified `completedWithin:` form and derives additions client-side from each task's
  own `created` field — no unverified operator on the path at all.

* **`dependency-graph-detect.ms` ran an N+1** — `rtm.getTasks("parent:" + id)` once per project,
  ~107 signed calls at ~0.9 RPS. The parent→children map is derived client-side from one broad
  read instead (the same divergence `detectors.build_health_check` already makes).
"""

from __future__ import annotations

from typing import Any

from .canvas_seed import map_kind
from .parsers import extract_note_body, parse_estimate_minutes
from .project_index import _active, _priority_code
from .project_plan import _PROJECT_TAG, _TEST_TAG, REDACTED_TAG, _norm_date, _permalink
from .surface_queue import parse_timestamp

# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #

_FOCUS_TAG = "focus"

#: Canonical life contexts in report order. FOUR members — `client` is canonical
#: (`tag-taxonomy.md` § Life Context) and was absent from every script's hard-coded
#: `["work","personal","leanworking"]`. Live usage is currently zero, so including it costs
#: nothing and stops a future `#client` item vanishing from every report.
LIFE_ORDER = ("work", "client", "leanworking", "personal")
#: Canonical workflow states in report order (`tag-taxonomy.md` § GTD Workflow State).
STATE_ORDER = ("action", "waiting_for", "project", "focus", "someday")

#: Projects excluded from the dependency backfill (`dependency-graph-detect.ms` header).
DEPENDENCY_SKIP_TAGS = ("do_not_auto_progress", "hold", "someday", "archived", "cancelled")
DEPENDENCY_MIN_CHILDREN = 2
DEPENDENCY_DEFAULT_CAP = 200

DEFAULT_STALE_DAYS = 30
DEFAULT_REVIEW_DAYS = 7


def _tags(task: dict[str, Any]) -> set[str]:
    return {str(t).strip().lower() for t in (task.get("tags") or [])}


def _by_id(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(t.get("id") or ""): t for t in tasks}


def _life4(tags: set[str]) -> str:
    """The life context including `client` — `project_index._life` reads a three-member tuple."""
    return next((t for t in LIFE_ORDER if t in tags), "")


def _state(tags: set[str]) -> str:
    return next((s for s in STATE_ORDER if s in tags), "")


def _children_of(tasks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        parent = str(t.get("parent_task_id") or "")
        if parent:
            out.setdefault(parent, []).append(t)
    return out


# --------------------------------------------------------------------------- #
# gtd_dependency_gaps
# --------------------------------------------------------------------------- #


def has_depends_on_note(task: dict[str, Any]) -> bool:
    """Whether any note on the task is a DEPENDS-ON note.

    Matches the note TITLE (line 1 — RTM has no title field), not the whole body, so a note that
    merely *mentions* a dependency in prose does not count the project as captured. Active and
    resolved edges both count: a resolved edge still proves the discipline was applied here.
    """
    for n in task.get("notes") or []:
        title = (extract_note_body(n) or "").split("\n", 1)[0]
        if "DEPENDS-ON" in title.upper():
            return True
    return False


def build_dependency_gaps(
    parsed: list[dict[str, Any]],
    *,
    max_projects: int = DEPENDENCY_DEFAULT_CAP,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Projects with >=2 open children and no dependency edge captured on any of them.

    Serves the legacy backfill in `agents/dependency-graph-proposal.md` (paced 5 per batch via
    `AI_Questions`).

    **The result is NOT the final set and the tool description says so.** The agent additionally
    reads each project's `context.md` for `dependencies:` and `dependency_graph_declined: true` —
    vault state this server cannot see. What comes back is the RTM-derived upper bound.

    Two deliberate divergences from `dependency-graph-detect.ms`: children come from one broad
    read rather than a per-project `parent:` query (the N+1 above), and the cap is applied AFTER
    the sort, not during the scan — the script truncated in RTM's arbitrary order and then sorted
    the survivors, so `max_projects` did not return the largest projects it claimed to.
    """
    children = _children_of(parsed)
    by_id = _by_id(parsed)

    eligible: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for t in parsed:
        tags = _tags(t)
        if _PROJECT_TAG not in tags or t.get("completed") or _TEST_TAG in tags:
            continue
        pid = str(t.get("id") or "")
        row = {
            "project_id": pid,
            "name": t.get("name") or "",
            "list_id": str(t.get("list_id") or ""),
            "parent_id": str(t.get("parent_task_id") or ""),
            "tags": sorted(tags),
            "redacted": REDACTED_TAG in tags,
            "deep_link": _permalink(pid, by_id, t.get("list_id")),
        }

        blocking = sorted(tags & set(DEPENDENCY_SKIP_TAGS))
        if blocking:
            skipped.append({**row, "reason": "disqualifying_tag", "detail": ",".join(blocking)})
            continue

        open_children = [c for c in children.get(pid, []) if not c.get("completed")]
        if len(open_children) < DEPENDENCY_MIN_CHILDREN:
            skipped.append(
                {
                    **row,
                    "reason": "too_few_open_children",
                    "detail": str(len(open_children)),
                    "open_child_count": len(open_children),
                }
            )
            continue

        if any(has_depends_on_note(c) for c in open_children):
            skipped.append(
                {
                    **row,
                    "reason": "graph_already_captured",
                    "detail": "a child carries a DEPENDS-ON note",
                    "open_child_count": len(open_children),
                }
            )
            continue

        eligible.append(
            {
                **row,
                "open_child_count": len(open_children),
                "updated": _norm_date(t.get("modified"), timezone),
            }
        )

    # Larger projects benefit most from explicit capture — surface them first, THEN cap.
    eligible.sort(key=lambda r: (-r["open_child_count"], r["name"].lower()))
    skipped.sort(key=lambda r: (r["reason"], r["name"].lower()))
    total = len(eligible)
    capped = max_projects > 0 and total > max_projects
    return {
        "eligible": eligible[:max_projects] if max_projects > 0 else eligible,
        "eligible_count": min(total, max_projects) if max_projects > 0 else total,
        "eligible_total": total,
        "capped": capped,
        "max_projects": max_projects,
        "skipped": skipped,
        "skipped_count": len(skipped),
        "vault_filter_pending": (
            "RTM-derived only — an upper bound. The calling agent must still exclude projects "
            "whose context.md carries `dependencies:` or `dependency_graph_declined: true`; that "
            "is vault state, outside this server's read boundary."
        ),
    }


# --------------------------------------------------------------------------- #
# gtd_review_report
# --------------------------------------------------------------------------- #


def build_review_report(
    incomplete: list[dict[str, Any]],
    completed: list[dict[str, Any]],
    inbox: list[dict[str, Any]],
    *,
    days: int,
    now: str,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """The weekly review's quantitative snapshot.

    `completed` is the cohort from `completedWithin:"<days> days of today"` — the relative form
    RTM actually parses (see the module header). Additions are derived from each incomplete
    task's own `created` timestamp rather than an `addedWithin:` filter: it needs no operator on
    the trust path and it answers the question the script meant to ask (*items added in the
    window that are still open*), where `addedWithin:` would also count items added and closed
    inside the window.
    """
    window_start = parse_timestamp(now)
    if window_start is not None:
        from datetime import timedelta

        window_start = window_start - timedelta(days=days)

    completed_by_life: dict[str, int] = dict.fromkeys(LIFE_ORDER, 0)
    completed_untagged = 0
    for t in completed:
        tags = _tags(t)
        if _TEST_TAG in tags or _PROJECT_TAG in tags or _FOCUS_TAG in tags:
            continue
        life = _life4(tags)
        if life:
            completed_by_life[life] += 1
        else:
            completed_untagged += 1

    added_by_life: dict[str, int] = dict.fromkeys(LIFE_ORDER, 0)
    added_untagged = 0
    added_undated = 0
    state_counts: dict[str, dict[str, int]] = {
        life: dict.fromkeys(STATE_ORDER, 0) for life in LIFE_ORDER
    }
    overdue = 0
    today_key = (today or "")[:10]

    for t in incomplete:
        tags = _tags(t)
        life = _life4(tags)
        state = _state(tags)
        if life and state:
            state_counts[life][state] += 1
        created = parse_timestamp(t.get("created"))
        if created is None:
            added_undated += 1
        elif window_start is not None and created >= window_start:
            if life:
                added_by_life[life] += 1
            else:
                added_untagged += 1
        due = _norm_date(t.get("due"), timezone)
        if due and today_key and due < today_key:
            overdue += 1

    total_completed = sum(completed_by_life.values()) + completed_untagged
    total_added = sum(added_by_life.values()) + added_untagged
    net = total_added - total_completed
    return {
        "window_days": days,
        "current_date": today,
        "completed": {
            "by_life_context": completed_by_life,
            "no_life_context": completed_untagged,
            "total": total_completed,
        },
        "added": {
            "by_life_context": added_by_life,
            "no_life_context": added_untagged,
            "undated_creation": added_undated,
            "total": total_added,
        },
        "current_state": {
            life: {
                "by_workflow_state": state_counts[life],
                "total": sum(state_counts[life].values()),
            }
            for life in LIFE_ORDER
        },
        "overdue_count": overdue,
        "inbox_depth": len(inbox),
        "velocity": {
            "net_change": net,
            "direction": "growing" if net > 0 else "shrinking" if net < 0 else "stable",
        },
    }


# --------------------------------------------------------------------------- #
# gtd_item_stale
# --------------------------------------------------------------------------- #


def build_item_stale(
    tasks: list[dict[str, Any]],
    *,
    days: int,
    now: str,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Incomplete items untouched for more than `days`, excluding someday/maybe.

    **Divergence: the `isSubtask:true` clause is dropped.** `stale-items.ms` restricted the scan
    to subtasks with no stated rationale, which made every top-level project and every Area of
    Focus structurally invisible to a hygiene report whose whole purpose is finding forgotten
    work (live: 628 of 1016 candidate items). Rows are grouped by workflow state instead, so a
    consumer that wants the old scope can read the `action` / `waiting_for` buckets and a
    consumer reviewing horizons can read `project` / `focus`.
    """
    from datetime import timedelta

    cutoff = parse_timestamp(now)
    cutoff = cutoff - timedelta(days=days) if cutoff is not None else None
    by_id = _by_id(tasks)

    rows: list[dict[str, Any]] = []
    undated = 0
    for t in tasks:
        tags = _tags(t)
        if t.get("completed") or _TEST_TAG in tags or "someday" in tags:
            continue
        modified = parse_timestamp(t.get("modified"))
        if modified is None:
            undated += 1
            continue
        if cutoff is None or modified >= cutoff:
            continue
        end = parse_timestamp(now)
        age = int((end - modified).total_seconds() // 86400) if end else 0
        rows.append(
            {
                "task_id": str(t.get("id") or ""),
                "name": t.get("name") or "",
                "state": _state(tags) or "other",
                "kind": map_kind(sorted(tags)),
                "life": _life4(tags),
                "age_days": age,
                "updated": _norm_date(t.get("modified"), timezone),
                "due": _norm_date(t.get("due"), timezone),
                "priority": _priority_code(t),
                "parent_id": str(t.get("parent_task_id") or ""),
                "redacted": REDACTED_TAG in tags,
                "deep_link": _permalink(str(t.get("id") or ""), by_id, t.get("list_id")),
            }
        )

    rows.sort(key=lambda r: (-r["age_days"], r["name"].lower()))
    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    return {
        "threshold_days": days,
        "current_date": today,
        "rows": rows,
        "count": len(rows),
        "by_state": dict(sorted(by_state.items())),
        "undated_modification": undated,
    }


# --------------------------------------------------------------------------- #
# gtd_workload_report
# --------------------------------------------------------------------------- #


def build_workload_report(tasks: list[dict[str, Any]], *, today: str) -> dict[str, Any]:
    """Life context x workflow state, with estimate totals — an AGGREGATION, not a row list.

    That shape is why this is a `_report` and not a `gtd_query` perspective (designed change
    D11). Estimates are summed for every state that carries them, not only `action` as
    `workload-balance.ms` did: a waiting-for or calendar entry with an estimate is real committed
    time, and dropping it understated the load.
    """
    cells: dict[str, dict[str, dict[str, int]]] = {
        life: {
            state: {"count": 0, "estimated_count": 0, "estimate_minutes": 0}
            for state in STATE_ORDER
        }
        for life in LIFE_ORDER
    }
    unclassified = 0

    for t in tasks:
        tags = _tags(t)
        if t.get("completed") or _TEST_TAG in tags:
            continue
        life, state = _life4(tags), _state(tags)
        if not life or not state:
            unclassified += 1
            continue
        cell = cells[life][state]
        cell["count"] += 1
        minutes = parse_estimate_minutes(t.get("estimate"))
        if minutes is not None:
            cell["estimated_count"] += 1
            cell["estimate_minutes"] += minutes

    by_life: dict[str, Any] = {}
    for life in LIFE_ORDER:
        total = sum(c["count"] for c in cells[life].values())
        minutes = sum(c["estimate_minutes"] for c in cells[life].values())
        estimated = sum(c["estimated_count"] for c in cells[life].values())
        by_life[life] = {
            "by_workflow_state": cells[life],
            "total": total,
            "estimated_count": estimated,
            "estimate_minutes": minutes,
            "estimate_hours": round(minutes / 60, 1),
            # How much of the load is actually sized — an unestimated majority makes the hours
            # figure a floor, not a total, and the consumer should be able to see that.
            "estimate_coverage_pct": 0 if total == 0 else round(100 * estimated / total),
        }

    grand_minutes = sum(v["estimate_minutes"] for v in by_life.values())
    return {
        "current_date": today,
        "by_life_context": by_life,
        "totals": {
            "count": sum(v["total"] for v in by_life.values()),
            "estimated_count": sum(v["estimated_count"] for v in by_life.values()),
            "estimate_minutes": grand_minutes,
            "estimate_hours": round(grand_minutes / 60, 1),
        },
        "unclassified_count": unclassified,
    }


# --------------------------------------------------------------------------- #
# gtd_focus_index
# --------------------------------------------------------------------------- #


def build_focus_index(
    parsed: list[dict[str, Any]],
    *,
    include_someday: bool = False,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Areas of Focus grouped by life context — the Horizon-2 view.

    A new capability with no script behind it (designed change D14). Nothing served this
    directly: focus areas exist only inside `gtd_project_index`'s navigator payload, so asking
    "what are my areas of focus?" meant calling a project tool and discarding most of the
    response. Pairs with `gtd_project_index` at the horizon above it.

    Selection reuses `project_index._active` — the same lifecycle gate the portfolio uses — so a
    focus that appears here and a focus that appears there can never disagree.
    """
    by_id = _by_id(parsed)
    children = _children_of(parsed)

    rows: list[dict[str, Any]] = []
    for t in parsed:
        tags = _tags(t)
        if _FOCUS_TAG not in tags or _PROJECT_TAG in tags:
            continue
        if not _active(sorted(tags), t.get("completed"), include_someday=include_someday):
            continue
        fid = str(t.get("id") or "")
        kids = children.get(fid, [])
        projects = [
            c
            for c in kids
            if _PROJECT_TAG in _tags(c)
            and _active(sorted(_tags(c)), c.get("completed"), include_someday=include_someday)
        ]
        direct = [c for c in kids if _PROJECT_TAG not in _tags(c) and not c.get("completed")]
        rows.append(
            {
                "focus_id": fid,
                "focus": t.get("name") or "",
                "life": _life4(tags),
                "project_count": len(projects),
                "direct_item_count": len(direct),
                "priority": _priority_code(t),
                "updated": _norm_date(t.get("modified"), timezone),
                "redacted": REDACTED_TAG in tags,
                "parent_id": str(t.get("parent_task_id") or ""),
                "deep_link": _permalink(fid, by_id, t.get("list_id")),
            }
        )

    rows.sort(
        key=lambda r: (
            LIFE_ORDER.index(r["life"]) if r["life"] in LIFE_ORDER else 99,
            r["focus"].lower(),
        )
    )
    by_life: dict[str, int] = {}
    for r in rows:
        key = r["life"] or "(unclassified)"
        by_life[key] = by_life.get(key, 0) + 1
    return {
        "current_date": today,
        "rows": rows,
        "count": len(rows),
        "by_life_context": by_life,
        "unclassified_count": sum(1 for r in rows if not r["life"]),
    }


__all__ = [
    "DEFAULT_REVIEW_DAYS",
    "DEFAULT_STALE_DAYS",
    "DEPENDENCY_DEFAULT_CAP",
    "DEPENDENCY_MIN_CHILDREN",
    "DEPENDENCY_SKIP_TAGS",
    "LIFE_ORDER",
    "STATE_ORDER",
    "build_dependency_gaps",
    "build_focus_index",
    "build_item_stale",
    "build_review_report",
    "build_workload_report",
    "has_depends_on_note",
]
