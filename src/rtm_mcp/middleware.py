"""Call-boundary middleware — reject unknown tool parameters.

The defect this closes (raised 2026-07-25). A tool call carrying a parameter the tool
does not define was accepted silently, with a success response: the extra argument was
discarded and nothing said so. Required parameters were already validated strictly —
omitting `text` returns a `missing_argument` validation error naming `text` (measured on
this stack; the raising layer is FastMCP's signature binding) — so the strictness existed,
it just did not run in this direction.

The cost is not a corrupted write; it is a **confident success a caller reasons from**.
A `gtd_inbox_capture(text=…, type_tags=[…])` call returned an `applied[]` entry reading
`capture:tags` — the server correctly applying its own `#ai_conversation` pipeline tag —
which was misread as the (non-existent) tag write having landed, and a false defect
report followed. The dangerous case is worse and quieter: a misspelt *optional* on a
write tool (`gtd_item_create`, `gtd_item_set_properties`) writes the item without that
property and reports success, with nothing in `applied[]` or `errors[]` marking the
discarded intent.

**REJECT, do not warn.** A warning in a response body is exactly the class of signal
that gets ignored — and this defect exists precisely because a silent success let a
wrong conclusion stand; a `warnings[]` entry would have been read as carelessly as the
`applied[]` one was. The accepted cost is version coupling: a caller written against a
newer server passing a parameter an older one lacks now hard-fails rather than degrading.
That is tolerable here because both sides are the same author's and move together, and
because the failure announces itself loudly and immediately rather than silently.

**One middleware, not per-tool.** A single `on_call_tool` hook covers every tool in every
module and cannot drift as tools are added — the same reasoning behind the `_tool`
registration wrapper in `tools/gtd.py`. Per-tool `ConfigDict(extra="forbid")` would be 99
things to keep in step.

The rejection raises `ToolError`, matching the protocol-level shape RTM's existing
missing-required-parameter rejection already uses — it is deliberately NOT a
`build_response(data=build_error(...))` envelope error, because the call never reaches the
tool body and no `ErrorCode` registry entry is minted (which would churn every tool
fingerprint for a failure mode that is not a tool's own).
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

logger = logging.getLogger(__name__)


def unknown_parameter_message(tool_name: str, unknown: list[str], valid: list[str]) -> str:
    """The rejection prose.

    Naming the accepted parameters is the part that matters: it turns a rejection into
    the answer, which is the whole point — the caller is, by construction, confused.
    """
    return (
        f"unknown parameter(s) {unknown} for tool '{tool_name}'. "
        f"This tool accepts: {valid}. No write was performed. "
        "If the parameter you wanted exists on a different tool, check the tool "
        "description; if you believe it should exist here, raise an improvement "
        "candidate rather than working around it."
    )


class RejectUnknownParameters(Middleware):
    """Refuse a tool call carrying any parameter the tool does not define.

    Holds the server explicitly rather than reaching through the middleware context for
    it — one documented attribute (`FastMCP.get_tool`) instead of an internal, and it
    makes the middleware constructible in a test without a live request context.
    """

    #: No protocol-key passlist, and that is a measured decision rather than an omission.
    #: MCP carries `_meta` as a SIBLING of `arguments` on `CallToolRequestParams` (a
    #: pydantic field aliased `_meta`), so it never reaches this dict — verified on
    #: fastmcp 3.4.4 / mcp types. And a client that inlines `_meta` INTO `arguments` is
    #: rejected downstream by FastMCP's own signature binding regardless of what this
    #: middleware does ("Unexpected keyword argument", measured). Passing it through would
    #: therefore change nothing except substituting a worse message for a better one.
    #: An `_`-prefix rule would have been worse still — `_type_tags` is a typo, not
    #: protocol.

    def __init__(self, server: Any) -> None:
        self._server = server

    async def on_call_tool(self, context: Any, call_next: Any) -> Any:
        message = context.message
        provided = set(message.arguments or {})
        tool = await self._server.get_tool(message.name)
        if tool is None:
            # An unknown tool is not this middleware's error to raise — the dispatcher
            # below owns that message, and pre-empting it would replace a precise
            # "no such tool" with a confusing "no such parameter".
            return await call_next(context)

        valid = set((tool.parameters or {}).get("properties") or {})
        unknown = sorted(provided - valid)
        if unknown:
            logger.warning(
                "Rejected call to %s: unknown parameter(s) %s (accepts %s)",
                message.name,
                unknown,
                sorted(valid),
            )
            raise ToolError(unknown_parameter_message(message.name, unknown, sorted(valid)))

        return await call_next(context)
