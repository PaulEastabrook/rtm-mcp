---
report_type: feature-debrief
scope: rtm-mcp — project-scope chat threads aggregate descendant FILING notes (files[] provenance) — board-chat enrichment stage 2b
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-04
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR TBD (feature branch feat/project-scope-chat-filings, stacked on feat/chat-turn-attachments / PR #29), rtm-mcp v1.19.0 → v1.20.0
relates_to: brief "rtm-mcp stage 2b — project-scope chat threads aggregate child FILING notes" (Cowork session 2026-07-04);
            designed change 2026-07-04-board-chat-enrichment § 2.8 (the deferred cross-child increment);
            predecessor debrief chat-turn-attachments-debrief.md (v1.19.0 — stage 2);
            CONTRIBUTING § 14 (this debrief is the required handback)
status: DONE (server half) — needs PR #29 merged first (this stacks on it), then the MCP server
        restarted on v1.20.0; acceptance test is the EM thread (rtm:1179319604) once the packs'
        OUTPUT/FILING notes are backfilled Cowork-side
---

# Debrief — project-scope chat FILING aggregation (v1.20.0)

Built and tested: rtm-mcp **v1.20.0**, branch `feat/project-scope-chat-filings` (stacked on
`feat/chat-turn-attachments`, PR #29 — v1.19.0 was still unmerged, so this is a stacked PR that
retargets to `main` automatically when #29 merges). Suite green: **736 tests** (was 722),
`make lint` (ruff check + format + pyright) clean. Read-only extension; no new tag, no strict-tag
interaction, no activation-ordering hazard.

## What shipped

When `gtd_chat_thread`'s target task carries **`#project`**, the `files[]` FILING scan now
additionally covers the project's **descendant tasks** — children and grandchildren, the same
≤3-level `parent_task_id` tree `gtd_project_plan` walks — because a project's artefacts are filed
against its child actions, not the project task itself. This is exactly the triggering case: a
project-scope "what outputs have we produced?" reply now returns artefact cards instead of
`files: []`.

- **Provenance fields (additive):** each descendant-filed entry carries `item_id`/`item_name`
  (the descendant that filed it) alongside the existing `{path, label, note_id}`.
- **Everything else unchanged:** same OUTPUT-title-gated parser, same conservative correlation
  (earliest `ai` turn created at-or-after the OUTPUT note; after the last `ai` turn → unattached),
  paths byte-verbatim (the board's dedup guarantee holds), correlation over the full thread before
  the `since` filter.
- **Completed descendants included** — a completed action's filed output is still a project output
  (the thread read has spanned completed tasks since v1.16.1; the descendant walk mirrors that).
- **Item-scope threads byte-identical to v1.19.0** — no provenance fields, same-task only
  (regression-guarded by a shape test asserting exactly three keys).
- **Same one-call read** — the broad `getList` already carries the children; call surface stays
  exactly `["rtm.tasks.getList"]`, read-only (asserted in-suite).

## Design decisions & deviations

- **The gate is the `#project` tag, not subtask presence** (per the brief) — a non-project item
  with subtasks stays same-task-only. Tested both ways.
- **New pure helper `gtd_chat.project_descendants(parsed, project_id)`** — breadth-first walk over
  a `parent_task_id` children-index, project itself excluded, deleted rows excluded (mirroring
  `project_plan.build_envelope`'s child selection), cycle-guarded via a seen-set. I did NOT reuse
  `project_plan._ancestor_chain` (it walks up, not down); the BFS is the natural inverse and lives
  in `gtd_chat.py` beside its only consumer.
- **`_attach_filings` now takes `(note, provenance)` pairs** instead of a bare note list —
  provenance `None` for the target's own notes (v1 shape), `{item_id, item_name}` for
  descendant-sourced notes. `build_thread` grew an optional `descendants=` keyword; `None`/empty
  keeps the item-scope path byte-identical (same code path, provenance never set).
- **An OUTPUT note on the project task itself keeps the plain three-field shape** even in project
  scope. The brief says provenance names "the descendant that filed it" — the project is not a
  descendant, and the board's collection-level preference rule doesn't need the fields. Tested
  explicitly (own-note entry plain, child entry in the same turn carries provenance).
- **Scan order is deterministic:** the target's own notes first, then each descendant's in
  breadth-first order — so `files[]` within a turn is stable across polls.
- **Turns still come only from the target's notes.** A descendant's own CHAT thread is a separate
  conversation; a child's CHAT note contributes nothing to the project thread (tested).
- **No fetch change was needed** (the brief's "measure before changing the fetch shape" caveat):
  `gtd_chat_thread` already reads the whole account (`status:incomplete OR status:completed`,
  no list filter), so the descendants were already in the result set.

## Membrane / activation

- Vault-free, pure RTM; **no new tag** — no strict-tag/provisioning hazard.
- Purely additive + backward-compatible: item-scope responses are byte-identical; the board
  renders `files[]` agnostically (verified Cowork-side per the brief), so the provenance fields
  are inert until a later card nicety.
- Activation: **merge PR #29 first** (this branch stacks on it), merge this, restart the local
  MCP server on v1.20.0 (supersedes the pending v1.19.0 restart — one restart covers both);
  other machines at convenience.

## Verification done

- `make test`: **736 passed** (722 → 736: +12 pure in `tests/test_gtd_chat.py`, +2 FakeMCP tool
  tests in `tests/test_tools/test_gtd_tools.py` covering the brief's matrix — child/grandchild/
  completed-child attach with provenance, after-last-ai-turn unattached, two-window discipline
  across children, item-scope regression shape, non-#project-with-subtask same-task-only,
  read-only call surface).
- `make lint`: ruff check + `ruff format --check` + pyright all clean.
- **NOT run:** a live smoke against the real RTM account (needs the server restarted on v1.20.0
  and the EM packs' OUTPUT/FILING notes backfilled, which is Cowork-side work in flight).
  Validation is in-suite only; the EM thread (rtm:1179319604) is the designated acceptance test —
  a fresh `gtd_chat_thread` on it should show four artefact cards on the ~21:00 BST 2026-07-04
  reply once both halves land.

## Conventions

§ 3 (tool pattern — read tool, no timeline), § 7 (enriched docstring), § 8 (FakeMCP + read-only
call-surface assertion), § 9 (four-touchpoint lockstep: README, server.py instructions, CLAUDE.md
feature section + test inventory), § 10 (MINOR → v1.20.0 in pyproject + `__init__` + uv.lock),
§ 14 (this debrief). § 6 not in play (no tag write).

## Open items / handback

- **rtm-mcp:** merge PR #29, then this PR; restart the local server on v1.20.0.
- **Cowork side:** backfill the EM packs' OUTPUT/FILING notes on the child actions (already in
  flight per the brief), then run the acceptance test on rtm:1179319604. **Board — no action**
  (renders `files[]` agnostically; provenance fields are available for a later card nicety).
- **Later increment (not scoped):** cross-project scope walk beyond the project subtree; using
  `item_id`/`item_name` on the artefact card UI.

## Durable lesson / gotcha

The v1.19.0 lesson compounds rather than changes: the OUTPUT-title gate stays load-bearing at
project scope — a descendant tree multiplies the volume of historic notes scanned, so an ungated
`FILING:` match would multiply the noise too. New trap for the next author: **provenance is
per-source, not per-scope** — `_attach_filings` decides field shape from the `(note, provenance)`
pair, so the project's OWN notes keep the plain shape even when descendants are scanned; don't
"simplify" by stamping provenance on everything or the item-scope byte-compat guarantee (and the
board's shape assumptions) silently changes.

---
*Source of truth: CLAUDE.md § "Conversation surface" (turn-attachments paragraph) +
`gtd_chat.build_thread` / `project_descendants` / `_attach_filings` docstrings + the
`gtd_chat_thread` tool docstring. Provenance: brief "rtm-mcp stage 2b" (Cowork session
2026-07-04), implemented on feat/project-scope-chat-filings.*
