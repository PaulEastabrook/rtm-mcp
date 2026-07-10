---
report_type: feature-debrief
scope: rtm-mcp — extend the project_id commit carve-out to `notes` (add-project-note)
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-06
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: branch feat/project-note-carveout (off main @ f39ea28), rtm-mcp v1.26.0 → v1.27.0
relates_to: addendum brief "rtm-mcp: extend the project_id carve-out to notes (v1.27.0)" (slug rtm-mcp-project-note-carveout);
            predecessor rtm-mcp-commit-scope-project-verbs-debrief.md (v1.26.0);
            parent designed change 2026-07-05-commit-granularity-classes.md (decision 10);
            CONTRIBUTING § 14
status: needs-restart — DONE in-repo (833 tests green, lint+pyright clean); the MCP server must be
        restarted on v1.27.0 before the board ships the add-project-note control
---

# Debrief — extend the project_id commit carve-out to `notes` (v1.27.0)

## What shipped
A one-line correction to v1.26.0. The board's project-scope op set is rename / add-project-note /
complete / delete; v1.26.0 carved `project_id` out of the child-membership gate for
`edits`/`completes`/`removes` but left `notes` child-only. v1.27.0 adds `notes` to the carve-out, so
`notes[project_id] = {type, text}` is accepted — a content note ON the project (a legitimate
project-level journal entry). `execute` and `order` remain child-only.

The eligible-target set is now: **`edits`, `notes`, `completes`, `removes`** accept `project_id`;
`execute`, `order` do not. The carve-out stays `project_id`-only (arbitrary non-children rejected).

## Design decisions & deviations
- **No deviation.** Exactly the addendum's one-flag change: `_check_ids((ops.get("notes")…).keys(),
  "notes", allow_project=True)` in `canvas_commit.validate_commit`. The apply path needed **no
  change** — the notes loop already keys the write with `_ids(rid)`, and `project_id` is in `by_id`
  (it is in the fetched task set), so `_ids(project_id)` resolves the project's own triple.
- **Two notes on the project is correct.** A `scope:"project"` add-project-note commit writes the
  user's content note AND the v1.26.0 `COMMIT (project)` audit note — both on the project task. They
  are separate records; neither is coalesced or suppressed (addendum § 2). The new tool test asserts
  both titles land on `PROJECT_ID`.
- The instant/item audit-note target selection is unaffected: it already excludes `project_id` from
  the referenced-id pool, so a `notes[project_id]`-only commit at item scope still falls back to the
  project for its audit note (a non-issue in practice — the board uses `scope:"project"` here).

## Membrane / activation
- Additive + backward-compatible; **no new tag**, nothing to provision. Old callers unaffected
  (default scope `"plan"`, and `notes` on a child id behaves exactly as before).
- **To go live:** restart the MCP server on **v1.27.0** before the marketplace template ships the
  add-project-note control. Deploy order otherwise unchanged from v1.26.0.

## Verification done
- **Ran:** `uv run pytest` → **833 passed** (was 831; +2, both in `test_gtd_tools.py`). `ruff check`,
  `ruff format --check`, `pyright src` → all clean / 0 errors.
- **New/changed tests:** validator `test_project_entity_verbs_accept_project_id` now includes a
  `notes[P]` entry; `test_project_id_still_rejected_for_non_carve_ops` moved `notes` from the
  rejected set to the accepted set (execute/order stay rejected); tool test
  `test_project_note_via_notes_lands_on_project` (content note + `COMMIT (project)` audit note both on
  the project) and `test_execute_on_project_id_still_rejected`.
- **NOT run:** any live RTM smoke — no server restart, mocked `client.call` only. The live end-to-end
  (board add-project-note → note on the project) is the Cowork side's acceptance run post-restart.

## Conventions
- § 6 — no tag minted. § 9 lockstep — updated `README.md`, `server.py` instructions, `CLAUDE.md`
  (module table + commit deep-dive + § Testing counts: 831 → 833, `test_gtd_tools.py` 110 → 112).
  § 10 — minor bump 1.26.0 → 1.27.0 (`pyproject.toml` + `__init__.py` + `uv.lock`).

## Open items / handback
- **Paul / host:** merge `feat/project-note-carveout` and **restart the server on v1.27.0**; report
  the SHA to the Cowork side (the marketplace commit body cites it).
- **Cowork side — no server action beyond the restart:** `notes[project_id]` is now accepted; the
  add-project-note control can ship. **No contract divergence** — matches the addendum exactly.

## Durable lesson / gotcha
- The apply path needed no change *because* the project task is always in the commit's `getList`
  result, so `_ids(project_id)` already resolves. When extending a carve-out to a new op map, check
  whether the apply loop keys off `by_id`/`_ids` (it will just work) vs a child-only structure (it
  won't) — here it was the former.

## Footer
Source of truth: `CLAUDE.md` § "Canvas tools" (the `gtd_apply_canvas_commit` deep-dive, the
project-entity-verbs bullet) + `canvas_commit.validate_commit`. Provenance: addendum brief
rtm-mcp-project-note-carveout (2026-07-06), parent designed change
2026-07-05-commit-granularity-classes.md (decision 10), capture item RTM 1214686922.
