---
title: Handback debrief — redaction is a client-side viewing curtain, not a server data vault
version: 1.30.0
date: 2026-07-13
from: Claude Code (rtm-mcp)
to: Cowork/GTD session (Paul)
supersedes: engage-part2-index-fields (v1.29.0) — for the redaction-of-actions behaviour only
feature-commit: d535966
---

# Handback debrief — redaction is a client-side viewing curtain, not a server data vault (v1.30.0)

## What changed, in one line

`gtd_project_index` now returns the engage-lens funnel fields (`estimate` / `contexts` /
`energy` / `exec`) for **every** action row — shielded or not. The server stopped nulling them
on redacted rows. The `redacted` flag still flows; the client does the shielding.

## The decision (why)

Redaction (`#redacted`) is a **client-side viewing curtain** — an over-the-shoulder privacy
blur — **not a server data vault** (Paul, 2026-07-13). The system was already modelled that way:
the server has always returned **names and due dates** for shielded rows, and the GTD board
client already shields the display (locked placeholder, non-selectable, excluded from the funnel,
counts never leak — there's a client test asserting a filter can't leak a hidden estimate via
count changes).

v1.29.0 introduced a **server-side nulling** of the four engage fields for redacted rows only.
That was an inconsistent over-hardening: names still flowed but the engage fields didn't, so
~176 shielded rows dropped out of the engage data entirely (they showed as empty-context rows in
the live index). v1.30.0 removes the nulling so the data flows behind the curtain like the name
and date already did.

The alternative — a true data vault that strips names/notes too — is **explicitly not wanted**;
it contradicts the established behaviour and would be a much larger change.

## The invariant (now codified, not just a one-off fix)

Added to `CLAUDE.md` (Redaction surface section): **the server SURFACES redaction and WRITES the
tag, but never ENFORCES it by suppressing data. Enforcement is 100% client-side.**

- **Allowed server-side:** derive/emit the `redacted` boolean; set/unset `#redacted` via
  `gtd_set_redaction`. (Metadata + marking mechanism.)
- **Forbidden server-side:** nulling, stripping, withholding, or dropping any field/row on
  `redacted`.

**Standing check:** `grep -rn "redact" src/` must show only flag-emission + the
`gtd_set_redaction` write — no code path suppresses a field/row on `redacted`. Verified clean at
v1.30.0 (audited every hit; the only enforcement anywhere was the `build_actions` nulling, now
removed).

## The change, concretely

- `src/rtm_mcp/project_index.py` `build_actions`: removed the `if redacted: estimate=None;
  contexts=[]; energy=None; execv=None` block — the four fields are now always computed
  (`parse_estimate_minutes` / `_contexts` / `_energy` / `_exec`). The `redacted` cascade flag
  (own tag OR redacted project OR redacted focus) is unchanged and still emitted. Docstring +
  inline comments updated to state the curtain-not-vault principle.

## Canvas-seed consistency (checked)

`gtd_project_canvas` (`canvas_seed.py`) was inspected: `map_row` computes context (`c`), comms
(`m`), and priority (`p`) for **every** action unconditionally, and `redacted` is a flag only —
**no engage/context nulling on shielded seed items**. So the canvas path was already
curtain-not-vault; **no change needed there**. The two read tools are consistent.

## Tests

- `tests/test_project_index.py`: replaced `test_shielded_action_suppresses_engage_fields` with
  two guard tests that pin the invariant — `test_shielded_action_still_carries_engage_fields`
  (shielded via a redacted-project **cascade**) and
  `test_own_tag_shielded_action_still_carries_engage_fields` (shielded via the row's **own**
  `#redacted` tag). Both assert the full engage data flows (`estimate==30`,
  `contexts==["location_home"]`, `energy=="high"`, `exec=="now"`) with `redacted: true`. These
  are the guard that stops the suppression creeping back.
- `tests/test_tools/test_gtd_tools.py::test_project_action_and_focus_redacted` was left as-is —
  it only asserts the `redacted` flag cascades, no engage suppression.
- Test count: **851** (was 850; net +1 — removed 1 suppression test, added 2 guards). `CLAUDE.md`
  inventory updated (`test_project_index.py` 72→73, total 850→851).

## Verification boundary (honest)

- `make test` equivalent (`.venv/bin/python -m pytest -q`): **851 passed**. Full suite, not just
  the touched files.
- I did **not** exercise the live tool against RTM or observe the board rendering — this is a
  pure-function behaviour change covered by unit tests, and the client is unchanged and already
  released. The live confirmation (shielded rows carrying real estimates in the index; the board
  still locking them) is Paul's to observe after the server restarts.
- Environment note: the Dropbox-hosted `.venv` was partially synced (missing `pytest/` package
  dir, then a broken `pygments` module). I recreated it fresh (`uv venv` + `uv pip install
  -e ".[dev]"`) — it now resolves Python 3.14 with pytest 9.1.1. This is a local-env artefact,
  not a repo change.

## Client side

**No change required.** The consumer is the GTD board's engage lens
(`project-plan-artifact.html`) in the marketplace repo — already released. It shields on the
`redacted` flag alone. No marketplace change is part of this work.

## Deploy note (action required)

Restart the running rtm-mcp server **through the Claude/Cowork connector** (not a bare
`kill`+relaunch — that orphans the host's managed child and throws `write EPIPE`) so the host
re-spawns v1.30.0. Until then the tool serves v1.29.0 (shielded rows still null their engage
fields).

## Acceptance (met)

- `gtd_project_index.actions[]` shielded rows now carry real `estimate` / `contexts` / `energy` /
  `exec`, same as non-shielded rows. ✓
- Canvas seed consistent (was already flag-only). ✓
- No server-side enforcement anywhere; invariant documented in `CLAUDE.md`; guard tests pin it. ✓
- `make test` green (851); version 1.30.0; debrief filed. ✓
- Server restart via the connector — **pending Paul**.
