report_type: handback-debrief
scope: gtd-domain-tool-suite / Phase-4b (the AI-surface subsystem)
target_repo: rtm-mcp
version_shipped: 2.8.0
branch: main
status: debriefed
derived_at: 2026-07-24

# Handback debrief — Phase 4b: the AI-surface subsystem

## 1. What landed

rtm-mcp **v2.8.0**, commit `4091be6` on `main`. **87 tools.** Two governed tools:

| Tool | Envelope | Annotation |
|---|---|---|
| `gtd_surface_create` | `SurfaceCreateEnvelope` | additive |
| `gtd_surface_resolve` | `SurfaceResolveEnvelope` | **destructive** |

The brief's §2 instruction to treat the six sources as authoritative was the right call: the
source read produced **13 numbered divergences**, five of which changed the implementation. §2 also
warned that prior briefs carried inferred-internals errors — that pattern repeated here, and the
sources caught it.

## 2. Divergences between the brief and the authoritative sources (§2 said the sources win)

**a. "Five item types" conflates two vocabularies — and the source's own derivation rule is
broken.** The `item_type` INPUT is `question|alert|notification|surface|activity_report`
(`ai-surface-creator.md:39`); the TAG is `q_question|q_alert|q_notification|q_surface|q_activity`.
`ai-surface-creator.md:168` instructs deriving `q_<item_type>` — which for the fifth type yields
**`q_activity_report`**, not canonical. Worse, gtd's `validate-tags.py:167` accepts
`q_[a-z0-9_]+` as a pattern family, so that spelling **passes validation** and lands in RTM while
being invisible to every scan filter and smart list. **Implemented as an explicit lookup table,
never derivation**, with a test pinning it. *Live check: `q_activity_report` is not among the
account's 18 `q_*` tags, so the source bug has not yet fired.* **gtd-side fix needed.**

**b. The lifecycle is TWO DISJOINT machines, not one flat set.** The brief's
`q_pending → q_processed/q_answered/q_acknowledged/auto_closed` is wrong.
`tag-taxonomy.md:136-147`: AI_Questions is `q_pending → q_answered → q_processed` (and
`processed` **removes** both prior states); AI_Activity is `q_open → q_acknowledged` or
`→ auto_closed`. `q_acknowledged` can never follow `q_pending`. The server rejects cross-machine
resolutions.

**c. Auto-close is a YAML body line, per-type.** Not a tag, not a due date:
`auto_close_at: YYYY-MM-DD` in the body frontmatter (`ai-surface-creator.md:143`). No single TTL —
notification +7d, surface +14d, activity_report +7d, `null` for question/alert. AI_Questions never
auto-closing is confirmed four independent times.

**d. The AI-LINK note lives on the LINKED ENTITY ONLY** (`journaling-lifecycle.md:655`) — not on
the surface item, not both. "Bidirectional" is asymmetric: forward = the `entities:` block in the
surface body; backward = one AI-LINK per entity. Also: `note-shape-catalogue.md` § 7 is a
three-line stub; the real grammar is `journaling-lifecycle.md:663-680`. Status enum is
`open|answered|processed|acknowledged|auto-closed|closed` — **`auto-closed` hyphenated** where the
tag is `auto_closed`.

**e. There is no AI-surface OUTCOME body shape — it is title-only.** The catalogue's OUTCOME
grammar is the *meeting* outcome (`Agenda:`/`Decisions made:`/…). Emitting that from a resolve tool
would write meeting-lifecycle notes onto surface items.

**f. Dual/triple-surface is not in `ai-surface.md`** (that file has no numbered sections at all) —
it is `plugin-marketplace-architect/.../communication-channels.md` §§ 3.4-3.5, which self-describes
as a distillation, not an authority. The brief was **right** that the caller orchestrates: every
source produces exactly one item. `paired_refs` emits the cross-reference lines at create time.

**g. Minor but load-bearing:** priority is RTM's **field**, not a tag (`!1` is SmartAdd syntax);
`meta`/`scheduled_task` get no AI-LINK, capped at 20; no life-context or workflow-state tag (no
source applies one, and doing so would leak surface items into the GTD smart lists); response-shape
coupling is a hard rule (`none` mandatory for AI_Activity, illegal for AI_Questions).

**h. `q_urgent` does not exist** — `communication-channels.md:152,182` invents it; it appears in no
gtd source, and the `q_*` wildcard would wave it through. Deliberately not implemented.

## 3. The `publish_ai_activity` finding — a divergence resolution, not a port

The brief says these tools should "realise" that interface. **Realising it as specified would
produce broken items.** `publish-ai-activity.py`'s composed body has **no YAML frontmatter**, so an
item created that way carries no `auto_close_at` (→ can never auto-close, despite the protocol
defaulting callers to `q_surface` and promising 7-14 day closure), no `item_id` (the AI-LINK
matching key), no `entities` (no fan-out), no `asked_by`/`asked_at`. It also writes **no AI-LINK
notes at all**. Yet those items still match the scan's eligibility query forever and accumulate
against the 50-item bloat threshold.

`publish-ai-activity-protocol.md:27` states "the two paths must not diverge" — they already do.
**`gtd_surface_create` writes the creator's full semantics, so reducing the protocol to a call on
it is what makes that sentence true.** Recorded here as a conscious divergence resolution.

## 4. Test results

- **Full suite green: 1294** (was 1265; **+29**). ruff + **pyright clean on a clean venv**
  (CI's pinned 1.1.408 — see §7).
- `test_gtd_writes.py` +18: the two vocabularies + the `q_activity_report` footgun; routing;
  per-list tag sets incl. **no life-context/workflow-state leakage**; entity facets; per-type TTL +
  never-for-questions; the body frontmatter the scan needs; every AI-LINK field + `Status: open`;
  meta/scheduled_task skip + cap; **the two disjoint machines** (three illegal cross-machine cases);
  `processed` removing both prior states; the hyphen/underscore split; title-only OUTCOME;
  response-shape rule 4; `q_urgent` absent.
- `test_gtd_tools.py` +11: question→AI_Questions with correct tags and priority-as-field;
  activity_report→`q_activity`; body frontmatter + AI-LINK **on the entity**; meta gets no AI-LINK;
  response-shape rejection writes nothing; unresolvable entity writes nothing; **idempotency on an
  existing item_id**; resolve transitions + link rewrite; cross-machine rejection; `auto-closed`
  hyphenation; non-surface-item rejection.
- **Fingerprint churn: 2 added, 0 changed — fully additive-only.** No new `ErrorCode`.
- **Live smoke-test** (`#test` throwaways, 2/2 cleaned up): created a `surface` → routed to
  AI_Activity, tags `ai_activity, ai_conversation, q_action, q_open, q_surface, test` (note the
  `q_action` facet **derived from the linked entity**), `auto_close_at: 2026-08-07` (+14d), AI-LINK
  note `118493556` written on the entity; then resolved `acknowledged` → completed, link `Status:`
  → `closed`, OUTCOME `2026-07-24 — OUTCOME — Acknowledged: ZZ smoke complete`.

## 5. `q_*` provisioning (the §5 invariant)

**Every tag these tools write is already provisioned** — no D8-style gate. The account carries **18
`q_*` tags** plus `claude_question`, `ai_activity`, `ai_conversation`, `auto_closed`. Both lists
exist and are writable (`51542311 AI_Questions`, `51542342 AI_Activity`, neither smart nor locked).

Worth recording (Paul asked whether the non-obvious ones were deadwood): `q_action`, `q_person`,
`q_project`, `q_waiting_for`, `q_meta`, `q_scheduled_task`, `q_queue_bloat` are **live, not
deadwood** — 95 uses between them across 44,460 tasks, most recently modified 2026-07-24, with 70
open items. They are instances of the codified open `q_<entity-type>` family
(`tag-taxonomy.md:118`, enforced by `validate-tags.py:167`), which is why they don't appear
individually in the repo. The server therefore existence-gates the facet axis rather than
enum-gating it.

## 6. Coverage delta

AI-surface rows flip **COVERED**: surface-item creation (both lists, all five types), the AI-LINK
back-link discipline, the `q_*` lifecycle transitions, auto-close resolution, and the OUTCOME +
completion close-out. `ai-surface-creator.md` and `ai-surface-scan.md` (~18 consuming agents) now
have a governed path. Remaining gaps are only the intentionally-generic set + deferred Tier-3, plus
4c.

## 7. Marketplace-side lockstep

New this phase (the first two are **source bugs**, not preferences):
1. **`q_activity_report`** — fix `ai-surface-creator.md:168`'s derivation rule to a table. The
   `q_*` wildcard makes this class of error uncatchable by `validate-tags.py`.
2. **AI-LINK `Status:` values** — the creator writes `q_pending`/`q_open` (`:216`) and the scan
   writes the literal `processed → closed` (`:61`); neither is in the six-value enum. Three
   sources, three conventions.
3. **`publish_ai_activity`** — reduce to a call on `gtd_surface_create` (§3); this fixes the
   never-auto-closes defect.
4. **`q_urgent`** in `communication-channels.md` — it exists in no gtd source; remove or codify.
5. **Route** `ai-surface-creator` / `ai-surface-scan` and the ~18 consumers onto the tools.
6. Stale: `ai-surface.md:74` cadence vs `ai-surface-scan.md:15`; `ai-surface-scan.md` lines
   170/174/190 contradict § 3e on self-reporting (§ 3e wins — a resolve tool must not report on its
   own run); `ANSWER` registered in the catalogue but defined/written nowhere.

Standing carry-overs unchanged: the OUTPUT/FILING single-vs-pair reconciliation (4a, Paul's
decision pending), the DoR-catalogue note, the completion fan-out decision, the DEPENDS-ON doc
fixes, `ai_speculative` provisioning.

**And the critical path is unchanged: 41 `gtd_*` tools now exist across six phases with zero
consumers wired.**

## 8. Verification boundary (honest)

§4's suite/lint/fingerprints are machine-verified and reproducible; the live smoke-test is a single
real-account round-trip (cleaned up). The tools have **not** run inside the deployed MCP server
(still v2.3.0 — Phases 1-4b, eighteen write tools, all need a restart). 4c was not built.

**Process note:** my local `make lint` again reported clean while CI's pyright found a real error
(4a) — the recurring stale-venv problem. For 4b I ran pyright on a **freshly synced venv** before
committing, which caught one genuine typing defect. That should be the standing practice.
