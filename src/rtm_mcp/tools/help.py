"""The tool-affordance help surface — `rtm_tool_help` (tier 2).

One tool, two arities: no argument returns the whole-server purpose index (the cheap "which
tool?" answer), a tool name returns that tool's full contract. Both are projections of the
LIVE advertised schema, built by the pure `tool_help` module — so help cannot drift from what
callers are actually told, and a new tool appears in the index without anyone remembering to
add it.

Offline: introspection only, no RTM API call, no timeline, no clock — the same posture as
`gtd_item_shape`.
"""

from typing import Annotated, Any

from fastmcp import Context

from ..error_codes import ErrorCode
from ..models import TOOL_HELP_OUTPUT
from ..response_builder import READ_ONLY_ANNOTATIONS, build_error, build_response
from ..tool_help import build_contract, build_index
from ..tool_params import optional_string


def register_help_tools(mcp: Any, get_client: Any) -> None:
    """Register the affordance help tool.

    Takes `get_client` for signature symmetry with every other `register_*_tools`, and never
    calls it — this tool reaches RTM not at all.
    """

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=TOOL_HELP_OUTPUT)
    async def rtm_tool_help(
        ctx: Context,
        tool_name: Annotated[
            str | None,
            optional_string(
                "The tool to document, e.g. 'gtd_canvas_commit'. OMIT IT to get the "
                "whole-server index instead — one purpose line per tool. Unqualified names "
                "and the fully-qualified 'mcp__rtm__<tool>' form are both accepted."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """RTM — the server's own manual: what every tool is for, and how to call one correctly.

        Call with NO argument when choosing a tool — returns a one-line purpose for all 100
        tools, split into the two families (generic RTM primitives, GTD domain compositions).
        Call WITH a tool name once chosen, to get the call right first time. Use it instead
        of guessing at parameters, and instead of calling a governed write speculatively to
        see what it rejects.

        Read-only and OFFLINE: introspection only — no RTM call, no timeline, no write. Safe
        to call at any point, including mid-workflow.

        The named form adds only what the description and JSON schema cannot: parameter
        combination rules (this family bans advertised `anyOf`, so unions cannot be expressed
        structurally), worked examples for nested params, every return case in prose, the
        read/write posture and undo path, the typed-error catalogue with recovery, and the
        chain edges. No domain judgement — which GTD workflow a tool serves stays with the
        `gtd` skill, and the contract points there.

        Args:
            tool_name: Omit for the index; pass a name for one tool's full contract.

        Returns (on success, no argument): `{"server", "tool_count", "families": {"rtm":
            {"label", "tools": [{"tool", "purpose", "layer", "consumer", "read_only"}]},
            "gtd": {...}}, "next_step"}`.
        Returns (on success, with a name): `{"tool", "purpose", "taxonomy": {"domain",
            "layer", "consumer"}, "posture": {"read_only", "idempotent", "destructive",
            "summary", "undo"?, "confirmation"?}, "parameters": [{"name", "type",
            "required", "description", "enum"?}], "combination_rules": [...], "examples":
            [...], "returns": "...", "errors": [{"code", "recovery"}], "chain"?:
            {"produced_by", "feeds_into"}, "see_also"?}`.
        Returns (on miss / bad input): `{"error": {"code": "invalid_input", ...}}` when
            `tool_name` names no registered tool — `error.details.candidates` carries the
            nearest names, and calling with no argument lists every one.
        """
        tools = await mcp.list_tools()
        views = []
        for tool in tools:
            advertised = tool.to_mcp_tool() if hasattr(tool, "to_mcp_tool") else tool
            annotations = getattr(advertised, "annotations", None)
            views.append(
                {
                    "name": tool.name,
                    "description": advertised.description or "",
                    "input_schema": advertised.inputSchema or {},
                    "annotations": (
                        annotations.model_dump(mode="json", exclude_none=True)
                        if annotations is not None
                        else {}
                    ),
                }
            )

        if tool_name is None:
            return build_response(data=build_index(views))

        # Accept the qualified form a caller may have copied out of a client's tool listing.
        wanted = tool_name.strip()
        wanted = wanted.removeprefix("mcp__rtm__").removeprefix("rtm__")
        match = next((v for v in views if v["name"] == wanted), None)
        if match is None:
            import difflib

            names = [str(v["name"]) for v in views]
            candidates = difflib.get_close_matches(wanted, names, n=5, cutoff=0.5)
            return build_response(
                data=build_error(
                    ErrorCode.INVALID_INPUT,
                    f"No tool named '{tool_name}'. Call rtm_tool_help() with no argument for "
                    "the full index of every registered tool.",
                    candidates=candidates,
                    tool_name=tool_name,
                )
            )

        return build_response(data=build_contract(match))
