---
report_type: handback-debrief
scope: gtd-domain-tool-suite / Wave 1 — eight additive reads + the naming standard
implemented_by: claude-code (rtm-mcp repo)
derived_at: 2026-07-25
target_repo: rtm-mcp
artifact: v2.9.0 — branch pending, 8 new tools (95 total), 1391 tests
relates_to:
  - brief: Wave 1 hand-off brief, 2026-07-25
  - designed_change: general/plugin-marketplace-architect/designed-changes/2026-07-25-gtd-milkscript-retirement-designed-change.md (approved 2026-07-25, D1–D15)
  - predecessor: 2026-07-24-rtm-mcp-phase4b-debrief.md
status: needs-restart
---

# Handback debrief — Wave 1: the MilkScript retirement

**Eight additive read tools ship on v2.9.0, and the naming standard is frozen into
`CONTRIBUTING.md` § 2 as design of record.** Nothing existing changed name or shape, nothing
writes, no new tag — so the 36 scheduled tasks are unaffected and this can ship at any hour. The
only step to go live is a server restart on v2.9.0.

All eight were **verified against Paul's live production account**, not fixtures alone. The
headline the brief asked for: `gtd_engine_report`'s 30-day window returns **12 contributions
drafted / 37 touched**, where the retired script reported **0 / 0** — and independently,
`gtd_dependency_gaps` returns **exactly 21** eligible projects, matching the Wave 0 probe done
from a completely separate code path.

---

## 1. What shipped

| Tool | Replaces | Live result (2026-07-25) |
|---|---|---|
| `gtd_surface_queue` | `ai-surface-scan-questions.ms` + `-activity.ms` | 80 questions / 56 activity rows; 7 with a response detected; 6 auto-close due; 88 missing metadata |
| `gtd_engine_report` | `engine-telemetry-aggregator.ms` | 30d: 12 drafted, 37 touched, categories + states resolved |
| `gtd_dependency_gaps` | `dependency-graph-detect.ms` | 21 eligible, 86 skipped (16 tag / 30 graphed / 40 too-few-children) |
| `gtd_tag_report` | `tag-audit.ms` | 88 account tags → 64 canonical, 13 family, 4 non-canonical active, 5 unused |
| `gtd_review_report` | `weekly-review-stats.ms` | 7d: 52 completed, 61 added, 25 overdue, inbox 142 |
| `gtd_item_stale` | `stale-items.ms` | 208 items >30d untouched |
| `gtd_workload_report` | `workload-balance.ms` | 694 classified, 117.5h estimated, 322 unclassified |
| `gtd_focus_index` | *(new capability)* | 56 areas — work 26, personal 24, leanworking 6 |

All read-only (`readOnlyHint` + `idempotentHint`), all six documentation surfaces, all named to
the new standard from birth so Wave 2's rename never touches them.

---

## 2. Two defect classes the sweep did not find

The brief named three faults in `engine-telemetry-aggregator.ms`. Building against live data
found **two more**, each independently sufficient to zero the same figures.

**A. `Phase:` is not the field — `State:` is.** The `.ms` matches `/Phase:\s*(\w+)/`. The
canonical CONTRIB body field is **`State:`** (`journaling-lifecycle.md` § "CONTRIB Notes — The
Canonical Form"); `phase` is the *artefact frontmatter* field, which lives in the vault, not RTM.
Measured live: **`State:` appears on 33 of 39 contribution notes; `Phase:` on zero.** The regex
could never have matched anything.

**B. Note accessors are wrong too, and survived the 2026-07-24 correctness pass.** The `.ms`
still reads `notes[j].getTitle()` / `.getBody()` behind the guard idiom. A Note has neither —
only `getContent()`. So both were `""` on every note and category/state resolved to `"unknown"`
for every contribution. The 2026-07-24 pass fixed the *task* accessors and left these untouched.

**Net: `gtd_engine_report`'s predecessor had four independent paths to a 0% acceptance rate.**
That is why `monitor-outcomes-weekly` and `-monthly` have been raising adaptation proposals from
telemetry that was structurally zero — not stale numbers, no numbers, presented as findings.

**C. And a fifth, in a different substrate entirely.** `weekly-review-stats.ms` reported **zero
completions and zero additions, always** — not a MilkScript fault but an **RTM filter** one.
`completedAfter:` / `addedAfter:` are real operators, but RTM does not parse the relative phrase
`"N days ago"` for them. Measured:

| Filter | Rows |
|---|---|
| `completedAfter:"7 days ago"` | **0** |
| `completedWithin:"7 days of today"` | **53** |
| `completedAfter:07/18/2026` | 73 |
| `addedAfter:"7 days ago"` | **0** |
| `addedWithin:"7 days of today"` | 91 |

The query matched nothing and the report presented it as a finding. `gtd_review_report` uses the
verified `completedWithin:` form, and derives additions client-side from each task's own
`created` timestamp — no unverified operator on the trust path at all. A test asserts the tool
never emits `completedAfter` / `addedAfter`.

---

## 3. Design decisions & deviations from the brief

### 3.1 `response_detected` is INCLUSION-based — the brief specified exclusion

**This is the one substantive deviation, and it is load-bearing.** The brief (§ 3a) specified
detection by *exclusion* against `note-shape-catalogue.md` § 2 — "a note after `asked_at` whose
title is not a system type", with "derive the list from it, never hardcode".

Measured against the live lists, that rule is unusable:

- **All 44** notes on eligible items whose titles do not parse as `YYYY-MM-DD — TYPE — …` are
  **engine**-authored (13 frontmatter fences, 21 bare `AI-LINK`, 10 one-off engine run logs).
- The parsed-but-off-catalogue types — `Q`, `Q-BODY`, `Q-UPDATE`, `UPDATE`, `QUESTION`, `A`,
  `META QUESTION`, ~50 notes — are engine-authored too.
- **Zero** Paul-typed free-text notes exist on the eligible set. Where Paul *has* answered, the
  engine transcribed it as a typed `ANSWER` / `RESPONSE` / `REPLY` / `DECISION` note.

Exclusion would therefore fire on **essentially every item in the queue**, and the consumer's
response to `response_detected` is to spend an expensive processing pass and then **resolve** the
item. A false positive is a wrong resolve on work Paul never answered; a false negative costs one
scan's delay (the item stays pending and the next scan re-checks). **Precision wins.**

So `response_detected` fires on three named paths only — `q_answered_tag`,
`completed_unresolved`, `response_note` — each surfaced in `response_evidence[].path` so the
agent can branch on *which*. **The exclusion signal is not discarded**: notes that are neither
response-class nor recognisably engine-authored are quarantined in `unrecognised_notes[]`, which
never sets the boolean. Live, that is 16 entries across 136 rows, versus the ~all-of-them
exclusion would have produced.

The brief's stated boundary is preserved exactly and repeated in the tool description: **the
server detects that a response EXISTS; the agent decides what it MEANS.**

### 3.2 Completed items are in scope — the `.ms` filter made a documented path unreachable

`ai-surface-scan.md` § 3b.2 names "closure-with-response" (Paul answered and completed in one
action) as a detection path, but the `.ms` eligibility was `status:incomplete`, so that path
could never fire. The filters widen to `(status:incomplete OR status:completed)` while still
excluding the terminal lifecycle tags — so only anomalies come through. Measured cost: **+3 rows
on `AI_Questions`, +4 on `AI_Activity`.** Live, this is where 4 of the 7 detections came from.

### 3.3 Three N+1 fan-outs replaced with one broad read

- `dependency-graph-detect.ms` ran `rtm.getTasks("parent:" + id)` **per project** — ~107 signed
  calls at ~0.9 RPS. The parent→children map now comes from one read.
- `tag-audit.ms` ran a `tag:<name>` query **per non-canonical tag** — up to 87 calls. Usage is
  tallied client-side from the one read the minimum-tag-set signals need anyway.

Same answers, two calls total each. This is the divergence `detectors.build_health_check` already
makes against `health-check.ms`.

### 3.4 Smaller deliberate divergences (each pinned by a test)

- **`gtd_item_stale` drops `isSubtask:true`.** The `.ms` restricted the scan to subtasks with no
  stated rationale, making every top-level project and Area of Focus structurally invisible to a
  report whose purpose is finding forgotten work. Rows are grouped `by_state` instead, so a
  caller wanting the old scope reads the `action`/`waiting_for` buckets. Live: 208 stale items,
  of which 19 foci and 11 projects would have been invisible.
- **Life contexts are the canonical FOUR.** Every script hard-coded
  `["work","personal","leanworking"]`; `client` is canonical per `tag-taxonomy.md`. Usage is
  currently zero, so this costs nothing and stops a future `#client` item vanishing.
- **`max_projects` is applied AFTER the sort.** The `.ms` truncated during the scan in RTM's
  arbitrary order, then sorted the survivors — so it did not return the largest projects it
  claimed to.
- **Estimates are summed for every workflow state**, not only `action`. A waiting-for with an
  estimate is real committed time.
- **`gtd_engine_report` emits no zero it cannot justify.** `monitor-outcomes.md` § 4c's schema
  also asks for unblock-walk outcomes, cluster yield, scheduled-task run health and per-agent
  yield. None is derivable from RTM state. They are named in `gaps[]` with a reason rather than
  reported as zeros — *a zero meaning "not measured" is the exact failure this tool exists to
  end*. The speculation upgrade rate stays withdrawn per D2 and is listed there too.

### 3.5 The taxonomy and note vocabulary are codified server-side

The server is standalone and cannot read the marketplace markdown at runtime, so
`tag_report.CANONICAL_TAGS` and `surface_queue.CATALOGUE_NOTE_TYPES` are Python constants —
exactly as `engage_commit.py` codifies the engage verdict grammar. **The markdown remains the
authority; a change there is a lockstep change here.** `tag-audit.ms`'s hand-copied 24-tag list
had drifted so far (missing every `q_*`, every `ai_*`, `client`, `focus`, `hold`, `quick_win`,
`single_action`, the energy pair, `redacted`, and all four plugin families) that against 88 live
tags it would have reported the overwhelming majority as "outside taxonomy" — noise, not a
finding.

Classification is **three-way** (`canonical` / `family` / `non_canonical`, plus `retired`),
because binary would lie. People tags are the honest caveat: the taxonomy says they accumulate
organically and names only two, so a person tag is indistinguishable from a typo by any
deterministic rule — they land in `non_canonical` and `people_caveat` says so in the payload.

---

## 4. Things found in gtd's own sources that look wrong

Reported per the brief's § 2 instruction. **None is fixed here** — each is gtd-side or would
change shipped tool output.

1. **The server writes a note title its own gate would reject.** `gtd_surface_create` writes the
   surface body note as `<date> — ACTIVITY_REPORT — <summary>` for the fifth item type. The
   note-title grammar's TYPE token excludes the underscore, so `note_shape.check_title` **rejects
   it**. With `RTM_STRICT_NOTES=shape` enabled, every activity-report creation through a gated
   path would be blocked. Latent today only because the gate is off by default.
2. **The five surface body-note types are not in `note-shape-catalogue.md` § 2.**
   `QUESTION`/`ALERT`/`NOTIFICATION`/`SURFACE`/`ACTIVITY_REPORT` are written by this server
   today; `validate-note.py` would reject all five as unknown TYPEs. They need registering (and
   `ACTIVITY_REPORT` needs the grammar question in (1) resolving).
3. **`gtd_reads.parse_note_type` mis-splits hyphenated types.** Its TYPE token is `[A-Z][A-Z /-]*`
   and its separator alternation admits a bare hyphen, so non-greedy matching splits at the
   type's own hyphen: `AI-LINK` parses as type `AI`, and likewise `DEPENDS-ON`, `SOURCE-DRAFT`,
   `CONTRIB-UPDATE`, `TMPL-CHILD`. Shipped in v2.3.0 and used by `gtd_context`. `surface_queue`
   deliberately does **not** reuse it (its own regex requires the whitespace the catalogue
   mandates around the separator, which disambiguates). Fixing the shared helper would change
   `gtd_context` output, so it is out of scope for an additive release.
4. **Two published CONTRIB state vocabularies disagree.** `journaling-lifecycle.md` says
   `drafted|accepted|edited|discarded|superseded|stale`; `tag-taxonomy.md` §
   `ai_contrib_drafted` says `drafted|offered|accepted|discarded|superseded|stale|archived` (no
   `edited`). The union is counted and observed values reported verbatim; the report names the
   divergence in `gaps[]`. Live data also carries `surfaced`, which is in **neither**.
5. **`#hold` is used but not codified.** `project_index` treats it as a portfolio-exclusion tag
   and it is live in the account, but `tag-taxonomy.md` does not list it. Treated as canonical
   here so it does not read as an unknown tag.
6. **`_LIFE_TAGS` is three-membered in two server modules.** `project_plan.py` and `gtd_reads.py`
   both omit `client`, so a `#client` project would show `life: ""` in `gtd_project_index`. Zero
   live impact today (no `#client` items). Not changed — it would alter shipped output.

**A live finding worth Paul's attention, now visible for the first time:** with the arithmetic
fixed, the 30-day contribution cohort is `{drafted: 9, unknown: 3}` — **nothing has ever reached
`accepted`**. The 0% acceptance rate is now a real observation rather than an artefact, and it
says the contribution engine drafts but the acceptance loop never closes. Previously the two were
indistinguishable.

---

## 5. Membrane / activation

- **Additive and backward-compatible.** No existing tool changes name, shape or behaviour.
- **Read-only.** No write, no timeline, no transaction on any of the eight.
- **No new tag** — so there is **no strict-tag activation-ordering hazard** (unlike the finalise
  and overlay-refresh marks).
- **Vault-free.** Pure RTM; `gtd_dependency_gaps` deliberately stops at the RTM boundary and says
  so in its payload.
- **To go live: restart the MCP server on v2.9.0.** That is the whole activation step.

---

## 6. Verification — what was run, and what was not

**Run and passing:**

- `make lint` — ruff check + `ruff format --check` + pyright over `src`: **0 errors, 0 warnings**.
- `make test` — **1391 passed**. (Was 1294. +122 new tests, −25 from removing the stale
  `test_error_codes 2.py` duplicate — see § 8.6.)
- `make fingerprints` — regenerated; 95 tools, `source_version 2.9.0`. The freshness guard passes.
- **A live read of all eight tools against Paul's production account**, exercising the real tool
  functions through a `FakeMCP` shim with a real `RTMClient` — i.e. the shipped code path, not a
  re-implementation. Figures in § 1.
- **Cross-validation:** `gtd_dependency_gaps` returned **21** eligible, matching the Wave 0
  MilkScript probe exactly — two independent implementations, same answer. `gtd_engine_report`'s
  30-day cohort returned **12 created / 37 modified**, matching the figures the corrected `.ms`
  header itself records.

**Explicitly NOT done:**

- **The tools have not been called through a restarted MCP server.** The live verification
  invoked the tool functions in-process against the real API; it did not go through the MCP
  transport of a restarted server. A restart is still required before any consumer can call them.
- **No output-parity probe against the `.ms` scripts** — deliberate, per D1. Parity would
  validate known-wrong behaviour. Verification is against each consumer's documented need plus
  the live read.
- **No gtd-side consumer migration, no `.ms` deletions, no thin-launcher refactors.** All
  marketplace-repo work, out of scope for this repo.
- **The `RTM_STRICT_NOTES=shape` interaction in § 4.1 was reasoned and unit-checked
  (`note_shape.check_title` rejects the title), not exercised end-to-end** through a gated write.

**Test design note.** The `gtd_engine_report` regression fixtures are built so that **the old
logic scores 0 and the correct logic scores non-zero** — one per fault, plus one combining all
four (old: 0% acceptance on four separate grounds; correct: 50%). A test that merely exercised
the happy path would have passed against the broken script too, which is precisely how this went
unnoticed for months. The `response_detected` negative — an item carrying only system notes must
not trip it — is pinned across every engine note shape observed live.

---

## 7. Conventions

| § | Applied |
|---|---|
| § 2 | **Rewritten** — the CQS + aggregate-grouped naming standard frozen as design of record (D6–D14), with the pre-existing exceptions marked as known debt, not precedent |
| § 3 / § 7 | Six documentation surfaces on all eight; enriched docstrings with multi-case `Returns` |
| § 8 | Pure-module tests + `FakeMCP` tool tests + the read-only call-surface assertion on all eight |
| § 9 | All four touchpoints: `README.md`, `server.py` instructions, `CLAUDE.md` (tree + module table + feature section), test inventory; fingerprints regenerated |
| § 10 | Minor bump 2.8.0 → **2.9.0** (new tools, no breaking change) — `pyproject.toml`, `__init__.py`, `uv.lock` together |
| § 11 | Quality gate passed |
| § 13 | Not applicable — these are **not** byte-compat ports; D1 explicitly forbids parity |

---

## 8. Open items / handback

**For gtd (marketplace repo) — the rest of Wave 1:**

1. Migrate consumers onto the eight tools; **delete all 18 `.ms` files**; drop the fallback
   framing (D3).
2. Refactor the seven scheduled-task specs to thin launchers and extend audit check `8.5.34` to
   flag a raw `gtd_*` name or `*.ms` filename regardless of size (D15).
3. Register the five surface body-note types in `note-shape-catalogue.md` § 2 and resolve the
   `ACTIVITY_REPORT` underscore-vs-grammar conflict (§ 4.1–4.2).
4. Reconcile the two CONTRIB state vocabularies, and decide whether `surfaced` is canonical (§ 4.4).
5. Codify `#hold` in `tag-taxonomy.md` (§ 4.5).

**For rtm-mcp — DONE in this change (both were flagged, then fixed on request):**

6. ~~The `error_codes 2.py` / `test_error_codes 2.py` duplicates~~ — **removed** (`git rm`).
   These were Dropbox partial-sync artefacts committed by accident at v2.1.0 (3dd42e5). Both were
   **tracked**, and pytest collected the test copy, so a stale v2.1.0-era snapshot of the registry
   suite ran on every CI pass. Verified safe before deletion: both are strict **subsets** — the
   duplicate `ErrorCode` registry had **zero** members the real one lacks (and was missing four:
   `DOR_NOT_MET`, `INVALID_BLOCK_ORDER`, `INVALID_NOTE_TYPE`, `NOTE_SHAPE_REJECTED`), and the
   duplicate test file had **zero** tests the real one lacks (and was missing the three
   write-boundary-gate tests). The duplicate `src` module was never imported by anything — a
   filename containing a space cannot be imported as a module — and the duplicate *test* imported
   the **real** `rtm_mcp.error_codes`, so it was asserting a stale contract against live code.
   Suite total drops 1416 → **1391**; the `CLAUDE.md` inventory reconciles exactly.

7. ~~`CONTRIBUTING.md` § 7's stale `from __future__ import annotations` prohibition~~ —
   **rewritten, and the real hazard identified.** The old rule justified itself with *"no existing
   `src` module uses it"*, which was true when written (2026-06-20) and had been overtaken by six
   modules. But dropping it outright would have been wrong: **there is a genuine hazard, and it is
   not the one the rule named.**

   PEP 563 turns annotations into strings that FastMCP/pydantic must resolve at runtime against
   **module** globals. Every tool is registered *inside* `register_<group>_tools(...)`, so a
   **function-scoped** `Annotated` alias — a natural thing to define in a 6,000-line registration
   function — becomes an unresolvable forward reference. Measured on fastmcp 3.4.4:

   - module-level annotation under the import → advertised schemas **byte-identical**;
   - function-scoped alias under the import → `NameError: name 'LocalRef' is not defined`, raised
     from `list_tools()` during schema generation.

   So the rule is now **layered**: allowed in pure no-IO builders (where nine modules already use
   it), never in a schema surface (`tools/*.py`, `models.py`, `server.py`, `tool_params.py`). The
   tool modules work today only because their params happen to reference module-level names — the
   risk is latent, not absent. It fails loudly at server start rather than silently, which is
   stated in the rule.

**Still open for rtm-mcp:**

8. `gtd_reads.parse_note_type`'s hyphenated-type split (§ 4.3) — a real bug, but fixing it
   changes `gtd_context` output, so it wants its own change.

**Consumer (the live board / artifacts) — no action.** Nothing they call changed.

---

## 9. Durable lessons

**A guard on a method name is not defensive — it is the thing that hides the defect.** A
null-coalescing guard on a *misspelt* method never throws; it degrades into `null`, which reads
downstream as "no data" and to a human as "no activity". Guard **values** (`getParent()`
legitimately returns null), never **methods**. In a typed codebase the equivalent trap is a
`getattr(x, "foo", None)` or a bare `except` around an attribute access.

**A control that stops matching reports "no findings", which is indistinguishable from a clean
bill of health.** That shape recurred four times across this one investigation: the guard idiom;
a `Phase:` regex against a field named `State:`; a `completedAfter:"N days ago"` filter RTM
silently ignores; and the audit check whose threshold was bytes when the property was coupling.
**A check must be proven to fire on a known-bad input**, not merely to pass — which is why every
`gtd_engine_report` regression fixture is built to fail against the old logic.

**Do not build a detector from a specification without measuring the population it will run
against.** `response_detected` by exclusion is a perfectly reasonable rule that would have fired
on essentially every item in the live queue, and the consumer's response to a positive is to
*resolve* the item. Ten minutes of live measurement changed the design from
almost-always-true to 7-of-136.

**Where two implementations of the same judgement exist, make them agree by construction, and
where they cannot, cross-check them.** `gtd_focus_index` reuses `project_index._active` so it can
never disagree with the portfolio. `gtd_dependency_gaps` cannot share code with the Wave 0 probe —
so the fact that both return exactly 21 is the verification.

---

*Source of truth: `CLAUDE.md` § "Wave 1 — retiring the MilkScript library (eight reads, since
v2.9.0)" + the module docstrings in `surface_queue.py`, `engine_report.py`, `tag_report.py`,
`gtd_reports.py` (each names its own divergences), and the eight tool docstrings in
`tools/gtd.py`. Naming standard: `CONTRIBUTING.md` § 2. Provenance: Wave 1 hand-off brief
2026-07-25; designed change `2026-07-25-gtd-milkscript-retirement` (D1–D15, approved 2026-07-25);
live MilkScript API probe 2026-07-24; live measurement of Paul's production account 2026-07-25.*
