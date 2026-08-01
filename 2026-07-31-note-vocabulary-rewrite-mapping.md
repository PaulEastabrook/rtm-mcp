---
report_type: rewrite-mapping
title: Legacy note-title rewrite — token mapping and execution record
target: live RTM note titles (AI_Questions, AI_Activity, Inbox_Stuff, Processed)
raised: 2026-07-31
status: EXECUTED 2026-08-01 — 135 of 135 applied, 0 drift, 0 failures (see § 0)
census: full coverage, not sampled (180 / 69 / 974 / 3,342 distinct notes)
decision_taken: "§5 option 2 — rewrite to canonical, then tighten (Paul, 2026-07-31)"
edge_cases_in_scope: "near-misses + date-malformed (Paul, 2026-07-31)"
edge_cases_excluded: "mojibake note 118060873; 29 bare SOURCE / COMPLETION titles"
---

# Legacy note-title rewrite — mapping and execution record

## 0. Execution record — 2026-08-01

**135 of 135 applied. Zero drift, zero failures.** 133 executed as a batch (bodies preserved by
taking the stored body minus its first line; every edit verified against the returned body); 2 done
by hand because they needed judgement — `116960677` (a complete INCEPTION note with no title-line
summary; one drawn from its own "What this project is for" section) and `117763012` (whose body's
*second* line was already a well-formed title, so the malformed stray line 1 was dropped rather than
left as a duplicate).

**Verified live:** `AI_Activity`'s `unrecognised_notes` fell from **12 → 5**, and **zero
date-prefixed** off-vocabulary notes remain. The 5 survivors are all undated free-text titles
("Architect weekly pulse", "Scan summary", "Tag-discipline audit") — correctly exempt under the
free-text rule, which is the rule working rather than a gap.

### Two corrections the execution forced

**1. `Q` was the wrong target, and this document said so in three places.** `Q_OPEN → Q`, `Q-2 → Q`
and `q_question → Q` (§ 3.1, § 4) all pointed at `Q` — which is itself one of the **legacy AI-surface
spellings** that rtm-mcp v5.2.0 makes *readable but not writable*. Rewriting a legacy token to
another legacy token accomplishes nothing, and would have left three notes carrying a type the
server can no longer write.

Caught by the executing session, which noticed the writes succeeded and reasoned that the running
server must therefore predate v5.2.0 — correct, and a good catch. **All three were re-rewritten to
`QUESTION`**, the registered canonical form, and the notes are on `AI_Questions` where a
question-body is exactly what they are.

*The lesson for the next pass:* every rewrite target must be checked against
`WRITE_AUTHORISED_NOTE_TYPES`, not merely against "is it a real type". The dry run validated shape
(`check_title`) but not vocabulary, because the vocabulary gate did not exist when it was written.

**2. Note edits are NOT undoable.** § 6 step 5 claimed `batch_undo` as the rollback path. Every one
of the 135 edits returned `transaction_undoable: false` — RTM offers no undo for a note edit. The
recorded transaction ids are **audit-only**. Rollback would mean re-writing from the original
titles, which is why the census TSVs (which carry every original) are the real safety net and should
be retained.

### Also worth keeping

One note (`116633901`) has a blank line immediately after its title, and the leading newline in
`note_text` was stripped in transmission — twice. It was landed by sending the complete body
(title line included) as `note_text` with **no** `note_title`, which is valid because this corpus
stores titles as body line 1 anyway. Verified byte-correct afterwards, along with its
identically-shaped sibling `116633934`. A body-only edit is also the one `edit_note` path the note
gate never judges, so this is a usable escape hatch — and worth remembering rather than
rediscovering.

Results: `outputs/_rewrite/rewrite_applied.tsv` (133 rows) plus the 2 hand-done above.

## 1. Why this document exists

Paul chose to rewrite every off-vocabulary note title to the current catalogue rather than
promote the recurring tokens into it. That decision was taken with the full cost on the table
(~152 writes, and the collapse of `SCOPE` / `EXECUTOR` / `FILING` into existing types).

What was **not** decided is *which* canonical type each legacy token becomes. That is ~40
individual judgements, several of them genuinely arguable, and every one is a write against live
data. So they are proposed here for amendment rather than applied.

**Nothing in this document has been executed.** The census was read-only throughout.

## 2. Scope

| Class | Notes | In scope |
|---|---|---|
| Off-vocabulary, date-prefixed | 114 | yes |
| Near-miss (date + dashes, token fails `[A-Z][A-Z _/-]*`) | 24 | yes |
| Date-prefixed but malformed (delimiter missing / parenthesised date) | 14 | yes |
| Mojibake em-dashes (`118060873`) | 1 | **no** — excluded by Paul |
| Bare `SOURCE` ×25 / `COMPLETION` ×4, no date prefix | 29 | **no** — free-text rule |
| **Total to rewrite** | **~152** | |

Per-note detail lives in the census TSVs (§ 7). Counts below are distinct `note_id`.

## 3. Token mapping — off-vocabulary

Target vocabulary is `CATALOGUE_NOTE_TYPES` (25) plus the surface set for `AI_Activity` items.

### 3.1 High-confidence — the legacy token has an exact canonical sibling

| Legacy | n | → | Rationale |
|---|---:|---|---|
| `ANALYSIS` | 4 | `AI ANALYSIS` | Same thing, missing the `AI ` prefix. |
| `PUSHED` | 2 | `COMMIT` | Both bodies name a commit SHA on `origin/main`. |
| `COMPLETION-ADDENDUM` | 1 | `COMPLETION` | A completion note with a follow-up clause. |
| `AI CONTEXT` | 1 | `CONTEXT` | Prefix noise. |
| `PREP STALE` | 1 | `PREP` | A `PREP` note recording that a prior agenda was superseded. |
| `PROGRESS/OUTPUT` | 1 | `OUTPUT` | Body is "Pre-read drafted" — an artefact. |
| `Q_OPEN` | 1 | `Q` | Underscore variant; also the only underscore token in live data. |
| `ACTIVITY` | 4 | `ACTIVITY-REPORT` | Surface list; the canonical emitted token. |
| `AI-ACTIVITY` | 1 | `ACTIVITY-REPORT` | As above. |

### 3.2 Confident — a clear canonical home, some information narrowing

| Legacy | n | → | Rationale |
|---|---:|---|---|
| `SCOPE` | 15 | `CONTEXT` | **The largest information loss in this pass.** Every body records a scope change ("Project expanded from single waiting-for to 10-item phased plan"). `CONTEXT` is the nearest canonical home; the scope-change *distinction* does not survive. |
| `EXECUTOR` | 21 | `PROGRESS` | Engine run records — 20 consecutive "Skipped (nth occurrence)" plus a final one. All one series. |
| `FILING` | 8 | `OUTPUT` | "Artefacts filed to Agent Memory store" — the filing of an output. |
| `DRAFT` | 6 | `OUTPUT` | Drafted comms awaiting review. *(`SOURCE-DRAFT` considered and rejected — that type is for source drafts, not outbound comms.)* |
| `OUTPUT-UPDATE` | 5 | `OUTPUT` | Revisions of a previously filed output. |
| `ADDITION` | 4 | `CONTEXT` | Plan additions and resequencing. |
| `HANDOFF` | 2 | `OUTPUT` | "Increment 3 brief filed". |
| `DESIGN` | 2 | `OUTPUT` | "designed-change pack drafted". |
| `CHANGE-PROPOSAL` | 2 | `OUTPUT` | "designed-change filed". |
| `ERRATUM` | 2 | `CONTEXT` | Corrections to a prior note. |
| `STATUS` | 2 | `PROGRESS` | "Renewal late-cycle, in motion". |
| `DESIGNED-CHANGE` | 1 | `OUTPUT` | "architect design pass complete; awaiting approval". |
| `FINDINGS` | 1 | `AI ANALYSIS` | Grep results plus refined sequencing. |
| `INVESTIGATION` | 1 | `AI ANALYSIS` | An API-capability finding. |
| `RESEARCH` | 2 | `AI ANALYSIS` | Appears in both Inbox_Stuff and Processed. |
| `EVAL` | 1 | `PROGRESS` | A regression PASS record. |
| `ASYNC-PROBE` | 1 | `PROGRESS` | Body is "result". |
| `MILESTONE` | 1 | `PROGRESS` | "All 10 host conversations confirmed". |
| `PLAN` | 1 | `PROGRESS` | Actions created. |
| `PLANNING` | 1 | `PROGRESS` | "Monday action set". |
| `SENT` | 1 | `PROGRESS` | "ELI request emailed". |
| `MERGE` | 1 | `CASCADE` | "folded in CD enablement of the Pods". |
| `SUPERSEDED` | 1 | `CASCADE` | "merged into Continuous Delivery". |
| `CROSS-REF` | 1 | `AI-LINK` | "DCI board & RfD inventory". |
| `LINK` | 1 | `AI-LINK` | "strategic parent project spawned". |
| `AI APPROVED` | 1 | `DECISION` | "design approved inline". |
| `APPROVED` | 1 | `DECISION` | "phased, brief-driven". |
| `RECONCILIATION` | 1 | `DECISION` | "on-disk implementation supersedes pack scope". |
| `RESOLUTION` | 1 | `DECISION` | |
| `RESOLVED` | 1 | `DECISION` | |
| `AMENDMENT` | 1 | `CONTEXT` | |
| `IMPROVEMENT` | 1 | `CONTEXT` | |
| `REFINEMENTS` | 1 | `CONTEXT` | "Paul's design directives". |
| `REQUIREMENTS` | 1 | `CONTEXT` | "Captured requirements brief". |
| `BRAINSTORM` | 1 | `CONTEXT` | "candidate WoW-friction project ideas (seed set)". |
| `CHANGE` | 1 | `CONTEXT` | A schedule change. |
| `HR CONFIRMATION` | 1 | `CONTEXT` | "Resignation acknowledged, last day LOCKED". |

### 3.3 Arguable — flagged for your call

| Legacy | n | Proposed | Alternative | The tension |
|---|---:|---|---|---|
| `EXECUTOR` | 21 | `PROGRESS` | `SESSION` | These are engine-run records, not human progress. `SESSION` arguably fits better, but 20 of the 21 say only "Skipped". |
| `DECISION NEEDED` | 1 | `QUESTION` | `BLOCKER` | It is on `AI_Questions`, so `QUESTION` is consistent with its surface — but the body reads as a blocker. |
| `DRAFT` | 6 | `OUTPUT` | `SOURCE-DRAFT` | If `SOURCE-DRAFT` is broader than I have read it, these belong there. |
| `SCOPE` | 15 | `CONTEXT` | *(promote)* | Largest single cluster; the one where "rewrite" costs most. Re-flagged only so the cost is explicit at execution time. |

## 4. Near-misses (24) — rule-based

The token carries a qualifier the grammar rejects. Rule: **strip the qualifier, keep the base
type; where two types are joined, keep the first.**

| Pattern | → |
|---|---|
| `CONTEXT (revised)` / `(final)` / `(narrowed + updated)` (6) | `CONTEXT` |
| `SCOPE (update)` (2) | `CONTEXT` (per § 3.2) |
| `INCEPTION (updated again)` (1) | `INCEPTION` |
| `OUTPUT (revised)` (1) | `OUTPUT` |
| `DESIGN (locked)` (1) | `OUTPUT` |
| `SESSION: Image 5 (Tomasz Syczyk) appended` (1) | `SESSION` — qualifier moves into the summary |
| `CORRECTION + SCOPE` (1) | `CONTEXT` |
| `CONTEXT + DEPENDS-ON` (1) | `CONTEXT` |
| `DECISION + SCOPE` (1) | `DECISION` |
| `RESOLVED + REFERENCE` (1) | `DECISION` |
| `MERGED & RETIRED` (1) | `CASCADE` |
| `SOURCE+COMPLETION` (1) | `SOURCE` |
| `BACKFILL + REFINE` (1) | `PROGRESS` |
| `AMENDMENT 2` / `3` / `4` (3) | `CONTEXT` — the ordinal moves into the summary |
| `#improvement_candidate` (1) | `CONTEXT` |
| `Q-2` (1) | `Q` |
| `q_question` (1) | `Q` |
| `Izabela Jelonek` (1) | `CONTEXT` — no type at all; the name moves into the summary |

## 5. Malformed titles (14) — need a delimiter, and three need a summary

Rule: insert the missing ` — ` delimiters, strip parentheticals from the date, keep the existing
prose as the summary.

| note_id | Current | Proposed |
|---|---|---|
| `116751121` | `2026-04-06 OUTPUT: Agent Memory File Store — System Documentation` | `2026-04-06 — OUTPUT — Agent Memory File Store: System Documentation` |
| `116751122` | `2026-04-06 FILING: System Documentation → Agent Memory` | `2026-04-06 — OUTPUT — System Documentation filed to Agent Memory` |
| `116960856`, `116960858` | `2026-04-19 SOURCE — Image 4 (Simon Meek's tree) walk-through` | `2026-04-19 — SOURCE — Image 4 (Simon Meek's tree) walk-through` |
| `116960859` | `2026-04-19 SESSION — Image 4 (Simon Meek) additions` | `2026-04-19 — SESSION — Image 4 (Simon Meek) additions` |
| `116960954` | `2026-04-19 — SOURCE: Image 5 (Tomasz Syczyk's tree)` | `2026-04-19 — SOURCE — Image 5 (Tomasz Syczyk's tree)` |
| `116961006`, `116961007` | `2026-04-19 SOURCE — Image 6 (Roshni Vincent's tree) walk-through` | `2026-04-19 — SOURCE — Image 6 (Roshni Vincent's tree) walk-through` |
| `116961011` | `2026-04-19 SESSION — Image 6 (Roshni Vincent) — running total 9 …` | `2026-04-19 — SESSION — Image 6 (Roshni Vincent): running total 9 …` |
| `117568815`, `117568818` | `2026-05-26 (later) — STATE — 2-week interim renewal landed …` | `2026-05-26 — STATE — 2-week interim renewal landed …` |
| `117107570` | `2026-04-28 — Candidate review: Mattie McDonagh (HIRE)` | `2026-04-28 — CONTEXT — Candidate review: Mattie McDonagh (HIRE)` |
| `117763012` | `2026-06-09 catch-up confirmed — resolving` | `2026-06-09 — PROGRESS — catch-up confirmed, resolving` |

**One needs a decision:** `116960677` is the bare string `2026-04-19 INCEPTION` — a date and a
type with **no summary at all**. The shape gate requires a non-empty summary, so a summary must
be synthesised from the note body. Proposed: `2026-04-19 — INCEPTION — project inception`, unless
you would rather I read the body and draft something specific.

## 6. Execution plan — once signed off

1. **Dry run.** Compute all ~152 `(note_id, old_title, new_title)` triples and write them to a
   TSV for eyeball review. No API call.
2. **Verify the new titles pass the gate** — every proposed title through
   `note_shape.check_title` *and* the vocabulary check, offline, before any write.
3. **Write in batches of 20**, recording every `transaction_id`. `edit_note` on the
   title-changing path preserves the body; the body is re-sent verbatim, unmodified.
4. **Read back a sample** after each batch and diff against the intended title.
5. **Undo path:** `batch_undo` over the recorded transaction ids, in reverse order.
6. Only then tighten the vocabulary gate, which is the point of the exercise.

**Risk to name plainly:** RTM stores a note as `title\nbody`, so a title rewrite is a full-note
rewrite. A bug in the body-preservation path corrupts the note rather than mis-titling it. Step 3
re-sends the body verbatim and step 4 checks it — but this is why the dry run is not optional.

## 7. Provenance

Census run 2026-07-31, read-only, full coverage of every list with notes:

| List | Tasks | Notes (raw) | Notes (distinct) |
|---|---:|---:|---:|
| AI_Questions | 118 | 180 | 180 |
| AI_Activity | — | 69 items | — |
| Inbox_Stuff | 359 | 974 | 974 |
| Processed | 1,436 | 3,607 | 3,342 |

TSVs retained under `outputs/_measure/`: `census_inbox_full.tsv`,
`processed_note_titles_census.tsv`, `all_inbox.tsv`, `all_proc.tsv`.

Note counts reconcile against RTM's own `notes_count` for every task, so coverage is provable
rather than assumed. Processed was swept with read-only MilkScript (`getTasks` → `getNotes` →
`getContent`) because per-task fetching 1,286 taskseries was infeasible at 0.9 req/s; that path
was validated against 283 notes fetched via `get_task_notes`, byte-for-byte.

---
*Created: 2026-07-31 | Source: full read-only census of live RTM note titles, 2026-07-31; hand-off brief `note-type vocabulary promotion` (2026-07-30); rtm-mcp `surface_queue.py` / `gtd_writes.py` / `note_shape.py` at b4d47d3*
