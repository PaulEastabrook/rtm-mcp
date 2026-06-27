---
report_type: implementation-debrief
scope: Phase C cockpit § A — gtd_project_index portfolio read tool (server half) — SHIPPED
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-27
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #14 (merged to main, merge commit f711297; feature commit f69d4f7), rtm-mcp v1.9.0
relates_to: 2026-06-27 hand-off brief "gtd_project_index read tool (Phase C cockpit data source)"; designed-changes/2026-06-21-phase-c-cockpit.md § A
status: server half DONE; consumer (claude-plugins navigator pane) already shipped — only needs the MCP server restarted on v1.9.0 to light up
---

# Debrief — Phase C cockpit data source shipped: `gtd_project_index`

The server half is **built, tested, merged**: rtm-mcp **v1.9.0**, PR #14 → `main`
(merge commit `f711297`, feature commit `f69d4f7`). Merged `main` is green: **540 tests**, `make lint`
(ruff check + format + pyright) clean. This is the navigator's portfolio read; the gtd-side
consumer (the navigator pane in `project-plan-artifact.html`) is **already shipped and degrades
gracefully**, so nothing further is required on the gtd side except a server restart.

## 1. What shipped — the tool the navigator calls

**`gtd_project_index(include_someday: bool = False)`** — the third gtd **read** tool, sibling of
`gtd_project_plan` / `gtd_project_canvas`. Read-only: **one** `rtm.tasks.getList(status:incomplete)`
plus the session-cached timezone read; no write, no timeline. Returned wrapped the same way as the
other gtd read tools — `build_response(data=[...])` → `{data: [...], metadata: …}`, so the
artifact's `parseResult` unwraps `.data` (the navigator also accepts a bare list).

Per active project it emits:

```json
{
  "life": "work|personal|leanworking",
  "focus": "<Area-of-Focus name>",
  "focus_id": "<RTM task id of the parent focus>",
  "project": "<project name>",
  "project_id": "<RTM project task id>",
  "priority": "1|2|3|",
  "open_count": 0,
  "blocked_count": 0,
  "next_tickle": "YYYY-MM-DD|",
  "updated": "YYYY-MM-DD|"
}
```

sorted **life → focus → project**, or `[]` when there are no active projects.

## 2. Selection + counts — exactly as built (note two delegated decisions)

**Selection.** Incomplete tasks tagged `#project`, **not** `#test`. `#hold` is **always** excluded;
`#someday` is excluded unless `include_someday=True`. A project with no Area-of-Focus parent in the
fetched set is kept with `focus="(unfiled)"`, `focus_id=""` — never dropped.

**Counts are vault-free** — derived from the server's **thin** `plan_graph` over each project's rows
(the same membrane as `gtd_project_canvas` / `gtd_apply_canvas_commit`; the enriched AI-Memory
overlay stays gtd-side). `build_index` reuses the parity-pinned `project_plan.build_envelope` (so a
project's children, dates, and active `DEPENDS-ON` deps are reconstructed exactly as the canvas sees
them) and `plan_graph.build_graph` (so `blocked` is the same judgement the parity golden pins).

The brief delegated two modelling choices ("your call") — **decided as follows**:

- **`open_count` = ALL incomplete children** (actions + waiting-fors + calendar entries), not
  actions-only. The read only fetches incomplete tasks, so it is `len(rows)`.
- **`blocked_count`** = children the thin graph judges `blocked` — an open `DEPENDS-ON` upstream
  **within the project's own rows**. Cross-project / completed upstreams do **not** count (identical
  to how `gtd_project_canvas` derives blocked). `blocked_count ⊆ open_count`.
- **`next_tickle` includes overdue** — the earliest open `due` across the project's rows regardless
  of past/future (`""` when none). No clock dependency, so the result is deterministic.

`priority` is the project's raw RTM priority coerced to `"1"|"2"|"3"|""`; `next_tickle` / `updated`
are localised to the account timezone (the same BST off-by-one fix as the other gtd reads).

## 3. Consumer contract — already satisfied gtd-side (no action beyond restart)

Per the brief, the navigator is **already shipped** in claude-plugins
(`plugins/gtd/skills/gtd/references/templates/project-plan-artifact.html`): it calls
`mcp__rtm__gtd_project_index` on boot, renders the grouped life → focus → project list, re-seeds the
board on selection via the existing `gtd_project_canvas` path, and **falls back to the plain Load
input** if the tool errors. `gtd_project_index` is in the artifact `mcp_tools` whitelist (read-only).

So the only remaining step is **operational**: rebuild / restart the RTM MCP server on **v1.9.0** so
the new tool is exposed. The navigator then lights up automatically; until then it shows its Load
fallback (no breakage).

## 4. Activation — no hazard (contrast with Piece 0b)

Purely additive and **read-only**: writes nothing, gates no tags, introduces **no new tag**. Unlike
the 0b `#ai_overlay_refresh_needed` mark (which had to be provisioned in RTM before activation),
there is **no strict-tag-gate interaction and no activation-ordering hazard** here. Restart whenever
convenient.

## 5. Verification done

`make lint` + `make test` green on merged `main` (**540 tests**, up from 517). Coverage:

- **Pure** (`tests/test_project_index.py`, 20): selection (incomplete / `#project` / not-`#test`;
  `#hold` always excluded; `#someday` default-out / opt-in; completed-project excluded; empty),
  field-set shape, life-from-tag, focus / focus_id from parent (+ top-level → `(unfiled)` not
  dropped), priority mapping (1/2/3 and N→""), `updated` tz-localisation (BST), `open_count` = all
  incomplete children, `blocked_count` from a `DEPENDS-ON` edge, `next_tickle` earliest incl. overdue
  (+ empty), life → focus → project sort.
- **Wiring** (`tests/test_tools/test_gtd_tools.py::TestGtdProjectIndex`, 3): `{data:[…]}` list
  wrapper + row field-set + counts; read-only call surface (exactly one `rtm.tasks.getList`, no
  transaction); `include_someday` passthrough.

A live read against the real account was **not** run — the tool is not on the running server until
it is restarted on v1.9.0. Recommended smoke after restart: call `mcp__rtm__gtd_project_index` and
eyeball a couple of projects' `open_count` / `blocked_count` / `next_tickle` against the board.

## 6. Gotcha for future fixture authors

`DEPENDS-ON` upstream `task_id`s are extracted with a **digits-only** regex (real RTM ids are
numeric). Test fixtures that exercise `blocked_count` must use **numeric** child ids, or the edge
silently fails to resolve (a non-numeric id like `"c1"` collapses to `"1"` and misses the row set).
This bit the first draft of the tests; the fixtures now use numeric ids.

---
*Handback from the rtm-mcp implementation session (2026-06-27). Source of truth for the as-built
behaviour: rtm-mcp `CLAUDE.md` (§ Portfolio index — `gtd_project_index`) and the `gtd_project_index`
docstring. Consumer: claude-plugins `project-plan-artifact.html` navigator pane (already shipped).*
