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

Modes (``config.strict_notes``): ``off`` (default — inert), ``warn`` (log only, never
rejects), ``shape`` (reject). See CONTRIBUTING § 6.
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
            "To disable the gate entirely, unset RTM_STRICT_NOTES (default: off)."
        ),
        strict_notes_mode=True,
    )


def enforce_note_shape(
    client: Any, note_title: str, note_text: str, *, tool: str
) -> dict[str, Any] | None:
    """Gate a note-title write. Returns a guided-error dict to reject, or None to allow.

    No-op (returns None) in ``off`` mode — the default, so behaviour is byte-identical to
    pre-gate unless deliberately switched on. In ``warn`` mode a malformed title is logged
    and **allowed** (the observe-before-enforce stage). Synchronous: unlike the strict-tag
    gate this needs no account state, so it makes no API call in any mode.
    """
    mode = getattr(client.config, "strict_notes", "off")
    if mode not in ("warn", "shape"):
        return None

    title = effective_title(note_title, note_text)
    reason = check_title(title)
    if reason is None:
        return None

    logger.info("strict_notes(%s) %s via %s: %r", mode, reason, tool, title)
    if mode == "warn":
        return None

    return guided_error(title, reason)
