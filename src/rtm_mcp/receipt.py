"""The teaching receipt — what the caller asked for, set against what actually landed.

**The gap this closes, and why nothing else can.** The Tool Affordance Standard (v3.3.0)
shipped tier 1 (front-loaded selection) and tier 2 (`rtm_tool_help`), and *measured* tier 3
(teach-on-reject) unreachable on the hosted client: Claude Desktop re-registers every tool
through a strip-mode zod object, so an undeclared argument is deleted **client-side** and
never reaches this server (see `middleware.py` for the traced mechanism). A misspelt
**required** parameter still fails loudly — the required key goes missing and binding
rejects. A misspelt **optional modifier** does not: the write succeeds minus the property,
and success is reported with nothing marking the discarded intent.

**You cannot throw on what you were never told.** The server receives
`gtd_inbox_capture(text="…")` — a completely valid call. There is no anomaly to detect,
because the information was destroyed upstream. So this module attacks the problem from the
other end: the caller knows its *intent*, the server knows the *outcome*, and if the outcome
is made impossible to misread the caller can close the loop itself.

Three fields, attached to every governed write:

``not_applied[]``
    One entry per requested operation that produced **no write**. `applied[]` says what
    happened and `errors[]` catches per-op failures; neither says *"you asked for this and it
    did not land."* Always present, empty when everything landed — zero-not-absent, so a
    consumer can branch unconditionally.

``guidance``
    One plain next step on any response that is not a clean full success. The tier-3
    rejection discipline (`guided_rejection.py`) applied to *partial* success — the case
    where nothing errored but the outcome was still incomplete.

``advisory``
    The one signal that survives the client strip. The server cannot know what was removed,
    but it **can** observe that a governed write arrived carrying none of its optional
    parameters, and name the ones that are absent. It reasons about **absence**, which is the
    only thing still observable — which is precisely why it works where tier 3 cannot.

**The advisory is never a rejection and never blocks.** A minimal call is often legitimate,
so this is data the caller may ignore; a caller that ignores all three still gets a correct,
complete result. That is a hard invariant, not a preference.

**What "no optional parameter arrived" is operationalised as.** FastMCP binds defaults before
the tool body runs, so a wrapper cannot distinguish *omitted* from *explicitly passed at its
default value* — measured, not assumed. It does not need to: the two are behaviourally
identical (a parameter equal to its default changes nothing the tool does), so "absent" here
means **equal to its declared default**, and the advisory is exact with respect to what the
call actually did.

**Scope.** Governed `gtd_*` writes only, applied centrally at registration
(`tools/gtd.py::_tool`) rather than in 25 tool bodies — the same one-place-cannot-drift
reasoning as the `RejectUnknownParameters` middleware. The generic RTM primitives are the
documented permissive escape hatch and are deliberately untouched.
"""

from __future__ import annotations

from typing import Any

from .error_codes import ErrorCode

#: The three keys attached to every governed-write success payload. Named once so the
#: contract, the output models and the tests all read the same list.
RECEIPT_FIELDS: tuple[str, str, str] = ("not_applied", "guidance", "advisory")

#: The closed `not_applied[].reason` vocabulary — the fourth scoped view of the one `ErrorCode`
#: registry, alongside `COMMIT_REJECT_REASONS` / `CREATE_REJECT_REASONS` /
#: `ENGAGE_REJECT_REASONS` (§ 5, "one vocabulary, three scoped views"). Declared next to the
#: constructor that stamps it, so the advertised enum in `models.NotApplied` tracks the code by
#: construction rather than by a second hand-maintained list.
RECEIPT_REASONS: frozenset[ErrorCode] = frozenset(
    {ErrorCode.NO_CHANGE, ErrorCode.NO_DURABLE_WRITE, ErrorCode.NOT_ELIGIBLE}
)

#: Ceiling on the optional-parameter names rendered into an advisory. The widest governed
#: write (`gtd_surface_create`, 9 optionals) fits comfortably; the cap exists so a future
#: wide tool cannot turn an advisory into a wall.
MAX_NAMED_OPTIONALS = 12

#: The receipt's own tier-1 documentation, appended to every governed write's description at
#: registration. Three fields a caller has never seen before are worth nothing if nothing tells
#: it they exist — and `not_applied: []` on a clean success is the one part of the receipt that
#: carries no self-describing prose, so the description is the only place it can be introduced.
#:
#: Authored ONCE and projected, for the same reason the receipt is attached once: 25 copies is
#: 25 things to keep in step. It is deliberately terse — it is charged against the ~2 KB the
#: client keeps (CONTRIBUTING § 3), so it buys the imperative ("check it before reporting
#: success") and leaves the full contract to `rtm_tool_help`, which has no budget.
RECEIPT_DOC = (
    "Receipt: `not_applied[]` = what you asked for that was NOT written (empty when all "
    "landed); `guidance` = the next step when the outcome was not a clean success; `advisory` "
    "= the call carried no optional parameter. Check `not_applied[]` before reporting success."
)


def not_applied_entry(
    op: str,
    *,
    reason: ErrorCode,
    detail: str,
    requested: Any = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    """One `not_applied[]` entry — a requested operation that produced no write.

    `reason` is an `ErrorCode` member so the vocabulary stays unified with the envelope error
    and the commit engines' `rejected[].reason` (§ 5). `detail` is human prose and must never
    be parsed. `requested` carries what the caller asked for where it is meaningful (the tags,
    the verdict), and is omitted entirely when it would only restate `op`.
    """
    entry: dict[str, Any] = {"op": op, "reason": reason.value, "detail": detail}
    if item_id is not None:
        entry["id"] = item_id
    if requested is not None:
        entry["requested"] = requested
    return entry


def is_facet(default: Any) -> bool:
    """Whether an optional parameter is a value-bearing FACET rather than a control flag.

    The advisory exists for one failure: a stripped optional that carries DATA (a due date, a
    tag list, a note body), where the write lands without it and reports success. A boolean is
    a mode switch, not data, and stripping one cannot produce that failure —
    `confirm_destructive` going missing gets the call *rejected*, and `dry_run` or `timestamp`
    going missing changes behaviour the response then states plainly. So a boolean can never be
    the thing the caller silently lost, and counting it as a facet only generates noise.

    Measured, and this is why the rule exists rather than being a preference: after the eight
    payload parameters became required, the ONLY optional left on `gtd_engage_commit` was
    `confirm_destructive` and on `gtd_note_add` it was `timestamp` — so both fired the advisory
    on 100% of legitimate calls in the suite. Excluding booleans took the overall rate from
    31.8% to a figure driven entirely by genuine facets.
    """
    return not isinstance(default, bool)


def build_advisory(tool_name: str, absent: list[str], declared: list[str]) -> str | None:
    """The bare-call advisory, or None when the call carried at least one optional value.

    Fires only when **every** declared optional is absent — a call that supplied even one is
    evidently not a stripped-bare call, and flagging it would be noise. Returns None when the
    tool declares no optional parameters at all: there, absence carries no information.

    Names the absent parameters rather than saying merely "no optional parameters were
    received": the caller is being asked to compare the outcome against an intent only it
    knows, and it can only do that against specific names.
    """
    if not declared or len(absent) < len(declared):
        return None
    shown = sorted(absent)[:MAX_NAMED_OPTIONALS]
    more = len(absent) - len(shown)
    names = ", ".join(shown) + (f", and {more} more" if more > 0 else "")
    return (
        f"No optional parameter reached this call to {tool_name} — none of: {names}. "
        "If you meant to set one, it did not arrive: a misspelt optional is dropped by some "
        "MCP clients before the server sees it, so the write lands without it and still "
        "reports success. Compare the returned state against what you intended, and re-send "
        f'the missing property with the exact name above. See rtm_tool_help("{tool_name}").'
    )


def _count(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    return len(value) if isinstance(value, list) else 0


def build_guidance(data: dict[str, Any]) -> str | None:
    """The next step for a response that is not a clean full success, or None when it is.

    Ordered by severity, because only the most serious statement is worth making: a validation
    rejection wrote nothing at all; a per-op error means the batch **partially** applied and
    needs reconciling; a `not_applied[]` entry means the write was clean but narrower than
    asked for.
    """
    rejected = _count(data, "rejected")
    errors = _count(data, "errors")
    not_applied = _count(data, "not_applied")
    applied = _count(data, "applied")

    if rejected:
        return (
            f"Nothing was written — {rejected} item(s) failed validation. Read rejected[] for "
            "the reason on each, correct them, and re-send the whole payload; this tool "
            "validates before it applies, so there is no partial state to clean up."
        )
    if errors:
        return (
            f"PARTIAL WRITE — {applied} operation(s) landed and {errors} failed. The successful "
            "ones are durable. Read errors[] to see which failed, then either re-send just "
            "those or reverse the whole batch with batch_undo using the transaction ids in "
            "applied[]."
        )
    if not_applied:
        return (
            f"{applied} operation(s) landed; {not_applied} produced no write. Read not_applied[] "
            "— each entry names what was requested and why nothing was written. This is not an "
            "error, but if you expected a change there, it did not happen."
        )
    if applied == 0 and "applied" in data:
        return (
            "Nothing was written. The call was accepted but carried no operation to perform — "
            "check that the payload you intended actually reached this tool."
        )
    return None


def attach(
    data: dict[str, Any],
    *,
    tool_name: str,
    absent_optional: list[str],
    declared_optional: list[str],
) -> dict[str, Any]:
    """Attach the three receipt fields to a governed write's success payload.

    Returns `data` unchanged (never copied — the caller owns it) when it is an **error**
    envelope: `data.error` is the `success | error` union discriminator, a failure already
    carries its own typed teaching, and hanging outcome fields off it would blur the
    discriminator that consumers branch on.

    A `not_applied[]` a tool body has already populated is preserved; this only guarantees the
    key exists. `guidance` is derived last, so it sees those entries.
    """
    if not isinstance(data, dict) or "error" in data:
        return data
    data.setdefault("not_applied", [])
    data["advisory"] = build_advisory(tool_name, absent_optional, declared_optional)
    data["guidance"] = build_guidance(data)
    return data
