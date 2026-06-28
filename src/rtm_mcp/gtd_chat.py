"""Pure helpers for the GTD in-board AI conversation surface (the ``CHAT`` note class).

Pure (no IO). Backs the ``gtd_chat_post`` / ``gtd_chat_thread`` domain tools: the CHAT-note
**title grammar**, the posture **mode body-footer** round-trip, the **turn selector/parser**, and
the two **drain-signal tag** constants. Keeping the grammar parse here (no client) makes every case
unit-testable directly, matching ``project_plan.py`` / ``canvas_seed.py`` / ``canvas_commit.py``.

A CHAT turn is one RTM note on the *target task* (the project task for project-scope; the item task
for item-scope), titled::

    YYYY-MM-DD HH:MM — CHAT — <role> — <scope>

``<role>`` is ``me`` (Paul) or ``ai`` (the worker's reply); ``<scope>`` is a short display label
(the *attachment task* is the real scope). The body is the message text, optionally followed by a
``Mode: discuss|act`` footer line recording a ``me`` turn's requested posture.

The two tags — ``ai_chat_requested`` (the worker's durable work-list signal) and ``ai_chat`` (the
has-a-thread marker) — are RTM tag names (stored without ``#``). They are **provisioned
account-side**, never minted by the server: the strict-tag existence gate guards the one add path.
gtd owns the canonical CHAT grammar definition; this module mirrors it for the server side.
"""

import re
from datetime import UTC, datetime
from typing import Any

from .parsers import ensure_list, extract_note_body

# Drain-signal tags (bare RTM names — no '#'). Account-provisioned; never minted here.
AI_CHAT_REQUESTED = "ai_chat_requested"  # worker work-list signal (a me-turn awaits a reply)
AI_CHAT = "ai_chat"  # has-a-thread marker (left in place once a thread exists)

VALID_ROLES = frozenset({"me", "ai"})
VALID_MODES = frozenset({"discuss", "act"})

# Title grammar: "YYYY-MM-DD HH:MM — CHAT — <role> — <scope>" (space-em-dash-space separators).
_TITLE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) — CHAT — (me|ai) — (.*)$")
# Mode footer: a final "Mode: discuss|act" line (case-insensitive on the keyword).
_MODE_FOOTER_RE = re.compile(r"^Mode:\s*(discuss|act)\s*$", re.IGNORECASE)


def local_stamp(timezone: str | None) -> str:
    """The current 'YYYY-MM-DD HH:MM' wall-clock stamp localised to *timezone* (UTC fallback).

    Graceful like ``parsers._convert_rtm_date``: an unknown/unset zone falls back to UTC, never
    raises. This is the only clock-dependent helper here; the title format itself is pure.
    """
    tzinfo: Any = UTC
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            tzinfo = ZoneInfo(timezone)
        except Exception:
            tzinfo = UTC
    return datetime.now(tzinfo).strftime("%Y-%m-%d %H:%M")


def format_chat_title(stamp: str, role: str, scope: str) -> str:
    """Build a CHAT note title from a pre-computed local *stamp* ('YYYY-MM-DD HH:MM')."""
    return f"{stamp} — CHAT — {role} — {scope}"


def parse_chat_title(title: str) -> dict[str, str] | None:
    """Parse a CHAT note title → ``{stamp, role, scope}``; ``None`` if it is not a CHAT turn."""
    m = _TITLE_RE.match(title or "")
    if not m:
        return None
    return {"stamp": m.group(1), "role": m.group(2), "scope": m.group(3)}


def append_mode_footer(text: str, mode: str | None) -> str:
    """Append a ``Mode: <mode>`` footer line to *text* when *mode* is set (else *text* verbatim)."""
    if not mode:
        return text
    body = (text or "").rstrip("\n")
    return f"{body}\n\nMode: {mode}"


def parse_body(body: str) -> tuple[str, str | None]:
    """Split a CHAT body into ``(message_text, mode)``.

    A trailing ``Mode: discuss|act`` line (the posture footer) is stripped from the returned text
    and surfaced as *mode*; with no footer the original body is returned unchanged and *mode* is
    ``None``.
    """
    text = body or ""
    lines = text.rstrip().split("\n")
    if lines:
        m = _MODE_FOOTER_RE.match(lines[-1].strip())
        if m:
            remaining = "\n".join(lines[:-1]).rstrip()
            return remaining, m.group(1).lower()
    return text, None


def parse_turn(note: dict[str, Any]) -> dict[str, Any] | None:
    """Parse one RTM note dict into a CHAT turn, or ``None`` if it is not a CHAT note.

    Returns ``{note_id, role, scope, text, created}`` plus ``mode`` when a footer is present.
    Robust to notes authored by either ``gtd_chat_post`` or a worker's direct ``add_note`` call,
    and to both note-body shapes (``$t`` and ``body``) via ``parsers.extract_note_body``.
    """
    parsed = parse_chat_title(note.get("title") or "")
    if not parsed:
        return None
    text, mode = parse_body(extract_note_body(note))
    turn: dict[str, Any] = {
        "note_id": note.get("id"),
        "role": parsed["role"],
        "scope": parsed["scope"],
        "text": text,
        "created": note.get("created"),
    }
    if mode:
        turn["mode"] = mode
    return turn


def _after(created: str | None, since: str) -> bool:
    """True when note *created* is strictly after *since* (ISO-8601). String-compare fallback."""
    if not created:
        return False
    try:
        c = datetime.fromisoformat(created.replace("Z", "+00:00"))
        s = datetime.fromisoformat(since.replace("Z", "+00:00"))
        return c > s
    except Exception:
        return created > since


def build_thread(notes: Any, *, since: str | None = None) -> list[dict[str, Any]]:
    """Build the CHAT thread for a task: its CHAT turns oldest-first, non-CHAT notes excluded.

    *notes* is the raw note collection from a parsed task (``ensure_list``-normalised). When *since*
    is given (ISO-8601), only turns created strictly after it are returned (incremental poll).
    """
    turns: list[dict[str, Any]] = []
    for note in ensure_list(notes):
        if not isinstance(note, dict):
            continue
        turn = parse_turn(note)
        if turn is None:
            continue
        if since and not _after(turn.get("created"), since):
            continue
        turns.append(turn)
    turns.sort(key=lambda t: t.get("created") or "")
    return turns
