"""List management tools for RTM MCP."""

from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from ..client import RTMClient
from ..lookup import resolve_list_id
from ..models import (
    GET_LISTS_OUTPUT,
    LIST_MESSAGE_OUTPUT,
    LIST_WRITE_OUTPUT,
)
from ..parsers import format_list, parse_lists_response
from ..response_builder import (
    ADDITIVE_WRITE_ANNOTATIONS,
    DESTRUCTIVE_WRITE_ANNOTATIONS,
    READ_ONLY_ANNOTATIONS,
    build_response,
    record_and_build_response,
)
from ..tool_params import optional_string


def register_list_tools(mcp: Any, get_client: Any) -> None:
    """Register all list-related tools."""

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=GET_LISTS_OUTPUT)
    async def get_lists(
        ctx: Context,
        include_archived: Annotated[
            bool,
            Field(description="Include archived (hidden) lists in the result."),
        ] = False,
        include_smart: Annotated[
            bool,
            Field(
                description="Include smart lists (saved-search views); set False for only writable lists."
            ),
        ] = True,
    ) -> dict[str, Any]:
        """Retrieve all RTM lists. Returns both regular and smart lists by default,
        sorted by position. Use this to find list names needed by move_task, add_task,
        and other list-based operations. Archived lists are hidden by default.

        Args:
            include_archived: Include archived lists (default: false).
            include_smart: Include smart lists — saved search filters (default: true).

        Returns:
            {"lists": [{id, name, smart, locked, archived}], "count": N}.

            Flag meanings (important for choosing a write target):
            - smart=true  → a smart list (saved-search view). READ-ONLY: cannot
              add_task or move_task into it. Pass include_smart=false to list only
              writable lists.
            - locked=true → a system list (e.g. Inbox, Sent) that cannot be
              renamed or deleted.
            - archived=true → hidden from default views (only shown when
              include_archived=true).
        """
        client: RTMClient = await get_client()

        result = await client.call("rtm.lists.getList")
        lists = parse_lists_response(result)

        # Filter based on preferences
        if not include_archived:
            lists = [lst for lst in lists if not lst["archived"]]
        if not include_smart:
            lists = [lst for lst in lists if not lst["smart"]]

        # Sort by position
        lists.sort(key=lambda x: (x["position"] if x["position"] >= 0 else 9999, x["name"]))

        return build_response(
            data={
                "lists": [format_list(lst) for lst in lists],
                "count": len(lists),
            },
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=LIST_WRITE_OUTPUT)
    async def add_list(
        ctx: Context,
        name: Annotated[str, Field(description="Name for the new list.")],
        filter: Annotated[
            str | None,
            optional_string(
                "Optional RTM filter string; supplying it creates a read-only smart list. Omit for a regular list."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Create a new list. Optionally provide a filter string to create a smart list
        (a saved search). Smart lists are read-only — tasks cannot be added directly.

        Args:
            name: Name for the new list.
            filter: RTM filter string to make this a smart list (e.g., "priority:1 AND
                dueBefore:tomorrow"). Omit for a regular list.

        Returns:
            {"list": {...}, "message": "Created list: ..."} with transaction_id.
        """
        client: RTMClient = await get_client()

        params: dict[str, Any] = {"name": name}
        if filter:
            params["filter"] = filter

        result = await client.call("rtm.lists.add", require_timeline=True, **params)

        # Parse the created list
        lst = result.get("list", {})

        return record_and_build_response(
            client,
            result,
            data={
                "list": format_list(lst),
                "message": f"Created list: {name}",
            },
            tool_name="add_list",
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=LIST_WRITE_OUTPUT)
    async def rename_list(
        ctx: Context,
        list_name: Annotated[
            str,
            Field(
                description="Current name of the list to rename (resolved to its id via get_lists)."
            ),
        ],
        new_name: Annotated[str, Field(description="New name for the list.")],
    ) -> dict[str, Any]:
        """Rename a list. Locked system lists (e.g., Inbox, Sent) cannot be renamed.
        Use get_lists to see available list names.

        Returns:
            {"list": {...}, "message": "Renamed '...' to '...'"} with transaction_id.
        """
        client: RTMClient = await get_client()

        resolved = await resolve_list_id(client, list_name)
        if "error" in resolved:
            return build_response(data=resolved)

        result = await client.call(
            "rtm.lists.setName",
            require_timeline=True,
            list_id=resolved["list_id"],
            name=new_name,
        )

        lst = result.get("list", {})

        return record_and_build_response(
            client,
            result,
            data={
                "list": format_list(lst),
                "message": f"Renamed '{list_name}' to '{new_name}'",
            },
            tool_name="rename_list",
        )

    @mcp.tool(annotations=DESTRUCTIVE_WRITE_ANNOTATIONS, output_schema=LIST_MESSAGE_OUTPUT)
    async def delete_list(
        ctx: Context,
        list_name: Annotated[
            str,
            Field(
                description="Name of the list to delete (locked system lists like Inbox/Sent are rejected)."
            ),
        ],
    ) -> dict[str, Any]:
        """Delete a list. Locked system lists (e.g., Inbox, Sent) cannot be deleted.
        Tasks in the list should be moved or deleted first. Use get_lists to see
        available list names.

        Returns:
            {"message": "Deleted list: ..."} with transaction_id for undo.
        """
        client: RTMClient = await get_client()

        resolved = await resolve_list_id(client, list_name)
        if "error" in resolved:
            return build_response(data=resolved)

        if resolved["list"]["locked"]:
            return build_response(
                data={
                    "error": f"Cannot delete '{list_name}' — it is a locked system list (e.g. Inbox, Sent)."
                },
            )

        result = await client.call(
            "rtm.lists.delete",
            require_timeline=True,
            list_id=resolved["list_id"],
        )

        return record_and_build_response(
            client,
            result,
            data={"message": f"Deleted list: {list_name}"},
            tool_name="delete_list",
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=LIST_WRITE_OUTPUT)
    async def archive_list(
        ctx: Context,
        list_name: Annotated[
            str,
            Field(
                description="Name of the list to archive (hides it from default views; tasks remain filterable)."
            ),
        ],
    ) -> dict[str, Any]:
        """Archive a list. Archived lists are hidden from default views but their
        tasks remain accessible via filters. Use unarchive_list to restore.

        Returns:
            {"list": {...}, "message": "Archived list: ..."} with transaction_id.
        """
        client: RTMClient = await get_client()

        resolved = await resolve_list_id(client, list_name)
        if "error" in resolved:
            return build_response(data=resolved)

        result = await client.call(
            "rtm.lists.archive",
            require_timeline=True,
            list_id=resolved["list_id"],
        )

        lst = result.get("list", {})

        return record_and_build_response(
            client,
            result,
            data={
                "list": format_list(lst),
                "message": f"Archived list: {list_name}",
            },
            tool_name="archive_list",
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=LIST_WRITE_OUTPUT)
    async def unarchive_list(
        ctx: Context,
        list_name: Annotated[
            str,
            Field(
                description="Name of the archived list to restore (find it via get_lists(include_archived=True))."
            ),
        ],
    ) -> dict[str, Any]:
        """Restore an archived list back to active. Use get_lists(include_archived=True)
        to find archived list names.

        Returns:
            {"list": {...}, "message": "Unarchived list: ..."} with transaction_id.
        """
        client: RTMClient = await get_client()

        resolved = await resolve_list_id(client, list_name)
        if "error" in resolved:
            return build_response(data=resolved)

        result = await client.call(
            "rtm.lists.unarchive",
            require_timeline=True,
            list_id=resolved["list_id"],
        )

        lst = result.get("list", {})

        return record_and_build_response(
            client,
            result,
            data={
                "list": format_list(lst),
                "message": f"Unarchived list: {list_name}",
            },
            tool_name="unarchive_list",
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=LIST_MESSAGE_OUTPUT)
    async def set_default_list(
        ctx: Context,
        list_name: Annotated[
            str,
            Field(
                description="Name of the list to make the default target for add_task calls that omit a list."
            ),
        ],
    ) -> dict[str, Any]:
        """Set the default list for new tasks. When add_task is called without a
        list_name, tasks go to this list. Use get_lists to find available list names.

        Returns:
            {"message": "Default list set to: ..."} with transaction_id for undo
            when RTM reports one.
        """
        client: RTMClient = await get_client()

        resolved = await resolve_list_id(client, list_name)
        if "error" in resolved:
            return build_response(data=resolved)

        result = await client.call(
            "rtm.lists.setDefaultList",
            require_timeline=True,
            list_id=resolved["list_id"],
        )

        return record_and_build_response(
            client,
            result,
            data={"message": f"Default list set to: {list_name}"},
            tool_name="set_default_list",
        )
