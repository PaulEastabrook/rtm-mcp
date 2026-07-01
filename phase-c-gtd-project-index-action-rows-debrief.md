---
report_type: implementation-debrief
scope: Phase C cockpit — gtd_project_index action-row enrichment (type + due + priority + blocked) — SHIPPED
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-28
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #17 (v1.11.0 — due/priority/blocked, merge 1c549eb) + PR #18 (v1.12.0 — type, merge 6531839)
relates_to: 2026-06-27 hand-off brief "enrich gtd_project_index action rows with type/due/priority/blocked"; phase-c-gtd-project-index-foci-actions-debrief.md (v1.10.0 actions[]+foci[]); designed-changes/2026-06-21-phase-c-cockpit.md
status: server half DONE on main; gtd-side consumers (find results + What's-hot band) ship in parallel and are backward-compatible — only needs the MCP server restarted on v1.12.0 to expose the enriched rows
---

# Debrief — `gtd_project_index` action rows enriched: `type` + `due` + `priority` + `blocked`

The action-row enrichment is **built, tested, merged**. It landed in **two** PRs because the
hand-off brief was issued twice — the second revision added `type` to the same row that the first
revision's three urgency fields had just shipped on:

| Field(s) | Version | PR | Merge |
|---|---|---|---|
| `due`, `priority`, `blocked` | **v1.11.0** | [#17](https://github.com/PaulEastabrook/rtm-mcp/pull/17) | `1c549eb` |
| `type` | **v1.12.0** | [#18](https://github.com/PaulEastabrook/rtm-mcp/pull/18) | `6531839` |

Merged `main` is green: **564 tests**, `make lint` (ruff check + format + pyright) clean. The whole
change is **additive, read-only, vault-free**.

> ⚠️ **Versioning note for the coworker's tracking.** Both brief revisions were labelled
> **v1.11.0**. By the time the second (with `type`) arrived, v1.11.0 was already taken by the
> `due`/`priority`/`blocked` trio, so `type` shipped as **v1.12.0**. The current as-built version on
> `main` is **v1.12.0** and carries all four fields. If your designed-change doc still says
> "v1.11.0 adds type", that's the only drift — the behaviour is exactly as the brief specified.

## 1. What shipped — the enriched `actions[]` row

`gtd_project_index` still returns `{projects, foci, actions}` (unchanged envelope; `projects` and
`foci` untouched). Each `actions[]` row gained **four** fields over the v1.10.0
`{action_id, name, project_id, project, focus, life}` shape:

```json
{
  "action_id": "<id>", "name": "<action>", "project_id": "<id>",
  "project": "<name>", "focus": "<name>", "life": "<life>",
  "type": "action" | "waiting_for" | "calendar",   // canvas r.k classification
  "due": "YYYY-MM-DD",                              // own due/chase/calendar date, localised; "" if none
  "priority": "1" | "2" | "3" | "",                // RTM priority, same encoding as project rows
  "blocked": true | false                          // open DEPENDS-ON upstream, same thin-graph as blocked_count
}
```

sorted **life → focus → project → name**.

## 2. How each field is derived — all off work already done

`build_actions` already reconstructs each active project's rows via `project_plan.build_envelope`
and (for `blocked`) builds the thin `plan_graph.build_graph` — the same engines the per-project
counts use. So every new field is a read, not a new computation or call:

- **`type`** — `canvas_seed.map_kind(tags)`, the **exact** classification `gtd_project_canvas`
  applies for `r.k`: `#waiting_for` → `waiting_for`, `#calendar_entry` → `calendar`, otherwise
  `action`. Reusing `map_kind` (rather than re-deriving) keeps the find-result glyph in lockstep
  with the board glyph **by construction**. Controlled vocabulary — exactly those three strings.
- **`due`** — the row's own date, already localised by `build_envelope` (RTM returns UTC; the
  account-tz conversion is the same BST off-by-one fix the project `next_tickle` / canvas dates use).
  `""` when the item has no date. Overdue is a `due` earlier than today — **derived consumer-side**,
  no separate flag.
- **`priority`** — coerced to `"1"|"2"|"3"|""` via a new shared `_priority_code` helper, now used by
  **both** `build_index` and `build_actions` so the project and action encodings can't drift.
- **`blocked`** — the per-row judgement of the **same** thin plan-graph that produces each project's
  `blocked_count`: True iff the action has an open `DEPENDS-ON` upstream **within its project's own
  rows**. Cross-project / completed upstreams aren't in the fetched incomplete set, so they resolve
  to nothing → not blocked (identical rule to `blocked_count`; the two agree by construction).

## 3. Selection + membrane — unchanged

Selection is exactly v1.10.0: every incomplete child under an active project (actions, waiting-fors,
calendar entries — all jumpable), an individual child tagged `#test` skipped, every row carrying a
real project (top-level project's actions inherit `focus="(unfiled)"`). **Only fields were added.**

Still **one** signed `rtm.tasks.getList(status:incomplete)` plus the session-cached
`rtm.settings.getList` for the timezone. No new RTM call, no write, no timeline. Vault-free — the
AI-Memory overlay stays gtd-side, the same membrane as the rest of the gtd read tools.

## 4. Implementation map

- **`src/rtm_mcp/project_index.py`**:
  - `build_actions` now computes the plan-graph judgement per active project and emits `type`
    (`canvas_seed.map_kind`), `due` (off the localised row), `priority` (`_priority_code`), `blocked`.
  - New shared **`_priority_code(task)`** helper; `build_index` refactored to use it (output identical).
  - New import: `from .canvas_seed import map_kind` (canvas_seed has no internal deps → no cycle).
- **`src/rtm_mcp/tools/gtd.py`**: `gtd_project_index` docstring updated to document the four new
  action fields.

## 5. Backward compatibility & activation — no hazard

Purely additive. The shipped consumer reads only `name` + ids, so it ignores the new fields. The
parallel gtd-side consumers use them only when present:

- **Find/search results** render the per-`type` glyph (dot / clock / calendar) and, with
  `due`/`priority`, the status pills — for cross-project action results too (previously only
  open-project actions had type/date live).
- **What's-hot band** (`bandRefresh`) passes the enriched actions to askClaude alongside the
  projects to surface the hottest actions (overdue / due-today / high-priority / blocked-clearing)
  as a distinct tier. Bump `BAND_FMT` so the new shape recomputes.

No new tag, writes nothing, gates nothing → **no strict-tag-gate interaction, no activation-ordering
hazard** (same posture as v1.9.0 / v1.10.0). The only remaining step is **operational: rebuild /
restart the RTM MCP server on v1.12.0**. Until then the action rows return the v1.10.0 shape and the
consumers fall back (generic glyph, no pills, project-only band) — exactly as today.

## 6. Verification done

`make lint` + `make test` green on merged `main` (**564 tests**, up from 557). New coverage:

- **Pure** (`tests/test_project_index.py`):
  - `TestActionUrgencyFields` (7): `type` matches the canvas classification (action / waiting_for /
    calendar / default); `due` carried + localised (BST) + empty; `priority` encoding; `blocked`
    matches the plan-graph (+ False on an absent / cross-project upstream); waiting-for and calendar
    rows carry their date in `due`.
  - `TestActions::test_field_set_and_attribution` updated to the 10-field row.
- **Wiring** (`tests/test_tools/test_gtd_tools.py::TestGtdProjectIndex::test_actions_under_active_project`):
  asserts the full field-set incl. `type`/`due`/`priority`/`blocked`, that `101` is an `action` /
  unblocked upstream and `102` is `blocked`.

A live read against the real account was **not** run — the tool isn't on the running server until it
is restarted on v1.12.0. Recommended smoke after restart: call `mcp__rtm__gtd_project_index` and
confirm a waiting-for shows `type:"waiting_for"`, a calendar entry `type:"calendar"`, a blocked
action `blocked:true`, and that an action's `due` matches the board.

## 7. Gotcha for future fixture authors

`type` keys off the canvas tags: a calendar entry needs the **`#calendar_entry`** tag (not
`#calendar`) and a waiting-for the **`#waiting_for`** tag — that's what `canvas_seed.map_kind`
checks. A fixture tagged `#calendar` will classify as `action`. (The same digits-only `DEPENDS-ON`
`task_id` regex caveat from the v1.9.0 debrief still applies for `blocked` fixtures — use numeric
child ids.)

## 8. Open items for the coworker (gtd / claude-plugins side)

1. **Restart the RTM MCP server on v1.12.0** — the one operational step that exposes the four fields.
2. **Ship the find-results + What's-hot band updates** in `project-plan-artifact.html` (glyph from
   `type`, pills from `due`/`priority`, band tier from the enriched actions; bump `BAND_FMT`).
   Backward-compatible if the fields are absent.
3. **Reconcile the version label** in any designed-change / handoff doc that says "type = v1.11.0":
   the as-built is **v1.12.0** (see § 0 note).

---
*Handback from the rtm-mcp implementation session (2026-06-28). Source of truth for the as-built
behaviour: rtm-mcp `CLAUDE.md` (§ Portfolio index — `gtd_project_index`) and the `gtd_project_index`
docstring. Predecessors: phase-c-gtd-project-index-debrief.md (v1.9.0), -foci-actions-debrief.md
(v1.10.0). Consumers: claude-plugins `project-plan-artifact.html` find results + What's-hot band.*
