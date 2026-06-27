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
         next_tickle, updated}.
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

        life = _life(tags)

        parent = by_id.get(str(proj.get("parent_task_id") or ""))
        focus = (parent.get("name") or "") if parent else "(unfiled)"
        focus_id = parent["id"] if parent else ""

        pr = str(proj.get("priority") or "N")
        priority = pr if pr in _PRIORITY_CODES else ""

        out.append(
            {
                "life": life,
                "focus": focus,
                "focus_id": focus_id,
                "project": proj.get("name") or "",
                "project_id": pid,
                "priority": priority,
                "open_count": open_count,
                "blocked_count": blocked_count,
                "next_tickle": next_tickle,
                "updated": _norm_date(proj.get("modified"), timezone),
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

    timezone: forwarded to `build_envelope` for date localisation parity with the canvas (the row
        shape used here carries no date, but the reconstruction is shared, so we pass it through).

    Returns a list (sorted by life → focus → project → name for deterministic, grouped output) of
        {action_id, name, project_id, project, focus, life}.
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
        for r in env["rows"]:
            if _TEST_TAG in (r.get("tags") or []):
                continue
            out.append(
                {
                    "action_id": r["id"],
                    "name": r["name"],
                    "project_id": pid,
                    "project": project_name,
                    "focus": focus,
                    "life": life,
                }
            )

    out.sort(key=lambda r: (r["life"], r["focus"].lower(), r["project"].lower(), r["name"].lower()))
    return out
