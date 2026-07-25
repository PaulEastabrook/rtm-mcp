"""Pure (no-IO) grammar for the CONTRIB state machine — backs `gtd_contribution_transition`.

**Canonical definition:** `references/journaling-lifecycle.md` § "The contribution state machine"
(gtd v0.186.0). This module codifies it server-side exactly as `engage_commit.py` codifies the
engage verdict grammar and `tag_report.py` the tag taxonomy — the server is standalone and cannot
read the marketplace markdown at runtime. **The markdown is the authority; a change there is a
lockstep change here.**

Six states. One open, three judged, two invalidated:

    drafted ──┬─► accepted   ┐
              ├─► edited     ├─ judged      (Paul assessed the offer)
              ├─► discarded  ┘
              ├─► superseded ┐
              └─► stale      ┘─ invalidated (never assessed)

**The judged/invalidated split is load-bearing, not decorative.** The acceptance rate is
`accepted / (accepted + edited + discarded)`. A superseded or stale contribution was never judged,
so counting it in the denominator reads as a rejection Paul never made. `engine_report` honours
this: `INVALIDATED_STATES` is excluded from every rate denominator.

**Why this module exists at all.** For the engine's whole life *nothing has ever transitioned a
contribution*. Producing agents write `State: drafted`, then promote the **artefact's** `phase` to
`offered` — so the two diverge at the instant of creation and the note is never touched again.
Live measurement 2026-07-25: 33 notes at `drafted`, 1 at `surfaced`, 6 with no `State:` line,
**zero** at any terminal state. The 0% acceptance rate `gtd_engine_report` reports is a property
of the wiring, not of the work; this is the tool that makes the metric mean something.

**Direction of truth (inverted 2026-07-25):** the note's `State:` is the system of record and the
artefact's `phase:` mirrors it — RTM is queryable, the vault is not, and the engine telemetry
reads RTM. This server is vault-free, so the transition returns the artefact path and the CALLER
mirrors `phase`; the payload says so rather than leaving it implied.
"""

from __future__ import annotations

import re
from typing import Any

from .error_codes import ErrorCode
from .parsers import extract_note_body

#: The open state — the only legal source of a transition. The note IS the offer, so there is no
#: separate "written but not yet shown" state.
OPEN_STATE = "drafted"

#: Terminal, and Paul assessed the offer. These are the acceptance-rate denominator.
JUDGED_STATES = frozenset({"accepted", "edited", "discarded"})

#: Terminal, and never assessed — replaced or overtaken. EXCLUDED from every rate.
INVALIDATED_STATES = frozenset({"superseded", "stale"})

TERMINAL_STATES = JUDGED_STATES | INVALIDATED_STATES

#: The six canonical states.
CONTRIB_STATES = frozenset({OPEN_STATE}) | TERMINAL_STATES

#: Retired values, kept only so a reader of old data knows why they are not counted.
#: `offered` — the note is the offer, never observable at this layer. `archived` — no defined
#: meaning, no consumer, never written. `surfaced` — one live instance; `phase` vocabulary leaking
#: into the note field, not a state.
RETIRED_STATES = frozenset({"offered", "archived", "surfaced"})

#: state -> kind, for the payload and for the rate arithmetic.
STATE_KIND: dict[str, str] = {
    OPEN_STATE: "open",
    **{s: "judged" for s in sorted(JUDGED_STATES)},
    **{s: "invalidated" for s in sorted(INVALIDATED_STATES)},
}

#: The `Update mode:` vocabulary of a reassessment CONTRIB-UPDATE maps onto exactly the two
#: invalidated states (`journaling-lifecycle.md` § CONTRIB-UPDATE key principles). A JUDGED
#: transition has no `Update mode:` — see `make_update_note`.
_UPDATE_MODE_FOR: dict[str, str] = {"superseded": "revision", "stale": "stale"}

#: Reject reasons, drawn from the canonical registry (CONTRIBUTING § 5 — one vocabulary).
TRANSITION_REJECT_REASONS = frozenset(
    {
        ErrorCode.OFF_ENUM.value,
        ErrorCode.INVALID_INPUT.value,
        ErrorCode.NO_CONTRIBUTION_NOTE.value,
    }
)

#: The note types that CARRY the `State:` field. A `CONTRIB-UPDATE` records a transition; it does
#: not hold the state, so it is deliberately excluded from the rewrite target.
STATE_BEARING_TYPES = frozenset({"CONTRIB", "PREP"})

_STATE_RE = re.compile(r"^([ \t]*State:[ \t]*).*$", re.IGNORECASE | re.MULTILINE)
_DRAFTED_RE = re.compile(r"^[ \t]*Drafted:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)
_CATEGORY_RE = re.compile(r"^[ \t]*Category:[ \t]*(\S+)", re.IGNORECASE | re.MULTILINE)
#: Title TYPE token. Requires WHITESPACE around the separator so a hyphenated type is not split at
#: its own hyphen (the `gtd_reads.parse_note_type` defect recorded in the v2.9.0 debrief).
_TITLE_RE = re.compile(
    r"^\s*(\d{4}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2})?\s+[—–-]\s+([A-Z][A-Z _/-]*?)\s+[—–-]\s+(.*)$"  # noqa: RUF001
)


def note_title_body(note: dict[str, Any]) -> tuple[str, str]:
    """`(title, body)` — RTM has no title field, so the title is line 1 of the stored content."""
    content = extract_note_body(note) or ""
    title, _, rest = content.partition("\n")
    return title.strip(), rest


def note_type(title: str) -> str:
    m = _TITLE_RE.match(title or "")
    return m.group(2).strip() if m else ""


def find_state_note(task: dict[str, Any]) -> dict[str, Any] | None:
    """The CONTRIB / PREP note whose `State:` line is the system of record.

    Latest by created date. `CONTRIB-UPDATE` notes are excluded on purpose — the catalogue says
    *"the original CONTRIB note's State is updated"*, so an UPDATE records a transition rather
    than holding the state.
    """
    candidates = [
        n
        for n in (task.get("notes") or [])
        if note_type(note_title_body(n)[0]) in STATE_BEARING_TYPES
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda n: str(n.get("created") or ""))


def _state_line(body: str) -> str:
    """The raw text after `State:` on the first such line, or `""`."""
    for line in (body or "").split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("state:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def current_state(body: str) -> str:
    """The `State:` value — the FIRST TOKEN only, lower-cased. `""` when there is no such line.

    First-token, not the whole line, for two reasons. It matches `engine_report`'s
    `^\\s*State:\\s*(\\S+)` so the two can never disagree about what state a note is in. And the
    live estate needs it: 3 of 39 notes carry prose after the state word — one an entire
    paragraph (*"drafted (production happened in the interactive session — see the two output
    notes of 2026-07-04 …)"*), one `drafted — pending paul's review`, one `drafted → offered`
    (the `phase` vocabulary leaking in, exactly as the catalogue records). Reading the whole line
    would make every one of those an unrecognised state.
    """
    return _state_line(body).split()[0].lower().rstrip(".,;") if _state_line(body) else ""


def state_remainder(body: str) -> str:
    """Any prose AFTER the state token on the `State:` line (`""` when clean).

    `rewrite_state` replaces the whole line, so this is handed to the CONTRIB-UPDATE note rather
    than silently discarded — the prose is somebody's annotation, and losing it on transition
    would be a quiet deletion.
    """
    raw = _state_line(body)
    parts = raw.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def artefact_path(body: str) -> str:
    """The `Drafted:` path — returned so the CALLER can mirror `phase` in the vault."""
    m = _DRAFTED_RE.search(body or "")
    return m.group(1).strip() if m else ""


def category(body: str, title: str) -> str:
    """The contribution category — body `Category:` first (the canonical carrier), else the title
    segment for a PREP note's permanent `brief` alias."""
    m = _CATEGORY_RE.search(body or "")
    if m:
        return m.group(1).strip().lower().rstrip(".,;")
    return "brief" if note_type(title) == "PREP" else "unknown"


def rewrite_state(body: str, state: str) -> str:
    """Set the `State:` line to `state`, preserving the line's original indentation.

    When the note carries no `State:` line at all — 6 of 39 live notes — one is APPENDED rather
    than the note being rejected: the absence is the old wiring's fault, not the caller's, and
    refusing would make exactly those notes permanently untransitionable.

    The WHOLE line is replaced, so a line carrying trailing prose becomes a clean machine field.
    That prose is not lost: `state_remainder` hands it to the CONTRIB-UPDATE note.
    """
    if _STATE_RE.search(body or ""):
        return _STATE_RE.sub(lambda m: f"{m.group(1)}{state}", body, count=1)
    return f"{(body or '').rstrip()}\nState: {state}".lstrip("\n")


def make_update_note(
    *,
    state: str,
    previous_state: str,
    note: str,
    category_name: str,
    original_note_id: str,
    artefact: str,
    date: str,
    superseded_text: str = "",
) -> tuple[str, str]:
    """The `CONTRIB-UPDATE` note recording the transition — `(title, text)`.

    Title follows the catalogue: `YYYY-MM-DD — CONTRIB-UPDATE — <category> — <summary>`.

    **Divergence recorded honestly:** the catalogue's CONTRIB-UPDATE *body* grammar
    (`Update mode: addendum | delta | revision | stale`, `What shifted:`, …) is scoped to the
    **reassessment** loop — its own "Created by" line says so — and its vocabulary does not
    describe a JUDGED transition. So `Update mode:` is emitted only for the two invalidated
    states, where the catalogue vocabulary genuinely maps (`superseded`→`revision`,
    `stale`→`stale`); a judged transition carries `Transition:` / `State:` instead. Extending the
    catalogue to cover judged transitions is a gtd-side follow-up.
    """
    summary = f"{previous_state or 'unset'} → {state}"
    title = f"{date} — CONTRIB-UPDATE — {category_name} — {summary}"
    lines = [
        f"Original CONTRIB: {original_note_id}",
        f"Transition: {summary}",
        f"State: {state}",
        f"Kind: {STATE_KIND.get(state, 'unknown')}",
        "Trigger: gtd_contribution_transition",
    ]
    mode = _UPDATE_MODE_FOR.get(state)
    if mode:
        lines.append(f"Update mode: {mode}")
    if artefact:
        lines.append(f"Artefact: {artefact}")
    if superseded_text:
        # Prose that was sharing the machine `State:` line, preserved rather than dropped.
        lines.append(f"Superseded State: annotation: {superseded_text}")
    body = (note or "").strip()
    if body:
        lines += ["", body]
    lines += ["", "#ai_conversation"]
    return title, "\n".join(lines)


def validate_transition(*, state: str, note_found: bool, from_state: str) -> list[dict[str, Any]]:
    """`[]` to proceed, else the rejection list. Validate-then-apply: a rejection writes nothing.

    Three rejections, each with a distinct recovery:
      * `off_enum`             — `state` is not one of the five terminal values.
      * `no_contribution_note` — the task carries no CONTRIB / PREP note; there is nothing to
                                 transition, and retrying with a different state will not help.
      * `invalid_input`        — the contribution is already terminal. Terminals are terminal.
    """
    out: list[dict[str, Any]] = []
    if state not in TERMINAL_STATES:
        out.append(
            {
                "reason": ErrorCode.OFF_ENUM.value,
                "detail": (
                    f"state must be one of {sorted(TERMINAL_STATES)} — the five terminal states. "
                    f"'{state}' is "
                    + (
                        "the OPEN state (a contribution starts there; it is not a transition "
                        "target)."
                        if state == OPEN_STATE
                        else (
                            f"RETIRED ({', '.join(sorted(RETIRED_STATES))} are no longer written)."
                            if state in RETIRED_STATES
                            else "not a contribution state."
                        )
                    )
                ),
                "state": state,
            }
        )
        return out
    if not note_found:
        out.append(
            {
                "reason": ErrorCode.NO_CONTRIBUTION_NOTE.value,
                "detail": (
                    "the task carries no CONTRIB or PREP note, so there is no contribution to "
                    "transition. Only a task the engine has produced a contribution for can be "
                    "transitioned."
                ),
            }
        )
        return out
    if from_state in TERMINAL_STATES:
        out.append(
            {
                "reason": ErrorCode.INVALID_INPUT.value,
                "detail": (
                    f"the contribution is already terminal ('{from_state}'). Terminal states are "
                    "terminal — a re-judgement means a NEW contribution, not a re-transition."
                ),
                "from_state": from_state,
            }
        )
    return out


__all__ = [
    "CONTRIB_STATES",
    "INVALIDATED_STATES",
    "JUDGED_STATES",
    "OPEN_STATE",
    "RETIRED_STATES",
    "STATE_BEARING_TYPES",
    "STATE_KIND",
    "TERMINAL_STATES",
    "TRANSITION_REJECT_REASONS",
    "artefact_path",
    "category",
    "current_state",
    "find_state_note",
    "make_update_note",
    "note_title_body",
    "note_type",
    "rewrite_state",
    "state_remainder",
    "validate_transition",
]
