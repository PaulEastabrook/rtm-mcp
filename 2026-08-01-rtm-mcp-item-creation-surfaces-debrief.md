---
report_type: handback-debrief
scope: GTD item-creation surfaces — classifier divergence, silent property loss, blank-name drafts
implemented_by: Cowork session, 2026-08-01
derived_at: 2026-08-01
target_repo: rtm-mcp
artifact:
  branch: fix/item-creation-surface-divergence
  version: v6.2.0
relates_to:
  - "general/plugin-marketplace-architect/handoff-briefs/2026-07-31-gtd-rtm-mcp-item-creation-surfaces-brief.md"
  - "2026-08-01-rtm-mcp-silent-parameter-loss-debrief.md"
status: needs-restart
---

# Handback debrief — the three item-creation surfaces (v6.2.0)

**The brief's headline premise was wrong, and finding that out was the first hour's work.** It
described a v5.1.1 already sitting uncommitted on `main` and asked this session to review it. That
work is **not in the repo and never was** — the originating session left it uncommitted on a
different machine and it was never pushed. Meanwhile `main` advanced from v5.1.1 to **v6.1.1**
through an entirely separate programme (the note-vocabulary visit, then the silent-parameter-loss
detector), and the v5.1.1 the brief claimed is a *different* v5.1.1 in this repo's history
(`85d994b`, "recognise what the server writes"). So § 3.1 became re-implementation, not review.

**Every defect the brief describes was then re-verified against v6.1.1 rather than inherited.** All
four are live at HEAD. The v6.1.0 markup detector does not cover this class: it fires on markup
*leaked into* a string argument, and a classifier key the closed map ignores **arrives perfectly
well** and is simply never read. And `build_advisory` fires only when *every* optional is absent —
a commit carrying `project_id` and `adds` is never bare, so the incident would have been just as
silent today as it was on 2026-07-31.

---

## What shipped

**v6.2.0 — additive.** No signature change, no removed behaviour, no new `ErrorCode`, no gate.

| # | Change | Where |
|---|---|---|
| 1 | `classifiers.energy` read and written as a tag on both canvas surfaces | `canvas_commit.classifiers_to_tags` |
| 2 | `estimate` applied on `gtd_canvas_commit` `adds[]` (it already was on `items[]`) | `tools/gtd.py` adds loop |
| 3 | An unrecognised key at **either** level → `not_applied[]`, never dropped | `canvas_commit.unknown_keys` + `_unrecognised_key_entries` |
| 4 | `calendar_entry` accepted as a synonym of `calendar` | `canvas_commit.TYPE_TAG` |
| 5 | Blank / whitespace-only / non-string item `text` rejected up-front, both surfaces | `canvas_commit.blank_text_rejection` |
| 6 | `EXAMPLES` asserted callable against the live schema | `tests/test_tool_examples.py` (new) |
| 7 | Three wrong worked examples corrected | `tool_help.EXAMPLES` |

### The § 5 decision, and the evidence the brief could not see

The brief offered three options in preference order and asked for judgement given sight of the
artifact board's commit payload. **Taken: (c) unconditionally, (b) in full, and the honest subset
of (a) — everything in (a) that is non-breaking. Full key-unification deferred as a designed
change.**

**The board's payload settles it.** `recomputeStage` (line ~1193) and `draftItems` (line ~3013) of
`project-plan-artifact.html` both build `{type, text, classifiers}` where `classifiers` is exactly
`{context?, comms?, priority?, quick?}`. **The board never sends `energy` or `estimate` at all.**
So accepting them is **purely additive** — zero coordination, no version-lockstep arc, nothing to
break. The brief's worry that (a) is "breaking for the artifact board's commit payload" is true
only of the *key-renaming* half, which is a separable decision.

Two further observations from the same file strengthened it:

- **The board's engage funnel already READS both facets** (`engEstimate` / `engEnergyOf`, lines
  ~1598-99) and renders "unsized" / "unrated" chips. Its own UI is built around these two existing
  — it simply had no way to write them. This is closing a loop the board already half-implements,
  not adding a facet.
- **The board sends `calendar`**, matching the two canvas surfaces and diverging from
  `gtd_item_create`'s `calendar_entry` — which CONTRIBUTING § 2.5 quotes as the *anchor* that
  settles the `item` vocabulary. So neither spelling can simply win.

**Why full unification is not affordable, and would not have been in a later pass either.**
CONTRIBUTING § 2.8 records the decisive lesson from the v3.1.0 alias removal: *a rendered artifact
is a frozen copy of its template, so it is a live caller no repo grep can see* — the standing board
held four stale tool names in both its code and its `mcpTools` allowlist seven days after the
template moved on. Renaming `text`→`name`, `type`→`kind`, or flipping the calendar enum breaks
**every already-rendered board in Paul's account**, silently, with no upgrade path. That needs
§ 2.8's one-release alias machinery, which is a designed change, not a line item.

**But the enum divergence closes non-breakingly by widening**, and that is the incident's first
failure gone permanently: `calendar_entry` is now an accepted synonym mapping to the identical tag,
with `calendar` still the sole canonical spelling in the advertised description and the rejection
prose. Accepted ≠ advertised; the synonym is a migration affordance, pinned by test.

### Why no new `ErrorCode`

Reused `NO_DURABLE_WRITE` for the unrecognised-key entries. The churn ladder from the
2026-08-01 silent-parameter-loss debrief § 6 is the reason: **a new `ErrorCode` re-fingerprints all
100 tools; a member already in `RECEIPT_REASONS` costs nothing.** "You asked for this and no RTM
write happened" is exactly the outcome, `detail` carries the specifics, and CONTRIBUTING § 5 says
reuse where one fits. Total fingerprint churn is **2** — `gtd_canvas_commit` and
`gtd_project_create`, whose `adds[]` / `items[]` descriptions genuinely changed.

### Where the brief was factually wrong

**Its § 4.1 table records `energy` as a working sibling key on `gtd_project_create`.** It is not.
That surface applied `estimate` and did **not** advertise, read, or report `energy` — it was not
even in the `items[]` schema string. So `energy` was lost by **both** canvas surfaces, not one, and
the CBRE plan lost it whichever path wrote each item. Corrected in the changelog and pinned by
`test_item_energy_is_written_as_a_tag`.

**Its § 4.2 claim that `gtd_project_create`'s example keyed items on `name` does not hold here.**
That example has used `text` since v3.3.0 (`8360a51`) — verified with `git log -S`. The
`gtd_item_create` half of the claim is exactly right and was still live: `contexts=`, `life=` and
`waiting_on=` are not parameters and never have been.

**Its baseline test count (1743) was stale**; the true baseline at HEAD was **1824**.

### The EXAMPLES sweep found a third offender

The brief asked, in its own debrief template, whether the sweep would find more. **It did.**
`gtd_chat_post` used `message=` in both its worked examples; the parameter is `text`. Both examples
were unusable, in a tool the board polls, and nothing had ever checked. `tests/test_tool_examples.py`
parses each example with `ast` and asserts every keyword against the **live advertised schema** —
plus that no example omits a required parameter, uses positional arguments, or (on the two canvas
surfaces) keys an item on `name`. It found `gtd_chat_post` on its first run.

---

## Design decisions & deviations

1. **`energy` is a classifier, not a sibling key.** It *is* a tag, so it belongs beside `context`
   and `comms`. The payoff is structural rather than aesthetic: routing it through the single
   `classifiers_to_tags` means `collect_commit_tags` / `collect_create_tags` feed it to the
   strict-tag existence gate **for free**, with no new gate wiring and no second place to drift.
2. **`ENERGY_TAGS` moved to `canvas_commit`**, with `gtd_writes.ENERGY_LEVELS` now an alias of it.
   `gtd_writes` already imports `CONTEXT_TAGS` / `COMMS_TAGS` from there, so `canvas_commit` is the
   canonical home of the classifier vocabularies; the import direction forbids the reverse. This
   removed a duplicate definition rather than adding one. *(A third copy remains in
   `tag_report.ENERGY_TAGS` — pre-existing, out of scope, captured as a follow-up.)*
3. **Unrecognised keys are checked at both levels** (item and nested `classifiers{}`) because the
   two measured losses sat one at each — `estimate` a sibling key, `energy` a classifier. Checking
   one level would have caught one bug and left the class open.
4. **Reporting, never rejecting.** An unknown key is advisory data; the write still lands. A gate
   would break every caller passing a field a future version adds, and would invert the receipt's
   own invariant that a caller ignoring all three fields still gets a correct result.
5. **Blank `text` IS a rejection**, and that asymmetry is deliberate. An unknown key is a *narrower*
   write; a nameless item is an *impossible* one that RTM refuses per-child **after** the project
   and its notes are durable. Rejecting restores the atomicity the surface's own documentation
   claims — for this failure class only (see the honest-boundary note below).
6. **Deviation from the brief's § 8 versioning:** it proposed v5.2.0 for a (b)/(c)-only change. The
   repo is at 6.1.1, so this is **v6.2.0**. Additive throughout, so MINOR is right under
   CONTRIBUTING § 10 regardless.
7. **Deviation required by the repo's own guidance:** CONTRIBUTING § 14 requires this repo-root
   handback debrief; the brief asked only for the vault-side architect debrief. Both exist. § 9's
   four-place documentation lockstep and § 12.11's version bump are likewise repo obligations the
   brief did not enumerate.

---

## Membrane / activation

**Additive and backward-compatible.** Every call legal before v6.2.0 is legal now and behaves
identically, with two intended differences: a previously-silent dropped key now appears in
`not_applied[]` (advisory data — nothing branches on it), and a previously-half-written
blank-name draft is now rejected whole.

- **To go live: restart Claude Desktop onto v6.2.0.** Nothing in this change does anything until
  then. Note the still-open restart from v6.1.0/v6.1.1 — one restart picks up all three.
- **Tag provisioning:** `high_energy` / `low_energy` must exist in the RTM account before a caller
  passes `classifiers.energy` under strict-tag mode. **They already do** — `gtd_item_create` has
  written them since Phase 1 — so no action; recorded because the gate would reject the whole
  commit if they did not.
- **Ordering hazard: none.** The gtd-side lockstep (`write-recovery.md`, the corrected atomicity
  claim, the SKILL.md rule) is documentation and can land either side of the restart.
- **Rollback** is a branch revert; no data migration, no schema removal.

---

## Verification done — and its boundary

**Ran, on this machine, against `~/.venvs/rtm-mcp` (Python 3.14.3):**

- `make lint` — ruff check, `ruff format --check`, `check-tool-naming --strict`, pyright: **0 errors**.
- `make test` — **1868 passed, 0 failed** (baseline at HEAD: 1824; **+44**).
- `make fingerprints` — regenerated; 2 tools changed; `source_version` now 6.2.0.
- `make format` — applied.
- Per-file collection counts confirmed for the CLAUDE.md § 9 inventory.

**Not run, and why:**

- **No live smoke against the RTM account.** The server is not running v6.2.0 until Claude Desktop
  restarts, so every assertion here is in-suite. In particular, *`setEstimate` on an `adds[]` child
  has not been observed against real RTM* — it is asserted at the call boundary (method name +
  kwargs) via the `FakeMCP` pattern, exactly as the sibling `items[]` path already was.
- **The strict-tag path for `classifiers.energy` was not exercised against a real account.** The
  in-suite test asserts `high_energy` enters `collect_commit_tags`, which is what the gate reads.
- **The artifact board was read, not run.** The payload analysis is from the template source
  (`project-plan-artifact.html`), not from an observed live call. A *rendered* board may differ
  from its template — which is precisely the § 2.8 hazard this change refuses to gamble on, and the
  reason the breaking half of (a) was not taken.
- **The `tag_report.ENERGY_TAGS` third copy** was left alone rather than folded in.

**A hazard hit and worth recording:** a bare `uv run pytest` (to collect per-file counts) recreated
the in-repo `.venv` the Makefile pin exists to prevent, and immediately failed with
`ModuleNotFoundError`. The pin is on the `make` targets, not on `uv` — **any ad-hoc `uv` invocation
must carry `UV_PROJECT_ENVIRONMENT` explicitly.** The repo was also carrying a `.venv/lib 2` iCloud
conflict copy on arrival; `rm -rf .venv` before the first `make dev` is now the opening move.

---

## Conventions

| § | What it governed |
|---|---|
| § 2.5 / § 2.8 | The `calendar_entry` anchor; **rendered artifacts are invisible live callers** — the decisive constraint against renaming |
| § 3 / § 12.3a | Six documentation surfaces; `EXAMPLES` for JSON-coerced params |
| § 4.1 | The teaching receipt — populate `not_applied[]`, never gate on it |
| § 5 | Reuse an existing `ErrorCode`; the registry is additive-only |
| § 6 | Report-vs-reject placement; a gate must not be widened casually |
| § 7 / § 8 | Source style; `FakeMCP` + call-surface assertions |
| § 9 | Four-place lockstep — README, `server.py` instructions, CLAUDE.md tree, CLAUDE.md test inventory (+ fingerprints) |
| § 10 | SemVer — additive → MINOR |
| § 14 | This debrief |

---

## Open items / handback

| Item | Owner | State |
|---|---|---|
| Restart Claude Desktop onto v6.2.0 (also activates v6.1.0 / v6.1.1) | **Paul** | open — nothing is live until then |
| Full key unification (`text`↔`name`, `type`↔`kind`) via § 2.8 one-release aliases | **architect** | open — designed change, deliberately not attempted here |
| Board template: send `energy` / `estimate` on `adds[]` / `items[]` — the server now accepts them, the board's funnel already reads them, but its editor cannot set them | **gtd / ui-patterns** | open — the write half of a loop now open at both ends |
| `tag_report.ENERGY_TAGS` — the third copy of the energy pair | **rtm-mcp** | open, cosmetic |
| Sibling servers (agent-memory, mindmeister, meistertask) share the receipt and the same unrecognised-key exposure | **architect** | open — `unknown_keys` is ~10 lines and portable |
| The v5.1.1 work stranded uncommitted on the other machine | **Paul** | open — check that clone; it may hold unpushed work beyond this brief's scope |

**Consumer impact — additive only.** No consumer call changes shape, name, or behaviour. A consumer
that reads `not_applied[]` (the board does, via `naText`) may now see entries it did not before;
that is the feature.

---

## Durable lesson

**A brief is a snapshot, and the repo does not hold still.** This one was 24 hours old and wrong in
five separate ways — the work it called "already landed" did not exist, the version it named was
taken by different work, its baseline test count was stale, one row of its central divergence table
was factually inverted, and one of its two named example defects had been fixed three months
earlier. Nothing in it was careless; the repo simply moved. **Re-verify every premise against HEAD
before implementing, and report the deltas as findings rather than silently coding around them** —
the deltas were more informative than the brief.

The structural version, which is the same lesson the sibling debrief reached from the other side:
**the brief's most valuable output is where it turns out to be wrong.** Its own § 2 says so
("where any of these disagree with this brief, they win"), and its § 9.2 asks for the deviations
explicitly. That instruction is what made the first hour's reconnaissance the right use of time
rather than a detour.

And the narrow one, for anyone touching these three surfaces next: **a closed mapping that ignores
what it does not recognise is a data-loss bug wearing correct code.** `classifiers_to_tags` was
right as a function and wrong as a surface for months. The fix that matters is not the two facets
it now reads — it is that it now says what it did not.

---
*Source of truth: `CLAUDE.md` § "Canvas tools (`gtd_project_canvas` / `gtd_canvas_commit`)" and the
`gtd_canvas_commit` / `gtd_project_create` docstrings; `src/rtm_mcp/canvas_commit.py`
(`CLASSIFIER_KEYS`, `TYPE_TAG`, `unknown_keys`, `blank_text_rejection`). Provenance: hand-off brief
`2026-07-31-gtd-rtm-mcp-item-creation-surfaces-brief.md`, re-verified against v6.1.1 HEAD; the
artifact board's commit payload read from
`claude-plugins/plugins/gtd/skills/gtd/references/templates/project-plan-artifact.html`.*
