"""The note-type vocabularies — one home, four sets, each with a different job.

**This module exists because conflating those jobs is a defect class that has already fired
twice.** On 2026-07-31 a full-estate census found (a) the server writing `ACTIVITY-REPORT` while
its own reader recognised only `ACTIVITY_REPORT`, and (b) the *registered*-canonical set here
lagging gtd's `note-shape-catalogue.md` § 2 by five types for a week. Both produced a **wrong
answer rather than an error**, which is why neither announced itself. Holding the vocabularies in
one leaf module — rather than wherever their first consumer happened to sit — is what makes a
divergence visible as a diff instead of a silent mis-classification.

The four sets, and why none of them is a subset of another by accident:

* :data:`CATALOGUE_NOTE_TYPES` — **registered canonical**. The server codification of
  `note-shape-catalogue.md` § 2. The markdown is the authority (codification before validation);
  a change there is a lockstep change here, and the gtd-side `validate-note.py` reads the markdown
  at runtime so it needs no release to follow.
* :data:`SURFACE_NOTE_TYPES` — **legacy read-recognition, deliberately NOT writable**. Spellings
  live on the AI-surface lists that predate the governed tools: single letters, `Q-*` forms, and
  `ACTIVITY_REPORT` with the underscore the title grammar forbids. A reader must know them; a
  writer must never mint another. That asymmetry is the whole point of the set.
* :data:`RESPONSE_NOTE_TYPES` — a note recording **Paul's answer** on a surface item. Read for
  `response_detected`; writable, because an agent transcribing an answer is legitimate.
* :data:`BARE_MARKER_NOTE_TYPES` — types the server emits as bare markers via `notes.add`,
  bypassing the shape gate entirely (`project_plan._extract_deps_and_files` round-trips on them).
  Present here so the same TYPE is writable when a caller *does* date-prefix it properly.

:data:`WRITE_AUTHORISED_NOTE_TYPES` is the composition the vocabulary gate consults. It is
**derived, never hand-listed** — that rule is load-bearing, because a hand-maintained fifth list
is exactly the thing this module exists to prevent.

A pure leaf: imports nothing from the package, so every consumer can take it without a cycle.
"""

from __future__ import annotations

#: Registered canonical types — the codification of `note-shape-catalogue.md` § 2.
#:
#: The five AI-surface body types (`QUESTION` / `ALERT` / `NOTIFICATION` / `SURFACE` /
#: `ACTIVITY-REPORT`) belong HERE, not in the legacy set. They were registered in the markdown on
#: 2026-07-25 but stayed in `SURFACE_NOTE_TYPES` server-side for a week under a comment asserting
#: they were unregistered — measured and corrected 2026-08-01. `SCOPE` was registered 2026-08-01
#: (§ 2a: recurring, semantically distinct, deliberate — the one legacy token promoted rather than
#: rewritten).
CATALOGUE_NOTE_TYPES = frozenset(
    {
        # journalling lifecycle
        "INCEPTION",
        "CONTEXT",
        "DECISION",
        "PROGRESS",
        "COMPLETION",
        "CASCADE",
        "SCOPE",
        "STATE",
        "SESSION",
        "BLOCKER",
        # capture provenance / analysis
        "SOURCE",
        "SOURCE-DRAFT",
        "AI ANALYSIS",
        # contributions and meetings
        "CONTRIB",
        "CONTRIB-UPDATE",
        "PREP",
        "OUTCOME",
        # artefacts and structure
        "OUTPUT",
        "OUTPUTS",
        "DEPENDS-ON",
        "AI-LINK",
        # server-written machinery
        "CHAT",
        "COMMIT",
        "ORDER",
        "STEER",
        "TMPL-CHILD",
        # AI-surface body types (registered 2026-07-25)
        "QUESTION",
        "ALERT",
        "NOTIFICATION",
        "SURFACE",
        "ACTIVITY-REPORT",
    }
)

#: Legacy spellings live on the AI-surface lists. **Read-recognition only — never writable.**
#:
#: `ACTIVITY_REPORT` (underscore) is the sharpest case: it is what pre-Wave-1b notes carry, and it
#: is *unwritable by construction* because the § 1 TYPE token is `[A-Z][A-Z -]*` with no
#: underscore. Keeping it readable while refusing to write it is precisely the asymmetry a single
#: merged vocabulary cannot express.
SURFACE_NOTE_TYPES = frozenset(
    {
        "ACTIVITY_REPORT",  # pre-Wave-1b; the shape gate rejects the underscore
        "Q",
        "A",
        "N",
        "S",
        "AR",
        "Q-BODY",
        "Q-UPDATE",
        "UPDATE",
        "META QUESTION",
    }
)

#: A note carrying one of these records Paul's answer on a surface item. `DECISION` is also a
#: catalogue journalling type, and on a surface item a decision IS the response — so the response
#: test runs first in `classify_note`.
RESPONSE_NOTE_TYPES = frozenset({"ANSWER", "RESPONSE", "REPLY", "DECISION"})

#: Types the server writes as BARE markers (no date prefix) straight through `rtm.tasks.notes.add`,
#: bypassing the shape gate. `DEPENDS-ON` and `INCEPTION` are already catalogue members; `REDACTION`
#: and `TMPL-STAMP` are not, and are named here so a properly date-prefixed one is still writable.
BARE_MARKER_NOTE_TYPES = frozenset({"DEPENDS-ON", "INCEPTION", "REDACTION", "TMPL-STAMP"})

#: Everything a reader should recognise as engine-authored rather than a human response.
SYSTEM_NOTE_TYPES = CATALOGUE_NOTE_TYPES | SURFACE_NOTE_TYPES

#: The vocabulary gate's allow-list — **derived, never hand-listed**.
#:
#: Note what is absent: :data:`SURFACE_NOTE_TYPES`. Those spellings must stay *readable* and must
#: stop being *written* — a write set that included them would license exactly the drift the gate
#: exists to stop, and would make the 2026-07-31 remediation pointless the day after it ran.
WRITE_AUTHORISED_NOTE_TYPES = CATALOGUE_NOTE_TYPES | RESPONSE_NOTE_TYPES | BARE_MARKER_NOTE_TYPES

__all__ = [
    "BARE_MARKER_NOTE_TYPES",
    "CATALOGUE_NOTE_TYPES",
    "RESPONSE_NOTE_TYPES",
    "SURFACE_NOTE_TYPES",
    "SYSTEM_NOTE_TYPES",
    "WRITE_AUTHORISED_NOTE_TYPES",
]
