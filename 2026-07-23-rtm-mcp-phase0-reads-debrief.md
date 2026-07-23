report_type: handback-debrief
scope: gtd-domain-tool-suite / Track-0 + Phase-0 (reads pilot)
target_repo: rtm-mcp
brief: 2026-07-23 Track-0 + Phase-0 reads hand-off brief
version_shipped: 2.3.0
branch: feat/gtd-phase0-reads
status: debriefed
derived_at: 2026-07-23

# Handback debrief — Phase 0: typed GTD read tools on rtm-mcp

## 1. What landed

Thirteen read-only `gtd_*` tools (rtm-mcp **v2.3.0**), on branch `feat/gtd-phase0-reads`
(commits `7047a19` feat + `3e4af19` the todays_field scope fix). Additive only — every `.ms` script
and existing tool is untouched; no writes, no timeline, no new tag. **Detectors were promoted
one-tool-per-script** (Paul's decision), not a discriminated `gtd_candidates(kind)`.

**Nine promoted detectors** (faithful ports, `src/rtm_mcp/detectors.py`) — each envelope versioned:

| Tool | Source `.ms` | Envelope |
|---|---|---|
| `gtd_reassessment_candidates` | reassessment-candidates.ms | `ReassessmentEnvelope` |
| `gtd_unblock_candidates` | unblock-candidates.ms | `UnblockEnvelope` |
| `gtd_decision_candidates` | decision-candidates.ms | `DecisionEnvelope` |
| `gtd_deliverable_candidates` | deliverable-candidates.ms | `DeliverableEnvelope` |
| `gtd_research_candidates` | research-candidates.ms | `ResearchEnvelope` |
| `gtd_calendar_prep_candidates` | calendar-prep-candidates.ms | `CalendarPrepEnvelope` |
| `gtd_capture_candidates` | capture-candidates.ms | `CaptureEnvelope` |
| `gtd_topic_clusters` | topic-cluster-detector.ms | `TopicClustersEnvelope` |
| `gtd_health_check` | health-check.ms | `HealthCheckEnvelope` |

**Four new collection/context reads** (`src/rtm_mcp/gtd_reads.py`):

| Tool | Envelope | Note |
|---|---|---|
| `gtd_query(perspective)` | `GtdQueryEnvelope` (+ Candidates) | `next_actions_by_context` \| `todays_field` \| `focus_projects` |
| `gtd_inbox_state` | `InboxStateEnvelope` | 3 Inbox_Stuff health signals in one read |
| `gtd_waiting_for_queue` | `WaitingForEnvelope` | chase queue + >14-day staleness |
| `gtd_context(task_ref, depth)` | `GtdContextEnvelope` (+ Candidates) | STATE-first note-reading-protocol bundle |

Full six-surface conformance: enriched docstrings, per-param descriptions, `READ_ONLY_ANNOTATIONS`,
versioned `output_schema` on every tool, advisory `perspective`/`depth` enums sourced from the
canonical `VALID_PERSPECTIVES`/`VALID_DEPTHS` frozensets, and typed `data.error` (only `gtd_query`
and `gtd_context` are failable — `invalid_input`, `missing_parameter`, `task_not_found`,
`focus_not_found`; the 11 detector/collection reads are structurally infallible). Docs lockstep done
(README, server.py `instructions=`, CLAUDE.md arch tree + module table + test inventory); fingerprints
regenerated (69 tools, source_version 2.3.0).

## 2. Deviations from the brief (decisions, not diff)

- **Read strategy = verbatim filter passthrough.** Each detector's `rtm.getTasks("…")` filter string
  is passed *verbatim* to `rtm.tasks.getList(filter=…)`; the pure builder replays the identical
  client-side logic. This is the truest "document-what-is" port and made the faithful-port test
  trivial. Multi-query detectors issue several `getList` calls — the read-only **call surface stays
  exactly `["rtm.tasks.getList"]`** (one method), asserted per tool.
- **One intended faithful divergence — `gtd_health_check` avoids the `.ms` N+1.** The script ran one
  child sub-query *per project*; since all six of its queries are `status:incomplete`, the tool does
  **one broad read** and computes the parent→children map (and the `isSubtask`/`hasDueDate`/
  `updatedBefore` predicates) client-side. Same result set, no N+1. It also enriches each issue row
  with `task_id`/`deep_link` (the `.ms` emitted name-only text).
- **Output is typed rows, not the `.ms` line-oriented text.** The tools emit the structured candidate
  objects the scripts built internally, plus three deterministic enrichments the brief asked for —
  `deep_link` (`project_plan._permalink`), `kind` (`canvas_seed.map_kind`), and the `priority` band.
  `blocked`/`quick_win` were **not** added (they'd need per-candidate plan-graph reconstruction = new
  logic); flagged for a later phase.
- **`include_paused` (reassessment) deliberately not implemented** — its header documents it but the
  `.ms` code never reads it. Documented-but-dead; faithful ports don't resurrect it.
- **Naming** follows the brief's own examples (`gtd_<noun>_candidates`), noting the mild tension with
  the D10 verb-first ideal (`gtd_<verb>_<noun>`) — the brief's names won for this phase.

## 3. Test results

- **Full suite green: 1140 tests** (was 1077; +63). `make lint` clean (ruff + pyright, 0 errors).
- New: `tests/test_detectors.py` (28 faithful-logic tests), `tests/test_gtd_reads.py` (14),
  `TestGtdPhase0Reads` in `test_tools/test_gtd_tools.py` (21 — a parametrised read-only-call-surface
  test across all 13 + shape/typed-error spot-checks). `test_tool_schemas.py` +2 (the perspective/depth
  enum asserts) and the six-surface + advertised-error + fingerprint guards cover the 13 automatically.
- **Fingerprint delta: additive only — 13 new `mcp__rtm__gtd_*` entries** (56 → 69 tools). The
  pre-existing 56 fingerprints are unchanged (no schema churn — this was a pure addition, not an enum
  registry change).

## 4. Read-path benchmark — the pilot's gate evidence

Measured live against Paul's account (the tools run locally against real RTM; the connected server is
still v2.2.0). **`raw` = the getList payload the server consumes internally and the model never sees;
`model receives` = the compact typed projection returned to the caller.** The whole point of the phase
is that column-3 number, not column-2.

| Tool | getList calls | raw consumed (B) | model receives (B) | rows |
|---|---:|---:|---:|---:|
| reassessment | 3 | 68,397 | 9,485 | 21 |
| unblock | 5 | 555,480 | 22,869 | 50 |
| decision | 1 | 706,456 | **823** | 0 |
| deliverable | 1 | 706,456 | 12,165 | 21 |
| research | 1 | 706,456 | 1,500 | 3 |
| calendar_prep | 1 | 21,940 | 1,002 | 2 |
| capture | 4 | 68,354 | 9,980 | 21 |
| topic_clusters | 1 | 2,675,960 | 5,055 | 4 |
| health_check | 1 | 2,682,633 | 48,418 | 211 |
| query · todays_field | 1 | 119,596 | 15,755 | 46 |
| query · next_actions | 1 | 706,456 | 180,798 | 486 |
| inbox_state | 1 | 637,829 | 53,746 | — |
| waiting_for | 1 | 111,456 | 19,600 | 52 |
| context (1 task) | 2 | — | **2,126** | — |

**The three brief-representative reads (generic vs new tool, model-facing bytes):**
- **Chase queue** (`gtd_waiting_for_queue`): a raw `list_tasks(tag:waiting_for…)` echo is **111 KB /
  52 tasks** the model must interpret; the tool returns **19.6 KB** of typed rows with the `stale`
  flag computed server-side (**~5.7×** smaller, and pre-analysed).
- **Today's field** (`gtd_query todays_field`): raw **119.6 KB / 46 tasks** → **15.8 KB** (**~7.6×**).
- **Context for a task** (`gtd_context`): the note-reading protocol is otherwise 3–4 generic calls
  (find task + `get_task_notes` + siblings + parent notes) the model stitches together; the tool is
  **one logical call returning 2.1 KB** — STATE-first, siblings + ancestry included.

**Headline.** The model never ingests the multi-megabyte raw `getList` payloads (topic-cluster
**2.68 MB**, health-check **2.68 MB**, the action list **706 KB**). For the candidate detectors it
receives **only the matching candidates** — e.g. `gtd_decision_candidates` returns **823 bytes /
"0 candidates today"** instead of the model reading 486 raw actions to find none. Reductions of
**1–3 orders of magnitude** on the payload the model pays for, plus the GTD interpretation (kind,
staleness, blocked-note detection, clustering) moved server-side. **The benchmark is rewarding — it
authorises the Phase 1 (everyday writes) brief.**

**Faithful-port cross-check (live).** Two detectors — one tag-scan (`reassessment`) and one
regex-based (`deliverable`) — were run as their `.ms` via `rtm_run_script_ephemeral` and compared
id-for-id to the native tool against the same live account: **both byte-identical (21 = 21)**. (A
first deliverable run showed 42 vs 21; the cause was a harness artifact — the ephemeral runtime's
`getTags()` returns tag *objects*, not strings, so my hand-rolled comparison silently failed; using
`tag.getName()` it matched exactly. Not a tool discrepancy.) The remaining seven detectors are pinned
by the unit-level faithful-logic tests; a full live sweep is a cheap follow-up.

**Bug caught by live verification (fixed in-phase).** `gtd_query todays_field` initially matched
**39,225 rows** — the list-catalogue TODAY filter is a *smart-list definition* whose incomplete-scoping
the RTM UI implies; via the API its absence pulls years of completed/recurring dated occurrences. Now
explicitly scoped to `status:incomplete` (46 rows live). This is exactly the class of error unit tests
(mocked getList) cannot catch — the value of the live benchmark.

## 5. Marketplace-side lockstep (for a follow-up `/marketplace commit`)

This phase **enables**, but does not perform, the gtd consumer migration:
- Route the gtd periodic-workflow reads and `context-initialisation` through the new tools
  (`gtd_reassessment_candidates` etc. instead of `rtm_run_script_ephemeral <script>.ms`;
  `gtd_context` for the note-reading protocol; `gtd_query`/`gtd_inbox_state`/`gtd_waiting_for_queue`
  for the collection views). **Leave the `.ms` scripts in place** — deprecation is a separate,
  migration-gated step.
- **Cite, don't duplicate**: the wrapper skill can now point at the advertised versioned envelopes
  instead of hand-documenting shapes.
- **Track-0 codification** (naming/param-contract in git-ops `mcp-tool-documentation-standard.md`)
  remains a parallel marketplace action; note the `gtd_<verb>_<noun>` vs `gtd_<noun>_candidates`
  tension for that decision. The write-tool codification gaps (`#hold`/`#do_not_auto_progress`,
  smart-list count) stay deferred to the write phases.
- **Activation**: ✅ DONE — server restarted on v2.3.0 (2026-07-23); all 13 tools live and
  smoke-tested through the deployed connector (see the verification boundary below).

## 6. Follow-ups / open items
- Live faithful-port sweep of the remaining 7 detectors (cheap; two representatives already identical).
- `blocked`/`quick_win` candidate-row enrichment (deferred — needs per-candidate plan-graph).
- `gtd_context` note-ordering is a *reasonable-faithful* realisation of the protocol (STATE → INCEPTION
  → newest 2–3 → DECISION); exact tie-breaks are worth a review against journaling-lifecycle if the
  board surfaces edge cases.
- Recurring local-venv quirk (`uv sync` drops the editable install; cure = `rm -rf .venv && uv sync
  --all-extras` then `uv pip install -e .`) — unrelated to this change but hit twice this session.

## Verification boundary (honest)
Everything in §3 is machine-verified (suite + lint + fingerprints, reproducible via `make test` /
`make lint` / `make fingerprints`). §4's benchmark and cross-checks are **live, one-shot measurements
against Paul's account on 2026-07-23** — they will vary with account state, and only 2 of 9 detectors
were live-cross-checked (the other 7 rest on unit tests).

**Deployed-server verification (added after the v2.3.0 restart).** Paul restarted the MCP server and
Claude Desktop; all 13 tools are exposed and were smoke-tested **through the deployed connector**:
- Advertised schemas correct end-to-end — enriched descriptions survived the FastMCP docstring shim,
  both advisory enums (`perspective`, `depth`) present, typed-error contract documented.
- `gtd_decision_candidates` → compact payload with the faithful `skipped` reasons
  (personal-not-opted-in / already-contrib-drafted / matched-anti-pattern).
- `gtd_context` (bad ref) → structured `task_not_found` (`code`/`message`/`rtm_code`/`details.query`).
- `gtd_query focus_projects` (bad focus) → structured `focus_not_found`.
- **`gtd_query todays_field` → 46 rows** (the pre-fix filter matched 39,225) — the fix is live, and
  the payload is the intended typed projection (kind/priority/due/deep_link, overdue-first, with the
  untagged capture-catch items trailing).

One cosmetic defect found and fixed in that pass (`020ea6c`): `resolve_focus`'s `focus_not_found`
recovery hint named only `frame.focus` (the `gtd_create_project` param), misdirecting a `gtd_query`
caller; it now names both. Fingerprints unaffected (runtime prose is not part of the advertised
schema); suite still 1140 green, lint clean.
