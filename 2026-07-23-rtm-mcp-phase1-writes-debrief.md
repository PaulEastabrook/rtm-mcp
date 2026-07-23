report_type: handback-debrief
scope: gtd-domain-tool-suite / Phase-1 (everyday writes)
target_repo: rtm-mcp
brief: 2026-07-23 Phase-1 everyday-writes hand-off brief
version_shipped: 2.4.0
branch: feat/gtd-phase0-reads
status: debriefed
derived_at: 2026-07-23

# Handback debrief — Phase 1: the first governed GTD write tools

## 1. What landed

rtm-mcp **v2.4.0**, commit `cfea74e` (branch `feat/gtd-phase0-reads`, **not pushed / no PR**).
Four governed write tools + the Tier-1 shared-kernel promotion. Additive: no existing tool changed
behaviour, nothing removed, **no new RTM tag minted**.

| Tool | Output envelope | Annotation |
|---|---|---|
| `gtd_create_item` | `CreateItemEnvelope` (+ `Candidates`) | additive write |
| `gtd_add_note` | `GtdAddNoteEnvelope` (+ `Candidates`) | additive write |
| `gtd_capture` | `GtdCaptureEnvelope` | additive write |
| `gtd_transition_state` | `TransitionEnvelope` (+ `Candidates`) | additive write |

All four are ADDITIVE (none can complete or soft-delete a pre-existing task), validate-then-apply
(**a rejected write mutates nothing** — asserted on every rejection path), transaction-recorded
(revertible via `batch_undo`), and return **true post-state**: the real id triple RTM returned plus
the resulting tags/priority/due and a deep link — never a pre-write echo.

**The seven Tier-1 constants** live in the new pure module `src/rtm_mcp/gtd_writes.py`:
`LIFE_CONTEXTS`, `ITEM_KINDS` (+`WORKFLOW_STATES`), `ACTION_CONTEXTS`, `ENERGY_LEVELS`,
`COMMS_MODES`, `MOSCOW_BANDS` (+`MOSCOW_TO_PRIORITY`), `JOURNAL_NOTE_TYPES`. `ACTION_CONTEXTS` /
`COMMS_MODES` are **re-exported from `canvas_commit`**, not restated, so there is one taxonomy.
Each is advertised as an advisory `json_schema_extra` enum and asserted equal to its frozenset by
`test_tier1_vocabulary_enums_match_canonical_constants`. **Scoped to the new tools only** — the
generic `add_task`/`add_note` stay permissive (the escape hatch), per the brief's invariant.

## 2. Deviations from the brief (decisions, not diff)

**a. DoR is hard-gated — a deliberate, ratified divergence from gtd doctrine.** The brief said
enforce; gtd's own `definition-of-ready-catalogue.md` says the opposite (*"report-and-resolve, never
capture-blocking… degraded, not rejected"*, validator always exits 0). I raised the contradiction;
**Paul chose the hard gate**. Implemented as specified: a create missing a required axis is rejected
with `dor_not_met` + `missing[]` and writes nothing. **This is now a marketplace-side lockstep item**
— either the DoR catalogue gains a note that the server tool is deliberately stricter, or callers
must pre-fill before calling. It will refuse items gtd's prose says should be accepted degraded.

**b. The brief's kind/axis model was wrong in three places** (corrected against `tag-taxonomy.md`):
- **`calendar_entry` is NOT a workflow state** — it is a Special Tag. A calendar entry materialises
  **`action` + `calendar_entry`**. The brief treated it as a third workflow state.
- **`life_context` has four members** — `work`, `leanworking`, `client`, `personal`. `client` is
  canonical (a Work-domain refinement, codified 2026-06-07), though gtd's DoR life-context axis
  names only three. We accept all four (the taxonomy is authority for tag validity); flagged as a
  gtd-side inconsistency.
- **The brief's per-kind DoR lists were incomplete** — action and waiting_for both also require
  life-context; calendar_entry also requires action-context. Implemented from the catalogue table.

**c. The `relational` axis is advisory, not gated.** DoR requires it for an action (a DEPENDS-ON
edge or an explicit "parallel — no edge"), but DEPENDS-ON note authoring is *explicitly out of
Phase-1 scope*. Gating an axis the tool cannot satisfy would make every action create fail. It is
reported in `advisory[]` instead. **Follow-up**: gate it once the DEPENDS-ON tool lands.

**d. `project` is excluded from `ITEM_KINDS`.** The DoR catalogue has four kinds, but a project
already has its own governed tool (`gtd_create_project`) with a richer DoR (Area-of-Focus parent,
INCEPTION note, vault folder). No overlap was created.

**e. The "pure-journalling vs side-effect-bearing" note split is our construct, not gtd's.** No such
classification exists in the references. The real split is free-prose vs machine-parsed grammar; the
brief's eight types are all free-prose, so the scope holds — but `JOURNAL_NOTE_TYPES` is a
server-side invention and should be reflected gtd-side if it is to be canonical.

**f. `gtd_transition_state` stamps on EVERY transition** (the brief's recommended simple form).
Additional justification found during research: the progress-ability set the alternative would need
(`#hold` / `paused` / `archived` / `cancelled`) contains tags that are **not canonical** —
`validate-tags.py` would reject `hold`. The engine reads four tags it can never legally write. **A
genuine gtd-side codification gap, flagged.** The signal is stamped on the item's nearest `#project`
ancestor (matching the engage-commit precedent), not the item.

**g. Fingerprints are NOT additive-only — all 69 pre-existing changed.** The brief asked to confirm
no churn. The Tier-1 constants *are* correctly scoped (they are param enums on the new tools only).
The churn comes from the **three additive `ErrorCode` members** (`dor_not_met`,
`invalid_note_type`, `invalid_block_order`): `models.ErrorBody.code` is typed as the enum and
FastMCP 3.x inlines it, so every tool's `outputSchema` gains the three values. **Verified, not
assumed**: `add_task`'s source is untouched this phase (`git diff` shows only `tools/gtd.py`
changed) yet its advertised schema now contains all three codes. This is the behaviour CLAUDE.md
already documents for v2.2.0 — structural, not a behaviour change in 69 tools. I kept the typed
codes because the brief also requires typed discriminators for DoR failures specifically, and
`dor_not_met` + `missing[]` gives a caller a materially different recovery from `invalid_input`.

## 3. Test results

- **Full suite green: 1188** (was 1140; **+48**). `make lint` clean (ruff + ruff format + pyright,
  0 errors).
- New `tests/test_gtd_writes.py` (30) — the seven vocabularies, tag materialisation, hard-gated DoR,
  note title/block grammar, every validator rejection path.
- New tool tests in `test_tools/test_gtd_tools.py` (18) — one accept test per tool plus a
  **reject-writes-nothing** test for every rejection path (DoR gap, off-enum, bad date, unknown
  parent, side-effect note type, bad block order, empty capture, double workflow state, empty
  transition, strict-tag). Each asserts `not (methods & WRITE_METHODS)`.
- `test_tool_schemas.py` +1 — the Tier-1 enum-drift assertion; the reject-reason enum equality was
  extended to `GtdWriteRejection`.
- **Fingerprint delta: 4 added, 69 changed, 0 removed** — see § 2g for the verified cause.

## 4. Write-path benchmark — the Phase-2 gate evidence

Measured live against Paul's account using `#test`-tagged throwaway items under a throwaway `#test`
parent (so even the overlay-refresh stamp landed on disposable data); **all 6 items created across
both runs were deleted afterwards** (cleanup asserted in the harness output).

Representative create: one action under a project, fully specified (life context, context, energy,
estimate, MoSCoW band, CONTEXT note) **plus** the orchestration stamp.

| Path | Model round-trips | RTM API calls | Wall-clock |
|---|---:|---:|---:|
| Generic (`add_task` → `set_task_tags` → `set_task_priority` → `set_task_estimate` → `add_note` → `add_task_tags`) | **6** | 6 | 5.91 s |
| `gtd_create_item` (cold session) | **1** | 10 | 11.11 s |
| `gtd_create_item` (warm session, steady state) | **1** | 7 | 7.78 s |

Note: `gtd_add_note` = 1 round-trip / 2 RTM calls vs the generic `add_note`'s 1 / 1 — the extra call
is the task resolution that lets the caller pass a name instead of an id triple.

**The honest read — this is a mixed result.**
- **Model round-trips: 6 → 1, a 6× reduction.** This is the brief's stated target ("~3–6×") and it
  is met. It is also the number that costs tokens and model latency, and the one the wrapper skill
  actually pays.
- **RTM API calls went UP (6 → 7 warm), and wall-clock is ~1.3× SLOWER (5.91 s → 7.78 s).** RTM's
  rate limiter (~0.9 RPS sustained) dominates, so call count ≈ wall-clock. The domain path pays two
  reads the generic path skips: resolving `parent_ref` (a full `status:incomplete` fetch) and the
  `Processed` list-writability check. Cold sessions pay two more (the session-cached settings and
  account-tags reads).
- **What the extra ~1.9 s buys**: the DoR gate, enum validation, the strict-tag existence gate, list
  writability, structural tag materialisation (no hand-typed tag strings), true post-state, the
  orchestration stamp applied atomically, and one undoable batch. The generic path is faster
  *precisely because it skips every guard* — and it silently produced a degraded item in the same
  measurement (no DoR check exists on that path).
- **"Failed-call count" was not measurable synthetically.** The generic path's real-world failure
  modes (forgetting `parse=false`, mistyping a tag, forgetting the orchestration stamp, acting on a
  stale echo) are call-site discipline errors, not API errors — they show up as *wrong state*, not
  as failed calls. The domain path makes them structurally impossible, which is the substantive
  claim, but I have no live number for it and will not invent one.

**Concrete optimisation identified (not implemented — flagged rather than rushed):** session-cache
the `Processed` list resolution, and narrow the parent-resolution read when `parent_ref` is already
an id. Together these would take the warm create to ~5 RTM calls — *below* the generic path — making
the domain tool faster as well as safer. That is a cheap, well-scoped follow-up.

**Gate recommendation.** The round-trip target is met (6×) and the safety/correctness gains are
real, so on the brief's own stated criterion Phase 2 is authorised. But the wall-clock regression is
genuine and Phase 2's density/bulk tools will *amplify* it (bulk ops multiply the per-call
overhead), so I would sequence the caching optimisation above **into** Phase 2 rather than after it.
That is Paul's call, not mine.

## 5. Marketplace-side lockstep (for a follow-up `/marketplace commit`)

1. **The DoR posture divergence (§ 2a)** — the highest-priority item. gtd's DoR catalogue must
   record that `gtd_create_item` hard-gates, or callers will hit rejections the doctrine says
   shouldn't exist.
2. **Route the everyday write paths** (capture, create-action/waiting/calendar, add-note,
   state-transition) onto the new tools; narrow gtd's `validate-*.py` where the server now subsumes
   them (sequenced stage-2, not simultaneous). Generics stay in place.
3. **Three gtd-side codification gaps found** (all pre-existing, none introduced here):
   `hold`/`paused`/`archived`/`cancelled` read by the progress-ability gate but not canonical;
   `conversation_phone` vs `conversation_phone_call` in the DoR catalogue footnote; `client` missing
   from the DoR life-context axis. Also `SOURCE-CONFIRMED` / `BLOCKER-RESOLVED` are used by agents
   but absent from note-shape-catalogue § 2, so `validate-note.py` hard-fails them.
4. **`JOURNAL_NOTE_TYPES` (§ 2e)** should be reflected gtd-side if the journalling/side-effect split
   is to be canonical rather than a server-side construct.
5. **Naming/parameter convention** codified in git-ops `mcp-tool-documentation-standard.md` — all
   four are `gtd_<verb>_<noun>`, confirming the verb-first rule for writes.

## 6. Verification boundary (honest)

§ 3 is machine-verified and reproducible (`make test` / `make lint` / `make fingerprints`). § 4's
numbers are **live, single-run measurements against Paul's account on 2026-07-23** on a
rate-limited API — they will vary run to run, and the wall-clock figures in particular are dominated
by RTM's token bucket rather than by server work. The four tools have **not** yet run inside the
deployed MCP server (still v2.3.0) — that needs a restart. Nothing here has been pushed; the branch
carries both Phase 0 and Phase 1.
