"""GTD domain-composition tools for RTM MCP.

These tools speak a *consuming domain's* language (GTD) rather than mapping 1:1 to an
RTM API method. By convention they carry a `gtd_` prefix (generic RTM primitives stay
bare verbs like `add_task`/`list_tasks`); the prefix marks a GTD-shaped view over RTM
data and keeps a future lift of all `gtd_*` tools into a separate server a clean,
mechanical move.
"""

from typing import Any

from fastmcp import Context

from ..client import RTMClient
from ..parsers import parse_tasks_response
from ..project_plan import build_envelope, resolve_project
from ..response_builder import build_response


def register_gtd_tools(mcp: Any, get_client: Any) -> None:
    """Register GTD domain-composition tools."""

    @mcp.tool()
    async def gtd_project_plan(
        ctx: Context,
        project_id: str | None = None,
        project_name: str | None = None,
        list_id: str | None = None,
        include_completed: bool = True,
    ) -> dict[str, Any]:
        """GTD — return a whole project plan (the project + all its descendant items + every
        note, with full bodies) as the `project-plan-seed` envelope consumed by the GTD canvas.

        Read-only. Collapses the canvas read path from ~1+N calls to a SINGLE signed
        rtm.tasks.getList: it fetches the tasks once, reconstructs the project→children tree via
        parent_task_id, and emits the comprehensive envelope — the RTM token never leaves the
        server. The tool issues no write and creates no timeline.

        Identify the project by EXACTLY ONE of:
            project_id: the project (parent) task id. Preferred when known.
            project_name: resolved server-side to an incomplete, `project`-tagged, non-`test`
                task. If the name matches more than one, a candidate list is returned (the tool
                does not guess).

        Args:
            list_id: optional — scope the fetch to one list (smaller/faster). When omitted, the
                whole account is read so the project can be found anywhere.
            include_completed: include completed children (default True — the canvas needs the
                history rows). Set False for only-active items.

        Returns (on success): {"header": {...}, "rows": [...]} — the `project-plan-seed/3`
            envelope (project metadata + own notes in the header; one row per descendant with
            priority, dates, tags, permalink, deps, filed-artefact paths, and full note bodies).
        Returns (on ambiguity): {"candidates": [{id, name, list_id}, ...]} — call again with a
            project_id from the list.
        Returns (on miss / bad input): {"error": "..."}.
        """
        client: RTMClient = await get_client()

        if bool(project_id) == bool(project_name):
            return build_response(data={
                "error": "Provide exactly one of project_id or project_name."
            })

        filter_str = (
            "status:incomplete OR status:completed" if include_completed else "status:incomplete"
        )
        params: dict[str, Any] = {"filter": filter_str}
        if list_id:
            params["list_id"] = list_id

        result = await client.call("rtm.tasks.getList", **params)
        parsed = parse_tasks_response(result)

        if project_name:
            resolved = resolve_project(parsed, project_name)
            if "project" not in resolved:
                return build_response(data=resolved)  # error or candidates
            pid = resolved["project"]["id"]
        else:
            pid = str(project_id)
            if pid not in {t["id"] for t in parsed}:
                return build_response(data={
                    "error": f"Project {pid} not found in the fetched tasks. Check the id, or "
                    "pass list_id and/or include_completed=true if it lives in a specific list "
                    "or is completed."
                })

        return build_response(data=build_envelope(parsed, pid))
