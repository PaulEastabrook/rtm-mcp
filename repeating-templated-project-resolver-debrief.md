---
report_type: feature-debrief
scope: rtm-mcp — repeating-templated-project Wave B, server slice 2/2 (the read-side thin-engine resolver mirror + seed token surfacing + series parity golden)
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-05
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: feature branch feat/repeating-templated-project (stacked on the v1.19–v1.22 DC-4+MoSCoW stack), rtm-mcp v1.23.0 → v1.24.0
relates_to: handback brief "rtm-mcp — Wave B slice 2 resolver mirror" (Cowork, 2026-07-05);
            landed marketplace half — gtd v0.133.0, claude-plugins main @ 6cde8ad9d (plan_graph.py _resolve_ref + token_map, note-shape-catalogue § 5b grammar, series parity golden, test_plan_graph_series.py);
            designed change general/plugin-marketplace-architect/designed-changes/2026-07-05-repeating-templated-project.md (§ 9 status) + the ratified …-wave-b-slice2-build-spec.md;
            predecessor debrief repeating-templated-project-seed-debrief.md (v1.23.0, slice 1/2);
            CONTRIBUTING § 14 (this debrief is the required handback)
status: DONE (Wave B resolver mirror, slice 2/2) — needs the unmerged DC-4+MoSCoW stack merged first,
        then the MCP server restarted on v1.24.0 (this restart supersedes the pending v1.23.0 restart).
---

# Debrief — repeating-templated-project thin-engine resolver mirror (v1.24.0)

## What shipped

The rtm-mcp thin plan-graph engine now **resolves token-space references** for a repeating templated
project, byte-identically to the gtd enriched engine that already landed (marketplace `6cde8ad9d`). A
recurring project re-keys every occurrence's children with fresh `task_id`s, so a DEPENDS-ON dep or an
ORDER pin authored against a prior occurrence's raw id would go stale. The fix: each child carries a
**durable template-child token** (`tmpl-child/1`, a note RTM copies verbatim onto each new
occurrence); deps and pins are authored in **token-space**; the engine builds `token_map`
(`template_child_id → current occurrence id`) from the rows and `_resolve_ref` maps every reference to
the live id. A current id stays; a token maps forward; a stale-id-without-token is dropped by the
existing `id_set` membership guard (the safe floor — no bias).

Two halves, both additive and read-only:
- **`plan_graph.py`** (the derive) — mirrors the three gtd edits verbatim: `token_map` + `_resolve_ref`,
  `_resolve_ref` on the DEPENDS-ON dep edge, and on `clean_manual` (the ORDER pin).
- **`project_plan.py`** (the seed surface) — `_extract_deps_and_files` now returns a third value, the
  row's own `template_child_id` (parsed from its `tmpl-child/1` TMPL-CHILD note), and authors a dep in
  token-space when the DEPENDS-ON note carries a `Template-child-id:` line (else the raw `task_id`,
  byte-unchanged). Every row gains `template_child_id` (`""` for a one-off). This is what populates
  `token_map`.

**One-off projects are byte-unchanged** — no tokens ⇒ `token_map` empty ⇒ `_resolve_ref` is identity ⇒
every path is identical to before. The existing one-off parity golden proves it (unchanged and green);
the new series golden pins the token path.

## Design decisions & deviations

- **Mirrored the gtd reference verbatim — did not reinvent.** Per the brief's non-negotiable, the three
  `plan_graph.py` edits are the identical logic to gtd's `plan_graph.py` (`_resolve_ref` docstring and
  `token_map` comprehension copied word-for-word). The series golden was **copied byte-for-byte** from
  `plugins/gtd/skills/gtd/scripts/plan_graph_parity_golden_series.json` (verified `diff -q` →
  byte-identical), never independently regenerated — that copy *is* the cross-repo byte-identity
  guarantee. Fingerprint `938244b23cb6b228` reproduced exactly.
- **`order_note.py` untouched, as the brief directs.** The engine resolves id-or-slug transparently in
  `_resolve_ref`, so `order_note.resolve`/`from_envelope` just pass the `order` array through and the
  call site (`tools/gtd.py` `build_graph(..., manual_order=...)`) resolves. The `order-note/1` schema
  string is **unchanged**; the optional `id_space` field is informational for the writer, not read here.
- **Seed surfacing decisions (mine — the brief left the parse shape to the implementer):**
  - The row's own token is read from a note containing `tmpl-child/1` via
    `_TMPL_CHILD_RE = "template_child_id"\s*:\s*"([^"]+)"` — a body-substring match on the JSON, robust
    to the note whether authored by canvas-commit or `add_note`. First match wins (one token per child).
  - A token-space dep is detected by `_TMPL_REF_RE = Template-child-id:\s*"?([A-Za-z0-9_-]+)"?` inside
    an **active** DEPENDS-ON note; when present it **replaces** the raw `task_id` as the dep entry (not
    in addition to it) — matching gtd's authoring intent that a token-space dep is authored *as* the
    token. Without the line, the raw-`task_id` digits path is exactly as before.
  - `template_child_id` is snake_case on the row, matching the gtd engine's `r.get("template_child_id")`
    read and the seed-1 signals (`is_repeating`/`taskseries_id`) — one casing for the new fields.
- **`_extract_deps_and_files` return arity changed 2→3.** Both call sites updated (the project-level
  call discards the token as `_proj_tok`; the row call binds it). No external caller — only
  `tools/gtd.py` *mentions* the function in a comment (the create-path DEPENDS-ON round-trip), which is
  unaffected.
- **The series golden was ADDED, not a regeneration of the existing one-off golden.** They are two
  separate files (`plan_graph_parity_golden.json` one-off + `plan_graph_parity_golden_series.json`
  token path), each with its own test method. This keeps the "one-off byte-unchanged" proof explicit.
- **Version v1.23.0 → v1.24.0** (additive minor, § 10). Still stacked on the unmerged DC-4+MoSCoW stack,
  so v1.24.0 cannot reach main until that stack merges — same stacked posture as slice 1.
- **Pyright gotcha (not a design choice, worth recording):** annotating `def _resolve_ref(ref: Any) ->
  str` and then reassigning the param (`ref = str(ref)`) makes pyright keep the param's declared `Any`
  in the slot, so the return inferred as `Any | str | None`. Fixed by assigning to a fresh local
  (`key = str(ref)`) instead of reusing the param name. gtd's copy is untyped so never hit this.

## Membrane / activation

- **Additive + backward-compatible + vault-free.** A consumer ignoring `template_child_id` is
  unaffected; a one-off project reads `""` and behaves exactly as before. No new tag, no strict-tag
  interaction, no activation-ordering hazard.
- **To go live:** merge the DC-4+MoSCoW stack, then restart the MCP server on **v1.24.0** (this restart
  supersedes the pending v1.23.0 restart). No board/artifact change is required to benefit — the thin
  canvas read (`gtd_project_canvas`) and the index counts (`gtd_project_index`) both go through
  `build_graph`, so a recurring project's blocked judgement and order stop going stale the moment the
  server emits the token and resolves it.
- **Transitional divergence closes here** (for the read side): once the server restarts on v1.24.0, the
  thin engine resolves recurring projects identically to the enriched engine. The remaining divergence
  is only until authoring stamps tokens — see Open items.

## Verification done

- `make test`: **791 passed** (781 → 791: +6 `test_plan_graph.py` token-resolution cases mirroring gtd's
  `test_plan_graph_series.py`; +1 `test_plan_graph_parity.py` series-golden method; +3
  `test_project_plan.py` seed-surfacing cases — token default-empty, TMPL-CHILD surfaces token, DEPENDS-ON
  authored in token-space). The one-off `plan_graph_parity_golden.json` is **unchanged and green** (the
  one-off-neutral proof).
- `make lint`: ruff check + ruff format + pyright all clean.
- **Not run:** no live-RTM read. The resolver is validated against in-suite fixtures and the
  byte-identical golden, **not** against a live recurring project whose children actually carry
  `tmpl-child/1` notes — because **authoring that stamps those notes is gtd-side and not yet shipped**
  (§ 8 of the brief). So end-to-end, the resolver is dormant until gtd starts stamping tokens; confirm
  against a live recurring series after both that authoring lands and the server restarts. The
  cross-repo byte-identity is guaranteed by the copied golden, not re-derived here.

## Conventions

§ 9 documentation lockstep (CLAUDE.md module table for `project_plan.py` + `plan_graph.py`; test
inventory counts for `test_project_plan.py` 31→34, `test_plan_graph.py` 26→32, `test_plan_graph_parity.py`
1→2; total 781→791), § 10 version (1.24.0 in pyproject + `__init__` + uv.lock), § 13 port-lineage (the
engine stays a byte-compatible port of gtd's `plan_graph.py`), § 14 this debrief. Not a new tool, so the
§ 12 add-a-tool checklist does not apply.

## Open items / handback

**Consumer (read side) — no action** beyond the merge + restart above. The thin engine resolves the
moment tokens are present.

**Still open (deferred follow-on, NOT this session — § 8 of the brief), owned by the marketplace side:**
1. **Token stamping at authoring (gtd).** Write the `TMPL-CHILD` notes + the DEPENDS-ON
   `Template-child-id:` line at authoring (canvas-commit + `progression-fanout`), and back-fill on
   refresh for an existing recurring-project child lacking a token (idempotent). Until this lands, the
   resolver is present but has no tokens to resolve on live data — recurring-project deps stay in raw-id
   space and go stale across occurrence (the pre-Wave-B behaviour), which is the accepted transitional
   state.
2. **Per-occurrence overlay keying (agent-memory `plan_graph_store`).** Key the enriched overlay per
   occurrence so two concurrent open occurrences get separate coherent overlays; one-off keying stays
   byte-unchanged.

**Golden lockstep discipline:** the two parity goldens now exist byte-identically in both repos
(`tests/plan_graph_parity_golden.json` + `tests/plan_graph_parity_golden_series.json` here;
`plugins/gtd/skills/gtd/scripts/` there). Regenerate **only** in lockstep across both repos, or the
byte-identity guarantee silently breaks (each repo would carry a different golden yet both tests pass
locally).

## Durable lesson / gotcha

- **Mirror, don't reinvent — and prove it with a copied golden.** The whole value of the thin/enriched
  split is byte-identical resolution. The safe move is: copy the reference edits verbatim, copy the
  golden verbatim (`diff -q` to confirm), and let the test reproduce the fingerprint. If your engine
  can't reproduce the golden, the bug is in the mirror, never the golden.
- **The token is a note-body fact.** `template_child_id` rides a `tmpl-child/1` note body (RTM copies
  notes onto each occurrence — spike-confirmed), not any RTM field. The seed already carries full note
  bodies, so surfacing the token needed no new RTM read, just a parse.
- **A token-space dep replaces the raw id, it doesn't augment it.** When a DEPENDS-ON note carries
  `Template-child-id:`, the dep entry *is* the token; the raw-`task_id` fallback only fires when the
  line is absent. Getting this wrong (emitting both) would double-count the edge or leak stale ids past
  the `id_set` guard.
- **pyright + reassigned `Any` param.** Reassigning an `Any`-typed parameter keeps its declared type in
  the slot for return-type inference — assign to a fresh local instead. (rtm-mcp is typed; the gtd port
  is not, so this trap is rtm-mcp-only.)

---
*Source of truth: CLAUDE.md → module table (`project_plan.py` resolve-references token surfacing; `plan_graph.py`
resolve-references) + the `_extract_deps_and_files` / `build_graph._resolve_ref` docstrings. Canonical
grammar gtd-side in `references/note-shape-catalogue.md` § 5 + § 5b (TMPL-CHILD note + token-space
references). Provenance: Wave B slice-2 handback brief + designed change
2026-07-05-repeating-templated-project.md; landed marketplace half gtd v0.133.0 / claude-plugins
6cde8ad9d; implemented 2026-07-05 in this session, thin read-side mirror only per § 8 scoping.*
