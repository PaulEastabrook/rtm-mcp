"""Note-shape mode — the *mechanical* grammar gate for note-title writes.

The sibling of ``strict_tags.py``: a deterministic write-boundary gate that refuses a
malformed write at the server, so the discipline becomes an invariant no agent, session,
or scheduled engine can forget.

**Mechanical SHAPE only — never vocabulary.** The gate checks that a note title parses as::

    YYYY-MM-DD [HH:MM] — TYPE — summary

…a real calendar date, both em-dash separators, a well-formed non-empty TYPE token, and a
non-empty summary. It does **not** check that TYPE is a *canonical* note type — that
vocabulary lives in the gtd plugin (``references/note-shape-catalogue.md`` § 2, enforced by
``validate-note.py``) and stays plugin-side, exactly as canonical tag policing stays
plugin-side while this server gates tag *existence*. A well-shaped note carrying an
off-vocabulary TYPE passes here and is caught by the plugin validator / weekly notes-audit.

Importing a vocabulary into the server would be the drift this split exists to prevent.

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

Modes (``config.strict_notes``): ``shape`` (**the default since v5.1.0** — reject), ``warn``
(log only, never rejects), ``off`` (inert). See CONTRIBUTING § 6.

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
VALID_STRICT_NOTES_MODES = ("off", "warn", "shape")


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


def guided_error(title: str, reason: str) -> dict[str, Any]:
    """Build the self-documenting rejection (teaches recovery, like the strict-tag gate)."""
    return build_error(
        ErrorCode.NOTE_SHAPE_REJECTED,
        f"strict_notes: write rejected — {reason}",
        rejected_title=title,
        reason=reason,
        expected_shape=EXPECTED_SHAPE,
        how_to_proceed=(
            "Re-issue with a title matching "
            f"'{EXPECTED_SHAPE}' — for example "
            "'2026-07-19 — OUTPUT — brief drafted'. The date is the session's temporal "
            "anchor; separators are a spaced em-dash. This gate checks SHAPE only — the "
            "canonical TYPE vocabulary lives in the gtd note-shape catalogue "
            "(plugins/gtd/skills/gtd/references/note-shape-catalogue.md § 2), so a "
            "well-shaped title with an unknown TYPE passes here and is caught there. "
            "The gate is ON by default: set RTM_STRICT_NOTES=warn to log without "
            "rejecting, or RTM_STRICT_NOTES=off to disable it entirely."
        ),
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
    if mode not in ("warn", "shape"):
        return None

    title = effective_title(note_title, note_text)
    reason = check_title(title)
    if reason is None:
        return None

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

    return guided_error(title, reason)
