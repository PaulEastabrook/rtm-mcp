"""Utility tools for RTM MCP."""

from typing import Any

from fastmcp import Context

from ..lookup import resolve_list_id, resolve_task_ids
from ..parsers import ensure_list
from ..response_builder import build_response
from ..urls import build_list_url, resolve_task_url


def register_utility_tools(mcp: Any, get_client: Any) -> None:
    """Register utility and diagnostic tools."""

    @mcp.tool()
    async def test_connection(ctx: Context) -> dict[str, Any]:
        """Test connectivity to the RTM API. Use this to diagnose connection issues
        before attempting other operations. Returns response time in milliseconds.

        Returns:
            {"status": "connected", "response_time_ms": N} on success, or
            {"status": "error", "error": "..."} on failure.
        """
        import time

        from ..client import RTMClient

        client: RTMClient = await get_client()

        start = time.monotonic()
        try:
            result = await client.test_echo()
            elapsed = time.monotonic() - start

            return build_response(
                data={
                    "status": "connected",
                    "response_time_ms": round(elapsed * 1000, 2),
                    "api_response": result,
                },
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            return build_response(
                data={
                    "status": "error",
                    "error": str(e),
                    "response_time_ms": round(elapsed * 1000, 2),
                },
            )

    @mcp.tool()
    async def check_auth(ctx: Context) -> dict[str, Any]:
        """Verify that the stored auth token is valid and check permission level.
        Use this to confirm authentication before performing write operations.

        Returns:
            {"status": "authenticated", "user": {id, username, fullname},
            "permissions": "delete"} on success, or {"status": "not_authenticated"}.
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        try:
            result = await client.check_token()
            auth = result.get("auth", {})
            user = auth.get("user", {})

            return build_response(
                data={
                    "status": "authenticated",
                    "user": {
                        "id": user.get("id"),
                        "username": user.get("username"),
                        "fullname": user.get("fullname"),
                    },
                    "permissions": auth.get("perms"),
                },
            )
        except Exception as e:
            return build_response(
                data={
                    "status": "not_authenticated",
                    "error": str(e),
                },
            )

    @mcp.tool()
    async def get_tags(ctx: Context) -> dict[str, Any]:
        """Retrieve all tags used across your tasks, sorted alphabetically. Use this to
        discover existing tags before adding them to tasks, or to check tag names for
        use in list_tasks filters (e.g., filter="tag:work").

        Returns:
            {"tags": [{name}], "count": N}.
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        result = await client.call("rtm.tags.getList")

        tags_data = result.get("tags", {}).get("tag", [])
        if isinstance(tags_data, dict):
            tags_data = [tags_data]
        if isinstance(tags_data, str):
            tags_data = [{"name": tags_data}]

        tags = []
        for tag in tags_data:
            if isinstance(tag, str):
                tags.append({"name": tag})
            else:
                tags.append({
                    "name": tag.get("name", tag.get("$t", "")),
                })

        return build_response(
            data={
                "tags": sorted(tags, key=lambda x: x["name"]),
                "count": len(tags),
            },
        )

    @mcp.tool()
    async def get_locations(ctx: Context) -> dict[str, Any]:
        """Retrieve all saved locations. Locations can be assigned to tasks using
        the @location syntax in add_task, or filtered with list_tasks(filter="location:name").

        Returns:
            {"locations": [{id, name, latitude, longitude, zoom, address}], "count": N}.
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        result = await client.call("rtm.locations.getList")

        locations_data = ensure_list(result.get("locations", {}).get("location", []))

        locations = []
        for loc in locations_data:
            locations.append({
                "id": loc.get("id"),
                "name": loc.get("name"),
                "latitude": float(loc.get("latitude", 0)),
                "longitude": float(loc.get("longitude", 0)),
                "zoom": int(loc.get("zoom", 0)) if loc.get("zoom") else None,
                "address": loc.get("address"),
            })

        return build_response(
            data={
                "locations": locations,
                "count": len(locations),
            },
        )

    @mcp.tool()
    async def get_settings(ctx: Context) -> dict[str, Any]:
        """Retrieve user account settings including timezone, date/time format
        preferences, default list, and language. Useful for understanding how dates
        and times will be interpreted.

        Returns:
            {"timezone": "...", "date_format": "European/American", "time_format":
            "12-hour/24-hour", "default_list_id": "...", "language": "..."}.
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        result = await client.call("rtm.settings.getList")

        settings = result.get("settings", {})

        # Format settings nicely
        date_format = "European (DD/MM/YY)" if settings.get("dateformat") == "0" else "American (MM/DD/YY)"
        time_format = "12-hour" if settings.get("timeformat") == "0" else "24-hour"

        return build_response(
            data={
                "timezone": settings.get("timezone"),
                "date_format": date_format,
                "time_format": time_format,
                "default_list_id": settings.get("defaultlist"),
                "language": settings.get("language"),
                "raw": settings,
            },
        )

    @mcp.tool()
    async def parse_time(
        ctx: Context,
        text: str,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        """Parse a natural language time/date string into an ISO 8601 timestamp using
        RTM's parser. Useful for previewing how RTM will interpret date expressions
        before using them in set_task_due_date or set_task_start_date.

        Args:
            text: Time expression to parse (e.g., "tomorrow", "next friday", "in 2 hours",
                "dec 25", "3pm").
            timezone: IANA timezone (e.g., "America/New_York"). Defaults to UTC.

        Returns:
            {"input": "...", "parsed": "2026-04-02T00:00:00Z", "precision": "date"|"time"}.
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        params: dict[str, Any] = {"text": text}
        if timezone:
            params["timezone"] = timezone

        result = await client.call("rtm.time.parse", **params)

        time_data = result.get("time", {})

        return build_response(
            data={
                "input": text,
                "parsed": time_data.get("$t"),
                "precision": time_data.get("precision"),
            },
        )

    @mcp.tool()
    async def undo(
        ctx: Context,
        transaction_id: str,
    ) -> dict[str, Any]:
        """Undo a previous write operation using its transaction_id. Most write tools
        return a transaction_id in their metadata. Not all operations are undoable —
        check the "transaction_undoable" field in the original response. Must be called
        within the same session (timelines expire).

        Use get_timeline_info to see all transactions and their undo status. For
        undoing multiple operations at once, use batch_undo instead.

        Args:
            transaction_id: The transaction_id from the operation's response metadata
                or from get_timeline_info output.

        Returns:
            {"status": "success", "message": "Operation undone", "transaction_id": "..."}
            or {"status": "error", "error": "...", "transaction_id": "..."}.

        Examples:
            - undo(transaction_id="12345") → reverses that operation
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        try:
            await client.call(
                "rtm.transactions.undo",
                require_timeline=True,
                transaction_id=transaction_id,
            )

            client.mark_undone(transaction_id)

            return build_response(
                data={
                    "status": "success",
                    "message": "Operation undone",
                    "transaction_id": transaction_id,
                },
            )
        except Exception as e:
            return build_response(
                data={
                    "status": "error",
                    "error": str(e),
                    "transaction_id": transaction_id,
                },
            )

    @mcp.tool()
    async def batch_undo(
        ctx: Context,
        transaction_ids: list[str],
    ) -> dict[str, Any]:
        """Undo multiple write operations in one call. Operations are undone in
        reverse chronological order (most recent first) to maintain data consistency.
        All transaction_ids must belong to the current session's timeline.

        Processing stops on the first failure. Transactions already undone (via undo
        or a previous batch_undo) are skipped silently. Use get_timeline_info to see
        which transactions are available and their current undo status.

        Args:
            transaction_ids: List of transaction_ids to undo. Order does not matter —
                they are automatically sorted most-recent-first. Get IDs from write
                tool response metadata or from get_timeline_info output.

        Returns:
            {"undone": ["tx3", "tx2"], "skipped": ["tx1"], "failed": null |
            {"transaction_id": "...", "error": "..."}, "timeline_id": "..."}.

        Examples:
            - batch_undo(transaction_ids=["tx1", "tx2", "tx3"]) → undoes tx3, tx2,
              tx1 in that order
            - If tx2 fails: returns undone=["tx3"], failed={tx2 info}, tx1 not attempted
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        # Validate all IDs exist in the transaction log
        unknown = [tid for tid in transaction_ids if client.get_transaction(tid) is None]
        if unknown:
            return build_response(
                data={
                    "error": f"Unknown transaction IDs (not in current session): {unknown}. Use get_timeline_info to see valid transaction IDs.",
                },
            )

        # Sort by log order descending (most recent first)
        all_transactions = client.get_all_transactions()
        log_order = {entry.transaction_id: i for i, entry in enumerate(all_transactions)}
        sorted_ids = sorted(transaction_ids, key=lambda tid: log_order[tid], reverse=True)

        undone: list[str] = []
        skipped: list[str] = []
        failed: dict[str, str] | None = None

        for tid in sorted_ids:
            entry = client.get_transaction(tid)
            if entry and entry.undone:
                skipped.append(tid)
                continue

            try:
                await client.call(
                    "rtm.transactions.undo",
                    require_timeline=True,
                    transaction_id=tid,
                )
                client.mark_undone(tid)
                undone.append(tid)
            except Exception as e:
                failed = {"transaction_id": tid, "error": str(e)}
                break

        return build_response(
            data={
                "undone": undone,
                "skipped": skipped,
                "failed": failed,
                "timeline_id": client.timeline_id,
            },
        )

    @mcp.tool()
    async def get_timeline_info(ctx: Context) -> dict[str, Any]:
        """View the current session's timeline and full transaction history. Use this
        to review what write operations have been performed, which can be undone, and
        to get transaction_ids for undo or batch_undo.

        If no write operations have been performed yet, timeline_id and created_at
        will be null. Transactions are listed in chronological order (oldest first).

        Returns:
            {"timeline_id": "..." | null, "created_at": "ISO timestamp" | null,
            "transaction_count": N, "transactions": [{transaction_id, method,
            undoable, undone, summary}]}.

            Each transaction entry includes:
            - transaction_id: ID for use with undo or batch_undo
            - method: the tool that created it (e.g., "add_task")
            - undoable: whether RTM supports undoing this operation
            - undone: whether this transaction has already been undone
            - summary: human-readable description of what was done
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        transactions = client.get_all_transactions()

        return build_response(
            data={
                "timeline_id": client.timeline_id,
                "created_at": client.timeline_created_at,
                "transaction_count": len(transactions),
                "transactions": [
                    {
                        "transaction_id": entry.transaction_id,
                        "method": entry.method,
                        "undoable": entry.undoable,
                        "undone": entry.undone,
                        "summary": entry.summary,
                    }
                    for entry in transactions
                ],
            },
        )

    @mcp.tool()
    async def get_contacts(ctx: Context) -> dict[str, Any]:
        """Retrieve RTM contacts for task sharing. Contacts are users you can share
        tasks with via the RTM sharing feature. Use list_tasks with filter
        "isShared:true" to find shared tasks.

        Returns:
            {"contacts": [{id, fullname, username}], "count": N}.
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        result = await client.call("rtm.contacts.getList")

        contacts_data = ensure_list(result.get("contacts", {}).get("contact", []))

        contacts = []
        for contact in contacts_data:
            contacts.append({
                "id": contact.get("id"),
                "fullname": contact.get("fullname"),
                "username": contact.get("username"),
            })

        return build_response(
            data={
                "contacts": contacts,
                "count": len(contacts),
            },
        )

    @mcp.tool()
    async def get_groups(ctx: Context) -> dict[str, Any]:
        """Retrieve contact groups with member counts. Groups organize contacts for
        batch task sharing.

        Returns:
            {"groups": [{id, name, member_count}], "count": N}.
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        result = await client.call("rtm.groups.getList")

        groups_data = ensure_list(result.get("groups", {}).get("group", []))

        groups = []
        for group in groups_data:
            contacts = ensure_list(group.get("contacts", {}).get("contact", []))

            groups.append({
                "id": group.get("id"),
                "name": group.get("name"),
                "member_count": len(contacts),
            })

        return build_response(
            data={
                "groups": groups,
                "count": len(groups),
            },
        )

    @mcp.tool()
    async def get_rate_limit_status(ctx: Context) -> dict[str, Any]:
        """View current rate limiter state and request statistics. No API call
        is made — reads in-memory state only. Use this to diagnose unexpected
        slowness, check remaining burst capacity before a batch operation, or
        detect whether HTTP 503 errors are occurring (suggesting the safety
        margin needs increasing).

        Returns:
            {"tokens_available": 2.3, "bucket_capacity": 3, "refill_rate": 0.9,
            "safety_margin": 0.1, "requests_last_60s": 14, "retries_last_60s": 0,
            "http_503_count_session": 0, "connection_retries_last_60s": 0}.

            Key fields:
            - tokens_available: approximate burst capacity remaining right now
            - refill_rate: effective tokens/sec (1.0 minus safety_margin)
            - requests_last_60s: rolling window of all API requests
            - http_503_count_session: total 503s this session (increase safety_margin
              if non-zero)
            - connection_retries_last_60s: connection-level retries (timeout, DNS,
              TCP reset) in the last 60 seconds
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        bucket = client.bucket
        stats = client.rate_limit_stats
        config = client.config

        return build_response(
            data={
                "tokens_available": round(bucket.tokens_available, 2),
                "bucket_capacity": config.bucket_capacity,
                "refill_rate": round(1.0 * (1.0 - config.safety_margin), 2),
                "safety_margin": config.safety_margin,
                "requests_last_60s": stats.requests_last_60s(),
                "retries_last_60s": stats.retries_last_60s(),
                "http_503_count_session": stats.http_503_count_session,
                "connection_retries_last_60s": stats.conn_retries_last_60s(),
            },
        )

    @mcp.tool()
    async def get_task_url(
        ctx: Context,
        task_name: str | None = None,
        task_id: str | None = None,
        taskseries_id: str | None = None,
        list_id: str | None = None,
    ) -> dict[str, Any]:
        """Get the Remember The Milk web UI URL for a task, including its full
        hierarchy path. Use this to give the user a clickable link that opens
        the task directly in the RTM web app.

        The URL encodes the task's ancestor chain (e.g. focus area → project →
        action), so clicking it navigates straight to the task in context.

        Identify the task by either task_name or all three IDs.

        Caution: task_name uses fuzzy matching across incomplete tasks. For
        common names, prefer passing task_id + taskseries_id + list_id to
        avoid matching an unintended task.

        Args:
            task_name: Task name to search for (case-insensitive fuzzy match).
            task_id: The task's ID (from list_tasks output).
            taskseries_id: The task series ID (from list_tasks output).
            list_id: The list ID containing the task (from list_tasks output).

        Returns:
            {"url": "https://...", "task_name": "...", "list_name": "...",
            "list_id": "...", "hierarchy": [{name, level}]}.
            Optionally includes "warning" if a parent task could not be found.

        Examples:
            - get_task_url(task_name="Buy groceries") → URL with hierarchy
            - get_task_url(task_id="123", taskseries_id="456", list_id="789")
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()
        ids = await resolve_task_ids(
            client, task_name, task_id, taskseries_id, list_id,
            include_completed=True,
        )
        if "error" in ids:
            return build_response(data=ids)

        result = await resolve_task_url(
            client, ids["task_id"], ids["taskseries_id"], ids["list_id"],
        )
        return build_response(data=result)

    @mcp.tool()
    async def get_list_url(
        ctx: Context,
        list_name: str | None = None,
        list_id: str | None = None,
    ) -> dict[str, Any]:
        """Get the Remember The Milk web UI URL for a list. Use this to give
        the user a clickable link that opens the list in the RTM web app.

        Provide either list_name or list_id. Use get_lists to see available
        list names and IDs.

        Args:
            list_name: List name to look up (case-insensitive exact match).
            list_id: The list's ID (from get_lists output).

        Returns:
            {"url": "https://...", "list_name": "...", "list_id": "..."}.

        Examples:
            - get_list_url(list_name="Inbox") → URL for Inbox list
            - get_list_url(list_id="49657585") → URL for that list
        """
        from ..client import RTMClient

        client: RTMClient = await get_client()

        resolved_name: str | None = list_name
        resolved_id: str | None = list_id

        if list_name and not list_id:
            result = await resolve_list_id(client, list_name)
            if "error" in result:
                return build_response(data=result)
            resolved_id = result["list_id"]
            resolved_name = result["list"]["name"]
        elif list_id and not list_name:
            # Fetch list name for the response
            from ..parsers import parse_lists_response

            lists_result = await client.call("rtm.lists.getList")
            lists = parse_lists_response(lists_result)
            for lst in lists:
                if lst["id"] == list_id:
                    resolved_name = lst["name"]
                    break

        if not resolved_id:
            return build_response(data={
                "error": "Provide either list_name or list_id. "
                "Use get_lists to see available list names."
            })

        url = build_list_url(resolved_id)
        return build_response(data={
            "url": url,
            "list_name": resolved_name,
            "list_id": resolved_id,
        })
