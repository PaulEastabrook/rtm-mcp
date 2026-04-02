"""MCP response envelope builder and transaction recording.

This module handles the generic MCP response structure — the envelope
that wraps all tool responses with metadata, transaction info, and
analysis.  RTM-specific parsing and formatting live in ``parsers.py``.
"""

from datetime import datetime
from typing import Any


def build_response(
    data: dict[str, Any] | list[Any],
    analysis: dict[str, Any] | None = None,
    transaction_id: str | None = None,
    transaction_undoable: bool | None = None,
    timeline_id: str | None = None,
) -> dict[str, Any]:
    """Build a consistent response structure.

    Args:
        data: The main response data
        analysis: Optional analysis/insights
        transaction_id: Optional transaction ID for undo support
        transaction_undoable: Whether the transaction can be undone
        timeline_id: The timeline this transaction belongs to

    Returns:
        Structured response dict
    """
    response = {
        "data": data,
        "metadata": {
            "fetched_at": datetime.now().isoformat(),
        },
    }

    if analysis:
        response["analysis"] = analysis

    if transaction_id:
        response["metadata"]["transaction_id"] = transaction_id
    if transaction_undoable is not None:
        response["metadata"]["transaction_undoable"] = transaction_undoable
    if timeline_id:
        response["metadata"]["timeline_id"] = timeline_id

    return response


def get_transaction_id(result: dict[str, Any]) -> str | None:
    """Extract transaction ID from response for undo support."""
    transaction = result.get("transaction", {})
    return transaction.get("id")


def get_transaction_info(result: dict[str, Any]) -> tuple[str | None, bool]:
    """Extract transaction ID and undoable flag from RTM response.

    Returns:
        (transaction_id, undoable) — undoable is False if no transaction present.
    """
    transaction = result.get("transaction", {})
    tx_id = transaction.get("id")
    undoable = transaction.get("undoable") == "1"
    return tx_id, undoable


def record_and_build_response(
    client: Any,
    result: dict[str, Any],
    data: dict[str, Any],
    tool_name: str,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract transaction info, record to client log, and build response.

    Combines get_transaction_info + client.record_transaction + build_response
    into a single call for write tools.
    """
    tx_id, undoable = get_transaction_info(result)
    summary = data.get("message", tool_name)
    if tx_id:
        client.record_transaction(tx_id, tool_name, undoable, summary)
    return build_response(
        data=data,
        analysis=analysis,
        transaction_id=tx_id,
        transaction_undoable=undoable if tx_id else None,
        timeline_id=client.timeline_id if tx_id else None,
    )
