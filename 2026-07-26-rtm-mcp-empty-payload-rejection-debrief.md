---
report_type: handback-debrief
title: rtm-mcp v5.0.0 — empty-payload rejection + the partial-write branch observed
target_repo: rtm-mcp
brief: general/plugin-marketplace-architect/handoff-briefs/2026-07-26-rtm-mcp-empty-payload-rejection-brief.md
predecessor_debrief: 2026-07-26-rtm-mcp-receipt-refinements-debrief.md
raised: 2026-07-26
status: implemented — siblings unblocked
---

# Handback debrief — empty-payload rejection (v5.0.0)

> **Both items landed.** All eight reject `[]` / `{}` / `""` naming the parameter and writing
> nothing; the four out-of-scope categories are asserted intact, `rtm_tool_help()` included. The
> partial-write `guidance` branch is now **observed** rather than reasoned. Bump: **v5.0.0**, per the
> repo's own rule. Two findings worth reading — five of the eight already rejected empty, and my
> first implementation masked an unrelated validation error.

## 1. Version bump — v5.0.0, and the reasoning

`CONTRIBUTING.md` § 10: *"breaking envelope/signature changes → major."* Rejecting a call the server
previously accepted is breaking by exactly the reasoning that made v4.0.0 major — a caller doing this
today gets a success and will now get a rejection. **The rule decides, not the size of the diff**, so
v5.0.0 it is. Recording the discomfort honestly: three majors in one day is unusual, and the
alternative reading (that v4.0.0 had already declared the class breaking, making this a continuation)
was considered and rejected — v4.0.0 shipped, and a shipped contract is what a bump is measured
against.

## 2. Item 1 — present-but-empty payloads

All eight reject with `missing_parameter`, name the parameter, and perform **zero writes**
(asserted on `require_timeline=True`, the single marker every write carries).

Implemented **once**, as `gtd_writes.check_payload`, generalising the rule `validate_transition`
already applied to `add_tags`/`remove_tags` and **reusing `MISSING_PARAMETER`** — no new registry
member, so no 100-tool fingerprint churn. Whitespace-only strings count as empty (`body="   "` is
contentless by the same argument); flagged as slightly beyond the literal brief.

### Two findings

**(a) Five of the eight already rejected empty — the work was smaller than it looked.**
`validate_inbox_zero` / `validate_chase_sweep` / `validate_consolidate` already emitted
`missing_parameter` for an empty set; `gtd_item_transition_batch` refused an empty `items`; and
`gtd_project_create` failed downstream via focus resolution. Only three were genuinely silent:
`gtd_engage_commit` (the graceful no-op), `gtd_note_add` (empty body accepted), and
`gtd_inbox_item_close` (empty `derived_refs` accepted).

That produced a real design question the brief did not anticipate: **my first implementation
duplicated the rejection** on the three overlapping tools (two `missing_parameter` entries, one
naming the parameter and one not). Resolved by using `or` where a validator already covers the
empty case and `+` where it does not — documented at the call sites.

**(b) My first implementation masked an unrelated error.** With `or` semantics on `gtd_note_add`, a
call with *both* a bad `note_type` and an empty `body` reported only the body — and an existing test
caught it. `validate_add_note` has no empty-body rule of its own, so the two checks are
**complementary**: the caller should learn both in one round trip. That tool uses `+`.

### Two behaviours improved in passing

- `gtd_item_transition_batch` refused an empty `items` **after** a read. It now returns before it —
  a gate that still spends an API call is not a gate (CONTRIBUTING § 6).
- `gtd_project_create` reported the missing `frame.focus`, which reads as "one field is wrong" when
  the whole payload is absent. It now names `frame`, and rejects **before** the read.

### The question the brief told me to answer

**No in-repo engine relied on the graceful no-op.** This server has no internal callers of these
eight — every source match is prose, models, or help text — and **no test asserted the old
behaviour** (grepped for `"No items supplied"` / `"provide at least one item"`: zero hits in
`tests/`). So the counter-argument the brief recorded does not bite *here*. It may still bite
gtd-side, where I cannot see; the rendered-artifact risk from the v4.1.0 debrief applies unchanged.

### Out of scope — asserted, not assumed

All four categories have tests, and `rtm_tool_help()` is verified **over real stdio** as well as by
schema: no-arg still returns the 47 KB whole-server index. It has no required parameter and never
gained one.

## 3. Item 2 — the partial-write branch is now observed

Added an integration test: `gtd_engage_commit` over two items where the **second write fails**
mid-batch. Asserts `applied[]` non-empty, `errors[]` non-empty, `guidance` present naming **PARTIAL**
and `batch_undo`, and — the assertion that makes the advice followable — that the transaction ids
needed to reverse it are actually in the response.

**Worth recording:** the first attempt used a non-existent task id for the second item, and engage's
hard-fail ACL correctly rejected the *whole batch*, leaving no partial state. The test only exercises
what it claims because both ids exist and both verdicts are legal for their kind — noted in the test,
since the same trap awaits each sibling.

**Re-measured `guidance` emission rate** (174 governed-write calls):

| | v4.1.0 | v5.0.0 |
|---|---|---|
| emitted | 6 (3.7%) | **7 (4.0%)** |
| of which partial-write | **0** | **1** |
| of which `not_applied` | 6 | 6 |

The branch that justifies the field now fires. Advisory unaffected at 16.7%.

## 4. Test results

`make test` **1710 passed** (was 1693; +17) on **3.14, 3.12 and 3.11** — version parity is part of
my gate since v4.0.1, not just CI's. `make naming --strict` no findings. `ruff check` /
`format --check` clean. `pyright src` **0 errors**. Fingerprints regenerated: **2 tools churn**
(`gtd_engage_commit`, `gtd_project_create` — their `rejected[].reason` enums gained
`missing_parameter`), which is attributable rather than global.

**Stdio wire-verify 8/8**, now including: an empty `verdicts=[]` rejected over the wire naming the
parameter, and `rtm_tool_help()` no-arg still returning the index.

`check_payload` is registered in `_HELPER_CODES`, so the advertised-error-contract guard knows it
surfaces `missing_parameter` on a tool's behalf — which then forced two docstrings
(`gtd_engage_commit`, `gtd_project_create`) to document the new rejection. That is the lockstep
working as designed.

## 5. Follow-ups carried

- **Re-render standing board artifacts** after activation — unchanged and now more pointed: the
  eight parameters appear 6× in gtd's `project-plan-artifact.html`, and a rendered board is a live
  caller no grep can see. A board that computes an empty set now gets an error, not a no-op.
- Live governed-write verification against the production account — still not run.
- `_registry` in `tools/gtd.py` is dead code (v3.1.0 alias-removal scaffolding).

## 6. Siblings — unblocked, with seven lessons

1. `is_facet` from day one — booleans are not facets.
2. The registry question is answered: one registry, discriminate on the field.
3. `guidance` narrow from the start — partial-write and `not_applied` only.
4. Audit `applied.append(` with a null transaction **as work, not discovery**.
5. Cost the description block against the ~2 KB budget up front.
6. Normalise docstrings before appending, and run CI on the **oldest** supported Python.
7. **NEW —** before adding an empty-payload rule, check which validators **already** reject empty:
   here five of eight did, and a naive addition both duplicated rejections and masked an unrelated
   error. Use `or` where the validator overlaps, `+` where it complements.

Plus the harness hazard: entering `Client(mcp)` runs the real lifespan and overwrites the client
global, so patching it beforehand silently sends the call to the live account.

## 7. Activation

Restart on **v5.0.0**. Vault-free, no new tag, no new `ErrorCode`. §§ 1–2 are reverts if unwanted.
