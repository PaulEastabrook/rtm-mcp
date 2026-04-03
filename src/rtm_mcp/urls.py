"""RTM web UI URL construction and task hierarchy walking.

Builds deep-link URLs to the RTM web app for lists and tasks.
The web UI uses hash-based routing::

    https://www.rememberthemilk.com/app/#list/{list_id}[/{id1}/{id2}/{id3}]

where the segments after ``list_id`` represent the task hierarchy
(e.g. focus area → project → action in a GTD setup).
"""

from typing import Any

from .config import RTM_WEB_BASE_URL

# Which parsed-task field to use for URL path segments.
# RTM's parent_task_id stores a task_id ("id"), so the hierarchy chain
# naturally resolves via task_id.  Change to "taskseries_id" if
# verification shows the web UI uses taskseries IDs instead.
URL_SEGMENT_ID_FIELD: str = "id"


# ---------------------------------------------------------------------------
# Pure URL builders
# ---------------------------------------------------------------------------

def build_list_url(list_id: str) -> str:
    """Build a web UI URL for a list."""
    return f"{RTM_WEB_BASE_URL}#list/{list_id}"


def build_task_url(list_id: str, segment_ids: list[str]) -> str:
    """Build a web UI URL for a task given its ancestor chain.

    Args:
        list_id: The list containing the task hierarchy.
        segment_ids: Ordered root-first list of IDs for each hierarchy
            level (e.g. ``[focus_id, project_id, action_id]``).
    """
    segments = "/".join(segment_ids)
    return f"{RTM_WEB_BASE_URL}#list/{list_id}/{segments}"


# ---------------------------------------------------------------------------
# Parent chain walking
# ---------------------------------------------------------------------------

_MAX_DEPTH = 10  # RTM allows max 3 levels; guard against corruption


def walk_parent_chain(
    target_task: dict[str, Any],
    all_tasks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Walk ``parent_task_id`` pointers from *target_task* up to the root.

    Args:
        target_task: The task whose ancestry we're resolving.
        all_tasks: Every task in the same list (including completed).

    Returns:
        A tuple of ``(chain, warning)``.

        *chain* is ordered root-first and ends with *target_task*.
        *warning* is ``None`` on success, or a message if a parent
        could not be found (the chain will be partial in that case).
    """
    # Build lookup: task_id → task dict
    by_task_id: dict[str, dict[str, Any]] = {t["id"]: t for t in all_tasks}

    chain: list[dict[str, Any]] = [target_task]
    seen: set[str] = {target_task["id"]}
    warning: str | None = None

    current = target_task
    for _ in range(_MAX_DEPTH):
        parent_id = current.get("parent_task_id")
        if not parent_id:
            break  # reached root

        if parent_id in seen:
            warning = f"Cycle detected at task_id {parent_id}; chain may be incomplete."
            break

        parent = by_task_id.get(parent_id)
        if parent is None:
            warning = (
                f"Parent task_id {parent_id} not found in list. "
                "It may have been deleted. Chain is partial."
            )
            break

        seen.add(parent_id)
        chain.append(parent)
        current = parent

    chain.reverse()  # root-first order
    return chain, warning


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def resolve_task_url(
    client: Any,
    task_id: str,
    taskseries_id: str,
    list_id: str,
) -> dict[str, Any]:
    """Fetch the task hierarchy and build a full web UI URL.

    Makes one API call to fetch all tasks in the list (without status
    filter so completed parents are included), then walks the parent
    chain and constructs the URL.

    Returns a dict with ``url``, ``task_name``, ``list_name``,
    ``list_id``, ``hierarchy``, and optionally ``warning``.
    """
    from .parsers import parse_lists_response, parse_tasks_response

    # Fetch all tasks in this specific list (no status filter → includes completed)
    result = await client.call("rtm.tasks.getList", list_id=list_id)
    all_tasks = parse_tasks_response(result)

    # Find the target task
    target = None
    for t in all_tasks:
        if t["id"] == task_id and t["taskseries_id"] == taskseries_id:
            target = t
            break

    if target is None:
        return {"error": f"Task {task_id} not found in list {list_id}."}

    # Walk parent chain
    chain, warning = walk_parent_chain(target, all_tasks)

    # Build URL segments
    segment_ids = [t[URL_SEGMENT_ID_FIELD] for t in chain]
    url = build_task_url(list_id, segment_ids)

    # Build hierarchy info
    hierarchy = [
        {"name": t.get("name", ""), "level": i + 1}
        for i, t in enumerate(chain)
    ]

    # Resolve list name
    lists_result = await client.call("rtm.lists.getList")
    lists = parse_lists_response(lists_result)
    list_name = list_id
    for lst in lists:
        if lst["id"] == list_id:
            list_name = lst["name"]
            break

    response: dict[str, Any] = {
        "url": url,
        "task_name": target.get("name", ""),
        "list_name": list_name,
        "list_id": list_id,
        "hierarchy": hierarchy,
    }
    if warning:
        response["warning"] = warning

    return response
