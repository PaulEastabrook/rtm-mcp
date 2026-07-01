---
report_type: implementation-debrief
scope: Phase C cockpit — gtd_project_index project-row AI-progressible counts (ai_quick/ai_now/ai_later) — SHIPPED
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-28
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #19 (merged to main, merge commit ed22744; feature commit 621199e), rtm-mcp v1.13.0
relates_to: 2026-06-28 hand-off brief "enrich gtd_project_index project rows with AI-progressible counts"; phase-c-gtd-project-index-action-rows-debrief.md (v1.11.0/v1.12.0 action rows); gtd spec 0.9.124 (navigator sort split pill — Priority/Due/Blocked shipped, AI lens this brief)
status: server half DONE on main; gtd-side consumer (4th split-pill segment) ships in parallel and is backward-compatible — only needs the MCP server restarted on v1.13.0 to expose the counts
---

# Debrief — `gtd_project_index` project rows now carry `ai_quick` / `ai_now` / `ai_later`

Built, tested, merged: rtm-mcp **v1.13.0**, PR [#19](https://github.com/PaulEastabrook/rtm-mcp/pull/19)
→ `main` (merge `ed22744`, feature `621199e`). Merged `main` is green: **571 tests**, `make lint`
(ruff check + format + pyright) clean. Additive, read-only, vault-free.

## 1. What shipped

The navigator's per-life **sort split pill** (Priority / Due / Blocked) gets its 4th lens —
**AI-progressible** — ranking a life-context's projects by how much the progression engine can act
on now. Each `projects[]` row of `gtd_project_index` now carries three integer counts (envelope
`{projects, foci, actions}` and project selection otherwise unchanged; `actions[]` / `foci[]`
untouched):

```json
{ "...": "...", "ai_quick": 0, "ai_now": 0, "ai_later": 0 }
```

The consumer derives the sort key as `ai_quick + ai_now + ai_later` (and may later surface the three
as separate pills) — that's why three counts are returned, not one pre-summed total.

## 2. One source of truth — counts mirror the canvas by construction

`build_index` already reconstructs each project's rows (`project_plan.build_envelope`) and builds the
thin `plan_graph.build_graph` (for `blocked_count`). The three counts are a **pure tally off that
existing work**, classified with the **same functions** `gtd_project_canvas` uses, so the index and
an open plan can never disagree for the same project:

- **`ai_quick`** = rows the thin graph judges `quick_ready`. That predicate already encodes
  *action/calendar + not-done + unblocked + `#quick_win` tag*, and the canvas's `r.quick` is stamped
  from this same `quick_ready` (`canvas_overlay.apply_graph`). So `ai_quick` == the number of
  `quickReady` rows the open plan would show. Blocked quick-wins don't count (a quick win is by
  definition do-able now).
- **`ai_now`** = rows whose `canvas_seed.map_prog(tags)` is `"now"` — the durable
  `#ai_progress_requested` signal, the canvas's `r.prog === "now"`. Blocked excluded defensively
  (the engine only promotes unblocked work to "now").
- **`ai_later`** = rows whose `map_prog` is `"later"` — `#ai_progress_deferred`, the canvas's
  `r.prog === "later"`. **Not** filtered on blocked: "later" means queued-until-unblocked, so a
  blocked later still counts.

All three are **always present** (`0` when none), never absent.

## 3. Membrane & activation — no hazard

Still **one** signed `rtm.tasks.getList(status:incomplete)` plus the session-cached
`rtm.settings.getList`. No new RTM call, no write, no timeline. The counts only **read** the existing
`#quick_win` / `#ai_progress_requested` / `#ai_progress_deferred` signals (the same ones the canvas
reads) — **no tag write, no new tag, no `enforce_strict_tags` interaction, no activation-ordering
hazard**. Vault-free — the AI-Memory overlay stays gtd-side. Backward-compatible: existing consumers
ignore unknown fields; the gtd-side 4th pill segment renders only when the counts are present.

## 4. Implementation map

- **`src/rtm_mcp/project_index.py`** (only logic change): import extended to
  `from .canvas_seed import map_kind, map_prog`; `build_index` computes the three tallies off the
  `rows` + `judgement` it already has, and adds `ai_quick`/`ai_now`/`ai_later` to the row dict.
- **`src/rtm_mcp/tools/gtd.py`**: `gtd_project_index` docstring updated (projects bullet + Returns).

## 5. Versioning note for the coworker's tracking

The brief said "set this to the next minor from the current published version (e.g. v1.12.x →
v1.13.0)". The action-row enrichment had already consumed v1.11.0 (`due`/`priority`/`blocked`) and
v1.12.0 (`type`), so the as-built version for this AI-counts change is **v1.13.0**. Upstream
`ljadach/rtm-mcp` is at **v1.0.0** — this fork has diverged far beyond it (every `gtd_*` tool is
fork-only), so there is no numeric lockstep to honour; we bump the fork's own line.

## 6. Verification done

`make lint` + `make test` green on merged `main` (**571 tests**, up from 564). New coverage in
`tests/test_project_index.py::TestAIProgressCounts` (7):
- `ai_quick` counts unblocked `#quick_win` actions (and a `#quick_win` `#calendar_entry`); **excludes**
  a blocked quick-win and a `#waiting_for` quick-win (structural guard).
- `ai_now` counts `#ai_progress_requested`, **excludes** a blocked one.
- `ai_later` counts `#ai_progress_deferred` **including** a blocked one.
- zero-not-absent for a project with no AI-flagged work.
- **Canvas-seed parity guard**: builds the seed via the pure path (`build_envelope → build_seed →
  build_graph → apply_graph`) and asserts `ai_quick == #(r.quick)`, `ai_now == #(r.prog=="now")`,
  `ai_later == #(r.prog=="later")` — pins the one-source-of-truth claim.

Plus `TestShape.test_field_set` (pure) and `TestGtdProjectIndex::test_project_row_field_set` (tool,
via FakeMCP) updated to the 13-field row; the read-only call-surface assertion still holds.

A live read against the real account was **not** run — the tool isn't on the running server until it
is restarted on v1.13.0. Recommended smoke after restart: call `mcp__rtm__gtd_project_index`, pick a
project with a quick-win / progress-now / progress-later child, and confirm its `ai_quick`/`ai_now`/
`ai_later` match the quick / now / later rows shown when the same project is opened in
`gtd_project_canvas`.

## 7. Gotcha for future fixture authors (unchanged from prior debriefs)

`blocked` (and therefore `ai_quick`'s blocked-exclusion and `ai_later`'s blocked-inclusion) depends
on the `DEPENDS-ON` upstream `task_id`, extracted with a **digits-only** regex. Fixtures exercising
blocked must use **numeric** child ids — a non-numeric upstream id silently fails to resolve, so the
edge (and the blocked judgement) never forms. This bit the first draft of these tests; the blocked
fixtures use numeric ids (201/202, 301/302, 401/402).

## 8. Open items for the coworker (gtd / claude-plugins side)

1. **Restart the RTM MCP server on v1.13.0** — the one operational step that exposes the counts.
2. **Ship the 4th split-pill segment** in `project-plan-artifact.html`: append `['ai','bolt','AI']`
   to `NAVSORT_SEGS`; add `navSortAI(a,b) = (aiTotal(b) − aiTotal(a)) || navProjSort(a,b)` with
   `aiTotal(p) = (p.ai_quick||0)+(p.ai_now||0)+(p.ai_later||0)`; wire into `navProjCmp()`. Gate the
   4th segment on "any loaded project row has the counts" (backward-compatible). Decide the pill
   width trade-off (glyph-only Variant A vs widen the 234px pane) — flagged in the brief.
3. Optional follow-on: surface the three counts as a small pill on project rows / focus headers.

---
*Handback from the rtm-mcp implementation session (2026-06-28). Source of truth for the as-built
behaviour: rtm-mcp `CLAUDE.md` (§ Portfolio index — `gtd_project_index`) and the `gtd_project_index`
docstring. Predecessors: phase-c-gtd-project-index-debrief.md (v1.9.0), -foci-actions-debrief.md
(v1.10.0), -action-rows-debrief.md (v1.11.0/v1.12.0). Consumer: claude-plugins
`project-plan-artifact.html` navigator sort split pill (4th "AI" segment).*
