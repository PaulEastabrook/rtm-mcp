---
report_type: handback-debrief
scope: output-filing integrity — the journal-write gate, the derived OUTPUTS register, the
  reconciliation read, and the note gate's third tier (Moves 2, 3, 4, 6a, 6b)
implemented_by: Claude Code (rtm-mcp session, 2026-08-02)
derived_at: 2026-08-02
target_repo: rtm-mcp
artifact: branch `feat/output-filing-integrity`, v6.3.0 → v6.4.0 (uncommitted at time of writing —
  see Open items)
relates_to:
  - designed change `2026-08-02-output-filing-integrity.md` (approved, Paul, 2026-08-02)
  - hand-off brief "Bind the artefact to its journal note" (2026-08-02, plugin-marketplace-architect)
  - supersedes `2026-08-01-outputs-register-and-inbox-close-brief.md` § Gap A
  - sibling brief: agent-memory-mcp (Moves 1 and 5 — separate repo, not touched here)
  - predecessor: `2026-08-02-inbox-close-narrative-debrief.md` (v6.3.0)
status: needs-restart
---

# Output-filing integrity — rtm-mcp half

## What shipped

**Filing an artefact and journalling it were two unbound acts, so the second was forgettable — and
77% of the time it was forgotten.** v6.4.0 binds them: `gtd_note_attach_output` now refuses to
write an OUTPUT note whose `filing_path` does not resolve to a companion-tracked artefact in the AI
Memory vault. Alongside that, the project OUTPUTS register stops accumulating and starts being
*derived* (which repairs four measured defects as a side-effect of one change), and two read tools
land: `gtd_note_filing_gaps` reconciles RTM against the vault across six finding classes, and
`gtd_note_report` audits note shape estate-wide using the write gate's own functions. The note gate
itself gains a third tier for `CHAT` and `ORDER`.

Five of the brief's six moves are complete. **Move 6c — the four pure push-downs (`band_closure`,
`pin_feasibility`, `plan_item_defaults`, `draft_judgement`) — is deliberately not here**: the brief
scopes it as a separate slice after Moves 2–4, and folding it in would have tripled the pack.

## Design decisions & deviations

**The degrade-vs-reject split is the thing to understand before touching this code.** An unmounted
vault means the server cannot *see* the vault, not that the artefact is missing, so the gate is
inert and the write proceeds with a receipt advisory. A mounted vault with no artefact there is a
refusal. The two share no code path and are pinned by separate tests — a single fixture that omits
the vault would pass a gate that had collapsed them, which is precisely how this defect would ship.

**`resolve_vault_root` does not fall through on an explicit-but-invalid override**, so a mis-typed
`RTM_VAULT_ROOT` lands in the *degrade* branch. That is correct (an honest no-op) and is
commented at the call site so nobody "fixes" it into a rejection. It is also the only hermetic way
for a test to say "no vault" — see the gotcha below.

**A stated deviation from CONTRIBUTING § 6.** § 6 requires a *new* gate to ship default-off with
the enable decision separate. The design of record approved `reject` and Paul chose it, so the flag
and its enabled default ship together. The compensations are all present: `off` reproduces v6.3.0
byte-for-byte (asserted), `warn` is genuinely observable now the v5.1.0 file sink exists, a typo'd
mode fails loudly at config load, and the recovery guidance names its own shipped default.

**One `ErrorCode`, two verdicts.** `filing_unresolved` with `error.details.rejected_by` ∈
`artefact_missing` | `companion_missing`, following the v5.2.0 shape-vs-vocabulary precedent
exactly. A second code would be a synonym pair churning every fingerprint for a distinction the
details already carry.

**`source_action` is reported, not required, and that is sequencing rather than timidity.** Live
population is 0 of 40. Requiring it would reject 100% of legitimate calls on day one. Tighten only
after agent-memory-mcp's backfill lands *and* `gtd_note_filing_gaps` shows `join_unpopulated` at
zero — the read exists partly to make that judgeable.

**Deriving the register dissolved the migration trap rather than navigating it.** The duplicated
header line was *load-bearing*: RTM returns an empty title on read, so the old finder's second
disjunct (`extract_note_body(n).startswith("OUTPUTS:")`) was what actually matched. Writer, finder
and legacy acceptance therefore land in one commit — but because the register is now regenerated, a
wrong register is simply rebuilt rather than carefully edited.

**Two additions beyond the brief, both because the brief's plan would otherwise lose data
silently:**

1. **`register_paths()` + `output:register-row-dropped`.** A derived register carries only rows it
   can re-derive from a live OUTPUT note. A hand-typed row, or one whose note was deleted,
   disappears. That is correct for a projection — a projection that preserves unsourceable rows is
   an accumulator wearing a projection's name — but it must not be silent, so the old table is
   diffed against the derived set and the difference is reported in `not_applied[]`.
2. **The resolver falls back to the note's `created` date.** See the gotcha below; this one was
   caught by reading live data, not by reasoning.

**`prose_path` detects and does not parse.** Ten mutually incompatible dialects were counted live.
The server's job is to notice a path is being described; interpreting ten dialects is not it.

**`gtd_note_filing_gaps`, not `gtd_output_reconcile`.** An imperative verb on a read is the
`gtd_item_classify` drift `make naming --strict` exists to catch. `_gaps` is a registered
result-noun suffix (`gtd_dependency_gaps`) and outputs group under `note` per CONTRIBUTING § 2.3.
`make naming --strict` passes: 54 ok, 3 exempt, 0 unclassifiable.

## Membrane / activation

- **Vault-free in the write direction.** The companion seam stays read-only; `walk_artefacts` is an
  addition to that read, not a widening of it. Populating `source_action` is agent-memory-mcp's.
- **No new tag**, no strict-tag interaction, therefore **no activation-ordering hazard**.
- **All 102 fingerprints churn** — structural, from one new `ErrorCode` being inlined into every
  `ErrorBody.code`. Regenerated; the freshness guard passes.
- **Breaking on one tool.** `gtd_note_attach_output` gains a rejection path it did not have,
  deliberately, with `unfiled` shipping in the same release. `filing_path` becoming conditionally
  optional is a *loosening* and is non-breaking for every existing caller.
- **To go live: restart the server on v6.4.0.**
- **Rollback:** `RTM_STRICT_FILING=off` for the gate (asserted); a signature revert for the rest.
  Nothing was written to RTM by this change, so there is no data migration to reverse.

## Verification done

**Ran and green:**
- `make test` — **1957 passed** (from 1875; +82). New files: `tests/test_filing_gaps.py` (16),
  `tests/test_note_report.py` (13). Extended: `test_gtd_writes.py` 96→114,
  `test_tools/test_gtd_tools.py` 297→317, `test_note_shape.py` 56→66, `test_config.py` 34→40.
- `make lint` — `check-tool-naming.py --strict` (0 findings), `ruff check`, `ruff format --check`,
  `pyright` (0 errors).
- `make fingerprints` — regenerated, 102 tools, `source_version 6.4.0`.

**Load-bearing tests, so a reviewer knows which ones matter:**
- the gate's **zero-API-call** property on rejection (`client.call.call_count == 0`);
- **no-vault degrades AND the write lands**, driven through a real marker-less directory rather
  than a stubbed resolver — the marker check *is* the behaviour — with the reject counterfactual
  beside it, so the two branches are proven separate;
- the register's header appearing **exactly once across `note_title + note_text`** (the duplication
  lived in the concatenation, so an assertion on the body alone would have missed it);
- the emitted register title passing the server's **own** `check_title` *and* `check_type` (the
  Wave-1b `ACTIVITY-REPORT` precedent);
- `gtd_note_filing_gaps` with no vault: classes **named in `gaps[]`, counts `None` never `0`** —
  plus the counterfactual that a *mounted but empty* vault reads as genuinely clean;
- the guard-the-guards: one fixture trips all six filing classes and all five note classes, and a
  test fails if it stops doing so;
- `note_report` using the gate's functions **by object identity**.

**NOT run, explicitly:**
- **No live smoke test.** The gate, the derived register and both reads have never executed against
  the real RTM account or the real vault — the MCP server has not been restarted on v6.4.0 (and is
  in fact still behind several releases). Everything above is in-suite.
- **No RTM writes were made by this work.** The only live calls were three read-only
  `get_task_notes` and one `list_tasks`, taken to capture the register bodies.
- **The four live registers were NOT rewritten.** See Open items.
- **No behavioural evals.** gtd's `complete` and `engine` suites assert on OUTPUT notes and this
  change alters their pre-conditions; the design of record recommends folding that into the weekly
  regression rather than spending at design time, and that recommendation was followed.

## Conventions

§ 2 naming (both new tools; `--strict` passes) · § 3/§ 7 six surfaces + enriched docstrings ·
§ 3a affordance tiers (`COMBINATION_RULES`, `RECOVERY`, `CHAIN`, two reasoned
`OVER_BUDGET_EXEMPTIONS`) · § 5 additive-only `ErrorCode` · **§ 6 write gates — with the
default-off rule deviated from, and the deviation stated** · § 9 documentation lockstep (README,
`server.py` instructions, `CLAUDE.md` tree + module table + feature section + test inventory) ·
§ 10 minor bump · § 14 this debrief.

## Open items / handback

**Paul — operational:**
1. **Restart the MCP server on v6.4.0.** Note this restart is well overdue independently: the
   running server predates v6.1.0/v6.2.0/v6.3.0 too.
2. **Commit and merge** `feat/output-filing-integrity`. ⚠ The branch also carries the **uncommitted
   v6.3.0 work** it was branched from (`gtd_inbox_item_close.narrative`) — that was already
   uncommitted on `main` when this session started and has been carried along, not authored here.
   Decide whether to split it into its own commit first.
3. **Decide on the live register migration.** It was deliberately **not performed**: RTM note edits
   are not undoable, and the derived writer regenerates each register on that project's next attach
   anyway (the finder accepts the legacy form for one release, so nothing is orphaned meanwhile).
   The pre-change bodies are captured at
   `migration-capture/2026-08-02-outputs-register-pre-migration-capture.md`. If you want the
   rewrite done eagerly rather than lazily, that is a separate authorised step — and read that
   file's closing table first, because the Claude Coworking register's four rows predate the
   `FILING:` convention and are unlikely to re-derive as-is.

**Blocked on agent-memory-mcp (Moves 1 + 5):**
4. Tightening `source_action` from advisory to required. Gate it on `gtd_note_filing_gaps`
   reporting `join_unpopulated: 0`, not on elapsed time.

**claude-plugins side, after this lands:**
5. `/gtd output-reconcile` consuming `gtd_note_filing_gaps`; `agent-memory:maintain` using it in
   place of the register-drift check it cannot perform; the `notes-audit` agent repointed off
   `validate-note.py` onto `gtd_note_report`; `note-shape-catalogue.md` § 3a recording that a
   register row's Type and Status are *as at filing*, not current state.
6. **Drop `LEGACY_OUTPUTS_PREFIX` at v6.5.0.** It is a one-release compatibility window and there
   is a named constant and a docstring saying so. Left in place, it silently licenses the
   non-conformant title forever.

**Question the brief asked to put to Paul before Move 4 lands, still open:**
7. **Do you file artefacts by hand, outside any tool?** If so the gate cannot see them and
   `filed_unlinked` will report them as orphans on every run — a permanent false-positive class in
   a report whose whole value is that its findings are real. The tool's docstring carries the
   caveat, but the answer changes how you should read that class.

## Durable lesson / gotcha

**Read the live data before trusting a tie-break, even one the brief specified.** The brief named
`116751124` as Claude Coworking's register to migrate. My first `resolve_outputs_register` keyed
latest-wins on the **title date**, which sorts the undated legacy form as `""` — so it picked the
*other* note, `116750518`. Reading both live proved why that is wrong: `116750518` carries the
correct catalogue title but was abandoned 99 minutes after it was written, while `116751124`
carries the buggy title and is the one every subsequent filing updated for three weeks. Keying on
the title alone would have rebuilt into the dead register and dropped four live rows. The fix is a
fallback to the note's `created` date (not `modified` — that changes on every rebuild and would
make the ordering a function of the last run). Pinned by
`test_THE_LIVE_CLAUDE_COWORKING_PAIR_resolves_to_the_one_still_in_use`, which carries the real ids.

**Three smaller traps for the next author:**

- **`vault_root=None` does NOT mean "no vault" in a test.** `resolve_vault_root(None)` falls
  through to the host default `~/Documents/AI Memory`, which on this machine is Paul's real vault —
  so a "no vault" test silently walks it and fails confusingly. The hermetic form is an *explicit*
  marker-less directory (`_no_vault(tmp_path)`), which the resolver refuses without falling
  through. That is the same non-fallthrough property described as a feature above, used as a
  testing tool.
- **`elide()` must not rsplit when the cut lands exactly on a word boundary.** The first version
  dropped a complete final word ("the quick brown fox" → "the quick brown"), because
  `s[:limit-1].rsplit(" ", 1)[0]` cannot tell a mid-word cut from a clean one. Check the character
  at the boundary.
- **Adding `not_applied` to a result model breaks the ordering, not the schema.** The `Receipt`
  mixin already injects it via `_write_envelope_schema`; declaring it on the result class as well
  references `NotApplied` ~700 lines before its definition and raises at import.

---

*Source of truth: `CLAUDE.md` § "Output-filing integrity — the gate, the derived register, the
reconcile read (v6.4.0)", plus the module docstrings of `filing_gate.py`, `filing_gaps.py`,
`note_report.py` and `note_shape.py`. Provenance: designed change
`2026-08-02-output-filing-integrity.md` (approved 2026-08-02); measurements quoted throughout are
the 2026-08-01 reconciliation's, re-verified live only where this debrief says so.*
