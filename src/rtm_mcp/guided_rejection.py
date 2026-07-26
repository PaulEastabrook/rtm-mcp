"""Tier-3 affordance surface — the one guided-rejection shape.

A rejection is the only moment the server *makes* a caller read something. Every other
channel is opt-in: a description may be truncated, `annotations` and `_meta` may never reach
the model, and a help tool must be chosen. So the rejection is where teaching belongs —
Anthropic's *Writing effective tools for agents* puts it plainly: prompt-engineer the error
to communicate specific, actionable improvements rather than an opaque code.

**What this replaces.** v3.2.0's unknown-parameter gate returned the bare valid NAMES: no
purpose, no types, no required/optional, no enums, and a pointer to "the tool description"
with no payload for a caller that cannot see the listing. It told the caller they were wrong
without teaching them to be right — and every fact needed already existed in the advertised
schema and was simply discarded.

**One shape, three producers.** The repo already had two guided rejections that got this
right in their own corner and shared nothing: `strict_tags.guided_error` (a
`how_to_proceed` clause) and `engage_commit.validate` (a closest-legal `suggestion`). This
module is the convergence — `build_rejection` assembles the teaching content once and
`render_prose` renders it for the protocol-level path, so the unknown-parameter gate, the
combination gates and the vocabulary rejections read as one voice instead of three.

**Prose and structure, one source.** The call-boundary gate raises `ToolError` before the
tool body runs, so it can only carry a string — deliberately, since minting an `ErrorCode`
for a failure that is not a tool's own would churn every fingerprint (see `middleware.py`).
The envelope path carries the same fields under `error.details`. Both come from
`build_rejection`, which is why they cannot drift.
"""

from __future__ import annotations

import difflib
from typing import Any

#: Ceiling on the parameter table rendered into a rejection. The widest tool
#: (`gtd_surface_create`, 13 params) renders ~1.5 KB, which is affordable on a path that
#: only ever executes when the caller is already wrong — but a future 40-param tool should
#: not turn a rejection into a wall.
MAX_RENDERED_PARAMS = 16


def nearest_name(unknown: str, valid: list[str]) -> str | None:
    """The probable typo, or None. A single best guess — offering three is not a suggestion."""
    matches = difflib.get_close_matches(unknown, valid, n=1, cutoff=0.6)
    return matches[0] or None if matches else None


def build_rejection(
    tool_name: str,
    *,
    problem: str,
    purpose: str = "",
    parameters: list[dict[str, Any]] | None = None,
    unknown: list[str] | None = None,
    rules: list[str] | None = None,
    suggestion: str | None = None,
) -> dict[str, Any]:
    """Assemble the teaching payload for one rejected call.

    `parameters` is the projection of the tool's own advertised `inputSchema`
    (`tool_help.parameters`), so the rejection and the schema cannot disagree about what the
    tool accepts.
    """
    params = parameters or []
    valid = [str(p.get("name")) for p in params]
    rejection: dict[str, Any] = {
        "tool": tool_name,
        "problem": problem,
        "no_write_performed": True,
        "accepted_parameters": valid,
        "how_to_proceed": f'Call rtm_tool_help("{tool_name}") for the full contract.',
        "help": f'rtm_tool_help("{tool_name}")',
    }
    if purpose:
        rejection["tool_purpose"] = purpose
    if params:
        rejection["parameters"] = params[:MAX_RENDERED_PARAMS]
    if unknown:
        rejection["unknown_parameters"] = unknown
        guesses = {u: nearest_name(u, valid) for u in unknown}
        near = {u: g for u, g in guesses.items() if g}
        if near:
            rejection["did_you_mean"] = near
    if rules:
        rejection["combination_rules"] = rules
    if suggestion:
        rejection["suggestion"] = suggestion
    return rejection


def _render_param(p: dict[str, Any]) -> str:
    req = "required" if p.get("required") else "optional"
    bits = [f"{p.get('name')} ({p.get('type')}, {req})"]
    enum = p.get("enum")
    if enum:
        bits.append(f"one of {list(enum)}")
    desc = (p.get("description") or "").strip()
    if desc:
        first = desc.split(". ")[0].rstrip(".")
        bits.append(first)
    return "  - " + " — ".join(bits)


def render_prose(rejection: dict[str, Any]) -> str:
    """Render the payload as the prose a `ToolError` carries.

    Ordered by what the caller needs to retry: what went wrong, the correction if we can
    guess it, what the tool is for (they may have picked the wrong tool entirely), what it
    accepts, the rules a schema cannot state, and where to get the rest.
    """
    lines = [rejection["problem"], "No write was performed."]

    near = rejection.get("did_you_mean")
    if near:
        lines.append(
            "Did you mean: " + ", ".join(f"{k} -> {v}" for k, v in sorted(near.items())) + "?"
        )

    purpose = rejection.get("tool_purpose")
    if purpose:
        lines.append(f"\nWhat {rejection['tool']} is for: {purpose}")

    params = rejection.get("parameters")
    if params:
        lines.append(f"\n{rejection['tool']} accepts:")
        lines.extend(_render_param(p) for p in params)
        omitted = len(rejection.get("accepted_parameters", [])) - len(params)
        if omitted > 0:
            lines.append(f"  … and {omitted} more — see the help payload below.")
    elif rejection.get("accepted_parameters"):
        lines.append(f"\n{rejection['tool']} accepts: {rejection['accepted_parameters']}")

    rules = rejection.get("combination_rules")
    if rules:
        lines.append("\nRules this tool enforces:")
        lines.extend(f"  - {r}" for r in rules)

    suggestion = rejection.get("suggestion")
    if suggestion:
        lines.append(f"\nSuggestion: {suggestion}")

    lines.append(
        f"\nFor the full contract — worked examples, every return case, and the typed-error "
        f"catalogue — call {rejection['help']}. If the parameter you wanted belongs to a "
        f"different tool, call rtm_tool_help() with no argument for the index; if you believe "
        f"it should exist here, raise an improvement candidate rather than working around it."
    )
    return "\n".join(lines)
