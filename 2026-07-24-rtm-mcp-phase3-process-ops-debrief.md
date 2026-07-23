report_type: handback-debrief
scope: gtd-domain-tool-suite / Phase-3 (process ops)
target_repo: rtm-mcp
version_shipped: 2.6.0
branch: main
status: debriefed
derived_at: 2026-07-24

# Handback debrief — Phase 3: the process ops

## 1. What landed

rtm-mcp **v2.6.0**, commit `2e4daf5` on `main` (Phases 0–2 were merged and pushed earlier; CI
green). 81 tools total. Three governed apply tools, all `DESTRUCTIVE_WRITE_ANNOTATIONS`, all
sharing one `ProcessOpResult` envelope:

| Tool | Envelope | Verdict vocabulary | Reviewed via |
|---|---|---|---|
| `gtd_inbox_zero` | `InboxZeroEnvelope` | `tag` \| `move` \| `complete` \| `leave` | `gtd_inbox_state` |
| `gtd_chase_sweep` | `ChaseSweepEnvelope` | `retickle` \| `convert_to_action` \| `complete` \| `leave` | `gtd_waiting_for_queue` |
| `gtd_consolidate_apply` | `ConsolidateEnvelope` | `reparent` \| `link_dependency` \| `complete` \| `promote` | `gtd_topic_clusters` |

Each **applies a set the caller already reviewed** — none fetches-and-decides. All three share
`_apply_process_set`, which owns the atomicity contract, the bounded-input split, the
once-per-project signal, and the resumable failure split.

## 2. The batch-path investigation — the headline, and it's a negative result

**The brief's primary mitigation does not exist.** §4 asked me to determine whether same-verb items
could be grouped into an RTM multi-task call, which would make an N-item sweep O(N/20). I probed
the live API rather than inferring:

| Probe | Result |
|---|---|
| Comma-separated `taskseries_id` / `task_id` in one `addTags` | **Rejected** — "taskseries_id/task_id invalid or not provided" |
| Filter-based write (no ids at all) | **Rejected** — "list_id invalid or not provided" |
| Single write baseline | 1.12 s (rate limiter) |

**RTM has no multi-task write endpoint.** The official server's `rtm_batch_*` accept bare
`task_ids` with `maxItems: 20`, but RTM requires the full `list_id`/`taskseries_id`/`task_id`
triple per call — so those tools must resolve and loop internally. The cap of 20 is self-imposed,
not an API batch. Their documented "bypasses the custom rate limiter" is best explained by a
**separate API key with its own rate budget**, not fewer calls; borrowing that budget would mean
routing governed writes through ungoverned tools, trading away exactly what Phases 1–2 built.

So the design fell back to the brief's mitigations (2) and (3): **bounded input** and **honest
long-running**. I did not pretend otherwise anywhere in the docstrings.

## 3. Throughput benchmark — the decisive evidence

Live, N=20 chase sweep (`complete` verdict on 20 `#test` waiting-fors under a `#test` parent; all
21 items deleted afterwards, cleanup asserted):

| | Model round-trips | RTM calls | Wall-clock | Signals |
|---|---:|---:|---:|---|
| `gtd_chase_sweep` N=20 | **1** | 24 | **26.6 s** | 1 stamp, 1 project |
| Per-item generic baseline | 20 | ~20 | comparable | 20 chances to forget |

Breakdown: 1 resolution read + 20 completes + 1 signal stamp (+2 cold-cache reads) = 24 calls at
~1.33 s/item. **This is O(N) and it is inherent** — every RTM write is a separate rate-limited
call and no batching exists to change it.

**Read this honestly:** the process ops do **not** make sweeps fast. What they buy is:
- **20 model round-trips → 1** (the token/latency cost the wrapper actually pays);
- **whole-set validation** — one bad verdict rejects the call with nothing written, versus a
  per-item loop that fails halfway leaving inconsistent state;
- **the signal stamped once, guaranteed** — not 20 chances for the model to forget;
- **a resumable `results`/`remaining` split** when RTM fails mid-apply.

The bounded cap is 50 items/call, so the worst single call is roughly **65 s**. That is tolerable
but not invisible — a UI calling these should expect a long-running call, and the `remaining`
continuation exists so a 200-item review doesn't become one four-minute request.

## 4. The atomicity contract (chosen and documented, as §4 required)

**Validate-all-then-apply, with a resumable partial.** The whole reviewed set is validated first —
shape, every ref resolvable, verb-specific args, and one strict-tag gate over all tags — and a
single invalid item rejects the call with `applied_count: 0` and nothing written (the D9 spirit).
Because there is no batch, apply is then per item in order; if RTM fails mid-apply the tool returns
the exact `results` (applied) / `remaining` (not attempted) split so the caller resumes safely
rather than guessing. A strict whole-set *atomic* guarantee is not offered, because it cannot be
honoured against an API that has no transactional multi-write — claiming it would be a lie.

## 5. Deviations

- **No batch grouping** (§2) — the mitigation the brief hoped for doesn't exist. Everything else in
  §4 was implemented.
- **`gtd_chase_sweep`'s `convert_to_action` also clears the due date.** The brief lists only the
  tag swap, but a next action lives undated (the tickle is the waiting-for's chase prompt, and
  keeping it would leave a phantom overdue item). This matches the engage grammar's `next_actions`
  verdict. Noted rather than assumed.
- **`leave` counts as not-applied.** It appears in `results` with `applied: false` so the vector is
  complete, but it doesn't inflate `applied_count`.
- **Fingerprint churn is fully additive-only: 3 added, 0 changed.** No new `ErrorCode` and no shared
  enum change this phase — contrast Phase 1 (69 changed) and Phase 2 (4 changed), both explained.

## 6. Test results

- **Full suite green: 1236** (was 1220; **+16**). `make lint` clean (ruff + format + pyright).
- `test_gtd_writes.py` +5 — the three verdict vocabularies, the cap/split, and every validator
  rejection path (verb-specific args, self-dep, missing `why`).
- `test_gtd_tools.py` +11 — mixed-verb apply; **one bad verb writes nothing**; **one unresolvable
  ref writes nothing**; the bounded-input `remaining` continuation; chase verdict writes (retickle
  uses the `parse_time` result not the caller's text, convert clears the tickle); bad date writes
  nothing; **signal stamped once for three items**; **no fan-out event name written as a tag**
  (the Phase 2 guard re-asserted); consolidate reparent + DEPENDS-ON-on-the-dependent; self-dep
  writes nothing; promote lifts to top level.

## 7. Marketplace-side lockstep — now the critical path

The server-side programme is essentially complete (**35 `gtd_*` tools** across four phases) and
**none of the consumer migration has happened**. Nothing routes onto any of it yet. In priority
order:

1. **The DoR-divergence catalogue note** (Phase 1) — still the highest-priority carry-over.
2. **The completion fan-out decision** (Phase 2) — accept `fanout_events[]` as the contract, or
   codify `ai_completion_fanout_needed` and provision the tag in RTM.
3. **Route the flows**: weekly-review inbox-zero, chase sweep, consolidate-apply onto the new tools;
   plus the Phase 0–2 read/write paths still unrouted.
4. **The doc fixes**: DEPENDS-ON `Status:`/`Upstream type:` staleness; the four codification gaps
   (`hold`/`paused`/`archived`/`cancelled` not canonical; `conversation_phone`; `client` missing
   from the DoR life-context axis; `SOURCE-CONFIRMED`/`BLOCKER-RESOLVED` absent from note-shape §2).
5. **Design around O(N)** — any UI or scheduled task calling the process ops needs to expect a
   long-running call and use the `remaining` continuation.

## 8. Verification boundary (honest)

§6 is machine-verified and reproducible. §2's probes and §3's benchmark are **live, single-run
measurements** on a rate-limited API — the negative batch result is a hard API fact and will not
vary; the wall-clock numbers will. The three tools have **not** run inside the deployed MCP server
(still v2.3.0 — Phases 1, 2 and 3 all need a restart). The production-tail sub-phase
(`gtd_attach_output` / `gtd_attach_contribution`) was explicitly out of scope and is not built.

**Recommendation on the programme:** given the batch result and that 35 tools now exist with zero
consumers wired, I'd stop adding server tools and do the consumer migration next. The production
tail can wait until the migration shows whether it is actually wanted.
