---
report_type: handback-debrief
title: rtm-mcp v4.1.0 — the two receipt refinements (registry rename + guidance narrowing)
target_repo: rtm-mcp
brief: general/plugin-marketplace-architect/handoff-briefs/2026-07-26-rtm-mcp-receipt-refinements-brief.md
predecessor_debrief: 2026-07-26-rtm-mcp-teaching-receipts-debrief.md
raised: 2026-07-26
status: implemented — siblings unblocked
---

# Handback debrief — receipt refinements (v4.1.0)

> **Both refinements landed exactly as specified, and both were cheap.** Change 1 moved **zero
> fingerprints**, as the brief predicted. Change 2 cut `guidance` emissions from **62 to 6** across
> the same 162 governed-write calls. Two things to read before the siblings start: a **v4.0.1
> bugfix** that CI caught between the two debriefs, and one honest negative result about the branch
> we kept.

## 0. What happened between the debriefs — v4.0.1

**v4.0.0 was pushed with a bug that only exists on Python 3.11/3.12.** CI caught it; the local gate
(3.14) structurally could not.

`_with_receipt` composed each governed write's advertised description from the raw `fn.__doc__` and
appended an unindented receipt block. **Python 3.13+ dedents docstrings at compile time; 3.11 and
3.12 do not** — and appending an unindented block drops `inspect.getdoc`'s common-prefix dedent to
zero, so on those versions every line kept its source indentation. `gtd_item_set_redaction` measured
**1,946 bytes on 3.14 vs 2,106 on 3.12**, which broke the description-budget assertion *and* the
committed fingerprints. **All 25 governed writes were affected.**

Fixed by composing from `inspect.getdoc(fn)`. Verified by hashing `inputSchema` + `description` for
all 100 tools under 3.12 and 3.14: **zero differences**. Two guards added, both confirmed to **fail**
on the reverted form under 3.12.

**Carry to the siblings, as a sixth lesson:** *any server appending to a docstring must normalise
first, and must run CI on the oldest supported version to see this at all.* It is invisible on 3.13+.
My first attempt at the guard was also wrong — it asserted "no deeply-indented line", but a two-level
`Args:` continuation is legitimately 8 spaces after a correct dedent. The working guard measures the
**minimum** indentation once the appended block is removed.

## 1. Change 1 — the registry's stated purpose

Done exactly as briefed: the module and enum docstrings now read "every machine-branchable
**outcome** — failures and non-failure results alike", and the structural discriminator is recorded
prominently:

> a code in `not_applied[].reason` → an **outcome**; a code in `error.code` → a **failure**.
> The field, not the registry, carries the distinction.

No member renamed or moved, no `OutcomeCode` registry, no wire value changed. **Zero fingerprint
churn, verified** by diffing the `tools` map across a regeneration. The existing `# outcome` block
and the test asserting those three never reach `error.code` are kept — that test now enforces the
discriminator rather than papering over a mislabel, and its docstring says so.

Lockstep: `CLAUDE.md`'s `error_codes.py` row and `CONTRIBUTING.md` § 5 both quoted the old purpose
and were updated. § 5 gains an explicit bullet stating the discriminator.

## 2. Change 2 — `guidance` narrowed

Emitted now **only** on the partial-write and `not_applied` branches. Severity ordering unchanged
(partial write outranks `not_applied`; a test pins it).

**Re-measured over the same population as the trial** (every governed-write call in the tool suite,
162 calls):

| | v4.0.0 | v4.1.0 |
|---|---|---|
| `guidance` emitted | 62 (38%) | **6 (3.7%)** |
| of which full-rejection restatements | 56 | 0 |
| of which genuinely informative | 6 | **6 (all of them)** |

The advisory is unaffected at 17.3%.

**The honest negative result.** The partial-write branch — the one held up in the trial debrief as
*justifying the field* — **fired zero times** in the suite. It is covered by unit tests, but no
integration scenario exercises a mid-batch RTM failure. So the empirical case for keeping `guidance`
currently rests entirely on the `not_applied` branch; the partial-write branch is reasoned, not
observed. Worth knowing before three servers copy it.

**Two drops, one of them a consequence rather than an instruction.** The brief said to drop the
full-rejection branch. It said "emit ONLY on the partial-write and `not_applied` branches", which
also drops the bare zero-applied case — `applied: []` is the statement, so by the brief's own
principle it is a restatement. I implemented that reading.

> **⚠ Flagged consequence.** v4.0.0's guidance was what made an explicitly-empty payload
> (`items=[]` — still legal after the tightening, since only *absence* is rejected) visible. It
> now carries no interpretive signal at all: `applied: []`, `not_applied: []`, `guidance: null`.
> The v4.0.0 debrief § 2d relied on that branch when I declined to reject empty payloads. If that
> visibility mattered, the options are to restore the zero-applied branch or to reject empty
> payloads outright — **a decision I have deliberately left open rather than taken.**

Tier-2 prose (`tool_help.RECEIPT_CONTRACT`) updated to describe the narrowed behaviour, so the
advertised contract and the code agree. No schema change (`guidance` was always `str | None`), hence
no fingerprint churn from this change either.

## 3. Did the narrowing change any existing test's meaning?

Yes, and deliberately — `TestGuidance` was rewritten rather than extended:

- `test_rejection_outranks_everything` **deleted**; replaced by `test_silent_on_a_full_rejection`,
  which asserts the opposite. That inversion is the change, and leaving the old name asserting a
  weaker property would have hidden it.
- `test_zero_applied_is_reported` **inverted** to `test_silent_on_a_bare_zero_applied_response`,
  carrying the flagged consequence above as a comment.
- Added `test_partial_write_outranks_not_applied` — ordering was previously implicit.

No other test changed meaning. Suite: **1653 → 1693** across v4.0.0/v4.0.1/v4.1.0.

## 4. Test results

`make test` **1693 passed** on **3.14, 3.12 and 3.11** (all three run explicitly after v4.0.1 —
version parity is now part of my own gate, not just CI's). `make naming --strict` no findings.
`ruff check` / `format --check` clean. `pyright src` **0 errors**. `make fingerprints` regenerated;
`tools` map **byte-identical** to v4.0.1. Real stdio wire-verify: 6/6.

## 5. Follow-ups carried forward

- **Empty-payload visibility** (§ 2) — open decision.
- **Partial-write branch is unobserved** (§ 2) — an integration test that fails an op mid-batch
  would close it.
- Unchanged from the trial debrief: live governed-write verification not run; `_registry` in
  `tools/gtd.py` is dead code; **re-render standing board artifacts** after activation (the
  rendered-artifact risk the architect flagged — the eight tightened parameters appear 6 times in
  `project-plan-artifact.html`, and a rendered board is a live caller no grep can see).

## 6. Siblings — the lessons to carry

The trial's five, plus one from v4.0.1:

1. `is_facet` from day one — booleans are not facets.
2. The registry question is answered: one registry, discriminate on the field.
3. `guidance` narrow from the start — partial-write and `not_applied` only.
4. Audit `applied.append(` with a null transaction **as work, not discovery**.
5. Cost the description block against the ~2 KB budget up front.
6. **NEW —** normalise a docstring before appending to it, and run CI on the oldest supported
   Python, or this class of bug is invisible.

Plus the test-harness hazard: entering `Client(mcp)` runs the real lifespan and overwrites the
client global, so patching it beforehand silently sends the call to the live account.

## 7. Activation

Restart on **v4.1.0**. Vault-free, no new tag, no schema change, no fingerprint churn since v4.0.1.
Both changes are reverts if unwanted.
