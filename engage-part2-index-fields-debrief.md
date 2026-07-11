---
report_type: designed-change-handoff-debrief
scope: rtm-mcp — gtd_project_index per-action engage fields (estimate / contexts / energy / exec) + action-row redaction cascade
implemented_by: Claude Code (Opus 4.8) session on the rtm-mcp repo
derived_at: 2026-07-11
target_repo: rtm-mcp — ~/Library/CloudStorage/Dropbox/Coding/rtm-mcp
artifact:
  version: 1.29.0
  feature_commit: da131f2
  branch: feat/engage-part2-index-fields
relates_to:
  - brief: general/plugin-marketplace-architect/designed-changes/2026-07-05-gtd-engage-part2-live-artifact.md (Part 2 § B, wave 1)
  - predecessor debriefs: phase-c-gtd-project-index-foci-actions-debrief.md, redaction-debrief.md, focus-redaction-debrief.md
status: needs-restart
---

## What shipped

Each `actions` row from `gtd_project_index` now carries the four additive **engage-lens funnel
fields** the navigator's engage lens needs — `estimate` (minutes, or null), `contexts`
(action-context tags, may be `[]`), `energy` (`"high"|"low"|null`), and `exec`
(`"quick"|"now"|"later"|null`) — plus a first-class fix: **action-row `redacted` is now
server-derived and cascades** (own `#redacted` OR a redacted project OR a redacted Area of Focus),
and a shielded action carries **no** engage data (all four suppressed to null/`[]`). Additive and
backward-compatible — every existing field/tool is unchanged; the navigator that reads
`data.projects` and the current action fields is unaffected. Live-verified against the real account
(329 action rows, matching the brief's probe).

## Design decisions & deviations

- **`exec` is one classifier, two aggregations (as the brief asked).** `_exec` reuses the *same*
  `map_prog` (progression tags) + thin `plan_graph.quick_ready` judgement that already produces the
  project-level `ai_quick`/`ai_now`/`ai_later` tallies — nothing new is computed. It collapses to a
  single value with precedence **`now > later > quick`**: `now`/`later` are explicit, user-authored
  progression directives, so they outrank the derived 2-minute `quick` judgement (mirrors
  `map_prog`'s own "explicit tag wins" posture). On **non-overlapping** rows the per-action `exec`
  buckets reproduce the project tallies exactly — the consistency test
  (`test_exec_tallies_match_project_counts`) pins this.
- **Known, intended divergence from a naïve "sum == tallies" reading.** Two cases make the raw sum
  diverge, both by design, both documented in `_exec`'s docstring:
  1. A genuine *overlap* row (`#quick_win` AND `#ai_progress_requested`) is counted in **both**
     `ai_quick` and `ai_now` by `build_index` (independent sums), but `exec` — a single value —
     resolves it to `now`. Overlap is a tagging accident; the consistency test uses non-overlapping
     data as the brief's DoD specifies.
  2. A **redacted** row's `exec` is suppressed to null, but `build_index`'s tallies do **not**
     suppress for redaction. So on live data `sum(exec=='quick')` (11) can be < `sum(ai_quick)`.
     This is correct: the tallies are a count for the project chip; `exec` is per-visible-row data.
- **Redaction cascade moved server-side for actions only (a deliberate, brief-authorised change).**
  The original design kept the focus→project→action redaction cascade *client-side* (documented in
  the Redaction surface note). The brief makes redaction first-class and requires that a shielded
  row leak no engage data — which is only enforceable if the server knows the effective redaction
  state. So `build_actions` now computes `redacted = own OR project OR focus` and gates the four new
  fields on it. **Project and foci rows are untouched** (still own-tag-only) — actions are the sole
  cascade, because they are the only rows with engage data to suppress. This flipped one existing
  tool test's expectation (an open action under a redacted project/focus is now `redacted:true`);
  that assertion was updated with a comment explaining the cascade.
- **`contexts` is multi-value with no default** — unlike `canvas_seed.map_context` (single value,
  defaults to `using_device`). The engage funnel needs the *set* actually present so an empty list
  can exempt the item from the context filter; a default would wrongly filter-in every untagged
  action. Emitted in the canonical `_CONTEXT_TAGS` order for determinism; membership is **not**
  validated beyond that known set (gtd owns the taxonomy — pass-through verbatim).
- **`energy` both-tags → null** (defensive data-error posture, per the brief) rather than a
  preference; the gtd tag-audit flags the double-tag. The `#high_energy`/`#low_energy` pair is being
  codified gtd-side in parallel and is currently **absent** in the account — every live row reads
  `energy: null`, which is the intended "unrated → exempt" state.
- **`estimate`** reuses the canonical `parsers.parse_estimate_minutes` (handles ISO-8601 `PT…` and
  human "30 minutes"), read from the envelope row's raw estimate. 0/329 live rows carry one today
  (matches the brief's probe) — null-dominant is expected and fine.

## Membrane / activation

- **Vault-free, pure RTM, no new tag** — no strict-tag interaction, **no activation-ordering
  hazard**. (`#high_energy`/`#low_energy` are *read* if present; their absence is a clean null, not
  an error — they do not need to exist for this to ship.)
- **Additive + backward-compatible**: the four new fields and the widened `redacted` are extra keys
  on action rows; existing consumers ignore them.
- **To go live: restart the MCP server on v1.29.0.** The running connector is still 1.28.0 (so the
  live smokes below were run against the new code *in-process*, not through the connector). No other
  step. The gtd-side engage template consumes these fields and ships in parallel in Claude Desktop.

## Verification done

- **Ran:** `make lint` (ruff check + ruff format --check + pyright — clean) and `make test` —
  **850 passed** (was 840; +10 new tests in `tests/test_project_index.py`, +0 net in
  `test_gtd_tools.py` where 2 existing tests were amended).
- **New tests** (`TestActionEngageFields` + `TestRedaction` additions): estimate normalisation
  (minutes/ISO/null); contexts pass-through in canonical order + empty; energy high/low/both→null/
  neither→null; exec values + `now`-beats-`quick` precedence + blocked-`now` abstains + the
  tallies-match-project consistency test; redaction cascade from project and from focus; shielded-row
  engage-field suppression.
- **Live smoke (in-process, against the real account):** 329 action rows; full field set present;
  `exec` = {None: 318, quick: 11}; `energy` all null; `estimate` 0/329 with a value; `contexts` on
  99 rows; **175 shielded rows, 0 leaking engage data**; payload ~140 KB (growth negligible, ~4 small
  fields × 329 rows).
- **Not run:** the live smoke *through the MCP connector* — the connector serves 1.28.0 until the
  server is restarted, so it cannot yet see the new fields. Validated in-process instead (same code
  path the tool calls).

## Conventions

- § 6 tag discipline — no tag *writes* here (read-only tool); the cascade reads `#redacted` only.
- § 9 documentation lockstep — updated all four touchpoints: `README.md` (GTD tools), `server.py`
  instructions block, `CLAUDE.md` (module table + `project_index.py` feature section + Redaction
  surface note), and the § Testing test-count inventory (840 → 850; test_project_index.py 62 → 72).
- § 10 versioning — minor bump 1.28.0 → **1.29.0** (additive fields) in `pyproject.toml`,
  `src/rtm_mcp/__init__.py`, and `uv.lock`.

## Open items / handback

- **Consumer (gtd engage template) — no server action.** The fields are ready; the template reads
  them. Report back the version + commit to the parent pack § 3 change order and RTM Inbox_Stuff item
  1215859817 (the approved design item) — the RTM note is a manual step (this session did not write
  it).
- **Out of scope, not started (later waves):** the served `pulse` field (parent pack § C); any
  taxonomy/validation of the energy or context tags (gtd-side); provisioning
  `#high_energy`/`#low_energy` in the account (gtd-side — until then `energy` is uniformly null,
  which is correct).
- **Restart the server on v1.29.0** to expose the new fields through the connector.

## Durable lesson / gotcha

Two traps for the next author:

1. **`DEPENDS-ON` upstream ids are matched by a digits-only regex** (`project_plan._extract_deps_and_files`).
   A blocked-test fixture whose upstream id is non-numeric (e.g. `"up"`) silently yields *no* edge, so
   the item reads unblocked — the blocked-`now` test failed exactly this way until the ids were made
   numeric (`301`/`302`).
2. **`build_index` tallies and `build_actions.exec` are the same classifier but not the same
   aggregation.** The tallies are independent sums that can double-count an overlap row and never
   suppress for redaction; `exec` is a single per-row value that does both. Don't "fix" a live
   `sum(exec) != sum(ai_*)` mismatch — it's the redaction suppression (and rare tag overlaps), by
   design.

---
*Source of truth: `CLAUDE.md` → "Portfolio index (`gtd_project_index`)" §, the `project_index.py`
module-responsibility row, and the `build_actions` / `_exec` / `_energy` / `_contexts` docstrings.
Provenance: implemented 2026-07-11 from the Engage Part 2 brief (Part 2 § B, wave 1).*
