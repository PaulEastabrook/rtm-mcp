"""RTM response parsing, formatting, and normalization.

Handles the quirks of RTM's XML-to-JSON API responses: single items
returned as dicts instead of arrays, nested wrappers, text nodes stored
in ``$t``, and timezone conversion.
"""

from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def ensure_list(data: Any) -> list:
    """Normalize RTM response data to a list.

    RTM returns a single item as a dict and multiple items as a list.
    This handles both cases plus falsy values (None, empty string, ``[]``).
    """
    if not data:
        return []
    if isinstance(data, dict):
        return [data]
    return list(data)


def parse_nested_list(data: Any, key: str) -> list:
    """Extract ``data[key]`` from an RTM dict wrapper, normalizing to list.

    RTM wraps arrays in dicts: ``{"tag": ["a", "b"]}`` or ``{"tag": "single"}``.
    Returns ``[]`` when *data* is not a dict (e.g. an empty list ``[]``).
    """
    if isinstance(data, dict):
        inner = data.get(key, [])
        if isinstance(inner, str):
            return [inner]
        return ensure_list(inner)
    return []


def extract_note_body(note: dict[str, Any]) -> str:
    """Extract note body text from an RTM note dict.

    RTM stores the body in ``$t`` (XML text node) or ``body`` depending
    on the response context.
    """
    return note.get("$t", note.get("body", ""))


# ---------------------------------------------------------------------------
# Date / timezone
# ---------------------------------------------------------------------------


def _convert_rtm_date(due: str, timezone: str | None) -> str:
    """Convert RTM date (UTC) to user's timezone.

    Args:
        due: Date string from RTM (ISO 8601 format, typically with Z suffix)
        timezone: User's IANA timezone (e.g., 'Europe/Warsaw')

    Returns:
        ISO 8601 date string in user's timezone, or original if conversion fails
    """
    if not timezone:
        return due

    try:
        from zoneinfo import ZoneInfo

        due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        user_tz = ZoneInfo(timezone)
        due_local = due_dt.astimezone(user_tz)
        return due_local.isoformat()
    except Exception:
        return due


# ---------------------------------------------------------------------------
# Priority mapping
# ---------------------------------------------------------------------------


def _priority_label(priority: str) -> str:
    """Convert priority code to label."""
    labels = {
        "1": "high",
        "2": "medium",
        "3": "low",
        "N": "none",
    }
    return labels.get(priority, "none")


# The single canonical priority-INPUT vocabulary: the accepted tokens a caller may pass to the
# `priority` param (set_task_priority) mapped to RTM's wire codes ("1"/"2"/"3"/"N"). This is the ONE
# source of truth for that param's advertised `enum` (sorted(PRIORITY_INPUT_CODES)) so the schema can
# never drift from what priority_to_code() actually accepts. (Distinct from the read-side word/code
# maps in canvas_seed/project_plan/project_index, which convert RTM's stored "High"/"Medium"/… forms
# — a different fact, not a copy of this one.)
PRIORITY_INPUT_CODES: dict[str, str] = {
    "high": "1",
    "1": "1",
    "medium": "2",
    "2": "2",
    "low": "3",
    "3": "3",
    "none": "N",
    "0": "N",
    "n": "N",
}


def priority_to_code(priority: str | int | None) -> str:
    """Convert priority label/number to RTM code."""
    if priority is None:
        return "N"

    return PRIORITY_INPUT_CODES.get(str(priority).lower(), "N")


# RTM's `<rrule every="0|1">` attribute IS the recurrence-kind discriminator, and it is the ONLY
# place the fact is available: MilkScript exposes a bare `isRecurring()`, `rtm.Recurrence` is a
# write-only builder with no getter, and the search syntax has `isRepeating:true` but no
# repeat-TYPE operator. Measured live 2026-08-03 (118 repeating series): the attribute arrives
# through this server's JSON conversion as the STRING "1" or "0" on a dict that also carries the
# rule text in "$t" — e.g. {"every": "1", "$t": "FREQ=WEEKLY;INTERVAL=1;WKST=MO"}.
# `True`/`False` are deliberately absent and still covered: bool subclasses int, so `True == 1`
# and `False == 0` — adding them is a literal duplicate (ruff flags it) rather than extra reach.
_EVERY_TRUE: frozenset[object] = frozenset({"1", 1})
_EVERY_FALSE: frozenset[object] = frozenset({"0", 0})


def repeat_kind(rrule: Any) -> str | None:
    """Classify an RTM `rrule` element as an "every" or an "after" recurrence.

    The two kinds behave completely differently and the difference is invisible without this:

    - **every** ("every 2 weeks") — ONE taskseries, MANY tasks; name/tags/notes shared, and
      `taskseries_id` is **stable** across occurrences.
    - **after** ("after 2 weeks") — a NEW taskseries per occurrence, properties copied. **Nothing
      survives**: both `task_id` and `taskseries_id` re-key, so no RTM identifier of any kind
      links one occurrence to the next.

    Three-valued, and the third value is load-bearing:

    - ``"every"`` / ``"after"`` — classified.
    - ``None`` — either NOT repeating (no rule at all), or a rule this function could not
      classify. Those are distinguished by ``is_repeating`` sitting beside it: ``None`` with
      ``is_repeating`` False means "no rule"; ``None`` with ``is_repeating`` True means "a rule
      I could not read". A consumer that must not guess needs both.

    Deliberately NOT defaulted to ``"every"`` on an unreadable rule. A wrong ``"every"`` is
    precisely the silent-wrong-identity failure this exists to prevent — a caller keying durable
    state on `taskseries_id` would key it on an id that re-keys, and nothing would say so.

    A free deductive cross-check, for callers that want one: **a taskseries holding >=2 tasks is
    provably "every"**, since an `after` recurrence cannot produce two tasks in one series. It
    cannot confirm a never-yet-recurred series, which stays unknown. Verified live: of 31 series
    holding >=2 tasks, all 31 carried every="1" and none carried "0".
    """
    if not isinstance(rrule, dict):
        # No rule at all, or a shape this function does not recognise. Either way it cannot be
        # classified; `is_repeating` carries whether a rule was present.
        return None

    every = rrule.get("every")
    if every in _EVERY_TRUE:
        return "every"
    if every in _EVERY_FALSE:
        return "after"
    # A rule with no readable `every` attribute — the fourth case. Unclassified, never guessed.
    return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_task(
    task: dict[str, Any], include_ids: bool = True, timezone: str | None = None
) -> dict[str, Any]:
    """Format a task for response.

    Args:
        task: Raw task data from RTM
        include_ids: Whether to include task IDs
        timezone: User's IANA timezone for date conversion (e.g., 'Europe/Warsaw')

    Returns:
        Formatted task dict
    """
    due_display = None
    due_raw = task.get("due")
    if due_raw:
        due_display = _convert_rtm_date(due_raw, timezone)

    start_display = None
    start_raw = task.get("start")
    if start_raw:
        start_display = _convert_rtm_date(start_raw, timezone)

    formatted = {
        "name": task.get("name", ""),
        "priority": _priority_label(task.get("priority", "N")),
        "due": due_display,
        "start": start_display,
        "completed": task.get("completed") or None,
        "tags": task.get("tags", []),
        "url": task.get("url") or None,
        "notes_count": len(task.get("notes", [])),
        "estimate": task.get("estimate") or None,
        "parent_task_id": task.get("parent_task_id") or None,
        "subtask_count": task.get("subtask_count", 0),
        "modified": task.get("modified") or None,
        # Recurrence, as a PAIR. `repeat_kind` is meaningless alone: its `None` covers both "not
        # repeating" and "repeating, kind unreadable", and only `is_repeating` beside it separates
        # the two. So this formatter — which carried neither before — gains both or neither.
        "is_repeating": bool(task.get("is_repeating")),
        "repeat_kind": task.get("repeat_kind"),
    }

    if include_ids:
        formatted["id"] = task.get("id")
        formatted["taskseries_id"] = task.get("taskseries_id")
        formatted["list_id"] = task.get("list_id")

    return formatted


def _is_true(val: Any) -> bool:
    """Coerce an RTM boolean flag to a Python bool.

    RTM flags reach this code in two shapes: the raw API string (``"1"``/``"0"``)
    on write responses, and an already-parsed bool when the value has passed
    through ``parse_lists_response``. Handle both so ``format_list`` is correct
    regardless of which caller feeds it.
    """
    return val is True or val == "1"


def format_list(lst: dict[str, Any]) -> dict[str, Any]:
    """Format a list for response."""
    return {
        "id": lst.get("id"),
        "name": lst.get("name"),
        "smart": _is_true(lst.get("smart")),
        "archived": _is_true(lst.get("archived")),
        "locked": _is_true(lst.get("locked")),
    }


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_tasks_response(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse RTM tasks response into flat task list.

    RTM returns nested structure for getList:  tasks.list[].taskseries[].task[]
    Write operations (add, complete, etc.) use: list.taskseries[].task[]

    We flatten this to a simple list with all IDs attached.
    """
    tasks = []
    # Handle both response formats: getList wraps under "tasks", write ops use "list" directly
    task_lists = result.get("tasks", {}).get("list", [])
    if not task_lists and "list" in result:
        task_lists = result["list"]

    task_lists = ensure_list(task_lists)

    for tl in task_lists:
        list_id = tl.get("id")
        taskseries_list = ensure_list(tl.get("taskseries", []))

        for ts in taskseries_list:
            task_data = ensure_list(ts.get("task", []))
            tags = parse_nested_list(ts.get("tags", []), "tag")
            notes = parse_nested_list(ts.get("notes", []), "note")
            parent_task_id = ts.get("parent_task_id") or None
            # A recurring taskseries carries an `rrule` element (e.g. FREQ=WEEKLY); a one-off
            # series has none. This is a series-level fact — every open occurrence's task
            # instance inherits it. Surfaced so the GTD side can detect a "repeating templated
            # project" (its parent series recurs) without a second read.
            rrule = ts.get("rrule")
            is_repeating = bool(rrule)
            # ...and WHICH KIND of recurrence, which `is_repeating` alone cannot say. The kind
            # decides whether `taskseries_id` is a durable identity ("every") or re-keys on every
            # occurrence ("after"), so a consumer keying durable state on it must be able to tell.
            # See repeat_kind() for the three-valued contract.
            kind = repeat_kind(rrule)

            for t in task_data:
                tasks.append(
                    {
                        "id": t.get("id"),
                        "taskseries_id": ts.get("id"),
                        "list_id": list_id,
                        "name": ts.get("name"),
                        "due": t.get("due") or None,
                        "has_due_time": t.get("has_due_time") == "1",
                        "start": t.get("start") or None,
                        "has_start_time": t.get("has_start_time") == "1",
                        "completed": t.get("completed") or None,
                        "deleted": t.get("deleted") or None,
                        "priority": t.get("priority", "N"),
                        "postponed": int(t.get("postponed", 0)),
                        "estimate": t.get("estimate") or None,
                        "tags": tags if tags else [],
                        "notes": notes,
                        "url": ts.get("url") or None,
                        "location_id": ts.get("location_id") or None,
                        "parent_task_id": parent_task_id,
                        "is_repeating": is_repeating,
                        "repeat_kind": kind,
                        "created": ts.get("created") or None,
                        "modified": ts.get("modified") or None,
                    }
                )

    return tasks


def parse_lists_response(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse RTM lists response."""
    lists = ensure_list(result.get("lists", {}).get("list", []))

    return [
        {
            "id": lst.get("id"),
            "name": lst.get("name"),
            "deleted": lst.get("deleted") == "1",
            "locked": lst.get("locked") == "1",
            "archived": lst.get("archived") == "1",
            "position": int(lst.get("position", -1)),
            "smart": lst.get("smart") == "1",
            "filter": lst.get("filter"),
            "sort_order": lst.get("sort_order"),
        }
        for lst in lists
    ]


def parse_tags_response(result: dict[str, Any]) -> list[str]:
    """Parse ``rtm.tags.getList`` into a flat list of tag-name strings.

    RTM wraps tags as ``result["tags"]["tag"]`` which may be a single dict, a
    list, or a bare string; each entry may itself be a string or a dict carrying
    ``name`` or the XML text node ``$t``. Names are returned verbatim (no
    normalization) — callers normalize as needed.
    """
    raw = result.get("tags", {})
    if isinstance(raw, dict):
        raw = raw.get("tag", [])
    if isinstance(raw, str):
        raw = [raw] if raw else []

    names: list[str] = []
    for entry in ensure_list(raw):
        if isinstance(entry, str):
            name = entry
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("$t") or ""
        else:
            name = ""
        if name:
            names.append(name)
    return names


# ---------------------------------------------------------------------------
# Task analysis
# ---------------------------------------------------------------------------


def parse_estimate_minutes(estimate: str | None) -> int | None:
    """Parse RTM estimate string to minutes. Returns None if unparseable.

    Handles both ISO 8601 durations (P1D, PT1H30M, P1DT2H) and human-readable
    strings (2 days, 1 hour 30 minutes). Days count as 24 hours.
    """
    if not estimate:
        return None
    import re

    total = 0
    matched = False

    iso = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$", estimate)
    if iso:
        if iso.group(1):
            total += int(iso.group(1)) * 24 * 60
            matched = True
        if iso.group(2):
            total += int(iso.group(2)) * 60
            matched = True
        if iso.group(3):
            total += int(iso.group(3))
            matched = True
        return total if matched else None

    days = re.search(r"(\d+)\s*day", estimate)
    hours = re.search(r"(\d+)\s*hour", estimate)
    minutes = re.search(r"(\d+)\s*min", estimate)
    if days:
        total += int(days.group(1)) * 24 * 60
    if hours:
        total += int(hours.group(1)) * 60
    if minutes:
        total += int(minutes.group(1))
    return total if (days or hours or minutes) else None


def analyze_tasks(tasks: list[dict[str, Any]], timezone: str | None = None) -> dict[str, Any]:
    """Generate analysis insights for a list of parsed tasks.

    Args:
        tasks: List of task dictionaries from parse_tasks_response
        timezone: User's IANA timezone (e.g., 'Europe/Warsaw'). Falls back
                  to UTC if not provided.
    """
    import contextlib

    if not tasks:
        return {}

    priority_counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    overdue_count = 0
    due_today_count = 0
    total_estimate_minutes = 0
    without_estimate = 0
    tags_used: set[str] = set()

    from datetime import UTC
    from zoneinfo import ZoneInfo

    user_tz = None
    if timezone:
        with contextlib.suppress(Exception):
            user_tz = ZoneInfo(timezone)

    now = datetime.now(user_tz) if user_tz else datetime.now(UTC)
    today = now.date()

    for task in tasks:
        priority = task.get("priority", "N")
        if priority == "1":
            priority_counts["high"] += 1
        elif priority == "2":
            priority_counts["medium"] += 1
        elif priority == "3":
            priority_counts["low"] += 1
        else:
            priority_counts["none"] += 1

        due = task.get("due")
        if due:
            try:
                due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                if user_tz:
                    due_dt = due_dt.astimezone(user_tz)
                due_date = due_dt.date()
                if due_date < today:
                    overdue_count += 1
                elif due_date == today:
                    due_today_count += 1
            except ValueError:
                pass

        tags_used.update(task.get("tags", []))

        est = task.get("estimate")
        est_minutes = parse_estimate_minutes(est)
        if est_minutes is not None:
            total_estimate_minutes += est_minutes
        else:
            without_estimate += 1

    insights = []
    if overdue_count:
        insights.append(f"{overdue_count} overdue task(s)")
    if due_today_count:
        insights.append(f"{due_today_count} due today")
    if priority_counts["high"]:
        insights.append(f"{priority_counts['high']} high priority")
    if total_estimate_minutes:
        hours, mins = divmod(total_estimate_minutes, 60)
        if hours and mins:
            insights.append(f"{hours}h {mins}min total estimated")
        elif hours:
            insights.append(f"{hours}h total estimated")
        else:
            insights.append(f"{mins}min total estimated")
    if without_estimate:
        insights.append(f"{without_estimate} task(s) without estimate")

    return {
        "summary": {
            "total": len(tasks),
            "by_priority": priority_counts,
            "overdue": overdue_count,
            "due_today": due_today_count,
            "estimates": {
                "total_minutes": total_estimate_minutes,
                "total_display": f"{total_estimate_minutes // 60}h {total_estimate_minutes % 60}min",
                "without_estimate": without_estimate,
            },
        },
        "insights": insights,
        "tags_used": sorted(tags_used),
    }
