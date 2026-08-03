---
report_type: handback-debrief
scope: one durable entity handle on the gtd_* reads, and one door for occurrences
implemented_by: rtm-mcp (Claude Code session, 2026-08-03)
derived_at: 2026-08-03
target_repo: rtm-mcp
artifact: v6.9.0 (branch feat/entity-handle; see CHANGELOG.md v6.9.0)
relates_to:
  - brief "one entity handle, and one door for occurrences (rtm-mcp)", 2026-08-03
  - designed change general/plugin-marketplace-architect/designed-changes/2026-08-02-vault-naming-mirrors-rtm.md § 1a.4
  - rtm-mcp v6.8.0 handback (repeat_kind) — this consumes AND partially retracts it
status: needs-restart
---

# Handback — `entity_id` + `recurring`, and `list_task_occurrences` (v6.9.0)

**Both pieces shipped as specified.** Two of the brief's stated facts and one of v6.8.0's own
documented claims turned out to be **false on live data**; all three are corrected here with
measurements. Nothing in the delivered contract changed as a result — the handle rule is exactly
what the brief specified — but a test written to either false premise would have been wrong, and
one such test was already in the suite.

## What shipped

**Piece 1 — one handle.** `entity_id` (string, never empty) and `recurring` (real bool) on
`gtd_project_plan` (header + every row), `gtd_project_canvas` (frame + every seed item),
`gtd_project_index` (project, focus **and** action rows), `gtd_item_context` (the task view), and
on `format_task` so the generic tier carries it too.

| Case | `entity_id` | `recurring` |
|---|---|---|
| one-off | its own `task_id` | `false` |
| `every` repeat | its `taskseries_id` | `true` |
| `after` occurrence | its own `task_id` | `false` |

Derived once in `parsers.entity_handle` and read from there by every surface, so no two reads can
disagree. `taskseries_id` is retained wherever it already appeared.

**Piece 2 — one door.** `list_task_occurrences(taskseries_id, list_id=None,
include_completed=True)` — read-only, generic tier, one `getList`. Returns
`{taskseries_id, list_id, name, is_repeating, repeat_kind, entity_id, recurring, count,
current_count, occurrences: [{task_id, due, completed, current}]}`, oldest-first, deleted excluded.

## Design decisions & deviations

**`gtd_project_index` does carry the handle** — the brief left this to my judgement and I agree
with its view. The index deliberately carries neither `is_repeating` nor `taskseries_id` because
there is nothing there for a kind to qualify, but `entity_id` is a *domain handle*, not an RTM
internal, and the cockpit is precisely where a consumer resolves a project to its vault folder.
It is on all three collections, foci included — the vault has a focus tier, and the rule is applied
uniformly rather than special-cased (an area never recurs in practice, so its handle is its own id).

**Scope: four reads, not twenty.** The identity-bearing ones. Detector and candidate reads
(`gtd_*_candidates`, `gtd_engage_seed`, `gtd_next_actions`, …) are deliberately untouched: they
return work-lists, and their consumer goes to the plan or to `gtd_item_context` for identity.
Fanning the field onto every row-returning read would churn ~20 fingerprints for no consumer.
**If a coverage gap emerges, that is the list to extend.**

**`taskseries_id` was NOT removed, and this is the one place I stopped short of "wrap, not merely
expose."** Removing it is breaking; the gtd `series_guard` genuinely needs it on the envelope; and
on `gtd_item_context` I have no evidence either way about consumers. An additive change is
reversible, a removal is not. Its removal is naturally sequenced with the generic-tier exclusion
you will signal — **that is the follow-on that completes the wrap**, and it is yours to trigger.

**One guard the brief did not specify.** An `"every"` classification with no usable `taskseries_id`
degrades to `(task_id, False)`. Structurally unreachable — the `rrule` hangs on the very taskseries
whose id it is — but the direction is chosen deliberately: `recurring=False` on a truly recurring
item costs a folder per occurrence (ugly, recoverable), whereas `recurring=True` on a re-keying id
is the silent-wrong-identity failure the field exists to prevent. It buys a checkable invariant,
asserted in-suite and verified live over 3,043 tasks: **`recurring` is true iff `entity_id` is the
taskseries id.** This does not contradict the brief's "derive it from `repeat_kind`, do not
re-derive it from the presence of an id" — `repeat_kind` is still the discriminator; the id
presence is only a can-I-honour-it guard.

**`list_task_occurrences` takes one read, not two.** RTM's search syntax has no taskseries
operator, so a two-phase locate-then-narrow was considered and dropped: it needs `name:"…"`
filter-quoting, which is fragile on real names, and it adds an unreachable-branch problem for
fully-completed series. One `getList` plus a client-side match is simpler and correct in every
case; `list_id` is the cost knob and is pinned by test as reaching the wire.

## Three claims measured FALSE

**1. v6.8.0's "free, sound cross-check" is retracted — this repo's own claim.** It said a
taskseries holding ≥2 tasks is *provably* `every`, since an `after` recurrence cannot produce two
tasks in one series, and that this was "verified over the whole account." It was verified over
`status:incomplete` — 1,162 of the account's 44,730 tasks. Over all of them, **11 `after` series
hold ≥2 tasks**, the largest **86** deep (`226592019` "Taken protein shake?", every task carrying
`every="0"`). An `after` series accumulates its completed occurrences exactly as an `every` one
does; what re-keys is the series a *new* occurrence lands in, not the history already recorded.
The subset held only because an `after` series has at most one **open** occurrence — the next is
minted on completion — which is exactly what made the subset unrepresentative of the property.

Nothing executable depended on it. But it was offered to callers in a docstring, and a caller who
implemented it would mis-classify 11 series. **The test that "covered" it asserted
`repeat_kind({"every": "1"}) == "every"`** — it could not have failed whatever the live data said.
That is how the claim shipped behind a green suite; it is now pinned by the real counter-example.

**2. Counting is unsound in the other direction too.** **325** live series that do not repeat at
all hold ≥2 tasks — one 31 deep (`147643653`, an old weekly review) — because deleting a recurrence
rule leaves its occurrences behind. So the brief's *"a one-off → one occurrence. Legal and
unremarkable"* is false, and a test asserting it would have been wrong. `rrule/@every` is the only
discriminator, in both directions.

**3. `current` is not singular** — the brief was right, and it is confirmed live through the
shipped tool: `File company accounts` (476408903) returns `count=4, current_count=2`.

## Membrane / activation

Pure RTM data — **vault-free, no new tag, no gate, no strict-tag interaction, no new `ErrorCode`**
(a series miss reuses `TASK_NOT_FOUND`; a new member would re-fingerprint all 103 tools). Additive
and backward-compatible: no existing field changed name, type or value.

**To go live: restart the MCP server on v6.9.0.** No ordering hazard, nothing to provision.
Rollback is a revert.

## Verification done

- **`make test` — 2,080 passed, 0 failed, 0 skipped** (47 new tests). `make lint` clean (ruff
  check + format, pyright 0 errors), `make naming` clean, `make fingerprints` regenerated.
- **Mutation-tested: 15 of 15 mutants killed.** Every new guard was broken deliberately and the
  suite confirmed to fail. One survived the first pass — a `build_actions` mutation that
  re-derived the handle instead of reading it off the envelope — because the fixture had no
  `every`-repeating **action**, only an `every` project and an `after` action, and for those two
  the mutant produces identical output. **The fixture was fixed, not the assertion weakened**, and
  the mutant then died.
- **Live-verified against the real account, through the real server** (in-memory `Client` over
  `rtm_mcp.server.mcp`, so the whole MCP path incl. output-schema validation): the handle correct
  per kind on all four `gtd_*` reads with cross-read agreement (index row = plan header = canvas
  frame = item context); `entity_id` non-empty and `recurring` a real bool across 92 projects,
  56 foci and 402 actions; **the invariant checked over 3,043 live repeating tasks with zero
  violations**; and both refutations reproduced through the shipped tool (`226592019` returns
  `count=86, repeat_kind=after`; `147643653` returns `count=31, is_repeating=false`).
- **Not run:** nothing was written to RTM — every check is read-only by construction, so there is
  no write path exercised live and none is claimed. The **server has not been restarted**, so no
  downstream consumer (board artifact, chat session) has yet seen these fields; that is the
  activation step above, and it is the boundary of this verification.

## Conventions

§ 2 naming (`list_task_occurrences` is a generic bare-verb primitive, outside the `gtd_*`
domain-composition standard the check enforces) · § 5 additive-only `ErrorCode` (none added,
`TASK_NOT_FOUND` reused) · § 6 tag discipline (no tag touched) · § 7 six-surface docstrings ·
§ 9 lockstep (CLAUDE.md + CHANGELOG + test inventory updated with the code) · § 10 SemVer
(minor — additive) · § 14 this debrief.

## Open items / handback

1. **Restart the server on v6.9.0.** Nothing else is needed to activate.
2. **Removing `taskseries_id` from the domain reads is yours to trigger**, with the generic-tier
   exclusion. Until then both are present and `entity_id` is the one to read.
3. **Vault side — consumer, as scoped:** the vault schema (`entity_id`, `gtd_recurring`), the
   folder shape, and the re-derivation of the 124 backfilled values remain plugin-side.
4. **The gtd `note-shape-catalogue` / skill references are unaffected** — no note shape, tag or
   grammar changed. **Consumer — no action** beyond points 1–3.
5. **Housekeeping from the brief:** the `.venv` duplicate `.pth` was deleted. Two sibling
   cloud-sync duplicates remain in `.venv/bin` (`rtm-mcp 2`, `rtm-setup 2`) — reported rather than
   swept, since removing binaries was not in scope and no make target reaches them.
6. **The brief's `make test` finding is stale — no action.** Every make target has been pinned to
   `~/.venvs/rtm-mcp` since 2026-07-31 (`b4d47d3`), and that venv carries pytest, pytest-asyncio
   and respx. `/opt/anaconda3/bin/pytest` is still on PATH but no make target reaches it; the
   2,080-test run above used the venv interpreter.

## Durable lesson / gotcha

**A property verified on `status:incomplete` is not verified on the account.** That single mistake
produced the retraction above, and the shape recurs: the subset was *systematically* biased toward
the property holding (an `after` series has at most one open occurrence *by construction*), so the
sample could not have disconfirmed it. When a claim is about what RTM *can* hold, the completed
history is where the counter-examples live — and it is 38× larger than the open set here.

**And the test that guarded it could not fail.** `repeat_kind({"every": "1"}) == "every"` was
labelled the deductive cross-check and asserted something else entirely. When a test's docstring
makes a claim about *live data*, the assertion must reference live data — a fixture that restates
the function's own definition is documentation wearing a test's clothes.

Two smaller traps for the next author:

- **`entity_handle` reads three fields that live under different key names per surface.** Parsed
  tasks and envelope rows both use `id` for the task id; `header.project` uses `id` too. It takes
  keyword-only arguments precisely so a call site cannot silently pass the wrong one.
- **`gtd_project_index` can legitimately return two rows sharing one `entity_id`** — a recurring
  project with two open occurrences does exactly that (live: `File company accounts`, project_ids
  `1124622244` and `1195891528`, both `entity_id` `476408903`). That is one commitment with two
  instances, not a duplicate. A consumer keying a dict on `entity_id` will silently lose one.

---
*Source of truth: `CLAUDE.md` §§ "Recurrence: two kinds…" (incl. the retraction), "The durable
entity handle", "`list_task_occurrences`"; docstrings on `parsers.entity_handle`,
`parsers.repeat_kind`, `tools/tasks.py::list_task_occurrences`. Provenance: brief 2026-08-03;
live measurements taken against Paul's RTM account 2026-08-03 (44,730 tasks, 118 repeating series).*
