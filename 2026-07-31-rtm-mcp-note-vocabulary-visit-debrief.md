---
report_type: handback-debrief
title: Note-type vocabulary visit — what the measurement found, and why the gate did not ship
target_repo: rtm-mcp
brief: "Note-type vocabulary — promote the WRITE set to the gate, and prove the READ sets stay permissive (2026-07-30)"
shipped: v5.1.1 (two defect fixes + one taxonomy correction)
not_shipped: the vocabulary gate itself — deliberately, see § 4
raised: 2026-07-31
---

# Hand-back debrief — note-vocabulary visit

## 0. Summary

The brief asked for a vocabulary gate on note-title TYPE tokens, shipped inert. **It did not
ship, and that was the right call** — the measurement it asked for first (§ 5, "re-measure before
deciding") found the legacy backlog is six times larger than the brief expected and mostly
composed of types that are in active use rather than mistakes. Tightening ahead of that clean-up
would have relocated the failure, not removed it.

What did ship is two **silent defects** the measurement surfaced on the way, both in
`surface_queue.py`, one of which had taken a read tool off the air entirely.

## 1. § 8 Q1 — what is in the write-authorisation set, and what rule composed it?

**Not answered, because the set was not built.** The brief's § 4.1 asks for a set derived from
existing constants rather than a fourth hand-maintained list. That remains the right shape, and
the measurement adds a constraint the brief did not have: `CATALOGUE ∪ SURFACE` is **not**
sufficient (see Q5), and neither is `CATALOGUE ∪ SURFACE ∪ RESPONSE` while ~40 tokens are in live
use outside all three.

The composition rule can only be settled after the rewrite lands, because the rewrite is what
determines whether those ~40 tokens still exist.

## 2. § 8 Q2 — did the read sets stay permissive?

**Vacuously yes — nothing narrowed them, and one was widened.** No vocabulary gate was added, so
no read path changed behaviour except `SURFACE_NOTE_TYPES`, which gained `ACTIVITY-REPORT`.

The permissiveness tests the brief asked for are in place for the part that shipped:
`tests/test_surface_queue.py::TestEmittedSurfaceTitlesAreRecognisedOnTheReadPath::test_the_legacy_underscore_spelling_is_still_recognised`
pins the underscore form as recognised precisely *because* it can no longer be written. That is
the brief's § 6 principle, applied to the one case that was live.

## 3. § 8 Q3 — the legacy backlog, re-measured

**The brief expected 3 spellings / 18 notes. The census found ~40 tokens / 114 notes**, plus ~68
edge-case notes a naive rewrite would silently skip.

Coverage is provable, not sampled — note counts reconcile against RTM's own `notes_count` for
every task:

| List | Tasks | Notes (raw) | Notes (distinct) | Off-vocabulary |
|---|---:|---:|---:|---:|
| AI_Questions | 118 | 180 | 180 | 4 |
| AI_Activity | — | 69 items | — | 7 |
| Inbox_Stuff | 359 | 974 | 974 | 46 |
| Processed | 1,436 | 3,607 | 3,342 | 57 |

**The qualitative finding matters more than the count: most of these are not typos.** `SCOPE` ×15,
`EXECUTOR` ×21, `FILING` ×8, `DRAFT` ×6, `OUTPUT-UPDATE` ×5, `ADDITION` ×4 are recurring,
semantically distinct, and deliberate. `SCOPE` means something `CONTEXT` does not. This is a
**vocabulary gap**, not drift — the catalogue never caught up with how the system is used.

Paul was offered promote-the-recurring (~40 writes, no information loss) and chose **rewrite
everything to the current catalogue** (§ 5 option 2) with the cost explicit, plus the near-miss
and malformed classes in scope. The per-token mapping is proposed for sign-off in
`2026-07-31-note-vocabulary-rewrite-mapping.md`; **no live write has been made.**

**Dry run complete for two of four lists** — 136 planned rewrites (103 off-vocabulary, 24
near-miss, 9 malformed) across Inbox_Stuff and Processed, **every proposed title passing
`note_shape.check_title`, zero failures**. Plan at `outputs/_rewrite/rewrite_plan.tsv`.

Two gaps to close before execution:

- **11 notes on AI_Questions / AI_Activity are not in the plan.** They were measured through a
  path that truncated two titles, and a truncated title must never be written. They need a
  targeted re-fetch (≈9 tasks).
- **One unresolved note:** `117763012` — `2026-06-09 catch-up confirmed — resolving` has no
  recoverable TYPE token. Plus `116960677`, the bare string `2026-04-19 INCEPTION`, which has no
  summary at all; the shape gate requires one, so it has to be invented from the body.

## 4. § 8 Q4 — is it shipped inert, and what is the probe?

**Not shipped at all.** The brief sequenced the gate behind a re-measurement whose purpose was to
inform the § 5 decision; the measurement changed that decision's shape substantially, and the
rewrite it selected has not yet run. Shipping a gate — even inert — against a corpus about to be
rewritten would mean authoring the write-authorisation set twice.

The sequence now is: sign off the mapping → complete the plan (the 11 + 2 above) → execute the
rewrite → **then** build the gate against a clean corpus, ship it inert, and flip it in a separate
release with its own probe. That is the brief's own § 4.2 discipline, unchanged.

## 5. § 8 Q5 — what measurement contradicted

**Every figure in the brief's § 2 is correct.** JOURNAL 8, CATALOGUE 25, SURFACE 14, JOURNAL ⊂
CATALOGUE, SURFACE disjoint from CATALOGUE, 39 distinct. § 2a and § 2b verified against source at
`b4d47d3`. The brief's central reframe — three vocabularies with different jobs, conflating them
is the defect — is sound and was the most useful thing in it.

Three additions:

### 5.1 There is a fourth vocabulary the brief did not count

`RESPONSE_NOTE_TYPES` = {`ANSWER`, `RESPONSE`, `REPLY`, `DECISION`} in `surface_queue.py`, n=4.
Three of the four appear in **no other set**, so the true total is **42 distinct, not 39** — and a
`CATALOGUE ∪ SURFACE` composition would silently make `ANSWER` / `RESPONSE` / `REPLY` unwritable.
This strengthens the brief's § 4.1 warning rather than weakening it.

### 5.2 The emission set had already drifted from the read set

Wave 1b corrected the *emitted* activity-report token to `ACTIVITY-REPORT` (the shape grammar
forbids the underscore) but left `SURFACE_NOTE_TYPES` carrying only `ACTIVITY_REPORT`. **For two
releases the server wrote a note type its own classifier scored `unrecognised`** — two live notes
on `AI_Activity`, sitting in `unrecognised_notes[]`.

This is the brief's § 6 defect arrived at from the opposite end: § 6 guards against a gate
narrowing recognition; this was an *emission* widening past it. Both produce a **wrong answer, not
an error**, which is why neither announces itself. Fixed in v5.1.1, with the read and write sides
pinned together in one test so neither can move alone again.

### 5.3 A read tool was off the air, and had been silently

`gtd_surface_queue(surface="questions")` and `"both"` returned **nothing**:
`Output validation error: '[approve, decline, defer]' is not of type 'array'`.

`surface_body` writes `expected_response_options` block-style, so the parser only ever produced a
list. A live item carries the **flow** form, which went down the inline branch to `_scalar` and
landed a string under a key the row schema declares as an array; strict output validation then
rejected the whole response. **One item's metadata took out the entire surface.**

Fixed at two layers — `_option_list` reads the flow form, `_as_list` coerces at the row builder —
and the second is the general one. The parser is deliberately a focused reader of what
`surface_body` writes, so unanticipated shapes reaching a typed field will keep happening; what
must not keep happening is that one of them fails the whole response. Same posture as
`unrecognised_notes[]`: quarantine and report, never refuse.

## 6. Out of scope but found — artifact-shaped tools in the chat surface

Raised by Paul mid-session and worth recording, because three separate failures in one session
share a root.

`gtd_surface_queue` returned **65,127 characters** on `surface="activity"` (over the client's
tool-result ceiling, spilled to a file); failed output validation outright on `questions`; and
`list_tasks(hasNotes:true)` spilled 51.8 KB. The properties that make a tool good for a board —
whole-collection responses, strict fail-closed output schemas, denormalised pre-joined payloads —
are the properties that make it expensive or unusable for a chat caller.

**The server already has the concept and it is not load-bearing.** `tool_help.taxonomy()` derives
`consumer: artifact | agent | either` from a hand-authored `BFF_TOOLS` set — and
`gtd_surface_queue`, the tool that failed twice, **was not in it**, because membership is
remembered rather than derived from behaviour.

v5.1.1 adds it to `BFF_TOOLS` and `DUAL_CONSUMER`. The `DUAL_CONSUMER` entry is deliberately
awkward and the awkwardness is recorded in the source: no board reads this tool, so
`consumer: artifact` would be a false statement in `rtm_tool_help`, and `either` is the
least-wrong value available. **Shape and audience are two axes and the taxonomy conflates them.**

The durable fixes are a designed change, not lines in a set:

1. Derive BFF-ness from a **property** ("returns an unbounded collection" / "the output schema is
   a frontend contract") and assert it, so a new tool cannot be omitted by forgetting.
2. **Projection and bounds** on collection reads — `view: summary|full`, `limit`, `since`; thin by
   default. One contract, no drift, better than splitting into parallel agent tools.
3. **Fail open on read-tool output validation**, generally — § 5.3 is one instance of a class.
4. **Aggregate-first defaults**: `surface_queue` already computes the counts; for a chat caller
   those plus the rows needing a decision *are* the answer.

## 7. Verification

- `pytest`: **1,750 pass** on 3.11 and 3.12.
- The 7 new `surface_queue` tests verified to **FAIL against the unmodified parent** before being
  accepted — they test the fix, not the fixture.
- `ruff check`, `ruff format --check`, `pyright src`, `check-tool-naming.py --strict`: clean.
- **Per-tool fingerprints byte-identical** — no tool gained, lost or changed a parameter,
  description, annotation or output schema. Patch bump by CONTRIBUTING § 10.
- Documentation lockstep: `CHANGELOG.md`, `CLAUDE.md` module table, `CLAUDE.md` test inventory
  (`test_surface_queue.py` 32→42, `test_tool_help.py` 25→26).

**Two caveats, stated rather than buried.** `tests/test_companion.py::TestResolveVaultRoot` (2
tests) fails in the Linux dev sandbox because `resolve_vault_root` finds the container mount ahead
of the monkeypatched `$HOME`; unrelated to this change, and expected to pass under `make test` on
the host. And `tool-fingerprints.json` still records `source_version 5.1.0` because the sandbox's
editable-install metadata predates the bump — re-run `make fingerprints` after `uv sync` on the
host; the per-tool hashes are unchanged, so this is cosmetic.

## 8. Open items

**Items 1–4, 6 of the original list are CLOSED** — the mapping was signed off, the plan completed,
the rewrite executed (135/135, verified live), and the vocabulary gate shipped and locked on rather
than inert (Paul's call: the census had already measured what a `warn` stage would have re-measured).
The gtd lockstep landed as v0.204.0.

What remains:

1. **Restart the MCP server on v5.2.0.** Three things depend on it: the vocabulary gate goes live,
   and the two v5.1.1 fixes stay live. Until then the running server is on shape-only enforcement.
   *(Paul)*
2. **The BFF/consumer designed change** (§ 6) — captured, [RTM 1220206239](https://www.rememberthemilk.com/app/#list/51526642/1220206239).
3. **Note-body construction** — the "tool supplies syntax" change Paul raised at the close;
   captured as [RTM 1220383027](https://www.rememberthemilk.com/app/#list/51526642/1220383027), designed-change pack and
   hand-off brief filed under `general/plugin-marketplace-architect/`. Awaiting approval; closure
   gated on the returned debrief.
4. **The ~68 edge-case notes left out of scope** — 29 bare `SOURCE` / `COMPLETION` titles (free-text
   rule protects them), and the mojibake note `118060873`. Recorded, not forgotten.
5. **A liveness check for read tools.** Two silent failures in one session — a tool writing what it
   could not read, and a read returning nothing for seven weeks. A periodic assertion that each read
   tool still returns rows would have caught the second in June. Cheaper than either designed change
   above and arguably higher value.

---
*Created: 2026-07-31 | Source: hand-off brief `note-type vocabulary promotion` (2026-07-30); full read-only census of live RTM note titles, 2026-07-31; direct source read of rtm-mcp at b4d47d3; live failures observed in-session*
