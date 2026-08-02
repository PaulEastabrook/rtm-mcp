"""Note-shape mode — the *mechanical* grammar gate for note-title writes.

The sibling of ``strict_tags.py``: a deterministic write-boundary gate that refuses a
malformed write at the server, so the discipline becomes an invariant no agent, session,
or scheduled engine can forget.

**Two checks, and since v5.2.0 both are enforced.** The gate checks that a note title parses as::

    YYYY-MM-DD [HH:MM] — TYPE — summary

…a real calendar date, both em-dash separators, a well-formed non-empty TYPE token, and a
non-empty summary (:func:`check_title`) — **and** that TYPE is a registered type
(:func:`check_type`).

**Since v6.4.0 there is a third tier: the per-TYPE contract** (:func:`check_contract`), for the
two TYPEs whose grammar the server *already parses* — `CHAT` and `ORDER`. It runs in
`vocabulary` mode only, so `shape` stays a byte-for-byte v5.1.0 rollback step. It retires the
equivalent checks from gtd's `validate-note.py`: a ten-line reuse of a proven parser replaces a
pre-flight the caller had to remember to run. The verdict rides in `error.details.rejected_by`
(`chat_title` / `order_contract`) with **no new `ErrorCode`** — same ladder as v5.2.0.

**The vocabulary check is a reversal, and the reasoning is worth keeping.** Through v5.1.x this
module enforced shape only, on the CONTRIBUTING § 6 membrane: the server gates mechanics, the
plugin gates vocabulary, exactly as the server gates tag *existence* while gtd gates tag
*canonicality*. That split was correct while it held. It stopped holding when the split was
measured: a full-estate census on 2026-07-31 found **~40 off-vocabulary TYPE tokens across 114
notes**, accumulated over five months, because the plugin-side validator only runs when a caller
remembers to run it. A gate that can be forgotten is not a gate — the same argument that put the
other three write gates here.

What did NOT change is where the vocabulary is *decided*. `note-shape-catalogue.md` § 2 remains
the authority; this server **codifies** it (see :mod:`note_types`), exactly as
:mod:`engage_commit` codifies the verdict grammar. A new type is added to the markdown first —
codification before validation — and the gtd-side ``validate-note.py`` picks it up at runtime with
no release. Only the server's copy needs a version bump, and that lockstep is the accepted cost of
enforcement.

The write-authorised set is **derived**, never hand-listed
(:data:`note_types.WRITE_AUTHORISED_NOTE_TYPES`): a fifth hand-maintained vocabulary would be the
very drift this gate exists to stop.

**Where the title comes from.** RTM has no note-title field: ``notes.add``/``notes.edit``
store the body as ``<note_title>\\n<note_text>`` and return an empty title on read (the same
storage reality the CHAT / ORDER / TMPL-CHILD grammars rely on). So the *effective* title is
``note_title`` when supplied, else the first line of ``note_text`` — which is what a caller
authoring the grammar inline actually writes.

**Paul's free-text notes are never a violation (normative).** A note with **no date prefix** is
one Paul typed into the RTM app himself, and is his addition — not drift. This gate is safe on
that by *construction*, since it governs MCP writes only and never sees the app. It is stated
here because the discriminator binds the gtd-side **notes-audit** too, which scans existing notes
and would otherwise report them: *no date prefix → informational, never a finding; date-prefixed
but off-vocabulary TYPE → agent-written, and that is the finding.* The data separates cleanly —
agent-written notes always carry the ``YYYY-MM-DD — TYPE —`` prefix, Paul's are free prose.

Modes (``config.strict_notes``), an escalation: ``off`` (inert) → ``warn`` (log only, never
rejects) → ``shape`` (grammar; the v5.1.0 default, and the byte-for-byte rollback step) →
``vocabulary`` (grammar **and** a registered TYPE; **the default since v5.2.0**). See
CONTRIBUTING § 6.

**No ``warn`` stage was run before the flip, deliberately.** The observe-before-enforce step was
offered and declined (Paul, 2026-08-01) — the census had already measured the population the gate
would fire on, so `warn` would have re-measured what was known. Rollback is one env var per tier.

**Scope, precisely — this gate governs the escape hatch, not the gtd write paths.** It is wired
into the generic ``add_note`` and ``edit_note`` only. Every ``gtd_*`` note write calls
``rtm.tasks.notes.add`` directly and is conformant by construction (or validated by its own
grammar), which is why several of them legitimately write a bare marker title such as
``DEPENDS-ON`` that this grammar would reject. Do **not** "fix" that by wiring the gate in
there: those bare titles are load-bearing — ``project_plan._extract_deps_and_files`` round-trips
on them.
"""

import logging
import re
from datetime import date
from typing import Any

from .error_codes import ErrorCode
from .response_builder import build_error

logger = logging.getLogger(__name__)

# Em-dash is canonical; en-dash is tolerated on parse (the gtd validator warns on it
# rather than erroring, and this gate is mechanical — it must not be stricter).
_DASH = r"(?:—|–)"  # noqa: RUF001 — en-dash is deliberate (tolerated on parse)

# The mechanical title grammar. TYPE is "an uppercase token", NOT a vocabulary member:
# leading uppercase letter, then uppercase letters / spaces / hyphens (so OUTPUT,
# DEPENDS-ON and AI LINK all parse). Non-greedy so the SECOND dash ends the type.
_TITLE_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})(?:[ T](?P<time>\d{2}:\d{2}))?\s*"
    rf"{_DASH}\s*(?P<type>[A-Z][A-Z -]*?)\s*{_DASH}\s*(?P<summary>.*)$"
)

EXPECTED_SHAPE = "YYYY-MM-DD [HH:MM] — TYPE — summary"

# The `config.strict_notes` vocabulary. Owned here (the gate owns its own modes) and
# imported by config.py for field validation, so a typo'd env var fails loudly at load
# rather than silently leaving the gate inert.
#
# Ordered as an escalation: off → warn (log only) → shape (mechanical grammar) →
# vocabulary (grammar AND a registered TYPE). `vocabulary` is the shipped default since v5.2.0.
VALID_STRICT_NOTES_MODES = ("off", "warn", "shape", "vocabulary")

#: The modes in which the gate rejects rather than merely logging.
_ENFORCING_MODES = ("shape", "vocabulary")


def check_type(title: str) -> str | None:
    """Judge a note title's TYPE against the write-authorised vocabulary.

    Returns a reason string, or None when the type is registered (or the title does not parse,
    which is `check_title`'s finding to report, not this one's).

    **The allow-list is derived, never hand-listed** — see `note_types.WRITE_AUTHORISED_NOTE_TYPES`.
    A fifth hand-maintained vocabulary is precisely the drift this gate exists to stop, so it must
    not be created in order to enforce it.

    **The legacy AI-surface spellings are deliberately absent from the write set**, which is the
    asymmetry that makes this gate worth having: `ACTIVITY_REPORT`, `Q`, `AR` and the rest stay
    *readable* (`note_types.SURFACE_NOTE_TYPES`, consulted by `surface_queue.classify_note`) and
    stop being *writable*. A write set that admitted them would license the drift the 2026-07-31
    remediation pass was run to clear, the day after it ran.
    """
    from .note_types import SURFACE_NOTE_TYPES, WRITE_AUTHORISED_NOTE_TYPES

    match = _TITLE_RE.match(title or "")
    if not match:
        return None  # not a vocabulary finding — `check_title` owns the shape verdict
    note_type = match.group("type").strip()
    if note_type in WRITE_AUTHORISED_NOTE_TYPES:
        return None
    # Name the legacy case specifically. A caller reaching for `Q` is not guessing — they are
    # copying what is already on the list — so "unknown type" would be actively misleading.
    if note_type in SURFACE_NOTE_TYPES:
        return (
            f"note type '{note_type}' is a recognised LEGACY spelling and is no longer "
            "writable — it is read-only so existing notes still classify"
        )
    return f"note type '{note_type}' is not in the registered vocabulary"


def check_contract(title: str, note_text: str) -> tuple[str, str] | None:
    """Judge a note against the per-TYPE contract the server already owns code for.

    The third tier, after shape and vocabulary. Returns ``(rejected_by, reason)`` or None.

    **Only two TYPEs are judged, and that is a scoping decision rather than a starting point.**
    A tier-3 check earns its place when the server *already holds the parser* — so the check is
    ten lines over code proven by other tests, not a second grammar to keep in step. `CHAT`
    (:func:`gtd_chat.parse_chat_title`) and `ORDER` (:func:`order_note.parse`) qualify; nothing
    else currently does. Every other registered TYPE passes untouched, by design.

    **Why this exists at all, given the gtd writers cannot produce a malformed one.** A CHAT
    title written through ``gtd_chat_post`` is *constructed*, so it is conformant by
    construction — and that is exactly the point: this gate governs the generic ``add_note`` /
    ``edit_note`` escape hatch, which is where drift enters. It retires the equivalent checks
    from gtd's ``validate-note.py``, a pre-flight a caller had to remember to run.

    **The ORDER check is body-dependent, so a title-only edit is NOT judged.** ``edit_note``
    passes an empty body on its title-changing path (a body-only edit is never gated at all —
    the legacy-safety invariant), and judging an absent body would reject every legitimate
    ORDER title correction. Same reasoning, one tier down: judge what you were actually given.
    """
    match = _TITLE_RE.match(title or "")
    if not match:
        return None  # `check_title` owns the shape verdict
    note_type = match.group("type").strip()

    if note_type == "CHAT":
        from .gtd_chat import parse_chat_title

        if parse_chat_title(title) is None:
            return (
                "chat_title",
                "a CHAT note title must be "
                "'YYYY-MM-DD HH:MM — CHAT — <me|ai> — <scope>' (the wall-clock time and "
                "the role are both required)",
            )
        return None

    if note_type == "ORDER":
        if not (note_text or "").strip():
            return None  # body-dependent — see the docstring
        from .order_note import parse as parse_order

        verdict = parse_order(title, note_text)
        if not verdict["valid"]:
            return (
                "order_contract",
                "the ORDER note does not satisfy order-note/1: " + "; ".join(verdict["errors"]),
            )
    return None


def effective_title(note_title: str, note_text: str) -> str:
    """The title the gate judges.

    ``note_title`` when supplied, else the first line of ``note_text`` — RTM stores the
    body as ``title\\ntext``, so a caller authoring the grammar inline puts it on line 1.
    """
    if (note_title or "").strip():
        return note_title
    return (note_text or "").split("\n", 1)[0]


def check_title(title: str) -> str | None:
    """Judge a note title mechanically. Returns a reason string, or None if well-formed.

    Reasons are prose (a human/model fixes the title); the machine-branchable signal is
    the envelope's ``error.code == "note_shape_rejected"``.
    """
    if not (title or "").strip():
        return "note title is empty"

    match = _TITLE_RE.match(title)
    if not match:
        return (
            "note title does not parse as "
            f"'{EXPECTED_SHAPE}' — check the date prefix and both ' — ' separators"
        )

    # A parseable prefix must be a REAL calendar date: the regex admits 2026-13-45.
    year, month, day = (int(part) for part in match.group("date").split("-"))
    try:
        date(year, month, day)
    except ValueError:
        return f"'{match.group('date')}' is not a real calendar date"

    if match.group("time"):
        hour, minute = (int(part) for part in match.group("time").split(":"))
        if hour > 23 or minute > 59:
            return f"'{match.group('time')}' is not a real wall-clock time"

    if not match.group("summary").strip():
        return "note title summary is empty"

    return None


def guided_error(title: str, reason: str, *, kind: str = "shape") -> dict[str, Any]:
    """Build the self-documenting rejection (teaches recovery, like the strict-tag gate).

    `kind` is `"shape"`, `"vocabulary"`, or a tier-3 contract verdict (`"chat_title"` /
    `"order_contract"`). It rides in `error.details`, NOT as a second `ErrorCode`:
    `note_shape_rejected` already ships, and minting a `note_vocabulary_rejected` synonym would
    recreate exactly the drift the unified registry removed in v2.0.0 — and would churn all 100
    tool fingerprints for a distinction the details already carry. The tier-3 verdicts follow
    the same ladder: a details key churns nothing.
    """
    if kind == "chat_title":
        how = (
            "The title's shape and TYPE are fine; the CHAT grammar is not satisfied. A turn "
            "is 'YYYY-MM-DD HH:MM — CHAT — <role> — <scope>' with role ∈ me | ai. Prefer "
            "gtd_chat_post, which constructs the title (and manages the drain-signal tags) "
            "for you — this check governs the generic add_note escape hatch, where a "
            "hand-typed title can drift. To disable: RTM_STRICT_NOTES=shape keeps the "
            "grammar check without the per-TYPE contracts; RTM_STRICT_NOTES=off disables all."
        )
    elif kind == "order_contract":
        how = (
            "The title parses as an ORDER note but the body fails the order-note/1 "
            "self-check, so every consumer would ignore it (the contract fails closed). The "
            "body is one strict JSON object carrying schema/order/count/sha256/source/at, "
            "and count + sha256 must agree with `order`. Prefer gtd_canvas_commit's `order` "
            "parameter, which builds and signs the note for you. To disable: "
            "RTM_STRICT_NOTES=shape keeps the grammar check without the per-TYPE contracts; "
            "RTM_STRICT_NOTES=off disables all."
        )
    elif kind == "vocabulary":
        from .note_types import WRITE_AUTHORISED_NOTE_TYPES

        how = (
            "The title's SHAPE is fine; its TYPE is not registered. Re-issue with a "
            f"registered type: {', '.join(sorted(WRITE_AUTHORISED_NOTE_TYPES))}. "
            "The canonical vocabulary is gtd's note-shape catalogue "
            "(plugins/gtd/skills/gtd/references/note-shape-catalogue.md § 2) and the server "
            "codifies it — so a genuinely new type is added THERE first (codification before "
            "validation), never minted at the call site. If none fits, take the documented out: "
            "use the closest registered type, record the intended one in the body, and raise an "
            "#improvement_candidate. Prefer gtd_note_add, which builds a conformant title for "
            "you. To disable: RTM_STRICT_NOTES=shape keeps the grammar check without the "
            "vocabulary check; RTM_STRICT_NOTES=off disables both."
        )
    else:
        how = (
            "Re-issue with a title matching "
            f"'{EXPECTED_SHAPE}' — for example "
            "'2026-07-19 — OUTPUT — brief drafted'. The date is the session's temporal "
            "anchor; separators are a spaced em-dash. Prefer gtd_note_add, which builds the "
            "title for you. The gate is ON by default: set RTM_STRICT_NOTES=warn to log "
            "without rejecting, or RTM_STRICT_NOTES=off to disable it entirely."
        )
    return build_error(
        ErrorCode.NOTE_SHAPE_REJECTED,
        f"strict_notes: write rejected — {reason}",
        rejected_title=title,
        reason=reason,
        rejected_by=kind,
        expected_shape=EXPECTED_SHAPE,
        how_to_proceed=how,
        strict_notes_mode=True,
    )


def enforce_note_shape(
    client: Any, note_title: str, note_text: str, *, tool: str
) -> dict[str, Any] | None:
    """Gate a note-title write. Returns a guided-error dict to reject, or None to allow.

    ``shape`` (the default since v5.1.0) rejects; ``warn`` logs a malformed title and
    **allows** it (the observe-before-enforce stage); ``off`` is a no-op, reproducing pre-gate
    behaviour byte-for-byte. Synchronous: unlike the strict-tag gate this needs no account
    state, so it makes no API call in any mode.

    The ``"off"`` fallback on the ``getattr`` is for a config object that lacks the attribute
    entirely (a test double, an older config): **absent is not the same as unset**, and a gate
    that fires on a config it cannot read would be enforcing on a guess.
    """
    mode = getattr(client.config, "strict_notes", "off")
    if mode not in ("warn", *_ENFORCING_MODES):
        return None

    title = effective_title(note_title, note_text)
    reason = check_title(title)
    kind = "shape"
    if reason is None:
        # Shape is fine. In `vocabulary` mode the TYPE is judged too — and only then, so that
        # `shape` reproduces v5.1.0 behaviour byte-for-byte and remains a genuine rollback step.
        if mode != "vocabulary":
            return None
        reason = check_type(title)
        if reason is None:
            # Tier 3 — the per-TYPE contract, `vocabulary` mode ONLY. Keeping it out of `shape`
            # is what preserves that mode as a byte-for-byte v5.1.0 rollback step rather than
            # something merely close to it (CONTRIBUTING § 6, asserted per gate).
            contract = check_contract(title, note_text)
            if contract is None:
                return None
            kind, reason = contract
        else:
            kind = "vocabulary"

    # WARNING, not INFO — see the v3.0.1 note in `server.configure_logging`. In `warn` mode this
    # record is the ONLY effect the gate has, so a level that needs configuration to emit made
    # the entire mode a no-op: it did not block, and its observation could not be observed.
    # Anyone who set `warn` to gather evidence before enabling `shape` collected silence and
    # would have concluded the estate was clean.
    logger.warning(
        "strict_notes(%s) %s via %s: %r — %s",
        mode,
        reason,
        tool,
        title,
        "ALLOWED (observe-before-enforce)" if mode == "warn" else "REJECTED",
    )
    if mode == "warn":
        return None

    return guided_error(title, reason, kind=kind)
