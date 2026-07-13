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

from .canvas_seed import _CONTEXT_TAGS, map_kind, map_prog
from .gtd_chat import AI_CHAT, AI_OUTPUT_REVIEW_NEEDED
from .parsers import parse_estimate_minutes
from .plan_graph import build_graph
from .project_plan import (
    _LIFE_TAGS,
    _PROJECT_TAG,
    _TEST_TAG,
    REDACTED_TAG,
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

# Canonical energy-level tag pair (gtd tag-taxonomy). Surfaced per-action as "high"/"low"/None; both
# present is a tagging error → None (defensive — the gtd tag-audit flags the double-tag). The tags
# are codified gtd-side in parallel and may be absent in the account when this ships (→ None).
_ENERGY_HIGH = "high_energy"
_ENERGY_LOW = "low_energy"


def _life(tags: list[str]) -> str:
    """The first life-context tag on a task, or '' when none is present."""
    return next((tg for tg in tags if tg in _LIFE_TAGS), "")


def _contexts(tags: list[str]) -> list[str]:
    """The action-context tags present on the item, in the canonical `_CONTEXT_TAGS` order (may be
    empty). A pass-through of gtd's taxonomy — the server does NOT validate membership beyond this
    known set (gtd owns the taxonomy). Unlike `canvas_seed.map_context` (a single value with a
    default), this is the full multi-value set with no default, feeding the engage funnel's context
    criterion — an empty list simply exempts the item from that filter."""
    return [t for t in _CONTEXT_TAGS if t in tags]


def _energy(tags: list[str]) -> str | None:
    """The item's energy level from the `high_energy`/`low_energy` tag pair → "high"/"low"/None.
    Both tags present is a data error → None (defensive: never guess; the gtd tag-audit catches the
    double-tag). Absent (the common case until the tags are provisioned) → None, exempting the item
    from the engage funnel's energy criterion."""
    hi = _ENERGY_HIGH in tags
    lo = _ENERGY_LOW in tags
    if hi and lo:
        return None
    if hi:
        return "high"
    if lo:
        return "low"
    return None


def _exec(tags: list[str], judged: dict[str, Any]) -> str | None:
    """Per-action execute classification — a single-value read of the SAME judgement that feeds the
    project-level ai_quick/ai_now/ai_later tallies (one classifier, two aggregations), so the engage
    lens's quick-win segment and the board's execute pill read one truth. Precedence `now > later >
    quick`: `now`/`later` are the explicit progression directives (`map_prog`, an authored intent),
    `quick` the derived unblocked-2-minute judgement (`plan_graph.quick_ready`). None when the
    classifier abstains. Mirrors the tallies exactly on non-overlapping rows: a blocked-`now` item is
    excluded (as ai_now excludes it); a `later` item may be blocked (as ai_later counts it). The one
    divergence is a genuine overlap (a #quick_win item ALSO flagged progress-now/later) — it resolves
    to the explicit directive here while both tallies still count it; overlap is a tagging accident."""
    prog = map_prog(tags)
    if prog == "now" and not judged.get("blocked"):
        return "now"
    if prog == "later":
        return "later"
    if judged.get("quick_ready"):
        return "quick"
    return None


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
         next_tickle, updated, ai_quick, ai_now, ai_later, chat_count, chat_review_count, redacted}.

    `redacted` is the project's own #redacted viewing-curtain state (the navigator locks the row).

    The three ai_* counts are the navigator's AI-progressible sort lens, tallied off the SAME
    classification the canvas uses (so they can't disagree with an open plan): ai_quick = rows the
    thin plan-graph judges `quick_ready` (canvas r.quick — unblocked 2-minute #quick_win actions);
    ai_now = rows flagged #ai_progress_requested (canvas r.prog "now", blocked ones excluded);
    ai_later = rows flagged #ai_progress_deferred (canvas r.prog "later", may be blocked).

    chat_count / chat_review_count are the per-project conversation counts for the navigator chip +
    "Conversations" sort lens: chat_count = incomplete items tagged #ai_chat (a conversation is
    underway); chat_review_count = incomplete items tagged #ai_output_review_needed (AI has replied —
    Paul's turn). The review count is a subset signal, counted independently; the project task itself
    counts when it carries the tag. Both are always present (0 when none).

    waiting_count is the engage-filter roll-up for the navigator's Focus pill: incomplete waiting-for
    items in the project (the canvas's r.k "waiting_for" classification), unlocking the "waiting-for"
    filter segment. Always present (0 when none). (Its sibling decision_count — for the "decisions"
    segment — is not yet emitted: see the note in the module's gtd_project_index feature docs.)
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

        # The tool feeds a status:incomplete read, but build_envelope carries completed
        # children too when fed a broader parsed set (as other tools' reads are) — so
        # every count derives from the open rows only, uniformly.
        open_rows = [r for r in rows if not r.get("completed")]

        open_count = len(open_rows)
        blocked_count = sum(1 for r in open_rows if judgement.get(r["id"], {}).get("blocked"))
        dues = [r["due"] for r in open_rows if r.get("due")]
        next_tickle = min(dues) if dues else ""

        # AI-progressible tallies for the navigator's 4th sort lens — the SAME classification the
        # canvas applies (so index and an open plan never disagree): quick_ready from the thin
        # plan-graph (the canvas's r.quick), and the progression tri-state from map_prog (r.prog).
        # quick/now are unblocked by construction (now is filtered defensively); later may be blocked.
        ai_quick = sum(1 for r in open_rows if judgement.get(r["id"], {}).get("quick_ready"))
        ai_now = sum(
            1
            for r in open_rows
            if map_prog(r.get("tags") or []) == "now"
            and not judgement.get(r["id"], {}).get("blocked")
        )
        ai_later = sum(1 for r in open_rows if map_prog(r.get("tags") or []) == "later")

        # Conversation counts for the navigator chip + "Conversations" sort lens — a standing
        # per-project count the artifact can't derive for a non-open project (it only loads the open
        # project's rows). Incomplete only (the read is status:incomplete). `chat_review_count` is a
        # SUBSET signal (items awaiting review still have a conversation) — counted independently; the
        # artifact composes the display (total chip, amber when review > 0). The project task itself
        # counts when it carries the tag (a project-scoped conversation is one more subject).
        # `not r["completed"]` guards the incomplete-only rule directly (the getList is already
        # status:incomplete, but build_envelope carries completed children too, so guard here).
        chat_count = sum(1 for r in open_rows if AI_CHAT in (r.get("tags") or [])) + (
            1 if AI_CHAT in tags else 0
        )
        chat_review_count = sum(
            1 for r in open_rows if AI_OUTPUT_REVIEW_NEEDED in (r.get("tags") or [])
        ) + (1 if AI_OUTPUT_REVIEW_NEEDED in tags else 0)

        # Engage-filter roll-ups for the navigator's Focus pill — per-project counts the artifact
        # can't derive for a non-open project. waiting_count = incomplete waiting-for items (the
        # canvas's r.k "waiting_for" classification, so it matches the board glyph), unlocking the
        # deferred "waiting-for" segment. Same row set (the project's incomplete children) and
        # completed-guard as the counts above.
        waiting_count = sum(1 for r in open_rows if map_kind(r.get("tags") or []) == "waiting_for")

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
                "chat_count": chat_count,
                "chat_review_count": chat_review_count,
                "waiting_count": waiting_count,
                # Viewing-curtain flag from the project's own #redacted tag — the navigator locks the
                # row as a placeholder. Additive; the board redacts at project AND item level.
                "redacted": REDACTED_TAG in tags,
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

    Returns a list (sorted by life → focus for deterministic output) of
    {focus_id, focus, life, redacted}. `redacted` is the focus task's own #redacted viewing-curtain
    state — the navigator collapses a redacted area to a single "Redacted Area of Focus" row.
    """
    out: list[dict[str, Any]] = []
    for t in parsed:
        tags = t.get("tags") or []
        if _FOCUS_TAG not in tags or not _active(
            tags, t.get("completed"), include_someday=include_someday
        ):
            continue
        out.append(
            {
                "focus_id": t["id"],
                "focus": t.get("name") or "",
                "life": _life(tags),
                # Viewing-curtain flag from the focus task's own #redacted tag — the navigator
                # collapses the whole area to a single "Redacted Area of Focus" row (name + its
                # projects hidden; the cascade onto projects/actions is client-side).
                "redacted": REDACTED_TAG in tags,
            }
        )

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

    And the engage-lens funnel fields (the Allen four-criteria model — context / time / energy /
    priority — each independently absent-able, a null exempting the item from that filter, never
    hiding it):
    - `estimate` — the RTM time estimate normalised to whole minutes (`parse_estimate_minutes`), or
      None when unset/unparseable (the common case).
    - `contexts` — the action-context tags present (`_contexts`), verbatim (may be `[]`).
    - `energy` — "high"/"low"/None from the `high_energy`/`low_energy` pair (`_energy`).
    - `exec` — the single-value execute classification "quick"/"now"/"later"/None (`_exec`), the same
      judgement behind the project ai_quick/ai_now/ai_later tallies.

    Redaction is server-derived and CASCADES: a row is `redacted` when the action's own #redacted tag
    is set OR its project OR its Area-of-Focus is redacted — so the cockpit locks anything under a
    shielded parent. Redaction is a CLIENT-side viewing curtain, not a server data vault: the engage
    fields (`estimate`/`contexts`/`energy`/`exec`) are computed for EVERY row, shielded or not — the
    server only SURFACES the `redacted` flag and the client shields the display (locked placeholder,
    excluded from the funnel, counts never leak). The server never ENFORCES redaction by suppressing
    data (see the redaction invariant in CLAUDE.md).

    timezone: forwarded to `build_envelope` for date localisation parity with the canvas (so each
        action's `due` matches the project `next_tickle` / canvas date convention).

    Returns a list (sorted by life → focus → project → name for deterministic, grouped output) of
        {action_id, name, project_id, project, focus, life, type, due, priority, blocked, estimate,
         contexts, energy, exec, redacted}.
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
        # Redaction cascade sources: the project's own curtain and its Area-of-Focus's. A row under
        # either is shielded even when its own tag is absent (server-derived, so the engage
        # suppression below can trust one flag).
        proj_redacted = REDACTED_TAG in tags
        focus_redacted = bool(parent) and REDACTED_TAG in (parent.get("tags") or [])

        env = build_envelope(parsed, pid, timezone=timezone)
        rows = env["rows"]
        # Same thin plan-graph as build_index — so per-action `blocked` and the project's
        # `blocked_count` are one and the same judgement.
        judgement = build_graph(env["header"], rows).get("judgement", {})
        for r in rows:
            row_tags = r.get("tags") or []
            # completed-guard: the tool feeds a status:incomplete read, but a broader
            # parsed set must not surface done items as jumpable actions.
            if _TEST_TAG in row_tags or r.get("completed"):
                continue
            redacted = (REDACTED_TAG in row_tags) or proj_redacted or focus_redacted
            # Redaction is a CLIENT-side viewing curtain, not a server data vault (Paul, 2026-07-13).
            # Names and dates already flow for shielded rows; the client renders the locked placeholder
            # and excludes shielded rows from the funnel (counts never leak). So the engage fields flow
            # too — always computed — and the `redacted` flag below tells the client to shield the display.
            estimate = parse_estimate_minutes(r.get("estimate"))
            contexts = _contexts(row_tags)
            energy = _energy(row_tags)
            execv = _exec(row_tags, judgement.get(r["id"], {}))
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
                    # Engage-lens funnel fields — computed for EVERY row; the client shields the
                    # display via the `redacted` flag (viewing curtain, not a server data vault).
                    "estimate": estimate,
                    "contexts": contexts,
                    "energy": energy,
                    "exec": execv,
                    # Viewing-curtain flag — the action's own #redacted tag OR a cascade from a
                    # redacted project / Area-of-Focus. The cockpit locks the result row.
                    "redacted": redacted,
                }
            )

    out.sort(key=lambda r: (r["life"], r["focus"].lower(), r["project"].lower(), r["name"].lower()))
    return out
