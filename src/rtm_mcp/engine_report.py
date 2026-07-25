r"""Pure (no-IO) builder for `gtd_engine_report` — proactive-contribution engine telemetry.

Replaces `engine-telemetry-aggregator.ms`, consumed by `agents/monitor-outcomes.md` § 4c (the
`monitor-outcomes-weekly` and `monitor-outcomes-monthly` scheduled tasks).

**Built to intent, NOT ported — the script's arithmetic has never produced a real number.**
Four independent faults, each sufficient on its own to zero every contribution-outcome figure.
Three were known when this module was briefed; two of those three and one further fault were
confirmed against the live account on 2026-07-25:

1. **Wrong task accessors** (briefed; fixed in the `.ms` on 2026-07-24). `getCreated()` /
   `getModified()` do not exist — the guarded calls returned null, `inWindow(null)` was false,
   and every task was skipped. Live: a 30-day window is 12 created vs 37 modified, so the figures
   were never near zero in reality.

2. **Wrong window key** (briefed). Even corrected, "created in window" read the *modified*
   timestamp. Here the window is a **creation cohort** — *of the things drafted this week, how
   many were accepted* — and touched-in-window is reported separately under its own name, never
   folded in.

3. **Wrong note accessors — NOT briefed, found here.** The `.ms` still reads
   `notes[j].getTitle()` / `.getBody()` behind the same guard idiom. Per
   `references/milkscript-api-surface.md` a Note has neither: there is only `getContent()`, with
   the title on line 1. So both were `""` on every note, and category and phase resolved to
   `"unknown"` for every contribution — a second, independent path to a 0% acceptance rate that
   survived the 2026-07-24 correctness pass untouched.

4. **Wrong body field name — NOT briefed, found here.** The `.ms` matches `/Phase:\s*(\w+)/`.
   The canonical CONTRIB body field is **`State:`** (`journaling-lifecycle.md` § "CONTRIB Notes
   — The Canonical Form"); `phase` is the *artefact frontmatter* field, which lives in the vault,
   not in RTM. Live: `State:` appears on 33 of 39 contribution notes and `Phase:` on **zero**.
   The regex could never have matched anything.

**Speculation upgrade rate stays withdrawn (D2), and this module will not fabricate it.**
`#ai_speculative` is removed on both upgrade and discard, and the upgrade branch retitles a note
`SOURCE-CONFIRMED` — a type absent from `note-shape-catalogue.md` § 2. RTM retains no durable
marker separating the two outcomes. The old `produced minus still_speculative` over a set drawn from
`tag:ai_speculative` was 0% by arithmetic, not observation. The open population is reported and
the gap is named in `gaps[]`.

**Nothing un-derivable is emitted as a zero.** `monitor-outcomes.md` § 4c's schema also asks for
unblock-walk outcomes, cluster syntheses, scheduled-task run health and per-source-agent yield.
None is derivable from RTM state (they are session/vault facts), and the script never produced
them either. They appear in `gaps[]` by name rather than as zeros — a zero that means "not
measured" is the failure this whole module exists to end.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from .contribution import CONTRIB_STATES as CANONICAL_CONTRIB_STATES
from .contribution import INVALIDATED_STATES, JUDGED_STATES, RETIRED_STATES
from .gtd_writes import (
    AUTO_CLOSED,
    Q_ACKNOWLEDGED,
    Q_ANSWERED,
    Q_PROCESSED,
    SURFACE_TYPE_TAG,
)
from .parsers import extract_note_body
from .surface_queue import parse_timestamp

#: The RTM reads this report needs. Kept here so the tool layer and the tests name one source.
CONTRIB_FILTER = "(tag:ai_contrib_drafted OR tag:ai_prep_drafted) AND NOT tag:test"
QUESTIONS_FILTER = "list:AI_Questions AND tag:claude_question AND NOT tag:test"
ACTIVITY_FILTER = "list:AI_Activity AND tag:ai_activity AND NOT tag:test"
SPECULATIVE_FILTER = "tag:ai_speculative AND NOT tag:test"
DEFERRED_FILTER = "tag:ai_deferred_pending_unblock AND status:incomplete AND NOT tag:test"

#: `journaling-lifecycle.md` § CONTRIB body format. Advisory: an observed value outside the set
#: is still counted and reported verbatim (the report describes what is there, and the live
#: estate carries `surfaced`, which is in neither published vocabulary).
CONTRIB_CATEGORIES = frozenset(
    {"research", "draft", "brief", "decision", "unblock", "capture", "consolidate", "monitor"}
)
#: The SIX canonical states, imported from the state-machine module rather than restated — one
#: vocabulary, one home (`journaling-lifecycle.md` § "The contribution state machine" is the
#: authority). The v2.9.0 divergence between two published lists was resolved gtd-side on
#: 2026-07-25; `offered` / `archived` / `surfaced` are RETIRED and are no longer expected.
CONTRIB_STATES = CANONICAL_CONTRIB_STATES

#: Queue-bloat thresholds (`ai-surface.md` § Cost discipline).
QUESTIONS_BLOAT_THRESHOLD = 20
ACTIVITY_BLOAT_THRESHOLD = 50

DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 366

_STATE_RE = re.compile(r"^\s*State:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_CATEGORY_RE = re.compile(r"^\s*Category:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
_TITLE_CATEGORY_RE = re.compile(
    r"[—–-]\s*(?:CONTRIB|CONTRIB-UPDATE|PREP)\s*[—–]\s*([^—–:]+?)\s*[—–]"  # noqa: RUF001
)

_HOURS = 3600.0


def _pct(numerator: int, denominator: int) -> int:
    return 0 if denominator == 0 else round(100 * numerator / denominator)


def _note_lines(note: dict[str, Any]) -> tuple[str, str]:
    body = extract_note_body(note) or ""
    title, _, rest = body.partition("\n")
    return title.strip(), rest


def contribution_note(task: dict[str, Any]) -> dict[str, Any] | None:
    """The latest CONTRIB / CONTRIB-UPDATE / PREP note on a task, by created date.

    Latest-wins matches the state machine: `CONTRIB-UPDATE` supersedes the original CONTRIB.
    (The `.ms` took the last note in RTM's arbitrary return order, which is not the same thing.)
    """
    candidates = [
        n
        for n in (task.get("notes") or [])
        if any(k in _note_lines(n)[0].upper() for k in ("CONTRIB", "PREP"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda n: str(n.get("created") or ""))


def contribution_facets(note: dict[str, Any] | None) -> tuple[str, str]:
    """`(category, state)` from a CONTRIB / PREP note.

    Category comes from the **body** `Category:` line — the canonical carrier. The title segment
    is a fallback only: live, 35 of 39 titles have no category segment and the 4 that parse yield
    summary text, not a category. A PREP note with neither defaults to `brief`, its permanent
    category alias (`tag-taxonomy.md` § `ai_prep_drafted`).
    """
    if note is None:
        return "unknown", "unknown"
    title, body = _note_lines(note)

    state_match = _STATE_RE.search(body)
    state = state_match.group(1).strip().lower().rstrip(".,;") if state_match else "unknown"

    category_match = _CATEGORY_RE.search(body)
    if category_match:
        category = category_match.group(1).strip().lower().rstrip(".,;")
    else:
        title_match = _TITLE_CATEGORY_RE.search(title)
        raw = title_match.group(1).strip().lower() if title_match else ""
        category = (
            raw
            if raw in CONTRIB_CATEGORIES
            else ("brief" if "PREP" in title.upper() else "unknown")
        )
    return category, state


def _tally(pairs: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in pairs:
        out[p] = out.get(p, 0) + 1
    return dict(sorted(out.items()))


def build_contributions(tasks: list[dict[str, Any]], *, window_start: datetime) -> dict[str, Any]:
    """The contribution cohort — created in window — plus the touched figure alongside it."""
    cohort_ids: list[str] = []
    touched = 0
    undated = 0
    categories: list[str] = []
    states: list[str] = []
    per_category: dict[str, dict[str, int]] = {}

    for t in tasks:
        modified = parse_timestamp(t.get("modified"))
        if modified and modified >= window_start:
            touched += 1
        created = parse_timestamp(t.get("created"))
        if created is None:
            undated += 1
            continue
        if created < window_start:
            continue
        cohort_ids.append(str(t.get("id") or ""))
        category, state = contribution_facets(contribution_note(t))
        categories.append(category)
        states.append(state)
        bucket = per_category.setdefault(category, {"total": 0, "accepted": 0, "judged": 0})
        bucket["total"] += 1
        if state in JUDGED_STATES:
            bucket["judged"] += 1
        if state == "accepted":
            bucket["accepted"] += 1

    total = len(cohort_ids)
    by_state = _tally(states)
    accepted = by_state.get("accepted", 0)
    edited = by_state.get("edited", 0)
    discarded = by_state.get("discarded", 0)
    # THE DENOMINATOR IS THE JUDGED SET, NOT THE COHORT. A `superseded` or `stale` contribution
    # was never assessed, so counting it as a miss reads as a rejection Paul never made
    # (`journaling-lifecycle.md` § "Why judged and invalidated are different"). An UNKNOWN state —
    # a note the old wiring never transitioned — is likewise not a judgement and is excluded.
    judged = accepted + edited + discarded
    invalidated = sum(by_state.get(s, 0) for s in INVALIDATED_STATES)
    return {
        "drafted_in_window": total,
        "touched_in_window": touched,
        "undated_creation": undated,
        "open_total": len(tasks),
        "cohort_ids": cohort_ids,
        "by_category": _tally(categories),
        "by_state": by_state,
        "accepted_count": accepted,
        "edited_count": edited,
        "discarded_count": discarded,
        "stale_count": by_state.get("stale", 0),
        "judged_count": judged,
        "invalidated_count": invalidated,
        "unjudged_count": total - judged - invalidated,
        "acceptance_rate_pct": _pct(accepted, judged),
        "edit_rate_pct": _pct(edited, judged),
        "discard_rate_pct": _pct(discarded, judged),
        "rate_denominator": "judged (accepted + edited + discarded) — invalidated and "
        "not-yet-transitioned contributions are excluded",
        "per_category_acceptance_rate_pct": {
            k: _pct(v["accepted"], v["judged"]) for k, v in sorted(per_category.items())
        },
        "retired_states_observed": sorted({s for s in by_state if s in RETIRED_STATES}),
    }


def _engaged(tags: list[str]) -> bool:
    return any(t in tags for t in (Q_ACKNOWLEDGED, Q_PROCESSED, Q_ANSWERED))


def build_surface_side(
    tasks: list[dict[str, Any]], *, window_start: datetime, bloat_threshold: int
) -> dict[str, Any]:
    """One AI-surface list's engagement telemetry.

    `closed_in_window` keys off **modified**, deliberately and uniquely: closure is an EVENT, so
    a task completed this week was necessarily modified this week whatever week it was created.
    Everything else in this report is a creation cohort.
    """
    created_in_window = 0
    touched = 0
    closed = 0
    auto_closed = 0
    engaged = 0
    open_depth = 0
    latencies: list[float] = []
    per_type: dict[str, dict[str, int]] = {}

    for t in tasks:
        tags = list(t.get("tags") or [])
        completed = t.get("completed")
        if not completed:
            open_depth += 1
        created = parse_timestamp(t.get("created"))
        modified = parse_timestamp(t.get("modified"))
        if modified and modified >= window_start:
            touched += 1
            if completed:
                closed += 1
        if created is None or created < window_start:
            continue
        created_in_window += 1
        item_type = next((k for k, v in SURFACE_TYPE_TAG.items() if v in tags), "unclassified")
        bucket = per_type.setdefault(item_type, {"created": 0, "engaged": 0, "auto_closed": 0})
        bucket["created"] += 1
        if AUTO_CLOSED in tags:
            auto_closed += 1
            bucket["auto_closed"] += 1
        if _engaged(tags):
            engaged += 1
            bucket["engaged"] += 1
            if created and modified and modified >= created:
                latencies.append((modified - created).total_seconds() / _HOURS)

    return {
        "created_in_window": created_in_window,
        "touched_in_window": touched,
        "closed_in_window": closed,
        "auto_closed_in_window": auto_closed,
        "paul_engaged_in_window": engaged,
        "open_depth": open_depth,
        "queue_bloat": open_depth > bloat_threshold,
        "queue_bloat_threshold": bloat_threshold,
        # An approximation, named as one: RTM carries no per-transition timestamp, so the
        # elapsed time is creation → last modification of an engaged item, which also absorbs
        # any later engine edit. Directionally useful, not an SLA.
        "avg_latency_to_engagement_hours": (
            round(sum(latencies) / len(latencies), 1) if latencies else None
        ),
        "latency_basis": "created→last-modified of engaged items (approximate)",
        "per_item_type": {k: per_type[k] for k in sorted(per_type)},
    }


def build_speculation(tasks: list[dict[str, Any]], *, window_start: datetime) -> dict[str, Any]:
    """The OPEN speculative population only — see D2 in the module header."""
    opened = 0
    touched = 0
    oldest: datetime | None = None
    for t in tasks:
        modified = parse_timestamp(t.get("modified"))
        if modified and modified >= window_start:
            touched += 1
        created = parse_timestamp(t.get("created"))
        if created is None:
            continue
        if oldest is None or created < oldest:
            oldest = created
        if created >= window_start:
            opened += 1
    return {
        "open_total": len(tasks),
        "opened_in_window": opened,
        "touched_in_window": touched,
        "oldest_open": oldest.date().isoformat() if oldest else None,
        "upgrade_rate_reported": False,
    }


def build_engine_report(
    *,
    contributions: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    activity: list[dict[str, Any]],
    speculative: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
    now: str,
    window_days: int,
    today: str,
) -> dict[str, Any]:
    """The whole report. `now` is an ISO-8601 instant; the window is `[now - window_days, now]`."""
    end = parse_timestamp(now) or datetime.now(tz=UTC)
    start = end - timedelta(days=window_days)

    gaps = [
        {
            "metric": "speculation_upgrade_rate",
            "reason": "Not computable from RTM state: #ai_speculative is removed on BOTH upgrade "
            "and discard, and the upgrade branch retitles a note SOURCE-CONFIRMED — a type absent "
            "from note-shape-catalogue.md § 2. The previously-reported 0% was arithmetic, not "
            "observation. Restoring it needs a durable upgrade marker (an engine decision).",
        },
        {
            "metric": "unblock_walk_outcomes",
            "reason": "Session facts, not RTM state — walks run / outcome A-B-C / cascade depth "
            "are never written to a task. monitor-outcomes.md § 4c asks for them; no RTM read can "
            "supply them, and the retired script never did either.",
        },
        {
            "metric": "cluster_synthesis_yield",
            "reason": "Vault facts — syntheses and their accepted suggestions live in AI Memory, "
            "outside this server's read boundary.",
        },
        {
            "metric": "scheduled_task_run_health",
            "reason": "Runs / errors / durations live in the scheduled-task framework's own "
            "notifications, not in RTM.",
        },
    ]

    return {
        "window_days": window_days,
        "window_start": start.isoformat().replace("+00:00", "Z"),
        "window_end": end.isoformat().replace("+00:00", "Z"),
        "window_semantics": "creation cohort — 'in window' means CREATED in window; "
        "'touched' figures mean MODIFIED in window and are never folded in",
        "current_date": today,
        "contributions": build_contributions(contributions, window_start=start),
        "ai_surface": {
            "questions": build_surface_side(
                questions, window_start=start, bloat_threshold=QUESTIONS_BLOAT_THRESHOLD
            ),
            "activity": build_surface_side(
                activity, window_start=start, bloat_threshold=ACTIVITY_BLOAT_THRESHOLD
            ),
        },
        "speculation": build_speculation(speculative, window_start=start),
        "engine_state": {"deferred_pending_unblock": len(deferred)},
        "gaps": gaps,
    }


__all__ = [
    "ACTIVITY_BLOAT_THRESHOLD",
    "ACTIVITY_FILTER",
    "CONTRIB_CATEGORIES",
    "CONTRIB_FILTER",
    "CONTRIB_STATES",
    "DEFAULT_WINDOW_DAYS",
    "DEFERRED_FILTER",
    "MAX_WINDOW_DAYS",
    "QUESTIONS_BLOAT_THRESHOLD",
    "QUESTIONS_FILTER",
    "SPECULATIVE_FILTER",
    "build_contributions",
    "build_engine_report",
    "build_speculation",
    "build_surface_side",
    "contribution_facets",
    "contribution_note",
]
