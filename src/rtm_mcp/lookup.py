"""Shared lookup helpers for RTM MCP tools (tasks and lists)."""

from typing import Any


async def find_task(
    client: Any,
    name: str,
    include_completed: bool = False,
) -> dict[str, Any] | None:
    """Find a task by name with disambiguation.

    Searches for tasks matching *name* (exact match first, then substring).
    When multiple tasks match at the same tier, returns the most recently
    modified one — unless two or more candidates share the same modified
    timestamp, in which case an ``AmbiguousMatchError`` dict is returned
    via :func:`resolve_task_ids`.

    Args:
        client: An RTMClient instance.
        name: Task name to search for (case-insensitive).
        include_completed: If True, search all tasks; otherwise only incomplete.

    Returns:
        A single task dict on unambiguous match, or None if no match found.

    Raises:
        Nothing — ambiguity is handled by :func:`resolve_task_ids` which
        inspects the return value.
    """
    from .parsers import parse_tasks_response

    filter_str = None if include_completed else "status:incomplete"

    if filter_str:
        result = await client.call("rtm.tasks.getList", filter=filter_str)
    else:
        result = await client.call("rtm.tasks.getList")
    tasks = parse_tasks_response(result)

    name_lower = name.lower()

    # --- Exact match pass ---
    exact = [t for t in tasks if t["name"].lower() == name_lower]
    winner = _pick_winner(exact)
    if winner is not None:
        return winner

    # --- Substring match pass ---
    partial = [t for t in tasks if name_lower in t["name"].lower()]
    winner = _pick_winner(partial)
    if winner is not None:
        return winner

    return None


def _pick_winner(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the single best match from *candidates*, or None.

    Returns None when there are no candidates.  When there is exactly one
    candidate, returns it.  When there are multiple, sorts by ``modified``
    descending and returns the most recent.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Sort by modified descending — most recently touched first
    candidates.sort(key=lambda t: t.get("modified") or "", reverse=True)
    return candidates[0]


def _format_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format candidate tasks for an ambiguous-match error message."""
    formatted = []
    for t in candidates:
        formatted.append({
            "task_id": t.get("id"),
            "taskseries_id": t.get("taskseries_id"),
            "list_id": t.get("list_id"),
            "name": t.get("name"),
            "tags": t.get("tags", []),
            "due": t.get("due"),
            "modified": t.get("modified"),
            "completed": t.get("completed"),
        })
    return formatted


async def resolve_task_ids(
    client: Any,
    task_name: str | None,
    task_id: str | None,
    taskseries_id: str | None,
    list_id: str | None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Resolve task identifiers, searching by name if needed.

    Returns a dict with ``task_id``, ``taskseries_id``, ``list_id`` on
    success, or a dict with ``error`` (and optionally ``candidates``) on
    failure.
    """
    if task_name and not task_id:
        task = await find_task(client, task_name, include_completed=include_completed)
        if not task:
            return {
                "error": f"Task not found: '{task_name}'. "
                "Use list_tasks to search by filter or check spelling."
            }
        return {
            "task_id": task["id"],
            "taskseries_id": task["taskseries_id"],
            "list_id": task["list_id"],
        }

    if not all([task_id, taskseries_id, list_id]):
        return {
            "error": "Provide either task_name (for search) or all three: "
            "task_id, taskseries_id, and list_id. Get these from list_tasks."
        }

    return {
        "task_id": task_id,
        "taskseries_id": taskseries_id,
        "list_id": list_id,
    }


async def resolve_list_id(
    client: Any,
    list_name: str,
) -> dict[str, Any]:
    """Resolve a list name to its ID.

    Fetches all lists and does a case-insensitive name match.

    Returns:
        ``{"list_id": "...", "list": {...}}`` on success (``list`` is the
        full parsed list dict for callers that need to inspect e.g. ``locked``).
        ``{"error": "..."}`` if the list is not found.
    """
    from .parsers import parse_lists_response

    lists_result = await client.call("rtm.lists.getList")
    lists = parse_lists_response(lists_result)

    name_lower = list_name.lower()
    for lst in lists:
        if lst["name"].lower() == name_lower:
            return {"list_id": lst["id"], "list": lst}

    return {
        "error": f"List '{list_name}' not found. "
        "Use get_lists to see available list names."
    }
