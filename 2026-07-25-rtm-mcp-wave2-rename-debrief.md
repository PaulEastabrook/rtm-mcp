---
report_type: handback-debrief
scope: gtd-domain-tool-suite / Wave 2 — the rename, the gtd_query split, transitional aliases
implemented_by: claude-code (rtm-mcp repo)
derived_at: 2026-07-25
target_repo: rtm-mcp
artifact: v3.0.0 — 25 renames, gtd_query split into 3, 26 deprecated surfaces, 55 GTD tools, 1594 tests
relates_to:
  - brief: Wave 2 hand-off brief, 2026-07-25
  - designed_change: general/plugin-marketplace-architect/designed-changes/2026-07-25-gtd-milkscript-retirement-designed-change.md
  - predecessor: 2026-07-25-rtm-mcp-wave1b-debrief.md
status: needs-restart
breaking: true
---

# Handback debrief — Wave 2: the rename

**25 tools renamed, `gtd_query` split into three, 55 GTD tools all conformant.** Nothing changed
behaviour: same parameters, same return shapes, same error branches. All 25 old names plus
`gtd_query` remain callable as deprecated aliases until v3.1.0, each advertising a byte-identical
schema and logging its own invocation.

**Both § 4 amendments landed as specified.** The D9 check moved into this wave as instructed and
runs clean: **52 ok, 3 exempt, 26 deprecated, 0 findings, 0 unclassifiable.**

`CHANGELOG.md` is new — a breaking release needs a discoverable migration note, and burying one in
a dated debrief is the wrong place for it. It carries the full rename table.

---

## 1. The rename map reconciled independently

Before touching anything I reconciled the brief's map against the live v2.10.0 server rather than
trusting the claim that it had been verified:

| Check | Result |
|---|---|
| every `Before` name resolves to a live tool | ✅ none missing |
| every live gtd tool accounted for | ✅ none unaccounted |
| any name in both the renamed and unchanged sets | ✅ none |
| post-rename total | 25 + 27 + 3 = **55**, as the brief states |

Also checked before substituting: **no new name collides with any old name**, and **no old name is
a prefix of another gtd name** — so a single word-boundary pass was safe. (`\bgtd_capture\b` does
not match `gtd_capture_candidates`, because `_` is a word character.)

---

## 2. The alias mechanism

FastMCP's `tool()` takes an explicit `name=`, so an alias registers **the tool's own function**
under the old name — no copied body, one implementation per tool.

**The one wrinkle worth recording: the log forced a wrapper.** The brief requires every alias
invocation to log, and makes that log *the gate* for dropping the aliases at v3.1.0 ("zero alias
hits", not elapsed time). Registering the bare function gives nowhere to log from. So an alias is
a two-line wrapper that logs and awaits the target — still delegation, not a copied
implementation, and the annotations and output schema come from the tool's own registration entry
so they cannot drift. `TestDeprecatedAliases` asserts input schema, output schema **and**
annotations are byte-identical for all 25.

**`gtd_query` is the one deprecated surface that split rather than renamed**, so it cannot alias a
single tool. It is retained as a deprecated **dispatcher** delegating to the three replacements —
still no duplicated logic.

A `_tool()` recorder now wraps every GTD registration so the alias inherits the exact annotations
and schema rather than repeating them at the alias site. Repeating them would have been two things
to keep in step, which is the defect class this programme exists to remove.

---

## 3. The D9 check — and the three defects it found in itself

Shipped as `scripts/check-tool-naming.py` (`make naming`), report-only. **Its first three runs
each found a defect in the check, not in the suite** — which is the argument for writing the
known-bad fixtures first.

**a. A false positive on the whole detector family.** The first run flagged
`gtd_capture_candidates`: `capture` is in the imperative lexicon, and the tool is read-only. But
`capture` there is the contribution *shape* being detected — a noun adjunct — and `_candidates` is
the result noun. The rule ordering was wrong: **the suffix must beat an imperative-looking segment
elsewhere in the name**. Without that fix the check fires on `gtd_decision_candidates`,
`gtd_research_candidates` and the rest of the family.

**b. The lexicon blessed the very name being renamed.** I had `zero` in `IMPERATIVE_SEGMENTS`, so
`gtd_inbox_zero` classified as a conformant command — the exact ⚠ name Wave 2 renames for reading
as a state while writing. Removed; it is now `unclassifiable`, which is the honest verdict. A test
asserts `zero` stays out.

**c. A dead branch.** `stale` was in both `RESULT_NOUNS` and `ADJECTIVE_FILTERS`, so the
adjective-filter branch never executed and the decision it exists to record was invisible. Removed
from `RESULT_NOUNS`; a test asserts it is in exactly one.

**On `gtd_item_stale` — the brief predicted it would be the first unclassifiable, and asked what I
did.** I took the recommended option: **extended the query lexicon with a documented
adjective-filter form** listing `stale`, rather than renaming a Wave 1 tool for the sake of a
suffix. It is a read, it reads as a noun phrase, and it passes the read/write test; it simply
carries no result noun. The decision is recorded in the script and pinned by a test.

**Exemptions carry stated reasons and nothing is exempt by silence** — three: `gtd_next_actions`
(the D13 ubiquitous-language exception), `gtd_waiting_for_queue`, `gtd_engage_seed` (`seed` is the
result noun there, not the verb).

**One limitation, stated plainly.** The check tests name *form* against `readOnlyHint`. It cannot
see semantics — `gtd_complete_action` classified as `ok` even though its ⚠ was that it claimed to
be action-only while handling all three item kinds. That class of defect needs a human or a
schema-vs-description check, and this is not it.

---

## 4. Deviations

**One, and it is a documented one.** The brief's § 9 says "Changelog listing all 25 renames…".
This repo has no `CHANGELOG.md` — its history lives in dated debriefs. For a *breaking* release I
judged a changelog worth creating rather than pointing at a debrief, and did so; the debriefs
remain the per-wave record. Flagging it because it adds a file the brief did not ask for by name.

**No source disagreed with the brief this time** — the map reconciled exactly, and both § 4
amendments were unambiguous. The repo's contributor guidance required no deviation.

**Historical debriefs were deliberately NOT rewritten.** Roughly 200 old-name occurrences live in
the dated `*-debrief.md` files. They record what shipped at v2.9.0 and v2.10.0 *under those names*;
substituting would make them lie about what was released. Substitution was scoped to `src/`,
`tests/`, `README.md`, `CLAUDE.md`, `CONTRIBUTING.md` — 366 replacements across 23 files.

**One substitution hazard worth knowing about**, since the marketplace session hits the same one:
prose that deliberately contrasts an old and a new name gets flattened. `CONTRIBUTING.md` § 2.3
read "`gtd_capture` → `gtd_inbox_capture`" and became "`gtd_inbox_capture` →
`gtd_inbox_capture`". My arrow-detector missed it because the arrow wrapped a line. **Read the
diff on prose files; do not trust a self-arrow regex.** Related tense damage: passages describing
what a name *misleadingly said* now describe names that no longer mislead, and needed rewriting,
not substituting.

---

## 5. Verification

**Run and passing:**

- `ruff check` + `ruff format --check` + `pyright src` — **0 errors, 0 warnings**.
- `pytest` — **1594 passed** (from 1544; +50).
- `make fingerprints` — 125 advertised surfaces at `source_version 3.0.0`; freshness guard green.
- `make naming` — 0 findings, 0 unclassifiable.
- **Live read verification** against the production account through the shipped code paths:

| Check | Result |
|---|---|
| renamed reads work live | `gtd_health_report` 222 issues · `gtd_cluster_candidates` 4 · `gtd_item_shape` → `draft` |
| alias parity on live data | byte-identical for every alias exercised |
| `gtd_query` split parity | identical on all three — 33 today, 496 next actions, 107 focus projects |

**Test design.** Per the brief's § 8, the suite is built around the silent-failure mode:
- alias parity is proven **by calling** (`TestAliasDelegation`), not by comparing schemas alone;
- the alias set is pinned at **exactly 25 plus `gtd_query`**, so one cannot be quietly added or
  forgotten, and no alias may target another alias (a chain would break at v3.1.0);
- aliases are asserted **excluded from the tool count** — 55 tools, 26 deprecated surfaces;
- the split tools are asserted to reject each other's parameters — invalid combinations are now
  unrepresentable;
- the D9 check is asserted to **FIRE** on known-bad *and* unrecognised fixtures. A conformance
  check reporting zero findings because it skipped everything is worse than none.

**NOT done — the honest boundary:**

- **No live WRITE.** The brief asks for one, and I did not perform it, because it was not
  authorised: I offered a scratch-task write at the end of Wave 1b and the answer was "merge push
  and debrief". Two things reduce the risk relative to Wave 1b, where I recorded the same gap:
  this release ships **no new write logic at all** — the renamed write tools are the *same function
  objects* under new names, with schema parity asserted and delegation proven by call. The residual
  untested path is FastMCP's dispatch of a write tool under a renamed registration, which the
  read-side live parity exercises structurally. **Say the word and I will run one against a
  `#test`-tagged scratch task and clean it up.**
- **Not called through a restarted MCP server** — the live run invoked the tools in-process.
- **No marketplace-repo work** — the 33-file consumer substitution, graph regeneration and audit
  re-run are the marketplace session's (brief § 9 step 2).

---

## 6. The dividend the brief predicted, confirmed

The brief noted that Wave 1's thin-launcher refactor should have removed the scheduled tasks from
the blast radius. **Confirmed from this side too:** no scheduled-task spec is in this repo, and
nothing in the renamed surface is reachable from one without going through the plugin skill. Work
done for progressive-disclosure reasons removed a whole category of Wave 2 risk — worth keeping as
evidence for the thin-launcher discipline.

---

## 7. Open items

**rtm-mcp:**
1. A live write exercise, if wanted (§ 5).
2. **Wave 3 (v3.1.0):** drop the 25 aliases + `gtd_query`, and promote `make naming` to `--strict`
   in CI. **The gate is the alias-invocation log showing zero hits across a full scheduled-task
   cycle**, not elapsed time. When the aliases go, also remove `GTD_QUERY_OUTPUT` from `models.py`
   and the `gtd_query` entry from `READ_ONLY_TOOLS`.
3. Still open from Wave 1: `CONTRIBUTING.md` § 7's stale `from __future__` rule (untouched again);
   `gtd_reads.parse_note_type`'s hyphenated-type split.

**Marketplace repo:** the consumer migration, and the four quiet-failure files the brief names
(`project-plan-artifact.html`, `order_note.py`, `base-live-artifact.html`, and the three `.test.js`
suites that should fail loudly).

**Consumer — no action required yet.** That is what the aliases buy.

---

## 8. Durable lesson

**Write the known-bad fixtures before the check, because the first thing a new check tests is
itself.** The D9 check found three defects on its first three runs — a false positive across an
entire tool family, a lexicon entry that blessed the exact name being renamed, and a branch that
could never execute — and *every one of them would have presented as a clean run*. A check that
passes is indistinguishable from a check that is not looking, which is the same shape as the
MilkScript guard idiom, the `Phase:`/`State:` regex, the `"N days ago"` filter, and the
byte-threshold audit. The fixtures are what tell the two apart.

The corollary for a rename specifically: **substitution is safe for code and dangerous for prose.**
Code either compiles and passes or does not. Prose that *talks about* the names — a migration
note, a rationale, a "this one misleads" caveat — is silently corrupted by the same pass that
fixes the code, and no test will ever catch it.

---

*Source of truth: `CHANGELOG.md` (the rename table and migration), `CONTRIBUTING.md` § 2 (the
standard, § 2.7 the check, § 2.8 the alias policy), `CLAUDE.md` § "Wave 2 — the rename",
`scripts/check-tool-naming.py`. Provenance: Wave 2 hand-off brief 2026-07-25; designed change
`2026-07-25-gtd-milkscript-retirement` §§ 2a–2b, 5a–5b; independent reconciliation of the rename
map against the live v2.10.0 server and live read verification of the renamed surface, both
2026-07-25.*
