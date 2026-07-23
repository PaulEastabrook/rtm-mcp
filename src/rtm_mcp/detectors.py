"""Pure (no-IO) faithful ports of the GTD MilkScript detector scripts.

Each ``build_*`` here reproduces the query logic of one
``plugins/gtd/skills/gtd/scripts/*-candidates.ms`` / ``health-check.ms`` script (the reference the
GTD skill runs today via ``rtm_run_script_ephemeral``), byte-faithful to the detector's
**selection + fields**, re-emitted as typed rows instead of the script's line-oriented ``print``
text. The tool layer (``tools/gtd.py``) issues the detector's **verbatim** RTM ``filter=`` queries
against ``rtm.tasks.getList`` and hands the parsed rows here — so RTM's server evaluates the same
search string the ``.ms`` used, and this module only replays the identical client-side
filter/skip/sort logic. No clock, no network: the caller passes ``today`` (account-tz localised)
and ``timezone``.

Faithful-port discipline (document-what-is): the ``.ms`` scripts are the spec. Where a header
comment documents a param the code never reads (reassessment's ``include_paused``), it is NOT
implemented. Rows carry three deterministic enrichments the brief asks for and the ``.ms`` did not
emit — ``deep_link`` (``project_plan._permalink``), ``kind`` (``canvas_seed.map_kind``), and the
``priority`` band — these are additive projection metadata, not a logic change.
"""

from __future__ import annotations

import re
from typing import Any

from .canvas_seed import map_kind
from .note_shape import effective_title
from .parsers import extract_note_body
from .project_plan import _norm_date, _permalink

# --------------------------------------------------------------------------- #
# Verbatim RTM filter strings — copied from the .ms scripts (the query is the spec).
# The tool layer passes these to client.call("rtm.tasks.getList", filter=...).
# --------------------------------------------------------------------------- #

# reassessment-candidates.ms — two queries OR'd + deduped by id.
REASSESSMENT_QUERIES = (
    "tag:ai_contrib_drafted AND status:incomplete AND NOT tag:test AND NOT tag:do_not_auto_progress",
    "tag:ai_prep_drafted AND status:incomplete AND NOT tag:test AND NOT tag:do_not_auto_progress",
)

# unblock-candidates.ms — five source classes (order = dedup precedence).
UNBLOCK_QUERIES: tuple[tuple[str, str], ...] = (
    ("ai_deferred_pending_unblock", "tag:ai_deferred_pending_unblock AND status:incomplete"),
    ("waiting_for_overdue", "tag:waiting_for AND status:incomplete AND dueBefore:today"),
    (
        "blocker_note_active",
        "tag:action AND status:incomplete AND hasNotes:true AND noteContains:BLOCKER "
        "AND NOT tag:waiting_for",
    ),
    (
        "depends_on_active",
        "tag:action AND status:incomplete AND hasNotes:true AND noteContains:DEPENDS-ON "
        "AND NOT tag:waiting_for",
    ),
    ("speculative_stale", "tag:ai_speculative AND status:incomplete"),
)

# decision/deliverable/research/calendar-prep base queries.
ACTION_QUERY = "tag:action AND status:incomplete AND NOT tag:test"
CALENDAR_PREP_QUERY = "tag:calendar_entry AND status:incomplete AND NOT tag:test"

# capture-candidates.ms — incomplete + (optionally) completed-within-window.
CAPTURE_INCOMPLETE_QUERIES = REASSESSMENT_QUERIES  # identical two incomplete queries


def capture_completed_queries(window_days: int) -> tuple[str, str]:
    w = f'completedWithin:"{window_days} days of today"'
    return (
        f"tag:ai_contrib_drafted AND status:completed AND {w} AND NOT tag:test",
        f"tag:ai_prep_drafted AND status:completed AND {w} AND NOT tag:test",
    )


# topic-cluster-detector.ms / health-check.ms broad reads.
TOPIC_CLUSTER_QUERY = "status:incomplete AND NOT tag:test"
HEALTH_CHECK_QUERY = "status:incomplete"

# --------------------------------------------------------------------------- #
# Lexical heuristics — faithful translations of the JS regex arrays.
# --------------------------------------------------------------------------- #

_I = re.IGNORECASE

DECISION_PATTERNS = [
    re.compile(p, _I)
    for p in (
        r"^\s*(decide|choose|pick|select)\b",
        r"\bdecide\s+(between|whether|on|how|what|which)",
        r"\bchoose\s+(between|the|a|an|approach|option|alternative)",
        r"\bpick\s+(the|a|an|approach|option|alternative)",
        r"\bevaluate\s+(the\s+)?(options|alternatives|approaches|trade[- ]offs)\b",
        r"\breview\s+(the\s+)?(options|alternatives|approaches|trade[- ]offs)\b",
        r"\b(make|reach)\s+(a\s+)?decision\b",
        r"\bshould\s+(we|i)\s+",
        r"\bwhat['’‘]?s\s+the\s+(right|best)\s+(approach|option|way|move|call)\b",  # noqa: RUF001
        r"\bpros?\s+and\s+cons?\b",
        r"\bweigh\s+up\b",
        r"\b(approve|reject|accept|decline)\s+(the\s+)?(proposal|recommendation|approach|design)",
        r"\b(go|no[- ]go)\s+decision\b",
        r"\bsign[- ]?off\s+on\b",
    )
]
DECISION_ANTI = [
    re.compile(p, _I)
    for p in (
        r"\bemail\b",
        r"\bdraft\s+the\s+decision\s+(record|memo)",
        r"\bsend\b",
        r"\bresearch\b",
        r"\binvestigate\b",
        r"\bfind\s+out\b",
        r"\bbook\s+(meeting|slot|time)",
        r"\bmeet\s+(with|to)\b",
        r"\bwrite\s+up\s+the\s+decision\b",
    )
]

DELIVERABLE_PATTERNS = [
    re.compile(p, _I)
    for p in (
        r"^\s*(draft|write|compose|prepare)\b",
        r"^\s*(email|reply|respond)\b",
        r"^\s*(send|share|distribute|circulate)\b",
        r"^\s*(create|produce|generate|author)\s+(the\s+|a\s+|an\s+)?"
        r"(spec|document|brief|memo|paper|deck|slides|report|update|note|proposal|"
        r"recommendation|position|statement|letter)",
        r"^\s*(update|revise|edit|refine)\s+(the\s+)?"
        r"(spec|document|brief|memo|paper|deck|slides|report|note|proposal|policy|template)",
        r"^\s*(write\s+up|write-up)\b",
        r"\bposition(ing)?\s+statement\b",
        r"\b(weekly|monthly|quarterly)\s+(status|update|review|report|note)\b",
        r"\b(rfd|rfc|adr)\b",
        r"\bone[- ]pager\b",
        r"\bbusiness\s+case\b",
        r"\bjob\s+(spec|description)\b",
        r"\boffer\s+letter\b",
        r"\bappointment\s+letter\b",
        r"\balr\b",
    )
]
DELIVERABLE_ANTI = [
    re.compile(p, _I)
    for p in (
        r"\bdraft\s+(a\s+)?(decision|recommendation\s+(for|on)\s+how\s+to\s+decide)",
        r"\bdecide\s+(between|on|whether)",
        r"\bresearch\b",
        r"\binvestigate\b",
        r"\bfind\s+out\b",
        r"\blook\s+into\b",
        r"\bbook\s+(meeting|slot|time)",
        r"\bmeet\s+(with|to)\b",
    )
]

RESEARCH_PATTERNS = [
    re.compile(p, _I)
    for p in (
        r"\bfind\s+out\b",
        r"\blook\s+into\b",
        r"\bunderstand\b",
        r"\bresearch\b",
        r"\binvestigate\b",
        r"\bexplore\b",
        r"\blearn\s+about\b",
        r"\bsynthesis[ei]\b",
        r"\breview\s+(the\s+)?(literature|landscape|options|space)\b",
        r"\bcompare\b.*\bvs\b",
        r"\bcompare\b.*\bversus\b",
        r"\bassess\s+(the\s+)?(feasibility|viability|risk|impact)\b",
        r"\bevaluate\s+(the\s+)?(options|alternatives|approaches)\b",
    )
]
RESEARCH_ANTI = [
    re.compile(p, _I)
    for p in (
        r"\bemail\b",
        r"\bdraft\b",
        r"\bsend\b",
        r"\bdecide\b",
        r"\bbook\b.*\bmeeting\b",
        r"\bmeet\b.*\bto\s+research\b",
    )
]

# topic-cluster-detector.ms — the trivial-tag exclusion set (verbatim).
_TRIVIAL_TAGS = frozenset(
    {
        "action",
        "project",
        "focus",
        "waiting_for",
        "someday",
        "ai_conversation",
        "ai_output_review_needed",
        "ai_output_approved",
        "ai_contrib_drafted",
        "ai_prep_drafted",
        "ai_speculative",
        "ai_deferred_pending_unblock",
        "ai_pending_creation_fanout",
        "claude_question",
        "ai_activity",
        "calendar_entry",
        "test",
        "do_not_auto_progress",
        "personal",
        "work",
        "using_device",
        "location_home",
        "location_office",
        "location_errand",
        "conversation_messenger",
        "conversation_email",
        "conversation_phone_call",
        "conversation_video_call",
        "conversation_f2f",
        "purpose_principles",
        "vision",
        "goal",
        "chore",
        "gtd",
        "note",
        "ai_review",
        "ai_approved",
    }
)
_WORKFLOW_STATES = ("action", "waiting_for", "calendar_entry")
_PERSON_RE = re.compile(r"^[a-z]+$")

# Sort sentinel for a row with no date (JS `new Date(8640000000000000)`).
_FAR_FUTURE = "9999-12-31"

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _has(tags: list[str], target: str) -> bool:
    return target in tags


def _matches_any(name: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(name) for p in patterns)


def _prio(raw: str | None) -> str:
    """Raw RTM priority ("N"/"1"/"2"/"3") → the "1"|"2"|"3"|"" band (project-index encoding)."""
    return raw if raw in ("1", "2", "3") else ""


def _is_trivial_tag(tag: str) -> bool:
    """topic-cluster: static trivial set + dynamic q_* and ai_*optin exclusions."""
    if tag in _TRIVIAL_TAGS or tag.startswith("q_"):
        return True
    return tag.startswith("ai_") and "optin" in tag


def _note_title(note: dict[str, Any]) -> str:
    """The note's effective title — the explicit title field, else the body's first line (RTM
    stores ``title\\ntext`` in the single body field and returns an empty title on read)."""
    return effective_title(note.get("title") or "", extract_note_body(note))


def _deep_link(t: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    return _permalink(str(t.get("id")), by_id, t.get("list_id"))


def _base_row(t: dict[str, Any], by_id: dict[str, dict[str, Any]], timezone: str | None) -> dict:
    """The common typed-row projection every candidate carries."""
    return {
        "id": str(t.get("id") or ""),
        "name": t.get("name") or "",
        "kind": map_kind(t.get("tags") or []),
        "priority": _prio(t.get("priority")),
        "tags": list(t.get("tags") or []),
        "parent_id": t.get("parent_task_id") or None,
        "deep_link": _deep_link(t, by_id),
    }


def _effective_date_key(start: str | None, due: str | None) -> str:
    """min(start, due) if both, else start or due, else the far-future sentinel — a comparable
    key (raw UTC ISO strings sort lexicographically). Faithful to the .ms ``effectiveDate``."""
    if start and due:
        return start if start < due else due
    return start or due or _FAR_FUTURE


def _dedup_by_id(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """First-seen dedup across parsed result lists, preserving order (the .ms dedup contract)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for lst in lists:
        for t in lst:
            tid = str(t.get("id") or "")
            if tid and tid not in seen:
                seen.add(tid)
                out.append(t)
    return out


def _by_id(*lists: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for lst in lists:
        for t in lst:
            idx[str(t.get("id") or "")] = t
    return idx


# --------------------------------------------------------------------------- #
# 1. reassessment-candidates.ms
# --------------------------------------------------------------------------- #


def build_reassessment_candidates(
    contrib: list[dict[str, Any]],
    prep: list[dict[str, Any]],
    *,
    stale_threshold_days: int = 1,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Open ai_contrib_drafted / ai_prep_drafted contributions due for reassessment. Skips
    personal-unless-ai_research_optin and RTM-modified-within-``stale_threshold_days``; sorts by
    modified ascending (oldest first). ``include_paused`` is documented-but-unused in the .ms and
    is deliberately not implemented."""
    by_id = _by_id(contrib, prep)
    tasks = _dedup_by_id(contrib, prep)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for t in tasks:
        tags = t.get("tags") or []
        name = t.get("name") or ""
        modified = t.get("modified")
        if _has(tags, "personal") and not _has(tags, "ai_research_optin"):
            skipped.append({"name": name, "reason": "personal life-context, not opted in"})
            continue
        # RTM-modified within the stale threshold -> let it settle. today minus threshold, date-only.
        if modified and _norm_date(modified, timezone) > _minus_days(today, stale_threshold_days):
            skipped.append(
                {
                    "name": name,
                    "reason": f"RTM-modified within stale threshold ({stale_threshold_days}d)",
                }
            )
            continue
        tag_set = []
        if _has(tags, "ai_contrib_drafted"):
            tag_set.append("CONTRIB")
        if _has(tags, "ai_prep_drafted"):
            tag_set.append("PREP")
        row = _base_row(t, by_id, timezone)
        row["modified"] = _norm_date(modified, timezone)
        row["tag_set"] = tag_set
        candidates.append(row)

    candidates.sort(key=lambda c: c["modified"] or "")
    return {
        "candidates": candidates,
        "skipped": skipped,
        "stale_threshold_days": stale_threshold_days,
        "count": len(candidates),
    }


def _minus_days(iso_date: str, days: int) -> str:
    """YYYY-MM-DD minus N days (pure, no clock). Used only for date-only threshold comparison."""
    from datetime import date, timedelta

    try:
        y, m, d = (int(x) for x in iso_date[:10].split("-"))
        return (date(y, m, d) - timedelta(days=days)).isoformat()
    except Exception:
        return iso_date[:10]


def _plus_days(iso_date: str, days: int) -> str:
    from datetime import date, timedelta

    try:
        y, m, d = (int(x) for x in iso_date[:10].split("-"))
        return (date(y, m, d) + timedelta(days=days)).isoformat()
    except Exception:
        return iso_date[:10]


# --------------------------------------------------------------------------- #
# 2. unblock-candidates.ms — five source classes
# --------------------------------------------------------------------------- #


def build_unblock_candidates(
    class_results: dict[str, list[dict[str, Any]]],
    *,
    max_candidates: int = 50,
    include_speculative_stale: bool = True,
    stale_speculative_days: int = 14,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Union of five unblock-candidate classes with first-seen dedup (class order =
    precedence). class 3/4 require an active BLOCKER / DEPENDS-ON note **title**; class 5 keeps
    only ai_speculative items older than ``stale_speculative_days``. ``max_candidates`` (0 = no
    cap) is applied LAST across the merged set."""
    all_rows = [r for rows in class_results.values() for r in rows]
    by_id = _by_id(all_rows)
    disqualifying = ("test", "do_not_auto_progress", "someday")
    stale_cutoff = _minus_days(today, stale_speculative_days)

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _emit(t: dict[str, Any], source_class: str, extra: dict[str, Any] | None = None) -> None:
        row = _base_row(t, by_id, timezone)
        row["taskseries_id"] = str(t.get("taskseries_id") or "")
        row["list_id"] = str(t.get("list_id") or "")
        row["source_class"] = source_class
        if extra:
            row.update(extra)
        candidates.append(row)
        seen.add(str(t.get("id") or ""))

    for source_class, rows in class_results.items():
        for t in rows:
            tid = str(t.get("id") or "")
            tags = t.get("tags") or []
            name = t.get("name") or ""
            if any(_has(tags, d) for d in disqualifying):
                skipped.append(
                    {"id": tid, "name": name, "reason": "disqualifying tag", "source": source_class}
                )
                continue
            if tid in seen:
                continue
            if source_class == "waiting_for_overdue":
                _emit(t, source_class, {"due": _norm_date(t.get("due"), timezone)})
            elif source_class in ("blocker_note_active", "depends_on_active"):
                marker = "BLOCKER" if source_class == "blocker_note_active" else "DEPENDS-ON"
                if _has_active_note(t, marker):
                    _emit(t, source_class)
            elif source_class == "speculative_stale":
                if not include_speculative_stale:
                    continue
                modified = t.get("modified")
                if not modified or _norm_date(modified, timezone) > stale_cutoff:
                    continue  # not stale enough — silent skip (faithful)
                _emit(t, source_class, {"modified": _norm_date(modified, timezone)})
            else:  # ai_deferred_pending_unblock
                _emit(t, source_class)

    capped = candidates[:max_candidates] if max_candidates and max_candidates > 0 else candidates
    return {
        "candidates": capped,
        "skipped": skipped,
        "cap": max_candidates,
        "stale_speculative_days": stale_speculative_days,
        "count": len(capped),
    }


def _has_active_note(t: dict[str, Any], marker: str) -> bool:
    """A note whose effective title contains ``marker`` and, for BLOCKER, not BLOCKER-RESOLVED."""
    for n in t.get("notes") or []:
        title = _note_title(n)
        if marker in title:
            if marker == "BLOCKER" and "BLOCKER-RESOLVED" in title:
                continue
            return True
    return False


# --------------------------------------------------------------------------- #
# 3-5. decision / deliverable / research — shared lexical skeleton
# --------------------------------------------------------------------------- #


def _build_lexical(
    tasks: list[dict[str, Any]],
    *,
    patterns: list[re.Pattern[str]],
    anti: list[re.Pattern[str]],
    optin_tag: str,
    horizon_days: int,
    exclude_drafted: bool,
    today: str,
    timezone: str | None,
) -> dict[str, Any]:
    """The shared decision/deliverable/research loop. horizon_days == 0 → no date filter (the
    ``!= null`` guard); a lexical or out-of-horizon miss is a SILENT skip (not in ``skipped``)."""
    by_id = _by_id(tasks)
    horizon_end = _plus_days(today, horizon_days)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def _in_horizon(iso: str | None) -> bool:
        if horizon_days == 0:
            return True
        if not iso:
            return False
        d = _norm_date(iso, timezone)
        return bool(d) and today <= d <= horizon_end

    for t in tasks:
        tags = t.get("tags") or []
        name = t.get("name") or ""
        due = t.get("due")
        start = t.get("start")
        if not _matches_any(name, patterns):
            continue
        if _matches_any(name, anti):
            skipped.append({"name": name, "reason": "matched anti-pattern (other category)"})
            continue
        if horizon_days > 0 and not _in_horizon(due) and not _in_horizon(start):
            continue
        if _has(tags, "do_not_auto_progress"):
            skipped.append({"name": name, "reason": "do_not_auto_progress flagged"})
            continue
        if exclude_drafted and _has(tags, "ai_contrib_drafted"):
            skipped.append({"name": name, "reason": "already contrib-drafted"})
            continue
        if _has(tags, "personal") and not _has(tags, optin_tag):
            skipped.append({"name": name, "reason": "personal life-context, not opted in"})
            continue
        row = _base_row(t, by_id, timezone)
        key = _effective_date_key(start, due)
        row["due"] = _norm_date(due, timezone)
        row["start"] = _norm_date(start, timezone)
        row["date"] = "" if key == _FAR_FUTURE else _norm_date(key, timezone)
        row["_sort"] = key
        candidates.append(row)

    candidates.sort(key=lambda c: c.pop("_sort"))
    return {
        "candidates": candidates,
        "skipped": skipped,
        "horizon_days": horizon_days,
        "count": len(candidates),
    }


def build_decision_candidates(
    tasks: list[dict[str, Any]],
    *,
    horizon_days: int = 0,
    exclude_drafted: bool = True,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    return _build_lexical(
        tasks,
        patterns=DECISION_PATTERNS,
        anti=DECISION_ANTI,
        optin_tag="ai_decide_optin",
        horizon_days=horizon_days,
        exclude_drafted=exclude_drafted,
        today=today,
        timezone=timezone,
    )


def build_deliverable_candidates(
    tasks: list[dict[str, Any]],
    *,
    horizon_days: int = 0,
    exclude_drafted: bool = True,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    return _build_lexical(
        tasks,
        patterns=DELIVERABLE_PATTERNS,
        anti=DELIVERABLE_ANTI,
        optin_tag="ai_draft_optin",
        horizon_days=horizon_days,
        exclude_drafted=exclude_drafted,
        today=today,
        timezone=timezone,
    )


def build_research_candidates(
    tasks: list[dict[str, Any]],
    *,
    horizon_days: int = 2,
    exclude_drafted: bool = True,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    return _build_lexical(
        tasks,
        patterns=RESEARCH_PATTERNS,
        anti=RESEARCH_ANTI,
        optin_tag="ai_research_optin",
        horizon_days=horizon_days,
        exclude_drafted=exclude_drafted,
        today=today,
        timezone=timezone,
    )


# --------------------------------------------------------------------------- #
# 6. calendar-prep-candidates.ms
# --------------------------------------------------------------------------- #


def build_calendar_prep_candidates(
    tasks: list[dict[str, Any]],
    *,
    horizon_days: int = 2,
    exclude_drafted: bool = True,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Calendar entries with a start-OR-due date in the horizon window. Faithful to the .ms
    ``horizon_days || 2`` quirk: a falsy 0 becomes 2 (0 cannot disable the horizon here). No
    personal filter; skips do_not_auto_progress / ai_prep_drafted; emits time (from the raw due)."""
    horizon = horizon_days or 2  # || 2 — 0 becomes 2
    by_id = _by_id(tasks)
    horizon_end = _plus_days(today, horizon)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def _in_horizon(iso: str | None) -> bool:
        if not iso:
            return False
        d = _norm_date(iso, timezone)
        return bool(d) and today <= d <= horizon_end

    for t in tasks:
        tags = t.get("tags") or []
        name = t.get("name") or ""
        due = t.get("due")
        start = t.get("start")
        if not _in_horizon(due) and not _in_horizon(start):
            continue
        if _has(tags, "do_not_auto_progress"):
            skipped.append({"name": name, "reason": "do_not_auto_progress flagged"})
            continue
        if exclude_drafted and _has(tags, "ai_prep_drafted"):
            skipped.append({"name": name, "reason": "already prep-drafted"})
            continue
        row = _base_row(t, by_id, timezone)
        key = _effective_date_key(start, due)
        row["due"] = _norm_date(due, timezone)
        row["start"] = _norm_date(start, timezone)
        row["date"] = _norm_date(key, timezone)
        row["time"] = _extract_time(due if due else start, timezone)
        row["_sort"] = key
        candidates.append(row)

    candidates.sort(key=lambda c: c.pop("_sort"))
    return {
        "candidates": candidates,
        "skipped": skipped,
        "horizon_days": horizon,
        "count": len(candidates),
    }


def _extract_time(iso: str | None, timezone: str | None) -> str:
    """HH:MM in the account tz (the only detector that surfaces a time), "" when none."""
    if not iso or "T" not in iso:
        return ""
    from .parsers import _convert_rtm_date

    localised = _convert_rtm_date(iso, timezone) if timezone else iso
    try:
        return localised[11:16]
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# 7. capture-candidates.ms
# --------------------------------------------------------------------------- #


def build_capture_candidates(
    incomplete: list[list[dict[str, Any]]],
    completed: list[list[dict[str, Any]]],
    *,
    window_days: int = 7,
    today: str,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Recent ai_contrib_drafted / ai_prep_drafted contributions (incomplete + optionally
    completed-within-window). Skips personal-unless-ai_research_optin; window filter on modified
    (window_days == 0 → no window); sorts by modified DESCENDING (newest first)."""
    lists = [*incomplete, *completed]
    by_id = _by_id(*lists)
    tasks = _dedup_by_id(*lists)
    window_cutoff = _minus_days(today, window_days) if window_days > 0 else ""
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for t in tasks:
        tags = t.get("tags") or []
        name = t.get("name") or ""
        modified = t.get("modified")
        mod_date = _norm_date(modified, timezone)
        if _has(tags, "personal") and not _has(tags, "ai_research_optin"):
            skipped.append({"name": name, "reason": "personal life-context, not opted in"})
            continue
        if window_days > 0 and mod_date and mod_date < window_cutoff:
            skipped.append(
                {"name": name, "reason": f"modified before window ({window_days}d) cutoff"}
            )
            continue
        tag_set = []
        if _has(tags, "ai_contrib_drafted"):
            tag_set.append("CONTRIB")
        if _has(tags, "ai_prep_drafted"):
            tag_set.append("PREP")
        row = _base_row(t, by_id, timezone)
        row["modified"] = mod_date
        row["status"] = "completed" if t.get("completed") else "incomplete"
        row["tag_set"] = tag_set
        candidates.append(row)

    candidates.sort(key=lambda c: c["modified"] or "", reverse=True)
    return {
        "candidates": candidates,
        "skipped": skipped,
        "window_days": window_days,
        "count": len(candidates),
    }


# --------------------------------------------------------------------------- #
# 8. topic-cluster-detector.ms
# --------------------------------------------------------------------------- #


def build_topic_clusters(
    tasks: list[dict[str, Any]],
    *,
    threshold: int = 5,
    max_clusters: int = 20,
    exclude_personal: bool = True,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Cross-project tag clusters: a non-trivial tag carried by ≥``threshold`` workflow-state
    items across ≥2 distinct parent projects. anchor_type person = an all-lowercase 3-12 char tag.
    Sorted by item_count desc; ``max_clusters`` (0 = no cap) applied last."""
    index: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        tags = t.get("tags") or []
        if exclude_personal and _has(tags, "personal"):
            continue
        if not any(s in tags for s in _WORKFLOW_STATES):
            continue
        for tag in tags:
            if _is_trivial_tag(tag):
                continue
            index.setdefault(tag, []).append(
                {
                    "id": str(t.get("id") or ""),
                    "taskseries_id": str(t.get("taskseries_id") or ""),
                    "list_id": str(t.get("list_id") or ""),
                    "name": t.get("name") or "",
                    "parent_id": t.get("parent_task_id") or None,
                }
            )

    clusters: list[dict[str, Any]] = []
    for tag, items in index.items():
        if len(items) < threshold:
            continue
        parents = {i["parent_id"] for i in items if i["parent_id"]}
        if len(parents) < 2:
            continue
        clusters.append(
            {
                "anchor": tag,
                "anchor_type": "person" if _is_person_tag(tag) else "theme",
                "item_count": len(items),
                "distinct_projects": len(parents),
                "sample_items": [{"id": i["id"], "name": i["name"]} for i in items[:10]],
            }
        )

    clusters.sort(key=lambda c: c["item_count"], reverse=True)
    capped = clusters[:max_clusters] if max_clusters and max_clusters > 0 else clusters
    return {
        "clusters": capped,
        "threshold": threshold,
        "exclude_personal": exclude_personal,
        "cap": max_clusters,
        "count": len(capped),
    }


def _is_person_tag(tag: str) -> bool:
    return bool(_PERSON_RE.fullmatch(tag)) and 3 <= len(tag) <= 12


# --------------------------------------------------------------------------- #
# 9. health-check.ms — one broad status:incomplete read (consolidates the .ms N+1)
# --------------------------------------------------------------------------- #

_LIFE_CONTEXT = ("work", "personal", "leanworking")
_WORKFLOW_STATE_TAGS = ("action", "project", "focus", "waiting_for", "someday")


def build_health_check(
    tasks: list[dict[str, Any]], *, today: str, timezone: str | None = None
) -> dict[str, Any]:
    """Systemic GTD health audit — five issue categories over one status:incomplete read (the .ms
    ran a per-project child sub-query; this computes the parent→children map client-side for the
    same result, avoiding the N+1). Issue rows carry {category, name, task_id, deep_link} — an
    enrichment over the .ms name-only text."""
    by_id = {str(t.get("id") or ""): t for t in tasks}
    children: dict[str, list[dict[str, Any]]] = {}
    for t in tasks:
        pid = str(t.get("parent_task_id") or "")
        if pid:
            children.setdefault(pid, []).append(t)

    stale_cutoff = _minus_days(today, 14)
    issues: list[dict[str, Any]] = []

    def _issue(category: str, t: dict[str, Any]) -> None:
        issues.append(
            {
                "category": category,
                "name": t.get("name") or "",
                "task_id": str(t.get("id") or ""),
                "deep_link": _deep_link(t, by_id),
            }
        )

    for t in tasks:
        tags = t.get("tags") or []
        completed = t.get("completed")
        is_subtask = bool(t.get("parent_task_id"))
        if completed:
            continue
        # 1. STUCK PROJECT — a #project (not #test) with no incomplete #action child.
        if _has(tags, "project") and not _has(tags, "test"):
            kids = children.get(str(t.get("id") or ""), [])
            has_next = any(
                _has(k.get("tags") or [], "action")
                and not _has(k.get("tags") or [], "test")
                and not k.get("completed")
                for k in kids
            )
            if not has_next:
                _issue("stuck_project", t)
        if _has(tags, "test"):
            continue
        # 2-3 apply to subtasks only (the .ms queries carry isSubtask:true).
        if is_subtask:
            # 2. MISSING LIFE CONTEXT.
            if not any(_has(tags, lc) for lc in _LIFE_CONTEXT):
                _issue("missing_life_context", t)
            # 3. MISSING WORKFLOW STATE.
            if not any(_has(tags, ws) for ws in _WORKFLOW_STATE_TAGS):
                _issue("missing_workflow_state", t)
        # 4. STALE WAITING-FOR (>14d since modified) — not subtask-restricted in the .ms.
        if _has(tags, "waiting_for"):
            modified = t.get("modified")
            if modified and _norm_date(modified, timezone) < stale_cutoff:
                _issue("stale_waiting_for", t)
        # 5. ACTION WITH DUE DATE (potential misuse) — not subtask-restricted in the .ms.
        if (
            _has(tags, "action")
            and not _has(tags, "waiting_for")
            and not _has(tags, "calendar_entry")
            and t.get("due")
        ):
            _issue("action_with_due_date", t)

    return {"issues": issues, "count": len(issues), "current_date": today}
