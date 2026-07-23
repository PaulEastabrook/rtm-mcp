report_type: handback-debrief
scope: gtd-domain-tool-suite / Phase-2 (density + bulk + create-path caching)
target_repo: rtm-mcp
version_shipped: 2.5.0
branch: feat/gtd-phase0-reads
status: debriefed
derived_at: 2026-07-23

# Handback debrief — Phase 2: density, the bulk fan-out fix, and create-path caching

## 1. What landed

rtm-mcp **v2.5.0**, commits `1aee29a` (caching) + `ed99638` (five tools), branch
`feat/gtd-phase0-reads`, **not pushed / no PR**. 78 tools total.

| Tool | Envelope | Annotation |
|---|---|---|
| `gtd_complete_action` | `CompleteActionEnvelope` | **destructive** |
| `gtd_close_inbox_item` | `CloseInboxEnvelope` | **destructive** |
| `gtd_set_properties` | `SetPropertiesEnvelope` | additive |
| `gtd_link_dependency` | `LinkDependencyEnvelope` | additive |
| `gtd_batch_transition` | `BatchTransitionEnvelope` | **destructive** |

Plus the folded-in **create-path caching**: `client.get_lists_cached()` (300 s TTL) with
invalidation **centralised in `client.call()` keyed on the RTM method**, so a future list tool
cannot forget it; `lookup.resolve_system_list_id()` for the fixed system lists only (the uncached
resolver stays for caller-named lists, where staleness would be a correctness bug).

## 2. Deviations from the brief (decisions, not diff)

**a. The "≤4 progression signals" cannot be stamped — they are EVENT names, not tags.** The brief
says `gtd_complete_action` "stamps the ≤4 progression signals atomically". Research shows
`completed` / `decided` / `waiting_for_resolved` / `calendar_entry_completed` are `event:`
arguments to gtd's `progression-fanout` **agent**; no RTM tag by those names exists in the
taxonomy. A server cannot invoke an agent, and stamping non-existent tags would be rejected by the
strict-tag gate and would violate both "the server never mints a tag" and gtd's
codification-before-validation rule. **Implemented instead**: the tool *returns* them as
`fanout_events[]` for the caller to fire, and stamps the sanctioned durable mark
`#ai_overlay_refresh_needed` on the parent project — the exact pattern
`gtd_apply_canvas_commit` already uses. A test asserts none of the four event names is ever
written as a tag. **Codifying a real `ai_completion_fanout_needed` mark is a gtd-side decision**
(catalogue entry first, then you provision the tag in RTM) — flagged, not assumed.

**b. `gtd_link_dependency` does NOT mirror `context.md`.** That `dependencies:` frontmatter is a
**vault filesystem write**, and the membrane is explicit: *"rtm-mcp do the RTM write only and stay
vault-free — agent-memory owns the vault, gtd wraps RTM."* The tool writes the DEPENDS-ON note in
RTM (the system of record) and stamps the refresh mark; the mirror is gtd-side drain work. The
frontmatter is derivative by gtd's own definition, so nothing is lost.

**c. `DEPENDS-ON Status:` uses `active|resolved|obsolete`.** `note-shape-catalogue.md` § 5 says
`active|superseded`, but `journaling-lifecycle.md` and **five runtime call sites** all write
`resolved`. The catalogue is stale; a test pins the correct set. Similarly `Upstream type:` takes
the wider union including `project` and `external`. **Both are gtd-side doc fixes.**

**d. The Phase-1 `relational` DoR axis stays advisory.** The brief notes `gtd_link_dependency`
"unblocks" gating it. I did **not** enable the gate: `gtd_create_item` is shipped, and making a
previously-advisory axis mandatory is a **breaking** contract change for existing callers, which
§4's "additive-at-contract" invariant forbids. It is now *possible*; enabling it should be a
deliberate, announced change.

**e. `gtd_batch_transition` is annotated destructive.** The brief said "DESTRUCTIVE if a transition
defers/parks". Annotations are static, and the reachable worst case decides: a transition can park
pre-existing work (`#someday`), changing what surfaces in every view. Annotated destructive
unconditionally.

**f. Fingerprint churn — scoped and verified.** 5 added, **4 changed**, 0 removed. The four are
exactly the Phase-1 write tools, because they share the `GtdWriteRejection.reason` enum, which
gained `self_dep` + `destructive_unconfirmed`. **No new `ErrorCode` this phase**, so none of the
all-schema churn Phase 1 saw. This is the additive-only property the brief asked me to confirm.

## 3. Test results

- **Full suite green: 1220** (was 1188; **+32**). `make lint` clean (ruff + format + pyright).
- `tests/test_gtd_writes.py` +16 — completion-event guards (incl. `#test` fans out nothing, and
  `calendar_entry_completed` suppressed when an OUTCOME exists), the review→approved first-only
  transition, DEPENDS-ON required fields, and **eight series-guard tests** (one-off identity,
  collapse-to-nearest-active, the repeating-single-occurrence gate, completed rows excluded,
  undated-sorts-last, divergence surfaced with band aliases normalised).
- `test_gtd_tools.py` +14 — including **note-before-complete ordering**, CASCADE lands on the
  parent project, calendar-entry-requires-OUTCOME, review→approved, close-inbox refuses when a
  derived id is missing, series-guard redirect (`written_to_task_id` = the soonest-due occurrence,
  not the one named), self-dep rejection, and the two **all-or-nothing** bulk tests (one invalid
  item ⇒ `applied_count == 0` and `not (methods & WRITE_METHODS)`).
- Caching: `test_lists_cache_ttl_and_invalidation` (cache hit, central invalidation on mutation,
  **non**-invalidation on a read, TTL expiry) + a tool test asserting the create path issues no
  `rtm.lists.getList` and exactly one task read.

## 4. Write-path benchmark — the Phase-3 gate

Live against Paul's account with `#test` throwaways under a `#test` parent; **all 8 items deleted**
(cleanup asserted).

**A) Warm create, like-for-like** (both paths doing the same work: task + tags + priority +
estimate + CONTEXT note + orchestration stamp):

| Path | Model round-trips | RTM calls | Wall-clock |
|---|---:|---:|---:|
| Generic | 6 | 6 | 6.66 s |
| `gtd_create_item` (warm) | **1** | 7 | 7.78 s |

**I did not hit the brief's target of ≤5 RTM calls / beating the generic path, and I don't think it
is reachable.** Caching removed the list read (8 → 7). The remaining seven are irreducible: one
parent-resolution read, then six distinct RTM write methods (`add`, `setTags`, `setPriority`,
`setEstimate`, `notes.add`, `addTags`) that cannot be merged. The generic path is those same six
writes *minus* the resolution read — so the domain path is structurally **generic + 1**. Closing
that last call would need either a single-task fetch RTM does not offer, or giving up the
ancestor-correct signal target. **The round-trip win (6 → 1) stands; the wall-clock parity claim in
the Phase-2 brief was optimistic and I'd retire it.**

**B) Bulk headline — `gtd_batch_transition` over N=5:**

| | Model round-trips | Signals stamped | Failure mode |
|---|---:|---:|---|
| Generic (`rtm_batch_tag` + per-item fan-out) | 6 | 0–5, by discipline | silent skip on item 15 of 20 |
| `gtd_batch_transition` | **1** | **5/5, guaranteed** | all-or-nothing; nothing written on any invalid item |

Domain: 1 round-trip, 12 RTM calls, 13.34 s, `applied=5`, `signals=5/5`. **The bulk win is
round-trips and correctness, not RTM calls or wall-clock** — the tool writes per item rather than
via a batch endpoint. I did *not* measure the generic path's internal RTM calls (it is a different
MCP server) so I make no claim there; the comparison above is on the two axes I can actually
measure and that drive the decision.

**Gate recommendation.** On correctness the bulk result is exactly what the phase was for: the
per-item orchestration signal is now structurally guaranteed rather than a discipline the model can
silently drop, and the batch is all-or-nothing. On throughput there is no win, and there won't be
one while every write is a separate rate-limited RTM call. If Phase 3's process ops (`gtd_inbox_zero`,
`gtd_chase_sweep`) fan out over many items, they will be **slow** — worth designing around
(progress reporting, or accepting long-running calls) rather than discovering later.

## 5. Marketplace-side lockstep

1. **Decide the completion fan-out** (§ 2a) — either accept `fanout_events[]` as the contract, or
   codify `ai_completion_fanout_needed` in `tag-taxonomy.md` and provision it in RTM.
2. **Two gtd doc fixes** (§ 2c): DEPENDS-ON `Status:` and `Upstream type:` in
   `note-shape-catalogue.md` § 5 are stale relative to `journaling-lifecycle.md` and the runtime.
3. **The Phase-1 DoR-divergence catalogue note is still pending** — highest priority carried over.
4. **The Phase-1 codification gaps are still pending**: `hold`/`paused`/`archived`/`cancelled` read
   by the progress-ability gate but not canonical; `conversation_phone` typo; `client` missing from
   the DoR life-context axis; `SOURCE-CONFIRMED`/`BLOCKER-RESOLVED` absent from note-shape § 2.
5. **Route the completion / dependency / property / bulk-transition paths** onto the new tools.

## 6. Verification boundary (honest)

§ 3 is machine-verified and reproducible. § 4 is **single-run live measurement on a rate-limited
API** — wall-clock figures are dominated by RTM's token bucket, not server work, and will vary. The
five tools have **not** run inside the deployed MCP server (still v2.3.0 — Phase 1 and 2 both need a
restart). Nothing is pushed. The `gtd_complete_action` `new_items[]` parameter from the brief was
**not implemented** — emergent-item creation is already served by `gtd_create_item`, and folding a
second full DoR-gated create path into a destructive tool would have widened the blast radius of
the phase's riskiest tool for no capability gain; call the two tools in sequence.
