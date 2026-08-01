"""Call-boundary middleware — reject unknown tool parameters.

What this actually does — CORRECTED 2026-07-26, and the correction matters more than the
original claim. This module shipped at v3.2.0 saying it closed a hole where "a tool call
carrying a parameter the tool does not define was accepted silently, with a success
response". **That premise is measured false on the pinned stack.** A bare fastmcp 3.4.4
server with NO middleware at all rejects an undeclared argument at pydantic's call-schema
binding, before the tool body runs:

    1 validation error for call[echo]
    unknown_kwarg
      Unexpected keyword argument [type=unexpected_keyword_argument, input='SENTINEL']

Verified twice: directly on a bare `FastMCP` instance, and against v3.1.0 (`git archive`,
no `middleware.py` at all) driven over raw JSON-RPC. So **this middleware did not add a
gate — it replaced a pydantic dump with a teaching rejection.** That is a real improvement
in the message, and nothing more. `additionalProperties: false` on every advertised
inputSchema comes from pydantic's `kw_arguments_schema` (the no-`**kwargs` branch), not
from anything here.

Where the observed silence really came from. The motivating incident — a
`gtd_inbox_capture(text=…, type_tags=[…])` call that returned a success whose `applied[]`
read `capture:tags`, misread as the (non-existent) tag write landing — is on record in a
Desktop local-agent transcript. Its three undeclared keys never reached this server: the
Claude Desktop host re-registers each upstream tool through a JSON-Schema→zod converter
(`jsonSchemaToZodShape`) that reads **only** `properties` and `required`, wraps the result
in a plain strip-mode `z.object`, and forwards the PARSED object. Undeclared top-level
keys are silently deleted client-side. The shipped converter was measured invariant to
`additionalProperties` being `false`, `true`, or absent — so our closed schema is
discarded upstream, not enforced.

**Consequence, stated plainly: this middleware is unreachable through that host.** A sweep
of 2,517 transcripts — every session on the machine, including the whole scheduled-worker
population — found **zero** cases of any caller receiving its rejection through the MCP
boundary. It is retained as a backstop for caller populations that have not been measured
(a rendered board artifact, MCP Inspector, a non-Desktop client), and because a better
message costs nothing, but it must not be described as preventing the incident that
prompted it. It could not have.

The defect class itself is real and now lives one hop outside this server's reach: a
misspelt *optional* on a write tool (`gtd_item_create`, `gtd_item_set_properties`) is
stripped by the host, the item is written without that property, and success is reported
with nothing in `applied[]` or `errors[]` marking the discarded intent. Nothing
server-side can detect that.

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

from . import tool_help
from .guided_rejection import build_rejection, render_prose
from .receipt import detect_leaked_markup

logger = logging.getLogger(__name__)


def unknown_parameter_message(
    tool_name: str,
    unknown: list[str],
    valid: list[str],
    *,
    description: str = "",
    input_schema: dict[str, Any] | None = None,
) -> str:
    """The rejection prose — a teaching rejection, not just a refusal.

    Naming the accepted parameters is the part that matters: it turns a rejection into the
    answer, which is the whole point — the caller is, by construction, confused. Since
    v3.3.0 it names them with their types, required/optional, enums and one-line purpose,
    plus the tool's own purpose (the caller may have picked the wrong *tool* — that was the
    original `type_tags` case, where capture was simply the wrong tool for tagging), a
    nearest-name guess for a probable typo, and a pointer to the full contract.

    Every fact is projected from the tool's own advertised schema via `tool_help`, so the
    rejection cannot promise a parameter the schema does not carry. Built through the shared
    `guided_rejection` generator so this path, the combination gates and the vocabulary
    rejections speak with one voice.
    """
    params = tool_help.parameters(input_schema) if input_schema else []
    rejection = build_rejection(
        tool_name,
        problem=f"unknown parameter(s) {unknown} for tool '{tool_name}'.",
        purpose=tool_help.purpose_line(description),
        parameters=params,
        unknown=unknown,
        rules=tool_help.combination_rules(tool_name, input_schema),
    )
    # `valid` stays in the prose even when the table renders, so a caller (or a test)
    # scanning for the accepted set finds it in one place regardless of tool arity.
    return render_prose(rejection) + f"\n\nThis tool accepts: {valid}."


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

        schema = tool.parameters or {}
        valid = set(schema.get("properties") or {})
        unknown = sorted(provided - valid)
        if unknown:
            logger.warning(
                "Rejected call to %s: unknown parameter(s) %s (accepts %s)",
                message.name,
                unknown,
                sorted(valid),
            )
            raise ToolError(
                unknown_parameter_message(
                    message.name,
                    unknown,
                    sorted(valid),
                    description=getattr(tool, "description", "") or "",
                    input_schema=schema,
                )
            )

        # Leaked tool-call markup — LOG ONLY, never a rejection (v6.1.0).
        #
        # This middleware can only raise, so it is a gate by construction and therefore cannot
        # carry the caller-visible half; the receipt does that, on the 25 governed writes. What
        # it can do is cover the OTHER 75, which is where the traffic actually is — `add_note`
        # alone was measured at 78x the volume of `gtd_note_add`, and it is the documented
        # escape hatch, i.e. exactly where drift enters. A WARNING reaches the v5.1.0 file sink,
        # which survives the /dev/null fd 2 of a Desktop-spawned server.
        #
        # Deliberately NOT a ToolError: the anchor cannot distinguish a genuine leak from a note
        # DOCUMENTING one, and this repo journals its own defects into RTM through these tools.
        # Blocking would make writing about the bug impossible. See `receipt.detect_leaked_markup`.
        leaked = detect_leaked_markup(message.arguments or {}, valid)
        if leaked:
            logger.warning("Leaked tool-call markup in call to %s: %s", message.name, leaked)

        return await call_next(context)
