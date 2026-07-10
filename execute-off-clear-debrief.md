---
report_type: feature-debrief
scope: rtm-mcp — execute "off" (clear the progression directive) in gtd_apply_canvas_commit
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-10
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: branch feat/execute-off-clear (off main @ 09d34fe), feature commit 1fa05d8, rtm-mcp v1.27.0 → v1.28.0
relates_to: brief "rtm-mcp: execute off (clear the progression directive)" (slug rtm-mcp-execute-clear-op);
            parent designed change 2026-07-05-commit-granularity-classes.md (decision 2 — instant execute);
            predecessor rtm-mcp-commit-scope-project-verbs-debrief.md (v1.26.0);
            CONTRIBUTING § 14
status: needs-restart — DONE in-repo (840 tests green, ruff check + format clean); the MCP server must be
        restarted on v1.28.0 before the board ships instant execute with the off state
---

# Debrief — execute "off" (clear the progression directive) (v1.28.0)

## What shipped
`gtd_apply_canvas_commit`'s `execute` map gains a fourth value, **`"off"`** — the inverse of
`now`/`later`/`quick`. Where the set-values *write* a progression-directive tag, `"off"` **removes**
whichever are present: `#ai_progress_requested`, `#ai_progress_deferred`,
`#ai_deferred_pending_unblock`. This lets the board's execute pill (now moving to an instant control
that writes on click, `scope:"instant"`) return honestly to an **off** state.

- **Idempotent:** `"off"` on an item with no progression tags is a clean no-op — 0 writes, no error.
- **Fires no engine** — it only clears the durable directive (the board fires the engine on *set*).
- **Child-only, unchanged:** `execute` (incl. `off`) has no `project_id` carve-out; `off` on a
  non-child / the project id is `cross_project`-rejected like any other execute target.
- **No new tag minted** (removals only) — nothing to provision, no strict-tag activation hazard.

Consumer contract: `execute: {<child_id>: "now"|"later"|"quick"|"off"}`. A commit mixing `set` + `off`
across different child ids is fine (each keyed by id).

## Design decisions & deviations
- **Commit-only validity set — the one non-obvious decision.** `VALID_EXECUTE` is *imported by the
  create tool* (`canvas_create.validate_create`). Adding `"off"` to that shared frozenset would make
  `gtd_create_project` accept it too — and create's apply path calls
  `execute_progress_tags(mode)`, whose `else` branch returns `(AI_PROGRESS, …)`, so `"off"` there would
  wrongly **add** `#ai_progress_requested`. A brand-new item has nothing to clear, so I introduced
  `VALID_EXECUTE_COMMIT = VALID_EXECUTE ∪ {off}` used only by `validate_commit`; create stays on the
  set-only `VALID_EXECUTE` and correctly rejects `"off"` as `invalid_execute`. This is a deviation from
  a literal reading of "extend the execute map" but is the correct scoping — the brief itself confines
  the change to the commit tool.
- **`EXECUTE_CLEAR_TAGS` built from the constants, per the brief.** `EXECUTE_CLEAR_TAGS = (AI_PROGRESS,
  AI_PROGRESS_DEFERRED, AI_DEFERRED)` in `canvas_commit.py` — a tuple of the same constants the
  set-paths write, so `"off"` stays the precise inverse and can't drift from a hardcoded list.
- **Gate carve-out for off-only commits.** `collect_commit_tags` now gates the progression tags for
  **set-modes only** (`[v for v in execute.values() if v != "off"]`). An `off`-only commit therefore
  requires none of the progression tags to exist — only the unconditional `#ai_overlay_refresh_needed`
  mark (an `off` is a real, actionable op). Backward-compatible: a `now`/`quick`-only commit is
  unchanged.
- **Apply path (`tools/gtd.py`):** the `execute` loop branches on `mode == "off"` before
  `execute_progress_tags`, computes `present = [t for t in EXECUTE_CLEAR_TAGS if t in item.tags]`, and
  issues a single `removeTags` only when `present` is non-empty (the idempotence guard). Removal is
  never strict-gated (CONTRIBUTING § 6).

## Membrane / activation
- **Additive + backward-compatible.** No new tag, no strict-tag interaction, no ordering hazard.
- **Go-live:** restart the MCP server on **v1.28.0**. Then the Cowork/board side wires instant execute
  (now / later / off, `scope:"instant"`, "written ✓") + instant note + the disabled-while-row-dirty
  rule, completing the commit-scope board.

## Verification done
- **Ran:** `uv run pytest` — **840 passed** (was 833; +7). `ruff check` + `ruff format --check` clean on
  the four touched source/test files.
- **New tests:** `test_canvas_commit.py` (26 total) — `off` accepted as a commit value, off-only gates
  no progression tags (only the overlay-refresh mark), mixed off+set still gates the set tags, off stays
  child-only. `test_tools/test_gtd_tools.py` (115 total) — off clears the present directive tags via one
  `removeTags` with no progression `addTags`, idempotent no-op when none present, and a now→off
  round-trip leaving no directive.
- **NOT run:** no live RTM smoke against a real account (no server restart in this session), so behaviour
  is validated in-suite only. The integration tests drive the real tool through a mocked
  `client.call`, exercising the full validate→apply path.

## Conventions
- § 6 (tag discipline): closed classifier→tag mapping unchanged; `off` is removal-only → never gated.
- § 9 (doc lockstep): `README.md`, `server.py` tool doc, `CLAUDE.md` (execute values now
  `now|later|quick|off`) + § Testing counts (840; 26 / 115 per file).
- § 10 (version): minor bump 1.27.0 → 1.28.0 across `pyproject.toml` + `__init__.py` + `uv.lock`.

## Open items / handback
- **Consumer — board side owns the UI wiring** (instant execute now/later/off, `scope:"instant"`,
  written-✓ chip, disabled-while-dirty). The server half is complete.
- **Operator:** restart the MCP server on v1.28.0. Nothing to provision.
- Report the v1.28.0 feature commit **1fa05d8** (branch `feat/execute-off-clear`, not yet merged/pushed —
  raise the PR when ready).

## Durable lesson / gotcha
`VALID_EXECUTE` is shared between the commit and create validators, but `execute_progress_tags` has no
`"off"` branch (its `else` writes `AI_PROGRESS`). Any future execute value that means "clear" or
"remove" must NOT go into the shared set, or create will silently *add* a progress tag to brand-new
items. Keep clear-semantics values in `VALID_EXECUTE_COMMIT` and branch on them in the apply loop
before reaching `execute_progress_tags`.

## Footer
Source of truth: `CLAUDE.md` § "Canvas tools (gtd_project_canvas / gtd_apply_canvas_commit)" (the
now/later/off split) + the `gtd_apply_canvas_commit` docstring in `src/rtm_mcp/tools/gtd.py` and the
`VALID_EXECUTE_COMMIT` / `EXECUTE_CLEAR_TAGS` definitions in `src/rtm_mcp/canvas_commit.py`.
Provenance: brief rtm-mcp-execute-clear-op (2026-07-07, Cowork session with Paul); parent designed
change 2026-07-05-commit-granularity-classes.md decision 2.
