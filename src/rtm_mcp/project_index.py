"""Portfolio-index builder — the active-`#project` roll-up backing `gtd_project_index`.

Pure (no IO). Maps a flat, parsed `rtm.tasks.getList` result (as produced by
`parsers.parse_tasks_response`) into the Phase C cockpit navigator's data: one row per active
GTD project with at-a-glance state (open / blocked counts + next tickle). Vault-free by design —
the same membrane as `gtd_project_canvas` / `gtd_apply_canvas_commit`: the enriched plan-graph
overlay lives in AI Memory and is the gtd skill's concern, never the server's.

Counts derive from the server's THIN plan-graph over each project's rows: it reuses
`project_plan.build_envelope` (so a project's children, dates, and active DEPENDS-ON `deps` are
reconstructed exactly as the canvas sees them) and `plan_graph.build_graph` (so `blocked` is the
same judgement the parity golden pins — never re-derived ad hoc). The life-context tag, the parent
Area-of-Focus, the project priority, and the modified date come from the project task itself.
"""

from typing import Any

from .canvas_seed import map_kind, map_prog
from .plan_graph import build_graph
from .project_plan import (
    _LIFE_TAGS,
    _PROJECT_TAG,
    _TEST_TAG,
    _norm_date,
    build_envelope,
)

# Project lifecycle tags that take a project OUT of the active portfolio. `#hold` is always
# excluded; `#someday` is excluded unless the caller opts in (include_someday=True). These two are
# not part of project_plan's taxonomy, so they are defined here.
_SOMEDAY_TAG = "someday"
_HOLD_TAG = "hold"

# An Area of Focus carries the `#focus` tag — the marker the navigator uses to list every focus,
# including those with no active projects (so empty foci still render as group headers).
_FOCUS_TAG = "focus"

# RTM numeric priorities the navigator renders; anything else (RTM's "N") maps to "".
_PRIORITY_CODES = {"1", "2", "3"}


def _life(tags: list[str]) -> str:
    """The first life-context tag on a task, or '' when none is present."""
    return next((tg for tg in tags if tg in _LIFE_TAGS), "")


def _priority_code(task: dict[str, Any]) -> str:
    """A task's raw RTM priority coerced to the navigator encoding `"1"|"2"|"3"|""` (RTM's "N",
    or anything else, → "")."""
    pr = str(task.get("priority") or "N")
    return pr if pr in _PRIORITY_CODES else ""


def _active(tags: list[str], completed: Any, *, include_someday: bool) -> bool:
    """The shared active-portfolio lifecycle gate (used for both projects and foci): NOT completed,
    NOT `#test`, `#hold` always excluded, `#someday` excluded unless opted in. The caller layers on
    the membership tag (`#project` for the portfolio, `#focus` for areas)."""
    if completed or _TEST_TAG in tags or _HOLD_TAG in tags:
        return False
    return include_someday or _SOMEDAY_TAG not in tags


def build_index(
    parsed: list[dict[str, Any]],
    *,
    include_someday: bool = False,
    timezone: str | None = None,
) -> list[dict[str, Any]]:
    """Flat parsed tasks → the active-project portfolio index.

    Selection: incomplete tasks tagged `#project`, NOT `#test`; `#hold` always excluded, `#someday`
    excluded unless `include_someday`. A project that is somehow top-level (no Area-of-Focus parent
    in the fetched set) is kept with `focus="(unfiled)"`, `focus_id=""` — never dropped.

    timezone: the account's IANA zone — every date field is localised to it before truncation (RTM
        returns UTC, so a BST midnight date would otherwise render a day early). None → raw-UTC
        truncation (safe fallback, same as `build_envelope`).

    Returns a list (sorted by life → focus → project for deterministic output) of:
        {life, focus, focus_id, project, project_id, priority, open_count, blocked_count,
         next_tickle, updated, ai_quick, ai_now, ai_later}.

    The three ai_* counts are the navigator's AI-progressible sort lens, tallied off the SAME
    classification the canvas uses (so they can't disagree with an open plan): ai_quick = rows the
    thin plan-graph judges `quick_ready` (canvas r.quick — unblocked 2-minute #quick_win actions);
    ai_now = rows flagged #ai_progress_requested (canvas r.prog "now", blocked ones excluded);
    ai_later = rows flagged #ai_progress_deferred (canvas r.prog "later", may be blocked).
    """
    by_id = {t["id"]: t for t in parsed}
    out: list[dict[str, Any]] = []

    for proj in parsed:
        tags = proj.get("tags") or []
        if _PROJECT_TAG not in tags or not _active(
            tags, proj.get("completed"), include_someday=include_someday
        ):
            continue

        pid = proj["id"]
        # Reuse the parity-pinned reconstruction + plan-graph: identical row/dep semantics to the
        # canvas. O(P·N) over the parsed set, trivial at portfolio scale (~50 projects).
        env = build_envelope(parsed, pid, timezone=timezone)
        rows = env["rows"]
        judgement = build_graph(env["header"], rows).get("judgement", {})

        open_count = len(rows)  # all fetched children are incomplete
        blocked_count = sum(1 for r in rows if judgement.get(r["id"], {}).get("blocked"))
        dues = [r["due"] for r in rows if r.get("due")]
        next_tickle = min(dues) if dues else ""

        # AI-progressible tallies for the navigator's 4th sort lens — the SAME classification the
        # canvas applies (so index and an open plan never disagree): quick_ready from the thin
        # plan-graph (the canvas's r.quick), and the progression tri-state from map_prog (r.prog).
        # quick/now are unblocked by construction (now is filtered defensively); later may be blocked.
        ai_quick = sum(1 for r in rows if judgement.get(r["id"], {}).get("quick_ready"))
        ai_now = sum(
            1
            for r in rows
            if map_prog(r.get("tags") or []) == "now"
            and not judgement.get(r["id"], {}).get("blocked")
        )
        ai_later = sum(1 for r in rows if map_prog(r.get("tags") or []) == "later")

        life = _life(tags)

        parent = by_id.get(str(proj.get("parent_task_id") or ""))
        focus = (parent.get("name") or "") if parent else "(unfiled)"
        focus_id = parent["id"] if parent else ""

        out.append(
            {
                "life": life,
                "focus": focus,
                "focus_id": focus_id,
                "project": proj.get("name") or "",
                "project_id": pid,
                "priority": _priority_code(proj),
                "open_count": open_count,
                "blocked_count": blocked_count,
                "next_tickle": next_tickle,
                "updated": _norm_date(proj.get("modified"), timezone),
                "ai_quick": ai_quick,
                "ai_now": ai_now,
                "ai_later": ai_later,
            }
        )

    out.sort(key=lambda r: (r["life"], r["focus"].lower(), r["project"].lower()))
    return out


def build_foci(
    parsed: list[dict[str, Any]],
    *,
    include_someday: bool = False,
) -> list[dict[str, Any]]:
    """Flat parsed tasks → every active Area of Focus (the complete focus list).

    Selection: incomplete tasks tagged `#focus`, NOT `#test`; `#hold` always excluded, `#someday`
    excluded unless `include_someday` — the same lifecycle gate as the project portfolio, applied to
    areas. This is what lets the navigator render a focus that currently has zero active projects:
    `build_index` is one-row-per-project (so a project-less focus never appears there), whereas this
    list is sourced from the `#focus` tag directly.

    Returns a list (sorted by life → focus for deterministic output) of {focus_id, focus, life}.
    """
    out: list[dict[str, Any]] = []
    for t in parsed:
        tags = t.get("tags") or []
        if _FOCUS_TAG not in tags or not _active(
            tags, t.get("completed"), include_someday=include_someday
        ):
            continue
        out.append({"focus_id": t["id"], "focus": t.get("name") or "", "life": _life(tags)})

    out.sort(key=lambda r: (r["life"], r["focus"].lower()))
    return out


def build_actions(
    parsed: list[dict[str, Any]],
    *,
    include_someday: bool = False,
    timezone: str | None = None,
) -> list[dict[str, Any]]:
    """Flat parsed tasks → every incomplete action under an active project (the cockpit's search /
    jump-to index).

    An "action" here is any incomplete child the board shows — actions, waiting-fors, and calendar
    entries alike — because the cockpit search treats them all as jumpable items. The parent project
    must be active (the same selection as `build_index`); an individual child tagged `#test` is
    skipped even under an active project. Every emitted row carries a real `project_id`/`project`
    (and its `focus`/`life`) — a child can only be reached via an active project, so there are no
    dangling-project rows; a child of a top-level project inherits `focus="(unfiled)"`.

    Each row also carries the item kind plus the urgency signal the cockpit's "What's hot" band and
    find/search results render, read off work already done for the per-project counts:
    - `type` — the item kind `"action"|"waiting_for"|"calendar"`, the SAME classification the canvas
      applies (`canvas_seed.map_kind`, i.e. `gtd_project_canvas`'s `r.k`), so the UI picks the right
      glyph (dot / clock / calendar) for a cross-project action result.
    - `due` — the item's own due/chase/calendar date, localised to the account tz (RTM returns UTC),
      "" when none; overdue is just a `due` earlier than today, derived consumer-side.
    - `priority` — RTM priority in the same `"1"|"2"|"3"|""` encoding as the project rows.
    - `blocked` — True iff the action has an OPEN `DEPENDS-ON` upstream within its project's own rows,
      the same thin plan-graph judgement that feeds each project's `blocked_count` (cross-project /
      completed upstreams don't count).

    timezone: forwarded to `build_envelope` for date localisation parity with the canvas (so each
        action's `due` matches the project `next_tickle` / canvas date convention).

    Returns a list (sorted by life → focus → project → name for deterministic, grouped output) of
        {action_id, name, project_id, project, focus, life, type, due, priority, blocked}.
    """
    by_id = {t["id"]: t for t in parsed}
    out: list[dict[str, Any]] = []

    for proj in parsed:
        tags = proj.get("tags") or []
        if _PROJECT_TAG not in tags or not _active(
            tags, proj.get("completed"), include_someday=include_someday
        ):
            continue

        pid = proj["id"]
        life = _life(tags)
        parent = by_id.get(str(proj.get("parent_task_id") or ""))
        focus = (parent.get("name") or "") if parent else "(unfiled)"
        project_name = proj.get("name") or ""

        env = build_envelope(parsed, pid, timezone=timezone)
        rows = env["rows"]
        # Same thin plan-graph as build_index — so per-action `blocked` and the project's
        # `blocked_count` are one and the same judgement.
        judgement = build_graph(env["header"], rows).get("judgement", {})
        for r in rows:
            row_tags = r.get("tags") or []
            if _TEST_TAG in row_tags:
                continue
            out.append(
                {
                    "action_id": r["id"],
                    "name": r["name"],
                    "project_id": pid,
                    "project": project_name,
                    "focus": focus,
                    "life": life,
                    "type": map_kind(row_tags),  # canvas r.k classification
                    "due": r["due"],  # already localised by build_envelope
                    "priority": _priority_code(by_id.get(r["id"], {})),
                    "blocked": bool(judgement.get(r["id"], {}).get("blocked")),
                }
            )

    out.sort(key=lambda r: (r["life"], r["focus"].lower(), r["project"].lower(), r["name"].lower()))
    return out
