---
report_type: implementation-debrief
scope: Phase C cockpit § A — gtd_project_index enrichment (foci list + action index) — SHIPPED
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-27
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #16 (merged to main, merge commit 9ee8fcb; feature commit f401844), rtm-mcp v1.10.0
relates_to: 2026-06-27 hand-off brief "enrich gtd_project_index with the full focus list AND an action index"; phase-c-gtd-project-index-debrief.md (v1.9.0 server half); designed-changes/2026-06-21-phase-c-cockpit.md
status: server half DONE; consumer (claude-plugins navigator pane) ships in parallel and is backward-compatible — only needs the MCP server restarted on v1.10.0 to expose the enriched response
---

# Debrief — `gtd_project_index` enriched: focus list + action index shipped (v1.10.0)

The enrichment requested in the hand-off brief is **built, tested, merged**: rtm-mcp **v1.10.0**,
PR #16 → `main` (merge commit `9ee8fcb`, feature commit `f401844`). Merged `main` is green:
**557 tests** (up from 540), `make lint` (ruff check + format + pyright) clean. The change is
**additive and backward-compatible** — the consumer navigator keeps working unchanged; the updated
navigator (shipping in parallel, gtd-side) reads the two new collections.

## 1. What changed — the response shape

`gtd_project_index(include_someday: bool = False)` now returns an **object `{projects, foci, actions}`**
instead of a bare list. All three collections come from the **same single**
`rtm.tasks.getList(status:incomplete)` the tool already ran — no extra read, no new RTM call, still
no write and no timeline. Wrapped as before: `build_response(data={...})` → `{data: {projects, foci,
actions}, metadata: …}`.

```json
{
  "projects": [ { /* …exactly the v1.9.0 per-project row, unchanged… */ } ],
  "foci":     [ { "focus_id": "<id>", "focus": "<name>", "life": "work|personal|leanworking" } ],
  "actions":  [ { "action_id": "<id>", "name": "<action>", "project_id": "<id>",
                  "project": "<name>", "focus": "<name>", "life": "<life>" } ]
}
```

- **`projects`** — identical shape and selection to v1.9.0 (the old bare list became this key). No
  behaviour change; the existing pure tests for it stay green untouched.
- **`foci`** — every active Area of Focus, sorted **life → focus**. The fix for the gap Paul spotted:
  the per-project rows can never surface a focus that has *zero* active projects (it's
  one-row-per-project), so `foci` is sourced from the `#focus` tag directly and therefore lists
  **project-less foci too** (e.g. a line-management focus for a report).
- **`actions`** — every incomplete child under an active project, sorted **life → focus → project →
  name**. The cockpit's fast-search / jump-to index across the whole portfolio.

## 2. Selection + delegated decisions — exactly as built

**`foci` selection.** Incomplete tasks tagged **`#focus`**, **not** `#test`; `#hold` always excluded,
`#someday` excluded unless `include_someday=True` — the *same* lifecycle gate as the project
portfolio, applied to areas. `life` is the focus's own first life-context tag (or `""`).

> **Contract note for the gtd side:** Areas of Focus are identified by a **`#focus` tag**. This is
> what the brief specified, and it's how `build_foci` selects. (Note `gtd_project_plan`'s
> `resolve_focus` still finds areas structurally as *parents of `#project` tasks* — that path is
> unchanged and tag-agnostic; only the new `foci` list keys off `#focus`.) If any active focus area
> in the account is **not** yet tagged `#focus`, it won't appear in `foci` until it is. Worth a
> quick audit when the navigator lights up.

**`actions` selection.** Every incomplete child under an active project (same project selection as
`build_index`), with two delegated "your call" decisions from the brief **decided as follows**:

- **Waiting-fors and calendar entries are included** (not actions-only). The cockpit search treats
  every board item as jumpable, so all incomplete children are emitted. An individual child tagged
  **`#test` is skipped**, even under an active project.
- **No dangling-project rows.** A child is only reachable via an active project, so every action row
  carries a real `project_id` / `project`. A child of a **top-level** project inherits
  `focus="(unfiled)"` (mirroring the `projects` row convention) — never dropped, never orphaned.

**Parity preserved.** `build_actions` reuses the parity-pinned `project_plan.build_envelope` for each
active project's rows, so action attribution (and any future date use) matches the canvas exactly.
Counts/foci/actions remain **vault-free** — the enriched AI-Memory overlay stays gtd-side, the same
membrane as the rest of the gtd read/write tools.

## 3. Implementation map

- **`src/rtm_mcp/project_index.py`** (pure, no IO):
  - Factored a shared **`_active(tags, completed, *, include_someday)`** lifecycle gate and a
    **`_life(tags)`** helper; `build_index` now uses them (output identical — existing tests green).
  - New **`build_foci(parsed, *, include_someday=False)`** → the `{focus_id, focus, life}` list.
  - New **`build_actions(parsed, *, include_someday=False, timezone=None)`** → the flat action index.
- **`src/rtm_mcp/tools/gtd.py`**: `gtd_project_index` assembles `{projects, foci, actions}` from the
  three builders; the enriched docstring now documents all three collections and the backward-compat
  note.

## 4. Backward compatibility — why nothing breaks in between

The brief's key constraint, honoured: the **shipped** navigator reads the project list via
`Array.isArray(d) ? d : (d.data || d.projects)` after `parseResult` unwraps `.data`. With the new
object, `parseResult` returns `{projects, foci, actions}` and the shipped navigator picks
`d.projects` — so it **keeps working unchanged**, simply ignoring `foci` / `actions`. The updated
navigator additionally reads `foci` (empty focus headers) and `actions` (search). So the server can
ship whenever; the two halves are independent.

## 5. Activation — no hazard

Purely additive and **read-only**: writes nothing, gates no tags, introduces **no new tag**. `#focus`
is *read*, never written, so there is **no strict-tag-gate interaction and no activation-ordering
hazard** (same posture as v1.9.0; contrast Piece 0b's `#ai_overlay_refresh_needed`, which had to be
provisioned first). The only remaining step is **operational: rebuild / restart the RTM MCP server on
v1.10.0** so the enriched response is exposed. Until then the tool returns the v1.9.0 bare list and
the shipped navigator behaves exactly as today.

## 6. Verification done

`make lint` + `make test` green on merged `main` (**557 tests**, +17). Coverage of the new surface:

- **Pure** (`tests/test_project_index.py`, 20 → 34):
  - `build_foci` (8): lists all `#focus` areas **including project-less ones**; field-set; life-from-
    tag; `#test`/`#hold` excluded; `#someday` gated by `include_someday`; an untagged area is *not* a
    focus; life → focus sort.
  - `build_actions` (6): incomplete children of an active project; field-set + attribution; `#test`
    child excluded; child under an excluded (`#someday`) project not emitted (+ opt-in); top-level
    project's action → `(unfiled)`; deterministic grouped sort.
  - `build_index` (20): unchanged, all still green.
- **Wiring** (`tests/test_tools/test_gtd_tools.py::TestGtdProjectIndex`, 3 → 6): `{projects, foci,
  actions}` object shape; project-row field-set + counts; `foci` includes the empty focus area;
  `actions` field-set + attribution under an active project; read-only call surface (exactly one
  `rtm.tasks.getList`, no transaction); `include_someday` passthrough.

A live read against the real account was **not** run — the tool isn't on the running server until it
is restarted on v1.10.0. Recommended smoke after restart: call `mcp__rtm__gtd_project_index` and
confirm (a) every active `#focus` area appears in `foci`, including any with no projects, and
(b) `actions` covers the board items you'd want to jump to.

## 7. Open items for the coworker (gtd / claude-plugins side)

1. **Restart the RTM MCP server on v1.10.0** — the one operational step that exposes the enriched
   response.
2. **Ship the updated navigator** (`project-plan-artifact.html`): `navFetch` captures `foci`;
   `renderNav` merges empty foci into the `life → focus → project` tree as expandable 0-count
   headers; wire `actions` into the fast-search box. Backward-compatible — if `foci` is absent,
   behaviour is exactly as today.
3. **Audit focus-area tagging**: confirm active Areas of Focus carry the `#focus` tag (see the
   contract note in § 2) so they surface in `foci`.

---
*Handback from the rtm-mcp implementation session (2026-06-27). Source of truth for the as-built
behaviour: rtm-mcp `CLAUDE.md` (§ Portfolio index — `gtd_project_index`) and the `gtd_project_index`
docstring. Predecessor: phase-c-gtd-project-index-debrief.md (v1.9.0 server half). Consumer:
claude-plugins `project-plan-artifact.html` navigator pane.*
