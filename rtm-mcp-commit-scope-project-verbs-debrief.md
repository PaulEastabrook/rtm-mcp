---
report_type: feature-debrief
scope: rtm-mcp — commit `scope` label, per-scope audit notes, project-entity verbs, redaction audit note
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-06
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: branch feat/repeating-templated-project (uncommitted at time of writing), rtm-mcp v1.25.0 → v1.26.0
relates_to: brief "Claude Code hand-off brief — rtm-mcp: commit scope, per-scope audit notes, project-entity verbs"
            (2026-07-06, slug rtm-mcp-commit-scope-project-verbs);
            parent designed change general/plugin-marketplace-architect/designed-changes/2026-07-05-commit-granularity-classes.md;
            the marketplace-side half (gtd template / ui-patterns / specs) lands separately and cross-references this SHA;
            CONTRIBUTING § 14 (this debrief is the required handback)
status: needs-restart — DONE in-repo (831 tests green, lint clean); NOT yet committed and the MCP
        server must be restarted on v1.26.0 before the board can pass `scope` or the project verbs
---

# Debrief — commit scope, per-scope audit notes, project-entity verbs (v1.26.0)

## What shipped
Four additive changes to the two governed board-write tools, all backward-compatible:

1. **`gtd_apply_canvas_commit` gains an optional `scope`** — `"instant" | "item" | "project" |
   "plan"`, default `"plan"`. It is an **audit-note placement label only**: it does not touch
   validation, the strict-tag gate, durable-first apply, or `batch_undo`. An unknown value is
   rejected up-front (`invalid_scope`) with nothing written.
2. **One audit note per successful commit, placed per scope** — `instant`/`item` → on the single
   referenced item; `project` → on the project entity, titled `COMMIT (project)`; `plan` → the bare
   `COMMIT` note on the project (unchanged). The overlay-refresh mark still always lands on the
   project.
3. **Project-entity verbs** — `project_id` itself is now an accepted target for **rename**
   (`edits[project_id].text`), **complete** (`completes`) and **delete** (`removes`, soft-delete).
   The child-membership carve-out is `project_id`-only; destructive verbs still need
   `confirm_destructive`. The server writes durable RTM state only — it does **not** fire the
   gtd-side finalise engine.
4. **`gtd_set_redaction` writes a one-line `REDACTION` audit note** on the item after the tag write
   ("curtain drawn"/"curtain lifted"), carrying **no** `#ai_conversation` marker.

Final signatures:
- `gtd_apply_canvas_commit(project_id, order?, edits?, adds?, completes?, removes?, execute?, notes?, confirm_destructive=False, scope="plan")`
- `gtd_set_redaction(task_id, redacted)` — unchanged signature; the audit note is internal.

## Design decisions & deviations
- **No deviation from the brief in substance.** The one judgement call the brief left open:
  *how to determine the item target for `instant`/`item` scope.* I collect the referenced ids across
  `edits`/`completes`/`removes`/`execute`/`notes`/`order` (excluding `project_id`), take the first;
  else a freshly-created `adds` item's triple; else the project as a defensive fallback. For a
  well-formed instant/item commit there is exactly one referenced item, so the fallbacks never fire
  in practice — they just guarantee the audit note always lands somewhere valid.
- **Audit-note titles.** `plan` keeps the exact string `"COMMIT"` (a regression test pins it);
  every other scope is `f"COMMIT ({scope})"` so a project-scope note can never be mistaken for a
  plan-wide COMMIT event (the brief's explicit requirement). Body carries the scope + op counts +
  `#ai_conversation` (unchanged convention).
- **Carve-out lives in the pure validator** (`canvas_commit.validate_commit`), gated by a new
  `allow_project` flag applied to `edits`/`completes`/`removes` only. `execute`/`notes`/`order`
  stay child-only by omission — a project is not progressed, journalled per-item, or ordered among
  its siblings. This keeps the whole carve-out unit-testable without a client.
- **Redaction note is best-effort.** It is wrapped in try/except so a note-write failure can never
  undo the durable tag write; it records its own transaction so `batch_undo` still reverts it. The
  tag-write transaction stays the response's primary `transaction_id` (a redaction test pins
  `tx_addTags`). It deliberately omits `#ai_conversation` — redaction is a user viewing-state
  change, consistent with the existing "no `#ai_conversation` stamp" rule for this tool.
- **`record_and_build_response` dropped from `gtd_set_redaction`** in favour of explicit
  `get_transaction_info` + `record_transaction` + `build_response`, because the tool now records
  **two** transactions (tag + note) in chronological order and the helper only handles one. Removed
  the now-unused import.

## Membrane / activation
- **Additive + backward-compatible.** `scope` defaults to `"plan"` → the pre-scope path is
  byte-identical, so existing non-board callers are unaffected. The board is the only caller that
  will pass `instant`/`item`/`project`.
- **No new tag anywhere.** Both audit notes are note writes, not tag writes, so there is **no
  strict-tag interaction and no activation-ordering hazard** (unlike the finalise / overlay-refresh
  marks). Nothing to provision account-side.
- **To go live:** restart the MCP server on **v1.26.0**. Until then the board's new `scope`/verb
  calls would hit the old signature. The marketplace-side template that emits the new `scope` values
  must not ship ahead of that restart.

## Verification done
- **Ran:** `uv run pytest` → **831 passed** (was 816; +15: 12 in `test_gtd_tools.py`, 3 in
  `test_canvas_commit.py`). `uv run ruff check src tests` → clean. `uv run ruff format --check` →
  clean. `uv run pyright src` → 0 errors, 0 warnings.
- **New tests cover:** default scope → bare COMMIT on project; unknown scope rejected without
  writing; instant/item note on the referenced item; project-scope note distinctly titled on the
  project; project rename via `edits[project_id].text`; project complete requires confirm; project
  delete soft; carve-out is `project_id`-only; redaction add/remove audit note without
  `#ai_conversation`; strict-tag rejection writes no audit note; plus pure-validator carve-out cases.
- **NOT run:** any live RTM smoke — no server restart, no real `getList`/note write against the
  account. Validation is in-suite only (mocked `client.call`). The live end-to-end (board sends
  `scope`/project-verb commit → note lands on the right entity → undo reverts) is the Cowork side's
  acceptance run after the restart.

## Conventions
- § 6 tag discipline — no tag minted; removal never gated (redaction remove path unchanged).
- § 9 documentation lockstep — updated all four touchpoints: `README.md` (both tool entries),
  `server.py` `instructions=` (both entries), `CLAUDE.md` (module table + the commit feature
  deep-dive + the redaction section) and the § Testing test-count inventory (816 → 831; per-file
  counts for `test_gtd_tools.py` 98 → 110 and `test_canvas_commit.py` 19 → 22).
- § 10 versioning — minor bump (new feature/param) 1.25.0 → 1.26.0 in `pyproject.toml` +
  `src/rtm_mcp/__init__.py` + `uv.lock` (via `uv lock`).

## Open items / handback
- **Paul / host:** commit the branch and **restart the MCP server on v1.26.0**. Report the commit
  **SHA** back to the Cowork side — the marketplace commit body cites it.
- **Cowork (marketplace) side — no server action:** the gtd template can now call `scope` with all
  four values and target `project_id` for rename/complete/delete. There is **no contract divergence**
  to flag: the tool matches the brief exactly (the only open-ended point, item-target selection for
  instant/item, resolves to "the single referenced item" as the brief assumed).
- **Explicitly out of scope (untouched, per the brief):** the pmgo lease / engine-fire concurrency
  change (this server has no lease logic); the finalise-engine fire on project complete (board-side
  `runScheduledTask`).

## Durable lesson / gotcha
- The audit note is written **only inside `if applied:`** — a zero-apply or rejected commit writes
  no note. That is deliberate (matches the pre-existing COMMIT-note and overlay-refresh guards) and
  is asserted by `test_zero_apply_commit_does_not_stamp_overlay_refresh`. Don't "fix" it to always
  write.
- **The carve-out must NOT extend to `execute`/`notes`/`order`.** It is tempting to allow
  `project_id` everywhere once you've added the flag; the three child-only maps stay child-only by
  design. `test_project_id_still_rejected_for_non_carve_ops` locks this.
- A project-scope **delete** followed by the audit note + overlay-refresh mark writes to a
  now-soft-deleted task; those writes may fail and are captured in `errors` (batch-resilient). This
  is accepted, not a bug — don't add special-casing.

## Footer
Source of truth: `CLAUDE.md` § "Canvas tools" (the `gtd_apply_canvas_commit` deep-dive) and
§ "Redaction surface"; the enriched docstrings on `gtd_apply_canvas_commit` / `gtd_set_redaction`
in `src/rtm_mcp/tools/gtd.py`; the pure `validate_commit` + `VALID_SCOPES` in
`src/rtm_mcp/canvas_commit.py`. Provenance: brief rtm-mcp-commit-scope-project-verbs (2026-07-06),
parent designed change 2026-07-05-commit-granularity-classes.md, capture item RTM 1214686922.
