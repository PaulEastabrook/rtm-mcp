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

    **Absence has more than one cause, and this module must not pretend otherwise.** The client
    strip above is one. A second was measured on 2026-08-01: the caller emitted the value as
    literal tool-call markup folded into a sibling string parameter, so the key never existed
    and nothing was stripped — see ``build_advisory``, which names both and asserts neither.

    That second cause is, unlike the strip, **server-detectable** — the value arrives, in the
    wrong parameter, instead of being destroyed upstream. So since v6.1.0 the advisory has two
    triggers: ``build_advisory`` (absence, the original) and ``build_markup_advisory``
    (evidence). The second **closes the partial-loss blind spot for that cause**, because it
    fires on the markup itself rather than on total absence — the case the all-absent rule is
    silent in by construction, and which covers 15 of the 25 governed writes.

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

import re
from collections.abc import Iterable
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
    "= something about the call itself worth checking. Check `not_applied[]` before reporting "
    "success."
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

    (v6.0.0 gave `gtd_note_add` two genuine facets — `sources` / `ai_context` — so the advisory
    is live there again, on purpose: measured 7/12 suite calls, and the overall governed-write
    rate moved 17.8% → 21.1%. The rule below is unchanged; `timestamp` is still not a facet.)
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

    **It states the OBSERVATION, and offers causes as possibilities (v6.0.5).** Through v6.0.4
    it asserted one cause — "a misspelt optional is dropped by some MCP clients" — as fact.
    Measured over the whole transcript population on 2026-08-01, that cause had been the actual
    cause **0 of the 2 times the advisory has ever fired**: once the call was legitimately bare,
    and once the value was emitted as literal tool-call markup folded into a sibling string
    (`</narrative>\\n<parameter name="sources">[…]`), so nothing was misspelt and no client
    dropped anything — the key was never emitted. A confidently wrong cause is worse than none:
    it sent a hand-off brief hunting a client-side strip that had not happened.

    The markup cause is named FIRST because it is the one the caller can check for itself, and
    because — unlike a strip — it leaves the value in the durable write, so the damage is
    recoverable rather than merely reportable.
    """
    if not declared or len(absent) < len(declared):
        return None
    shown = sorted(absent)[:MAX_NAMED_OPTIONALS]
    more = len(absent) - len(shown)
    names = ", ".join(shown) + (f", and {more} more" if more > 0 else "")
    return (
        f"No optional parameter reached this call to {tool_name} — none of: {names}. "
        "That is the observation; the cause is not visible from here. If you meant to set one, "
        "two causes are on record. (1) It was emitted as literal tool-call markup inside "
        "another parameter — check the text you sent for a stray `</…>` or `<parameter "
        "name=…>` tail, which is written VERBATIM into the record if present. (2) A misspelt "
        "name was dropped by the client before the server saw it. Compare the returned state "
        "against what you intended, and re-send with the exact name above. "
        f'See rtm_tool_help("{tool_name}").'
    )


# --------------------------------------------------------------------------- #
# Leaked tool-call markup (v6.1.0) — the ONE parameter-loss cause the server can see.
#
# The client strip destroys the value upstream, so nothing here can detect it. This is the
# other cause, and it is the opposite shape: the caller emits XML-style tool-call delimiters
# mid-argument and the serialiser folds them into the PRECEDING string, so the value ARRIVES
# — in the wrong parameter — and is written verbatim. Measured 2026-08-01: 13 events over
# five months across four MCP servers and four model generations; 5 corrupted RTM notes via
# three governed writes; two parameters genuinely lost, one of them silently
# (`gtd_inbox_item_annotate.questions`, reported only as `questions_count: 0`).
#
# THE ANCHOR IS TOOL-SCOPED, and that is what makes it precise. A closing tag is a finding
# only when its name is a parameter THIS tool declares. Measured over 13,435 real RTM calls:
# 7 firings, all true positives, zero false positives — including a full HTML document passed
# to `add_note` (`</head>`, `</body>`, `</script>`), which does not fire because none of those
# is an `add_note` parameter. A bare `</…>` predicate would have flagged it.
#
# ADVISORY, NEVER A GATE, and this is not a preference. The one class the anchor cannot
# separate is a note DOCUMENTING this defect — and this repo journals its own findings into
# RTM through exactly the tools being watched. A gate would make writing about the bug
# impossible; the advisory merely mentions it, and says so in its own text.
# --------------------------------------------------------------------------- #

#: A closing tag. Matched against the tool's own declared parameter names — never used bare.
_CLOSE_TAG = re.compile(r"</\s*([A-Za-z_][A-Za-z0-9_-]*)\s*>")

#: The `<parameter name="X">` opener of the other dialect. Used ONLY to name the parameter the
#: caller was trying to open, never as the anchor — the bare-tag dialect (`</analysis_body>`,
#: `</completion>`) carries no opener at all and accounts for the majority of measured events,
#: so anchoring on this would miss most of them.
_PARAM_OPEN = re.compile(r"""<parameter\s+name\s*=\s*["']([A-Za-z_][A-Za-z0-9_-]*)["']""")


def detect_leaked_markup(supplied: dict[str, Any], declared: Iterable[str]) -> list[dict[str, Any]]:
    """Find tool-call markup folded into a string argument → one entry per affected parameter.

    `supplied` is the call's bound arguments; `declared` is every parameter name the tool
    defines (not only the optionals — the measured leaks closed over `narrative`,
    `analysis_body` and `completion`, all of them REQUIRED).

    Each entry is `{"param", "closed", "lost"}`: the parameter carrying the markup, the declared
    names whose closing tags appear inside it, and the parameters that consequently did NOT
    arrive as arguments.

    **`lost` unifies the two dialects, and the second half of it was found by a failing test
    rather than by design.** Dialect 1 names the target in a `<parameter name="sources">`
    opener. Dialect 2 has no opener at all — but it turns out to carry the same information:
    `</analysis_body>\\n<questions>[…]</questions>` closes `questions`, which is *also* a
    declared parameter of that tool. So a closing tag naming a declared parameter OTHER than
    the carrier is itself a lost-parameter signal, and both dialects reduce to one field.

    Empty list when there is nothing to report, so a caller can branch on truthiness.
    """
    names = set(declared)
    findings: list[dict[str, Any]] = []
    for param, value in sorted(supplied.items()):
        if not isinstance(value, str) or "</" not in value:
            continue
        closed = sorted({tag for tag in _CLOSE_TAG.findall(value) if tag in names})
        if not closed:
            continue
        lost = set(_PARAM_OPEN.findall(value)) | (set(closed) - {param})
        findings.append({"param": param, "closed": closed, "lost": sorted(lost)})
    return findings


def build_markup_advisory(tool_name: str, findings: list[dict[str, Any]]) -> str | None:
    """The leaked-markup advisory, or None when nothing was found.

    **This is the half that closes the partial-loss blind spot.** `build_advisory` fires only
    when EVERY optional facet is absent, so a call that supplies one facet correctly and loses
    another is silent — 15 of the 25 governed writes have that gap. This fires on the evidence
    itself rather than on total absence, so it speaks in exactly the case the other cannot.
    """
    if not findings:
        return None
    parts = []
    for f in findings:
        tags = ", ".join(f"`</{t}>`" for t in f["closed"])
        lost = ", ".join(f"`{name}`" for name in f["lost"])
        naming = f", and {lost} did not arrive as an argument" if lost else ""
        parts.append(f"inside `{f['param']}` ({tags}){naming}")
    where = "; ".join(parts)
    return (
        f"Tool-call markup arrived INSIDE a string argument to {tool_name} — {where}. That text "
        "is written VERBATIM into the record. This happens when tool-call delimiters are emitted "
        "mid-argument and folded into the preceding string, so the value never becomes a "
        "separate JSON key. Re-send the named parameter as its own argument, and check the "
        "written record for the stray markup. Nothing was blocked — if you are quoting this "
        "markup deliberately, ignore this."
    )


# --------------------------------------------------------------------------- #
# Name length (v6.6.0) — a GTD hygiene signal, and emphatically NOT a filesystem one.
#
# THE MEMBRANE. This server knows NOTHING about vaults, folders, slugs or path budgets, and
# this block must not be the place that changes. `companion.py` is the single vault seam, it
# is read-only, and it is documented as never to widen. An earlier draft of the designed
# change gave this repo the slug function, the path template and the length cap; that was
# corrected before implementation (`2026-08-02-vault-naming-mirrors-rtm` § 1a.1) precisely
# because it breached that boundary. What lives here is ONE integer and a comparison. The
# filesystem reasoning lives in gtd's `references/focus-area-map.md`; actual truncation is
# reported by `agent-memory-mcp` at filing time, where `folder_name()` can compute it.
#
# WHY 60 IS WORTH SAYING ANYTHING ABOUT, measured over the live estate 2026-08-02: live
# project names run 45% longer than archived ones (median slug 46.5 vs 32.0), and of the 31
# live projects over budget, **13 are defects the length merely exposed** — nine outcome
# statements sitting in the title field ("…(ensure this is objective and data backed)" is an
# acceptance criterion), four single actions mis-tagged as projects, two carrying a date that
# belongs on the due date. So the useful claim is "something is in the wrong field", not "your
# folder will be shortened" — and that judgement is the caller's, which is why this is an
# advisory and can never become a gate.
# --------------------------------------------------------------------------- #

#: Characters of raw item/project name above which the hygiene advisory fires (Paul, 2026-08-02).
NAME_ADVISORY_LIMIT = 60


def build_name_advisory(name: Any, *, limit: int = NAME_ADVISORY_LIMIT) -> str | None:
    """The name-length advisory, or None at or below the threshold (and for a non-string).

    **This is a deliberately ONE-SIDED proxy, and the direction is the safe one.** It measures
    the raw name; whether a vault folder actually truncates is decided by the *slug*, computed
    vault-side from a different quantity. Measured 2026-08-02: 6 live items truncate without
    tripping a 60-character advisory (e.g. a 56-character name that loses its last word), and
    **zero** trip the advisory without truncating. So the error is under-warning, never
    over-warning — which is what an advisory should get wrong if it must get something wrong.

    **A raw-name threshold is unsound in principle, not merely imprecise, so do not "fix" it by
    lowering the number.** Slugging expands as well as contracts: `&` becomes `and`, so
    `R&D & QA & Ops & Sec review` is 27 characters and slugs to 37. No raw-name threshold is
    sound, and reaching for a sounder one here would mean importing the slug rule — which is
    the membrane above. The band is closed at the other end instead, by the server that owns
    the rule.

    The message names a *length* and never a path, for the same reason.
    """
    if not isinstance(name, str) or len(name) <= limit:
        return None
    return (
        f"Name is {len(name)} characters. Long names usually mean something belongs in another "
        "field — an outcome statement, an acceptance criterion, or a date that belongs on the "
        "due date. Consider shortening."
    )


def _count(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    return len(value) if isinstance(value, list) else 0


def build_guidance(data: dict[str, Any]) -> str | None:
    """The next step, but ONLY where it says something the other fields do not (v4.1.0).

    **Narrowed after the v4.0.0 trial measured it.** It originally fired on any response that
    was not a clean full success, and **56 of 62 emissions were the full-rejection branch** —
    a restatement of the `rejected[]` array sitting immediately above it in the same payload.
    Duplication is not free: a field that usually repeats its neighbour trains a caller to skip
    it, which costs exactly the two branches below that are worth reading.

    Two branches survive, and severity ordering between them is unchanged:

    - **Partial write** — some ops are durable and some failed. This is the branch that
      justifies the field: the response otherwise reads as a success with a stray `errors[]`,
      and a blind retry re-applies everything that already succeeded.
    - **`not_applied[]` non-empty** — the write was clean but narrower than asked for.

    **Dropped: the full-rejection branch.** `rejected[]` already carries every reason; guidance
    added only a count. Also dropped, as a consequence of "only where it says something new":
    the bare zero-applied case, where `applied: []` is the statement.
    """
    errors = _count(data, "errors")
    not_applied = _count(data, "not_applied")
    applied = _count(data, "applied")

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
    return None


def attach(
    data: dict[str, Any],
    *,
    tool_name: str,
    absent_optional: list[str],
    declared_optional: list[str],
    leaked: list[dict[str, Any]] | None = None,
    item_name: Any = None,
) -> dict[str, Any]:
    """Attach the three receipt fields to a governed write's success payload.

    Returns `data` unchanged (never copied — the caller owns it) when it is an **error**
    envelope: `data.error` is the `success | error` union discriminator, a failure already
    carries its own typed teaching, and hanging outcome fields off it would blur the
    discriminator that consumers branch on.

    A `not_applied[]` a tool body has already populated is preserved; this only guarantees the
    key exists. `guidance` is derived last, so it sees those entries.

    **`leaked` OUTRANKS the bare-call advisory, because it explains it.** When markup is found,
    the absence of the optionals is not a separate fact to report — it is the same fact, and the
    markup advisory names the lost parameter where the bare-call one can only list what is
    missing. Reporting both would say one thing twice, which is the duplication v4.1.0 narrowed
    `guidance` to avoid. And the markup advisory still fires when the bare-call one is silent
    (some facets supplied, one lost), which is the whole point of having it.

    **The name advisory is APPENDED rather than ranked, and the asymmetry is the reason.**
    Markup and bare-call are mutually exclusive because one *explains* the other, so emitting
    both would say one thing twice. Name length explains neither and is explained by neither —
    it is an independent observation about data that DID land, where the other two are about
    data that may not have. Ranking it would silently drop a true signal; concatenating drops
    nothing and duplicates nothing. `item_name` is None for every tool that has no such name,
    so the producer is silent by construction rather than by exemption.
    """
    if not isinstance(data, dict) or "error" in data:
        return data
    data.setdefault("not_applied", [])
    loss = build_markup_advisory(tool_name, leaked or []) or build_advisory(
        tool_name, absent_optional, declared_optional
    )
    parts = [part for part in (loss, build_name_advisory(item_name)) if part]
    data["advisory"] = " ".join(parts) or None
    data["guidance"] = build_guidance(data)
    return data
