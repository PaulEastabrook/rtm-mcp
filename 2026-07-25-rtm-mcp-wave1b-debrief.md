---
report_type: handback-debrief
scope: gtd-domain-tool-suite / Wave 1b — two tools, one parameter, one rename
implemented_by: claude-code (rtm-mcp repo)
derived_at: 2026-07-25
target_repo: rtm-mcp
artifact: v2.10.0 — 2 new tools (97 total), 1 new parameter, 1 output-token fix, 1544 tests
relates_to:
  - brief: Wave 1b hand-off brief, 2026-07-25
  - designed_change: general/plugin-marketplace-architect/designed-changes/2026-07-25-gtd-milkscript-retirement-designed-change.md
  - predecessor: 2026-07-25-rtm-mcp-wave1-milkscript-retirement-debrief.md
status: needs-restart
---

# Handback debrief — Wave 1b: four remembered-discipline gaps closed

All four items ship on **v2.10.0**. Each replaces a rule a prompt or an agent had to *remember*
with one the server enforces. Additive and backward-compatible throughout: `clear_signal` defaults
to today's behaviour, the `ACTIVITY-REPORT` change affects only newly-written notes, and neither
new tool introduces a tag. **Activation is a server restart on v2.10.0.**

| # | Item | Status |
|---|---|---|
| 1 | `gtd_item_classify` | shipped — offline, reuses the detectors' own compiled patterns |
| 2 | `clear_signal` on `gtd_chat_post` | shipped — default `True`, unchanged behaviour |
| 3 | `ACTIVITY_REPORT` → `ACTIVITY-REPORT` | shipped — mapped, not derived |
| 4 | `gtd_contribution_transition` + `gtd_engine_report` rates | shipped — judged denominator |

---

## 1. Design decisions

### 1.1 The classifier shares the detectors' pattern objects rather than mirroring them

The brief said *"your compiled copy is a lockstep mirror of it"*. There was a better option:
`detectors.py` **already held** these exact arrays for the `gtd_*_candidates` tools, and I checked
them against `shape-patterns.md` line by line before building — they match.

So `classify_shape` lives in `detectors.py` and reuses `RESEARCH_PATTERNS` / `DELIVERABLE_ANTI` /
etc. **by reference**. That makes the contract `shape-patterns.md` states — *"an action the
fan-out classifies as `draft` is one the deliverable detector would have found"* — true **by
construction** instead of by two lists being kept in step. `TestLockstep` asserts the object
identity (`_SHAPE_RULES["draft"][0] is DELIVERABLE_PATTERNS`), so a future copy-paste fails there.

One mirror instead of two is also one fewer thing to drift when the markdown changes.

### 1.2 `clear_signal` defaults to `True`, and the reason is asymmetric

Both failure modes are not equal. Forgetting `clear_signal=False` on an interim note costs a board
poll that stops one step early. Forgetting `clear_signal=True` on a final reply leaves
`#ai_chat_requested` raised forever — the worker never releases the target and the board polls
indefinitely. The default protects against the worse one, exactly as the brief instructed.

`tag_changes` is `[]` for an interim note (nothing was touched) and the response echoes
`clear_signal` so a caller can see which path it took. A `me` turn echoes `null` — the flag does
not apply.

### 1.3 The `ACTIVITY-REPORT` fix is a map, not a string edit

The one-character change would have been to write `"ACTIVITY-REPORT"` at the call site. Instead
there is now `gtd_writes.SURFACE_BODY_NOTE_TYPE`, an explicit `item_type → TYPE token` map, because
the brief's root-cause note is the actual lesson: **the input enum and the output token are
different vocabularies and must be mapped, never derived.** A test asserts the map's keys equal
`SURFACE_ITEM_TYPES` and that `SURFACE_BODY_NOTE_TYPE["activity_report"] != "activity_report".upper()`
— so the derivation cannot creep back.

The test the brief actually asked for is the important one: **every emitted title passes
`note_shape.check_title`**, and the underscore form is asserted to fail it. That the server could
write a title its own validator rejects was the defect; the string was the symptom.

### 1.4 The contribution tool follows the repo's rejection shape, not the brief's

The brief said *"Branch on `data.error.code` per the v2.0.0 envelope"*. The repo's established
shape for a governed single-item write (`gtd_transition_state`, `gtd_surface_resolve`) is
`rejected: [{reason, detail}]` for **validation** rejections and `error.code` for a **resolver
miss**. Per the brief's own § 2 — *where the repo's guidance disagrees on local practice, it wins*
— I followed the repo. Both paths are documented in the tool's `Returns`, and the three reasons
(`off_enum`, `no_contribution_note`, `invalid_input`) come from the canonical `ErrorCode` registry.

One **new** registry member: `no_contribution_note`. Justified under CONTRIBUTING § 5 (reuse first)
because the recovery genuinely differs — there is nothing to transition, so retrying with a
different `state` cannot help. Additive-only discipline respected.

### 1.5 The CONTRIB-UPDATE body diverges from the catalogue, deliberately

The catalogue's CONTRIB-UPDATE **body** grammar (`Update mode: addendum | delta | revision |
stale`, `What shifted:`, `Material to the contribution because:`) is scoped to the **reassessment**
loop — its own *"Created by"* line says so — and its vocabulary does not describe a *judged*
transition. Forcing `accepted` into `Update mode:` would have been a lie.

So the note carries `Original CONTRIB:` / `Transition:` / `State:` / `Kind:` / `Trigger:` always,
and `Update mode:` **only** for the two invalidated states, where the catalogue vocabulary
genuinely maps (`superseded`→`revision`, `stale`→`stale`). The title follows the catalogue exactly
and is asserted to pass `check_title` for every terminal state. **Extending the catalogue to cover
judged transitions is a gtd-side follow-up** (§ 4.1).

---

## 2. What the live data forced

Two changes came from running the parser against all 45 real contribution tasks, and neither was
predictable from the sources.

### 2.1 `current_state` must read the FIRST TOKEN, not the line

Three live `State:` lines carry prose after the state word:

```
State: drafted (production happened in the interactive session — see the two output notes of
       2026-07-04; this scan pass adds the #ai_contrib_drafted state tag so subsequent scans
       de-duplicate)
State: drafted — pending paul's review (#ai_output_review_needed)
State: drafted → offered
```

Whole-line parsing made each an **unrecognised state**. Worse, it silently disagreed with
`engine_report`, whose regex is `^\s*State:\s*(\S+)` — first token. Two components reading the same
field and getting different answers is precisely the class of defect this programme exists to
close, so `current_state` now takes the first token and a test asserts the two **agree** on all
three live shapes.

The third line is worth noting on its own: `drafted → offered` is the `phase` vocabulary leaking
into the note field, exactly as the catalogue's "Retired values" section records.

### 2.2 The discarded prose is preserved, not dropped

`rewrite_state` replaces the whole line, so the machine field ends up clean (`State: accepted`
rather than `State: accepted (production happened…)`, which would have been actively misleading).
But that prose is somebody's annotation, and deleting it on transition would be a quiet data loss —
so `state_remainder` hands it to the CONTRIB-UPDATE note under `Superseded State: annotation:`.

### 2.3 A note with no `State:` line is transitioned anyway

Six live notes have none. The line is **appended** rather than the transition refused: the absence
is the old wiring's fault, not the caller's, and refusing would leave exactly the most-neglected
notes permanently stuck.

---

## 3. Live verification — figures

Read-only, against the production account, through the shipped code paths.

**`gtd_item_classify` over 496 live incomplete actions:**

| Shape | Count | Sample |
|---|---|---|
| `none` | 446 | *"Change phone tariff"* |
| `draft` | 41 | *"Draft the Principal Engineer R&R v0.1"* |
| `research` | 5 | *"Synthesise cohort feedback into Principal Engineer v0.2"* |
| `decide` | 4 | *"Decide whether to process a final dividend before dormancy"* |

The 90% `none` rate is expected and correct — most actions are not contribution-shaped, and the
detectors are equally selective. **Zero live names hit the `evaluate the options` ambiguity**, so
that overlap is real in the vocabulary but currently unexercised in the estate.

**Contribution state machine over all 45 contribution tasks:**

| Measure | Result |
|---|---|
| tasks with a state-bearing CONTRIB/PREP note | 39 (6 have none) |
| observed states | **32 `drafted`, 1 `surfaced`, 6 no `State:` line — zero terminal** |
| `rewrite_state` produced a valid new state | **39 / 39** |
| generated CONTRIB-UPDATE title passes `check_title` | **39 / 39** |
| would be rejected as already-terminal | **0** — every live contribution is transitionable |

This reconciles with the catalogue's own live measurement. Categories resolve too (22 `draft`,
7 `decision`, 3 `research`, 2 `brief`, 1 `capture`, 4 `unknown`), and 34 of 39 carry an artefact
path for the caller's `phase` mirror.

**Surface body-note titles vs the gate:** all five map to a token that passes; the old
`ACTIVITY_REPORT` is asserted to fail.

---

## 4. Found in gtd's sources — reported, not fixed

### 4.1 `shape-patterns.md` contradicts itself on `"Email about X"`

The research anti-pattern `/\bemail\b/i` carries the inline comment `// "Email about X" → draft`.
But the deliverable anti-patterns include `/\bresearch\b/i`, so *"Email about the research"* is
knocked out of **both** shapes and classifies as `none`.

The rules as written produce `none`; the comment says `draft`. I implemented **the rules**, since
they are the machine-readable spec, and the detectors agree (`gtd_deliverable_candidates` would
skip the same name) — so the lockstep contract holds either way. **The comment is aspirational and
should be corrected or the anti-pattern narrowed.** A test pins the current behaviour so the
decision is visible rather than accidental.

### 4.2 The CONTRIB-UPDATE body grammar has no judged-transition shape

See § 1.5. `journaling-lifecycle.md` § CONTRIB-UPDATE is written for reassessment only. The
catalogue needs a judged-transition body shape, or an explicit statement that the transition tool
owns one.

### 4.3 Carried forward from Wave 1, still open

`gtd_reads.parse_note_type` still splits hyphenated types at their own hyphen (`AI-LINK` → `AI`).
`contribution.py` and `surface_queue.py` each use their own whitespace-anchored regex to avoid it;
fixing the shared helper would change `gtd_context` output, so it still wants its own change.

### 4.4 A Wave 1 refinement I did **not** make

`note-shape-catalogue.md`'s new legacy sweep lists the live "response" spellings as `ANSWER` (4),
`RESPONSE` (1), `REPLY` (1), `RESOLVED` (1), `RESOLUTION` (1). `surface_queue.RESPONSE_NOTE_TYPES`
covers the first three plus `DECISION`, but not `RESOLVED` / `RESOLUTION` — 2 notes estate-wide.
Adding them would marginally improve `response_detected` recall. Out of scope here (it changes
shipped Wave 1 behaviour); flagged for a decision.

---

## 5. Verification — what was run, and what was NOT

**Run and passing:**

- `ruff check` + `ruff format --check` + `pyright src` — **0 errors, 0 warnings**.
- `pytest` — **1544 passed** (from 1391; +153).
- `make fingerprints` — 97 tools, `source_version 2.10.0`; freshness guard passing.
- **Live read-only verification** of items 1, 3 and the whole *parse* half of item 4 against the
  production account, through the shipped tool functions with a real `RTMClient` (§ 3).

**Explicitly NOT done — read this before assuming coverage:**

- **No live WRITE was performed.** `gtd_contribution_transition` and `gtd_chat_post(clear_signal)`
  are both writes to Paul's real task system — mutating a real CONTRIB note and posting real chat
  notes. I verified everything short of the write: the parse against all 39 live notes, the
  rewrite **simulated** on each real body and asserted, and the generated titles checked against
  the real gate. The `notes.edit` / `notes.add` calls themselves have been exercised only against
  mocks. **If you want a live write, say so and I will run one against a `#test`-tagged scratch
  task and clean it up.**
- **The tools have not been called through a restarted MCP server** — the live run invoked them
  in-process. A restart is still required before any consumer can call them.
- **No gtd-side consumer wiring** (`progression-fanout` → classify; `chat-worker` → `clear_signal`;
  `action-executor` / `completion-workflow` / `reassessment` → transition). Marketplace-repo work.

---

## 6. Conventions

| § | Applied |
|---|---|
| § 2 | Both new names conform to the CQS + aggregate-grouped standard frozen in Wave 1 — `gtd_item_classify` (area `item`, single-entity), `gtd_contribution_transition` (area `contribution`, command named for the operation) |
| § 3 / § 7 | Six documentation surfaces on both; `state` carries a canonical-constant-sourced enum asserted equal to `TERMINAL_STATES` (and asserted NOT to contain the open state) |
| § 5 | One new `ErrorCode` (`no_contribution_note`), additive-only; the other two reasons reused |
| § 8 | Pure-module tests + `FakeMCP` tool tests + a nothing-was-written assertion on every rejection path |
| § 9 | All four touchpoints + test inventory (reconciled to 1544 exactly); fingerprints regenerated |
| § 10 | Minor bump 2.9.0 → **2.10.0** across `pyproject.toml`, `__init__.py`, `uv.lock` |
| § 11 | Quality gate passed |

**Not touched:** CONTRIBUTING § 7's `from __future__ import annotations` rule. Wave 1 flagged it as
stale and Paul has not ruled; `contribution.py` follows its pure-module siblings.

---

## 7. Open items

**gtd (marketplace repo):** the consumer wiring above; the two catalogue corrections in §§ 4.1–4.2;
the Wave 1 carry-overs in §§ 4.3–4.4.

**rtm-mcp:** a live write-path exercise if wanted (§ 5); the `parse_note_type` fix (§ 4.3).

**Consumer (board / artifacts) — no action.** Nothing they call changed shape or default.

---

## 8. Durable lesson

**Two components reading the same field must be proven to agree, not assumed to.** The `State:`
line is read by `engine_report` (first token) and now by `contribution` — and my first
implementation read the whole line. On 36 of 39 live notes the two were identical; on 3 they
silently diverged, and nothing in either module's tests would have caught it. The fix was cheap;
finding it required running the parser over the real estate rather than over fixtures I had
written myself. **Fixtures encode what you already believe.**

The corollary, which this wave demonstrates twice: *the input vocabulary is not the output
vocabulary* (`activity_report` ≠ `ACTIVITY-REPORT`), and *the machine field is not a place for
prose* (`State: drafted (production happened…)`). Both are cases of a value being reused across a
boundary where it was never validated.

---

*Source of truth: `CLAUDE.md` § "Wave 1b — closing four remembered-discipline gaps (since
v2.10.0)" + the module docstrings in `contribution.py` and `detectors.py` (`classify_shape`), and
the tool docstrings in `tools/gtd.py`. Provenance: Wave 1b hand-off brief 2026-07-25;
`shape-patterns.md`, `chat-worker.md` § 3.6, `note-shape-catalogue.md` § 2 and
`journaling-lifecycle.md` § "The contribution state machine" (gtd v0.186.0); live measurement of
Paul's production account 2026-07-25.*
