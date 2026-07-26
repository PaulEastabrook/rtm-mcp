---
report_type: handback-debrief
title: rtm-mcp v4.0.0 — the teaching receipt + eight tightened parameters (TRIAL)
target_repo: rtm-mcp
designed_change: general/plugin-marketplace-architect/designed-changes/2026-07-26-tool-receipts-and-parameter-tightening.md
brief: 2026-07-26-rtm-mcp-teaching-receipts-brief.md
raised: 2026-07-26
status: implemented — awaiting review; family rollout gated on this debrief
rollout: TRIAL — rtm-mcp only. The three sibling servers were explicitly out of scope.
---

# Handback debrief — teaching receipts and parameter tightening (TRIAL)

> **Headline.** Both pieces landed. The receipt is attached centrally to all 25 governed writes and
> is schema-transparent (measured, with a control). The eight parameters are required. **The two
> most useful findings came from measuring rather than reasoning**, and both changed the design:
> the advisory shipped with two bugs that made it fire on 82% of calls, and — after the parameter
> tightening — it turned out the two pieces *interact*, pushing two tools to firing on 100% of
> legitimate calls until a correctness rule was added. Final rate: **17.3%**.
>
> **Recommendation: proceed to the family, with the `is_facet` rule included from the start.**
> One narrowing is proposed below; one question is answered "not proven and not provable here".

## 1. What landed

**Piece A — the three-part receipt.** Every governed `gtd_*` write (25 tools) returns:

| Field | Behaviour |
|---|---|
| `not_applied[]` | `{op, id, requested, reason, detail}` per requested op that wrote nothing. **Always present, `[]` when clean.** |
| `guidance` | One next step when the outcome was not a clean full success. `null` otherwise. |
| `advisory` | Set when the call carried **none** of the tool's optional value-bearing parameters, naming them. |

Attached by `tools/gtd.py::_tool` via the new pure-leaf `receipt.py`, **not** at 25 call sites — the
same reasoning as one `RejectUnknownParameters` middleware over 99 per-tool configs. A governed write
added later gets a receipt, its description block, and its output-schema fields by the act of being
registered.

`not_applied[]` is populated at four real no-write sites: `gtd_engage_commit` (`keep`/`do_now`
verdicts; duplicate STEER note), `gtd_canvas_commit` (`execute:"off"` with nothing to clear),
`gtd_item_transition` (tags already present / already absent — the designed change's canonical
example), `gtd_item_stamp_tokens` (a non-repeating project).

**Piece B — eight parameters tightened.** All eight now advertised `required` and non-nullable,
verified over real stdio.

**Three new `ErrorCode` members** — `no_change`, `no_durable_write`, `not_eligible` — as the
`not_applied[].reason` vocabulary: the *fourth* scoped view of the one registry.

## 2. Deviations from the brief — each with its reason

**(a) The registry's meaning was widened, deliberately.** The brief says `reason` draws from the
existing `ErrorCode` registry. It does — but `error_codes.py` is documented as "every
machine-branchable **failure**", and a `no_change` is not a failure. I followed the brief (one
vocabulary, not two) and recorded the widening explicitly in an `# outcome` block in the enum and in
a test asserting these three never appear as an `error.code`. **If the family disagrees, the fix is a
separate registry, and it should be decided before three more servers copy this.**

**(b) Two entries moved OUT of `applied[]`.** The brief says "no field removed or renamed"; this
removes no field but does change one array's *contents*. In `gtd_engage_commit`, a `keep`/`do_now`
verdict and a skipped duplicate STEER note were being appended to `applied[]` with
`transaction_id: None` — the latter literally labelled `"(skipped, duplicate)"` **inside the applied
list**. Leaving them there while also adding `not_applied[]` would have stated the same fact twice
and left `"Applied N write(s)"` counting non-writes. Given the change's own one-truth-per-fact
principle and a major bump already in hand, I moved them. **This is the one consumer-visible change
beyond "additive" — flagged prominently rather than buried.**

**(c) The receipt is documented on three surfaces, which the brief did not ask for.** Paul asked
mid-implementation whether anything tells a calling LLM what these fields are *for*. It did not —
and neither did `applied[]`, which has shipped for many versions with its *shape* documented and its
*purpose* nowhere. Added: one sentence in the server `instructions` (tier 1), a ~190-byte block on
each governed write's description (appended by the same central wrapper), and the full contract in
`rtm_tool_help` (tier 2, no budget). None restates another, per CONTRIBUTING § 3's
no-double-authoring rule. **Cost:** the `instructions` had 2 bytes of headroom, so tool enumerations
that `rtm_tool_help()` serves on demand were trimmed to pay for it — final size **2,046 bytes,
unchanged**. Two tools cross the 2 KB description budget solely because of the shared block and are
on the exemption list with that stated.

**(d) `gtd_note_add.body` required, but `[]`-style empty payloads are still accepted** on the batch
tools. The brief tightens *absence*; an explicitly-passed empty list is present-but-empty and still
returns the existing graceful no-op — now carrying `guidance: "Nothing was written…"`, which makes it
visible. Rejecting empty too would be a stricter change than briefed; flagging rather than doing it.

**(e) No live governed write was executed.** The wire-verify drives a real stdio server and proves
schema, rejection, and documentation over the protocol, and an in-process test proves the receipt
survives MCP serialisation against a mocked client. **A governed write against Paul's production RTM
account was not run** — that is a real residual gap, and it is his call whether to close it.

## 3. Test results

`make test` **1690 passed** (was 1653; +37, all in the new `tests/test_receipt.py`).
`make naming --strict` no findings. `ruff check` / `ruff format --check` clean. `pyright src`
**0 errors**. `make fingerprints` regenerated — **all 100 churn**, structurally, from the `ErrorCode`
enum being inlined into every `ErrorBody.code` plus the output-schema and description additions.

**Real stdio wire-verify — all six checks pass:** eight tightened params advertised `required`;
the receipt block on all 25 governed writes; on **none** of the 75 reads; `outputSchema` declaring
all three fields on every governed write; omitting `gtd_note_add.body` rejected over the wire naming
`body`; server `instructions` (2,046 B) carrying the imperative.

**Schema transparency, measured with a control.** The central wrapper could have corrupted every
advertised schema (FastMCP builds them from `inspect.signature`). Input schemas + descriptions were
hashed for all 100 tools against a v3.3.0 git worktree: **zero differences**, with a control
confirming the baseline process genuinely lacked `receipt.py`.

## 4. The four trial questions

### Q1. Did the advisory fire usefully or noisily?

**Measured across every governed-write call in the suite** — the best available proxy for legitimate
calls, since all were written before the advisory existed and none is shaped to trip or dodge it.

| Stage | Rate | Why |
|---|---|---|
| First implementation | **82%** (132/161) | Two bugs (see below) |
| After both fixes | **17.3%** | |
| After tightening (Piece B) | **31.8%** | Payloads became required, leaving control-flag-only optionals |
| After the `is_facet` rule | **17.3%** (28/162) | Booleans excluded |

**Two genuine bugs, both found only by measuring**, and both would have shipped:
1. It fired when *any* optional was absent, not when *all* were — so a call supplying `items` but
   not `confirm_destructive` was flagged. The brief's own wording ("no optional facets at all") was
   right; the code was not.
2. The wrapper read `kwargs` directly, so arguments passed **positionally** were reported absent.
   Harmless over MCP (which always uses keywords) but wrong for every in-process caller.

**The interaction finding is the one to carry to the siblings.** Tightening the payloads left
`gtd_engage_commit` with only `confirm_destructive` and `gtd_note_add` with only `timestamp` — so
both fired on **100%** of legitimate calls. The fix is a **correctness rule, not tuning**: a boolean
is a mode switch, not data, and a stripped boolean gets the call *rejected* (`confirm_destructive`)
or changes documented default behaviour visible in the response (`dry_run`, `timestamp`). It can
never be the silently-lost value the advisory exists for. `receipt.is_facet` excludes booleans; both
tools went to 0%.

**Verdict: useful, not noisy — keep it.** 17.3% is well short of "a majority of legitimate calls".
One tool still always fires (`gtd_note_attach_output`, 3/3, on `output_type`) but the sample is 3.

### Q2. Did `not_applied[]` catch a real case the previous envelope hid?

**Yes — and the sharpest one was hiding in plain sight inside `applied[]`.** `gtd_engage_commit`
appended `{"op": "engage:draft:steer-note (skipped, duplicate)", "transaction_id": None}` **to the
applied list**. A consumer counting `len(applied)`, or reading the tool's own
`"Applied N write(s)"` message, was told a write happened when none had. Same for every `keep` /
`do_now` verdict. That is precisely the class of misreport this change exists to remove, and it was
already shipping.

The other three sites are genuine but quieter: an `execute:"off"` clearing nothing, a
`gtd_item_transition` whose tags were already correct, a `gtd_item_stamp_tokens` on a one-off project.

### Q3. Is `guidance` worth its bytes?

**Yes, but narrowly, and the honest answer is "for one of its four branches".** Measured: emitted on
62 of 162 calls, of which **56 were "Nothing was written — N item(s) failed validation"** — a case
`rejected[]` already makes obvious. If `guidance` were only that, I would recommend dropping it.

It earns its place on the **partial-write** branch, which nothing else states: some ops are durable
and some failed, and the response otherwise looks like a success with a non-empty `errors[]`. A
caller that retries blindly double-applies what already succeeded. `guidance` names it PARTIAL and
points at `batch_undo` with the transaction ids. That is the branch worth the bytes.

**Recommendation:** keep, but consider narrowing to the partial-write and `not_applied` branches for
the siblings, and let `rejected[]` speak for itself. Deliberately not done here — the brief asked
for guidance on "any response that is not a clean full success", and changing that mid-trial would
have left the measurement unattributable.

### Q4. What would you change before three more servers implement this?

1. **Ship `is_facet` from day one.** Without it, tightening + advisory produces 100%-firing tools.
2. **Decide the registry question (§ 2a) first.** Whether outcome reasons belong in the error
   registry or a separate one is a one-line decision now and a four-repo migration later.
3. **Do the `applied[]` audit as part of the work, not as a discovery.** The most valuable thing
   found was a pre-existing misreport *inside* `applied[]`. Each sibling should be grepped for
   `applied.append(` with a null transaction before its receipt is designed.
4. **Budget the description block before writing it.** The receipt block is ~190 bytes × N writes.
   On this server that cost two new exemptions and a paid-for trim of `instructions`. A server with
   less headroom may need the tier-1 block dropped in favour of `instructions` + help alone.
5. **Guard the in-process protocol test.** Entering `Client(mcp)` runs the real lifespan, which
   overwrites the client global — patching it beforehand is silently discarded and **the call goes
   to the live account**. Caught here only because a resolution failed; it could as easily have been
   a write. Both guards are documented in `tests/test_receipt.py`.

**Not answerable here, and stated plainly:** whether a calling LLM *acts* on the receipt. The
mechanism is proven end to end; the behavioural payoff is reasoned, exactly as with front-loading in
v3.3.0. Only the eval tier can settle it.

## 5. Follow-ups (not done, flagged)

- **Live governed-write verification** against the production RTM account — deliberately not run.
- **`_registry` in `tools/gtd.py` is dead** — written, never read; scaffolding the v3.1.0 alias
  removal should have taken. Left alone to keep this diff attributable.
- **Empty-payload calls** (`items=[]`) remain graceful no-ops (§ 2d).
- **`guidance` narrowing** (Q3) if the family agrees.

## 6. Marketplace lockstep

| Node | Obligation |
|---|---|
| `plugin-marketplace-git-ops` | Standard § 3 gains the receipt contract **if this trial is accepted** |
| `plugin-marketplace-architect` | Receipt-conformance audit check, post-trial |
| `gtd` | Assert on `not_applied[]` at governed-write call sites; **note the eight now-required parameters** — a caller omitting one now hard-fails |
| Sibling MCP servers | Gated on this debrief; adopt § 4's five changes if approved |

**Activation:** restart the server on v4.0.0. Vault-free, no new tag, no strict-tag interaction.
Piece A is additive; Piece B is a revert. No one-way door.
