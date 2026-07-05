---
report_type: feature-debrief
scope: rtm-mcp — MoSCoW band joins the within-tier plan-graph sort (RTM priority field → band tie-break; priority enters the fingerprint; parity golden regenerated)
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-05
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR TBD, rtm-mcp v1.21.0 → v1.22.0 (changes currently uncommitted on branch feat/order-note-dc4, logically stacked on DC-4 / v1.21.0 — see Open items)
relates_to: brief "rtm-mcp relay brief — MoSCoW band joins the plan-graph within-tier sort (v1.21.0 → v1.22.0)" (2026-07-05);
            gtd-side landing gtd v0.130.0 "MoSCoW reaches the graph" / spec v0.29.0 (moscow-prioritisation.md; kickoff brief moscow-mechanics-and-triage-sweep § 4);
            predecessor debrief order-note-dc4-debrief.md (v1.21.0);
            CONTRIBUTING § 14 (this debrief is the required handback)
status: DONE (server half) — additive minor; needs the MCP server restarted on v1.22.0. Thin
        (server) / enriched (gtd) engines diverge transitionally until that restart, exactly as
        DC-4. No live acceptance run is owed on the server side.
---

# Debrief — MoSCoW band in the within-tier plan-graph sort (v1.22.0)

## What shipped

The plan-graph timeline order now breaks within-tier ties by **MoSCoW band** before date. The RTM
priority field *is* the band (`moscow-prioritisation.md`): Must (`!1`/High) → Should (`!2`/Medium)
→ Could (`!3`/Low) → untriaged (`!-`/absent, sorts **last**). So within a single readiness tier
(e.g. the ready cohort, or the quick-win cohort) a Must-important item now displays above a
Could-important one even when the Could has an earlier due date. Tier structure still outranks band
(readiness/leverage beats importance for *execution* order), manual ORDER pins still outrank all
cosmetic tiering, and the DAG stays absolute. Priority also joins the overlay fingerprint, so a
band edit now invalidates the cached enriched overlay and triggers a recompute. Nothing about the
node output shape, tool surface, or any envelope/note schema changed — `priority` was already in
the `project-plan-seed/3` rows; it was simply not yet an order input.

## Design decisions & deviations

- **Version is v1.21.0 → v1.22.0 as briefed** (the relay brief was drafted against the correct
  current head this time — no numbering drift, unlike DC-4). Additive minor per § 10.
- **`plan_graph.py` is the only source file touched.** Three edits, mirroring gtd v0.130.0
  case-for-case: (1) module-level `_BAND` dict + `_band_rank(row)` helper; (2) one band slot in
  `_timeline_order.sort_key`, inserted **between tier and due/start**; (3) `str(r.priority or "")`
  in `_fingerprint`, immediately **after** the estimate field. Byte-position of the fingerprint
  field matters for cross-repo parity — it sits exactly where gtd put it.
- **`sort_key` band position is `(pinned, tier, band, due, start, input-index)`.** Band is
  neutralised to `0` on pinned items (the pin index is already unique, so later tuple elements
  never engage — held constant purely for determinism, matching gtd).
- **`_BAND` accepts three surfaces:** the RTM API words (`High`/`Medium`/`Low`), their lowercase
  form (some wrapped reads emit lowercase), and the canvas/draft numeric surface (`"1"`/`"2"`/`"3"`).
  Anything else — including `NoPriority`/`N`/absent/empty — falls to untriaged (`3`). This is why
  the parity fixture's row 5 (`priority: ""`) is untriaged.
- **Untriaged sorts after Could, deliberately.** `!-` is triage debt, not a MoSCoW "Won't" (a real
  Won't is parked out of the plan entirely), so it is visibly last within its tier as a nudge to
  triage — not first, not mid.
- **The fingerprint flip is universal, and that's expected.** Adding the priority field to the
  per-row join changes the hashed string for *every* input, even rows with no priority (the joined
  string gains a field). So every cached overlay recomputes once on first read after deploy. The
  parity golden was regenerated in lockstep to encode the new fingerprint.
- **No deviation from the brief.** Every numbered item (band helper, sort_key slot, fingerprint
  field, docstring deltas, golden copy, 9 TestBand cases) landed as specified. The brief's
  "draft_judgement pass-through test — gtd-side only, no server equivalent" is covered here by
  TestBand case 4 (numeric priority surface), as the brief itself noted.

## Membrane / activation

- **No new tag, no schema bump, no new tool.** `priority` already flows in the envelope rows; this
  only changes how the pure engine *sorts* with it. There is **no strict-tag-gate interaction and
  no activation-ordering hazard.**
- **Additive + backward-compatible.** An untriaged plan (no priorities set) sorts exactly as before
  within each tier (all rows rank `3`, so the old due/start/input tie-break decides). The only
  observable change on a restart is: (a) triaged items re-tier within their cohort, and (b) every
  enriched overlay recomputes once (fingerprint flip).
- **Transitional divergence, same posture as DC-4.** Until the server is restarted on v1.22.0, the
  thin (server) engine and the enriched (gtd) engine will order triaged plans differently. This is
  acceptable and expected — flagged in the CLAUDE.md changelog note and here.
- **To go live:** restart the MCP server on v1.22.0. This ONE restart supersedes the pending
  v1.21.0 (DC-4) restart. No board re-bake or live acceptance run is owed *on the server side* —
  the change is invisible at the tool boundary (same shapes); the gtd side owns any enriched-engine
  parity re-verification it wants.

## Verification done

- `make test`: **778 passed** (769 → 778; +9 `TestBand` cases in `tests/test_plan_graph.py`). The
  regenerated `tests/plan_graph_parity_golden.json` is exercised by the existing
  `test_plan_graph_parity.py` (order `["1","3","4","2","5"]` → `["1","4","3","2","5"]`; fingerprint
  `942eed2665959aa9` → `fe2a0a6e201881f6`).
- `make lint`: ruff check + ruff format + pyright all clean.
- **Cross-repo parity is pinned two ways:** the golden was `cp`-copied **byte-identical** from
  gtd's `plugins/gtd/skills/gtd/scripts/plan_graph_parity_golden.json` (verified with `diff -q` →
  identical), and the 9 `TestBand` cases mirror gtd's `TestBand` suite one-for-one. Parity is
  asserted by mirroring, **not** by executing gtd's scripts in this repo's CI.
- **Not run:** no live-RTM read/write, no MCP server smoke (the change is pure and invisible at the
  tool boundary, so validation is in-suite via the mocked-client tests); no cross-membrane
  determinism eval against gtd's live `plan_graph_read.py` (the gtd side owns that if it wants it —
  the golden + mirrored suites are the byte-level guard on this side).

## Conventions

§ 9 documentation lockstep (CLAUDE.md module table + `plan_graph.py` deep-dive + test inventory
count 769 → 778 + the `test_plan_graph.py` line), § 10 version (1.22.0 in pyproject + `__init__` +
uv.lock together — per the repo-location memory), § 13 port lineage (module docstring cites gtd's
`plan_graph.py`; the golden + TestBand mirror gtd), § 14 this debrief. No § 6 tag-discipline
interaction (no tag write anywhere in the engine).

## Open items / handback

- **Operational (this repo):** the v1.22.0 changes are **uncommitted on `feat/order-note-dc4`**
  (which already carries the DC-4 v1.21.0 commit). They should be committed on their own branch
  logically stacked on DC-4 — e.g. `feat/moscow-band-plan-graph` — and PR'd after DC-4 (#31)
  merges, so the version bumps land in order. Whoever commits: message body should carry the
  brief's changelog line and note the transitional thin/enriched divergence.
- **gtd/Cowork side:** none owed by this server change beyond the shared restart. gtd v0.130.0
  already landed its half in claude-plugins (2026-07-05); its spec changelog references the lockstep
  fingerprint `fe2a0a6e201881f6`.
- **Consumer — no action.** The tool boundary is unchanged; boards and artifacts need no update.
  The only effect they see is a better within-tier order after the restart.

## Durable lesson / gotcha

**The parity golden's fingerprint is a lockstep contract — never regenerate it locally to "make the
test pass".** When `_fingerprint`'s hashed field list changes, the golden and the gtd copy must be
regenerated *together* and end up **byte-identical** (`diff -q` the two files). The correct move
here was `cp` from gtd's tree, not re-deriving from this repo's engine — re-deriving would pass
`test_plan_graph_parity.py` locally while silently drifting from gtd if the two engines' field
order ever disagreed. The test's own error message says exactly this: regenerate the golden only
when **both** engines change in lockstep, and update both copies. Also note the position-sensitivity:
the priority field goes *after* estimate and *before* the tags join — any other slot yields a
different (still self-consistent) hash that would not match gtd's.

---
*Source of truth: CLAUDE.md → module table (`plan_graph.py` row, now naming the band tie-break) +
the `plan_graph.py` module + `_band_rank`/`_fingerprint` docstrings; canonical grammar gtd-side in
`moscow-prioritisation.md` and gtd's `plan_graph.py`. Provenance: MoSCoW relay brief (gtd v0.130.0 /
spec v0.29.0, 2026-07-05); implemented 2026-07-05 in this session.*
