---
report_type: feature-debrief
scope: rtm-mcp — repeating-templated-project Wave B, server slice 1/2 (the seed detection signal); the read-time resolver (Wave B slice 2/2) is HANDED BACK, not built here
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-05
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: feature branch feat/repeating-templated-project (stacked on feat/order-note-dc4 / the v1.19–v1.22 DC-4+MoSCoW stack), rtm-mcp v1.22.0 → v1.23.0
relates_to: handover brief "Wave B — repeating templated project (rtm-mcp + gtd, cross-repo lockstep)" (Cowork architect, 2026-07-05);
            designed change general/plugin-marketplace-architect/designed-changes/2026-07-05-repeating-templated-project.md (approved, rtm:1214733760);
            gtd v0.132.0 (Wave 1 + Wave A already landed: series_guard.py + glossary concept);
            predecessor debrief order-note-dc4-debrief.md (v1.21.0);
            CONTRIBUTING § 14 (this debrief is the required handback)
status: DONE (Wave B seed signal, slice 1/2) — needs the DC-4 stack (feat/order-note-dc4) merged first,
        then the MCP server restarted on v1.23.0. The read-time resolver (slice 2/2) is OPEN and
        owned by the marketplace side — see "Open items / handback".
---

# Debrief — repeating-templated-project seed signal (v1.23.0)

## What shipped

The `project-plan-seed` envelope now tells a consumer **whether a task's own series recurs**. Every
row and `header.project` carry two additive fields: `is_repeating` (bool — True when the task's
parent RTM taskseries has an `rrule`) and `taskseries_id` (the series id). The envelope schema bumps
to **`project-plan-seed/3.1`**. This is the detection substrate for a *repeating templated project*:
gtd's **already-shipped** `series_guard.py` (v0.132.0) reads `r.get("is_repeating")` and groups
occurrences by `taskseries_id`, but until now rtm-mcp never emitted either field — so the band-collapse
guard was silently degraded to the "≥2 open occurrences sharing a series" heuristic alone. This turns
the real per-row recurrence signal on. Read-only, additive, vault-free; no new tag.

This is **slice 1 of 2** of rtm-mcp's Wave B. Per Paul's scoping this session (2026-07-05), **only the
MCP server was changed** — the cross-repo read-time resolver (`resolve-references`) is handed back to
the marketplace side rather than defined unilaterally from the server (it is a Shared-Kernel grammar
gtd canonically owns). See the handback section.

## Design decisions & deviations

- **`is_repeating` is derived from the taskseries `rrule`, at the series level.** In
  `parse_tasks_response` a single `is_repeating = bool(ts.get("rrule"))` is computed once per
  taskseries and stamped on every task instance under it — because recurrence is a series-level fact
  (spike-confirmed: priority + notes + the rrule are series-shared; completion/due/deletion are
  per-occurrence). A one-off series has no `rrule` element → False.
- **Schema bumped to `3.1` as the brief directs — a deliberate deviation from this repo's own
  additive-without-bump precedent.** The four prior additive envelope fields (`files`, `prog`,
  `redacted`, per-note `id`) were all added while keeping the string at `project-plan-seed/3`. The
  brief (§ 5a) explicitly calls for `3.1`, and it is safe: rtm-mcp's `canvas_seed.py` has **no** schema
  gate, and gtd's `build-canvas-seed.py` accepts any `project-plan-seed/` **prefix** (verified —
  `SCHEMA_PREFIX` startswith check at line 289), so the minor is transparent to every consumer. The
  only strict `== "project-plan-seed/3"` assertions were two in-repo tests, updated to `3.1`.
- **Field names are snake_case (`is_repeating` / `taskseries_id`) on BOTH rows and `header.project`,
  even though the header's other keys are camelCase (`projectId`, `listId`).** This is intentional:
  the row contract must match gtd's `series_guard` consumer **exactly** (`r.get("is_repeating")`,
  grouping on `taskseries_id`), and using one casing for the new fields across row + header avoids a
  split-brain contract. If the gtd side later wants a camelCase header alias, that's a trivial
  additive follow-up; the row contract — the one actually consumed today — is correct now.
- **Version is v1.22.0 → v1.23.0** (additive minor per § 10). The branch stacks on the unmerged
  DC-4 + MoSCoW stack (`feat/order-note-dc4`, v1.19–v1.22, which `git rev-list` shows is 4 commits
  ahead of `origin/main`), so v1.23.0 cannot reach main until that stack merges. Same stacked-PR
  posture as DC-4.
- **The parity golden was NOT regenerated, correctly.** `is_repeating`/`taskseries_id` are seed-only
  fields; `plan_graph.build_graph` neither reads nor emits them, so `plan_graph_parity_golden.json`
  (fingerprint `fe2a0a6e201881f6`) is untouched and still passes. The golden regeneration belongs to
  slice 2 (the resolver), which *does* change the derive — see handback.

## Membrane / activation

- **Additive + backward-compatible.** A consumer that ignores the fields is unaffected; absence reads
  as not-repeating / empty series. No behaviour changes for a one-off project.
- **No new tag; no strict-tag interaction; no activation-ordering hazard.** Unlike the finalise /
  overlay-refresh marks, nothing must be provisioned account-side.
- **To go live:** merge the DC-4 stack, then restart the MCP server on **v1.23.0** (this restart
  supersedes the pending v1.21.0/v1.22.0 restarts). No board/artifact change is required to benefit —
  gtd's `series_guard` consumes the field the moment the server emits it.

## Verification done

- `make test`: **781 passed** (778 → 781; +2 `test_project_plan.py` for the row/header signals default
  + surface-from-flag, +1 `test_response_builder.py` for `is_repeating` from the taskseries `rrule`).
  `make lint`: ruff check + ruff format + pyright all clean.
- **Not run:** no live-RTM read (the `rrule`→`is_repeating` mapping is validated only against a mocked
  `getList` shape carrying `rrule: {every, $t}` — the RTM JSON form; confirm against a live recurring
  series after restart). The resolver end-to-end is **not built** (slice 2). No parity-golden change to
  verify (no derive change).

## Conventions

§ 9 documentation lockstep (CLAUDE.md architecture tree + module table + test inventory; README /
server.py reference the seed version-agnostically, so no change there), § 10 version (1.23.0 in
pyproject + `__init__` + uv.lock), § 14 this debrief. Not a new tool, so the § 12 add-a-tool checklist
does not apply; the port-lineage § 13 pattern is untouched (no engine change).

## Open items / handback

**The read-time resolver (`resolve-references`, Wave B slice 2/2) is OPEN.** It was deliberately not
built here: it defines a **Shared-Kernel note grammar that gtd owns**, and building it server-first —
then regenerating the shared parity golden unilaterally — would invert that ownership and strand the
gtd side. It should land as a **coordinated marketplace change** (gtd + agent-memory) paired with the
rtm-mcp mirror, per the brief's lockstep discipline. Concretely, still to do:

1. **Define the token-space grammar (gtd-canonical).** Recommended shape, for the marketplace side to
   ratify:
   - a per-child **`TEMPLATE-CHILD-ID` note**, body `{"schema":"tmpl-child/1","template_child_id":"<slug>"}`,
     stamped at authoring (canvas-commit path + `progression-fanout` `event: created`). Rides RTM's
     note-copy-on-recurrence (spike-confirmed) → stable across occurrences.
   - a `template_child_id: "<slug>"` line added to the **DEPENDS-ON** note (alongside the existing raw
     `task_id`), so a dep is authored in token-space going forward.
   - the **ORDER note**: the § 4/§ 5c tension ("`order-note/1` grammar unchanged" vs "schema gains a
     token-space variant") must be resolved by gtd. Cleanest: keep `order-note/1` and carry tokens in
     the `order` array for a recurring project, resolved to current ids at read; if instead a variant
     is chosen, bump the note schema note in `note-shape-catalogue.md` and mirror both sides.
2. **rtm-mcp mirror (slice 2):** in `plan_graph.py`, build a `token → current-occurrence task_id` map
   from rows' `tmpl-child/1` notes; make the `add_edge` / `clean_manual` `id_set` membership guards
   token-aware **only when a map is present** (one-off path byte-unchanged); re-point deps + the ORDER
   pin through it; disjoint-ids-without-token → short-circuit (no bias), the safe floor. The seed's
   `_extract_deps_and_files` will also need to surface the `template_child_id` dep reference.
3. **gtd enriched side:** `plan_graph_refresh.refresh` token map + resolve; `order_note.py` surface the
   token; the same guard change in gtd's `plan_graph.py`. **Do not** set `repin.needed` on the
   disjoint-without-token short-circuit.
4. **agent-memory/file-store:** `plan_graph_store.overlay_path` keyed **per occurrence** (occurrence
   discriminator alongside `project_dir`); one-off keying byte-unchanged.
5. **Parity golden (both repos, lockstep):** add a recurring-project fixture, regenerate
   `plan_graph_parity_golden.json` in **both** repos identically; both engines must resolve
   byte-identical order. Note: the current golden calls `build_graph(header, rows)` with no
   `manual_order` — to pin the resolver's dep re-pointing it can extend the existing fixture (edges are
   in the thin surface); pinning the ORDER-pin re-pointing needs a golden that passes `manual_order`,
   or a separate resolver-unit fixture.
6. **Regression fixtures (§ 6 of the brief):** (1) Weekly-Review broken-deps — fresh occurrence whose
   child notes name the prior occurrence's ids → resolver re-points via token, edges survive; (2) two
   concurrent open occurrences with divergent child structure → separate coherent overlays, no clobber.
7. **Behavioural eval:** the order-flow suite's repeating-templated-project phrase pair — offered,
   cost-stated, run on Paul's go / defer to weekly.

**Transitional divergence is accepted** (DC-4 precedent): until slice 2 lands + the server restarts,
the thin and enriched engines may resolve *recurring* projects differently. The seed signal shipped
here is safe in the meantime (it only feeds detection, not the derive).

**Consumer — no action** for slice 1 beyond the merge + restart above; gtd's `series_guard` already
reads the field.

## Durable lesson / gotcha

- **Recurrence lives on the taskseries, not the task.** RTM's `getList` puts the `rrule` on the
  `<taskseries>` element (JSON: `"rrule": {"every": "...", "$t": "FREQ=..."}`), so it must be read from
  `ts`, not the per-instance `task`, and stamped onto every instance. `bool(ts.get("rrule"))` is the
  whole test — an empty/absent rrule is a one-off.
- **The token is a note-body fact, not an RTM field.** The spike killed `external_id` (opaque to the
  read path) — the durable child identity must ride a **note body**, which the seed already emits in
  full. So slice 2 needs **no new RTM-written field** on rtm-mcp's side; the resolver reads the token
  out of the notes the seed already carries.
- **Don't define the Shared-Kernel grammar from the server.** gtd is the canonical provider for the
  plan-graph + note grammar; regenerating the shared parity golden must happen in **both** repos in one
  lockstep move, or the byte-identical guarantee silently breaks (each repo would carry a different
  golden yet both tests would pass locally).

---
*Source of truth: CLAUDE.md → "GTD domain tools & the `gtd_project_plan` envelope" (the seed 3.1 note)
+ the `project_plan.py` / `parsers.py` module docstrings. Canonical concept + invariants gtd-side in
`references/gtd-glossary.md` (repeating templated project / occurrence / template-child token /
resolve-references). Provenance: Wave B handover brief + designed change
2026-07-05-repeating-templated-project.md (approved); implemented 2026-07-05 in this session, server
slice only per Paul's scoping.*
