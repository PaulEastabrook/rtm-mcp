"""MCP response envelope builder and transaction recording.

This module handles the generic MCP response structure — the envelope
that wraps all tool responses with metadata, transaction info, and
analysis.  RTM-specific parsing and formatting live in ``parsers.py``.
"""

from datetime import datetime
from typing import Any

from mcp.types import ToolAnnotations

# --------------------------------------------------------------------------- #
# Tool behaviour annotations — the MCP-standard hints a client/agent uses to
# reason about a tool BEFORE calling it (safe to call speculatively? does it
# mutate? is it reversible? is it idempotent?). Three constants span this
# server's postures (see CONTRIBUTING § 3). `openWorldHint=True` everywhere:
# every tool ultimately reaches the Remember The Milk SaaS API (an open,
# non-deterministic world), unlike a local-only backend.
#
# `idempotentHint` is set conservatively (False) on both write constants — the
# safe/pessimistic default (a retry is NOT assumed replay-safe). Where a specific
# write IS naturally idempotent (e.g. set_task_name), that nuance is documented
# in the tool's docstring, not the annotation. Hints are UX + speculative-call
# signals, NOT enforcement: the deterministic gates (confirm_destructive, the
# strict-tag existence gate, actionable typed errors) remain the sole safety
# authority.
# --------------------------------------------------------------------------- #

READ_ONLY_ANNOTATIONS = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
# Creates, additive field/tag updates, and the undo recovery path: mutate state
# but never delete or blindly overwrite; reversible via undo/batch_undo.
ADDITIVE_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)
# Deletes and irreversible removals (delete_task/list/note; canvas/engage commit
# completes+removes). `destructiveHint=True` even though undo can often reverse
# them — classify honestly; the undo path lives in the docstring.
DESTRUCTIVE_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
)


# Request-parameter names that carry credentials/signatures. RTM's
# ``rtm.test.echo`` reflects EVERY request parameter back verbatim, so an
# unredacted echo places these into the calling model's conversation context
# (and any transcript derived from it). Matched case-insensitively.
SECRET_KEYS = frozenset(
    {"api_key", "auth_token", "api_sig", "shared_secret", "secret", "token", "frob"}
)
_REDACTED = "***redacted***"


def redact_secrets(value: Any) -> Any:
    """Return a copy of ``value`` with any secret-bearing keys masked.

    Recurses through nested dicts/lists so a reflected API payload can never
    surface an ``api_key`` / ``auth_token`` / ``api_sig`` (or similar) in a
    tool response. Non-container values are returned unchanged; the input is
    not mutated.
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if isinstance(k, str) and k.lower() in SECRET_KEYS else redact_secrets(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


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
