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

# RTM numeric priorities the navigator renders; anything else (RTM's "N") maps to "".
_PRIORITY_CODES = {"1", "2", "3"}


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
        if _PROJECT_TAG not in tags or _TEST_TAG in tags or proj.get("completed"):
            continue
        if _HOLD_TAG in tags or (_SOMEDAY_TAG in tags and not include_someday):
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

        life = next((tg for tg in tags if tg in _LIFE_TAGS), "")

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
