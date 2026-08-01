# Changelog

Notable changes to rtm-mcp. Started at v3.0.0 because that is the first release with a migration
to describe; the full history before it is in the dated `*-debrief.md` files at the repo root, and
the architecture record is `CLAUDE.md`.

## v5.1.2 — SCOPE registered as a canonical note type

`SCOPE` added to `CATALOGUE_NOTE_TYPES` — the server codification of a canonical-vocabulary
change made **first** in gtd's `note-shape-catalogue.md` § 2a (codification before validation;
the markdown stays the authority, this file follows it).

**Why one legacy token was promoted while ~40 others are being rewritten.** The 2026-07-31
full-estate census found `SCOPE` in use 15 times across three months, always deliberately, always
recording the same thing: a project changing shape ("Project expanded from single waiting-for to
10-item phased plan", "Refocused to Shell-only", "Role reframed to Principal Platform Engineer").
No canonical type carries that meaning. Rewriting it to `CONTEXT` would have been the only change
in the remediation pass that **destroyed information rather than tidying it** — fifteen times.

The rule this establishes: promote a legacy token when it is recurring, semantically distinct from
every canonical type, **and** deliberate rather than a misspelling; rewrite it otherwise. Of ~40
observed tokens, `SCOPE` is the only one meeting all three. `EXECUTOR` (21 uses) is recurring and
deliberate but not distinct — it is engine `PROGRESS`. The bar is deliberately high: a catalogue
that admits every observed token stops being prescriptive.

Read-set addition only; no gate, no tool change, fingerprints byte-identical.

## v5.1.1 — the server recognises what the server writes, and one odd item stops killing a read

Two defects found while measuring for the note-vocabulary promotion (hand-off brief
`2026-07-30`), both in `surface_queue.py`, both **silent**: neither raised an error a caller could
act on, which is why neither had been noticed. Patch by § 10 — no tool gained, lost or changed a
parameter, description, annotation or output schema, and `tool-fingerprints.json` is byte-identical.

### 1. `ACTIVITY-REPORT` — the emission set had drifted from the read set

Wave 1b (v2.10.0) corrected the **emitted** token to `ACTIVITY-REPORT` (hyphen), because
`note_shape.check_title`'s TYPE grammar is `[A-Z][A-Z -]*` and rejects the underscore. The
**read** set `SURFACE_NOTE_TYPES` was not updated with it. So for two releases the server wrote a
note type its own classifier scored `unrecognised` — measured live 2026-07-31, two notes sitting
in `unrecognised_notes[]` on `AI_Activity`.

Both spellings are now in the read set, and that is not redundancy: the hyphen form is what the
server **writes**, the underscore form is what live data **carries** and can no longer be written.
Removing either re-opens a silent mis-classification.

**A mis-classification produces a wrong answer, not an error** — which is why the write-side
assertion Wave 1b added was not enough on its own. The read and write sides are now pinned
together in one test, so neither can move alone again.

### 2. `gtd_surface_queue` — one item's metadata took out the whole `questions` surface

`surface="questions"` and `surface="both"` returned **nothing at all**: `Output validation error:
'[approve, decline, defer]' is not of type 'array'`.

`surface_body` writes `expected_response_options` block-style, so the parser only ever produced a
list. A live item carries the **flow** form `expected_response_options: [approve, decline, defer]`
— written by something other than the current writer — which went down the inline branch to
`_scalar` and landed a *string* under a key the row schema declares as an array. Strict output
validation then rejected the entire response.

Fixed in two layers, and the second is the general one:

- `_option_list` reads the flow form properly (a bare scalar becomes a one-element list rather
  than an error — a single offered option is a coherent thing to have written).
- `_as_list` coerces at the row builder, so *whatever* the frontmatter carried, the field is the
  array the schema declares.

**The lesson is not "parse flow lists".** The parser is deliberately a focused reader of the
shapes `surface_body` writes, so unanticipated shapes reaching a typed field will keep happening.
What must not keep happening is that one of them fails the *whole* response — a read returning
nothing is strictly worse than a read returning one odd row, because the caller loses every good
row too. Same posture as `unrecognised_notes[]`: quarantine and report, never refuse.

### 3. `gtd_surface_queue` classified as a BFF tool

It returns an unbounded collection with a strict row schema, and in chat on 2026-07-31 it both
exceeded the client's tool-result ceiling (65,127 characters on `surface="activity"`) and failed
output validation on another surface — but it was absent from `BFF_TOOLS`, because that table is
authored from the memory of which tools were built for a board rather than derived from how a tool
behaves.

It is also in `DUAL_CONSUMER`, and the awkwardness is recorded rather than smoothed over: no board
reads this tool, so `consumer: artifact` would be false, and `either` is the least-wrong value the
vocabulary offers. **Shape and audience are two axes and the taxonomy conflates them.** Deriving
BFF-ness from a property, and splitting the axes, is a designed change — not a line in a set.

## v5.1.0 — a log sink that survives, and both dormant write gates switched on

Implements the approved designed change `2026-07-26-write-boundary-gate-observability.md`,
Stages 1–3. **Behaviour-changing but not breaking by § 10's criterion** — no envelope, signature,
parameter or return-shape change; the two changes are *configuration defaults*, each reversible
with one env var. See § 4 for the bump reasoning and its counter-argument.

### 1. A file log sink that survives `/dev/null` — the prerequisite for everything else

Records now go to a bounded `RotatingFileHandler` (1 MiB × 3 backups) at
**`~/.config/rtm-mcp/logs/rtm-mcp.log`**, **alongside** the existing stderr handler — a
terminal-launched server behaves exactly as before. Location overridable with the new
**`RTM_LOG_DIR`**; `RTM_LOG_LEVEL` still governs both channels.

**Why.** On a Desktop-spawned server **fd 2 is `/dev/null`** (measured with `lsof` + `stat`), so
every write-gate WARNING was destroyed. Interactively that is redundant — the caller already gets
a typed error — but in a **headless flow** the error goes to *an agent*, which handles or retries
it, and Paul never learns it happened. A gate firing repeatedly inside a 06:45 scheduled worker
was invisible. Not the repo clone (the launch config could write there, but logs in a working tree
mean `.gitignore` maintenance and a real chance of committing them); not stdout (JSON-RPC frames).

An unopenable sink **warns and continues** — an observability fix must not become an outage.

**The test is the deliverable.** An in-process "the record emitted" assertion passes against a
server with no sink at all, so the load-bearing test runs a real gate in a **child process with
fd 2 redirected to `/dev/null`**, plus a **counterfactual** that runs the same probe with the sink
unopenable and asserts the gate still fires and leaves no trace anywhere. Verified by stubbing the
sink out: the load-bearing test fails without it.

### 2. `RTM_STRICT_LIST_TARGETS` now ON by default

Refuses only `smart` / `locked` destination lists — both of which fail at RTM anyway — so this
converts a confusing downstream failure into a precise immediate one. No `warn` stage needed.
`add_task`'s **default-list fallback stays ungated**: a configured default of the locked built-in
Inbox would otherwise reject every bare capture on activation.

### 3. `RTM_STRICT_NOTES` now defaults to `shape`, skipping `warn`

Paul's decision. The skip is safe *because* of § 1: `warn` is log-and-allow, so with stderr dead it
neither blocked nor recorded — **the designed middle step did not exist in production**. The live
sample makes it unnecessary anyway: every agent-written title parses (`ORDER`, `CONTEXT`,
`AI-LINK`, `PROGRESS`, `INCEPTION`, `DEPENDS-ON`), as do the legacy `ACTIVITY` / `AR` /
`ACTIVITY REPORT` spellings — the gate checks shape, not vocabulary, and a space is legal in a TYPE
token. `ACTIVITY_REPORT` (underscore) fails correctly and was verified absent from live data.

**Blast radius, measured.** The gate is wired into the generic `add_note` / `edit_note` **only**.
All 37 `gtd_*` note writes call `rtm.tasks.notes.add` directly and never reach it — which is why
four of them legitimately write a bare marker title (`DEPENDS-ON`, `INCEPTION`, `REDACTION`,
`TMPL-STAMP`) this grammar would reject. **Those are correct**: `project_plan` round-trips on them.
So this governs exactly the escape hatch, which is where drift enters.

**The free-text rule (normative, now recorded in `note_shape.py`):** a note with **no date prefix**
is Paul's own, typed into the RTM app, and is never a violation. The gate is safe on that by
construction; the rule is written down because it binds the gtd-side notes-audit, which scans
existing notes — *no date prefix → informational, never a finding; date-prefixed but
off-vocabulary TYPE → agent-written, and that is the finding.*

**Vocabulary gating is explicitly not here.** The gate stays mechanical-shape-only; promoting the
full 27-type catalogue server-side is its own designed change, sequenced after this one.

### 4. Versioning — minor, with the counter-argument recorded

§ 10 reserves **major** for "breaking envelope/signature changes". There is none: the four changed
fingerprints (`add_note`, `edit_note`, `add_task`, `move_task`) are **description-only**, from
documenting the now-live gates, and no caller's code needs to change. The designed change specifies
minor independently.

**The counter-argument, stated plainly:** a consumer that today writes a free-form note title via
`add_note`, or targets a smart list, gets a hard failure after upgrading with no change on its
side — which under a strict reading of SemVer is breaking. It is shipped as minor because the
change is *configuration* rather than contract (the gates and their error codes shipped in v2.2.0;
only their defaults moved), and because the revert is one env var per gate, asserted by test:
`RTM_STRICT_NOTES=off`, `RTM_STRICT_LIST_TARGETS=0`.

### Membrane / activation

Vault-free, **no new tag**, **no new `ErrorCode`**, no schema or signature change. To go live:
restart the server on v5.1.0. Rollback is one env var per gate — no one-way door.

## v5.0.0 — present-but-empty payloads are rejected, and the partial-write branch is observed

**BREAKING** (§ 1). Implements `2026-07-26-rtm-mcp-empty-payload-rejection-brief.md`. The last two
items before the sibling rollout.

### 1. A payload that arrives present but EMPTY is rejected — BREAKING

v4.0.0 tightened **absence**; `[]` / `{}` / `""` stayed legal and returned a graceful no-op, and
v4.1.0's `guidance` narrowing then removed the only signal that made that no-op visible. Rather than
restore the signal, the silent case is removed.

**The rule: reject when a parameter *whose value is the work* is present but empty.** All eight
reject with `missing_parameter`, name the parameter, and write nothing:

`gtd_engage_commit.items` · `gtd_item_transition_batch.items` · `gtd_inbox_drain.dispositions` ·
`gtd_waiting_for_sweep.verdicts` · `gtd_cluster_consolidate.moves` · `gtd_project_create.frame` ·
`gtd_note_add.body` · `gtd_inbox_item_close.derived_refs`

Implemented once, in `gtd_writes.check_payload`, generalising the rule `validate_transition` already
applied to `add_tags`/`remove_tags` and **reusing its `MISSING_PARAMETER` reason** — a new registry
member would have churned all 100 fingerprints for a failure the registry already spells. A
whitespace-only string counts as empty (`body="   "` is contentless by the same argument).

**Explicitly NOT affected, and asserted so** — this is the half that is easy to break by accident:

| Untouched | Why |
|---|---|
| `rtm_tool_help()` with no argument | A designed **view selector** (v3.3.0): no argument returns the whole-server index. Breaking it would regress a shipped feature. |
| No-argument tools (`get_tags`, `check_auth`, `test_connection`) | Nothing can be empty. |
| Genuine optional facets (`due`, `energy`, `comms`, `extra_tags`, `context_note`) | Absence *and* emptiness are legitimate — covered by the receipt, never by rejection. |
| Booleans (`confirm_destructive`, `dry_run`, `timestamp`) | A mode switch, not data — the same reasoning as `receipt.is_facet`. |

Two behaviours improved in passing: `gtd_item_transition_batch` already refused an empty `items` but
only **after** a read — it now returns before it (a gate that still spends an API call is not a
gate); and `gtd_project_create` rejected an empty `frame` downstream via focus resolution, reporting
the missing `frame.focus`, which reads as "one field is wrong" when the whole payload is absent.

**No in-repo engine relied on the graceful no-op** — checked; this server has no internal callers of
these tools, and no test asserted the old behaviour.

Fingerprint churn is **2 tools** (`gtd_engage_commit`, `gtd_project_create`) — their advertised
`rejected[].reason` enums gained `missing_parameter`.

### 2. The partial-write `guidance` branch is now observed

The v4.1.0 debrief reported honestly that this branch — the one held up as *justifying* the field —
fired **zero times** across the suite: unit-tested, but no integration scenario exercised a mid-batch
RTM failure. Added one: a `gtd_engage_commit` over two items where the **second write fails**,
asserting `applied[]` non-empty, `errors[]` non-empty, `guidance` present naming **PARTIAL** and
`batch_undo`, and that the transaction ids needed to reverse it are actually in the response —
otherwise the advice is unfollowable.

**Re-measured: `guidance` emissions 6 → 7 of 174 calls (4.0%), and the new one is the partial-write
branch.** The advisory is unaffected at 16.7%.

## v4.1.0 — the two refinements the trial settled

Implements `2026-07-26-rtm-mcp-receipt-refinements-brief.md`. Both land **before** the three sibling
servers implement the receipt, so they inherit the corrected form rather than the trial form.

### 1. The registry's stated purpose, corrected (documentation only)

`error_codes.py` described itself as "every machine-branchable **failure**" while also holding three
outcome members. **The label was wrong, not the contents.** It now reads "every machine-branchable
**outcome** — failures and non-failure results alike", and records the reason a second registry is
unnecessary:

> the discriminator is the **field**, not the registry — a code in `not_applied[].reason` is an
> outcome; a code in `error.code` is a failure.

Nothing renamed, nothing moved, no wire value changed, **zero fingerprint churn** (verified). The
test asserting the outcome members never appear as an `error.code` now enforces that discriminator
rather than papering over a mislabel.

### 2. `guidance` narrowed to the branches that say something new

Measured in the v4.0.0 trial: **56 of 62 emissions** were the full-rejection branch — a restatement
of the `rejected[]` array in the same payload. Duplication trains a caller to skip the field, which
costs the branches that are worth reading.

`guidance` is now emitted **only** on:
- **partial write** — some ops durable, some failed; names it PARTIAL and points at `batch_undo`
  with the transaction ids, because a blind retry re-applies what already succeeded;
- **`not_applied[]` non-empty** — the write was clean but narrower than asked for.

Dropped: the full-rejection branch (`rejected[]` already lists every reason) and, as a consequence
of the same principle, the bare zero-applied case (`applied: []` is the statement). Severity ordering
between the survivors is unchanged.

**Re-measured: emissions fell from 62 to 6 across the same 162 governed-write calls (38% → 3.7%),
and every survivor is a genuine `not_applied` case.** Reported honestly: the partial-write branch —
the one held up as justifying the field — **fired zero times** in the suite. It is covered by unit
tests but no integration scenario exercises a mid-batch RTM failure.

**Consequence, flagged:** an explicitly-empty payload (`items=[]`, still legal) now carries no
interpretive signal — `applied: []` and `not_applied: []` are the whole story. v4.0.0's guidance
covered that case; this does not.

No schema change (`guidance` was already `str | None`), so no fingerprint churn from this either.

## v4.0.1 — the receipt docstring is now version-independent

**Bug fix, found by CI on Python 3.11/3.12 after v4.0.0 was pushed; the local gate runs 3.14 and
could not see it.**

`_with_receipt` composed each governed write's advertised description from the raw `fn.__doc__` and
appended an unindented receipt block. **Python 3.13+ dedents docstrings at compile time; 3.11 and
3.12 do not** — and appending an unindented block drops `inspect.getdoc`'s common-prefix dedent to
zero, so on those versions every line kept its source indentation. Measured: `gtd_item_set_redaction`
**1,946 bytes on 3.14 vs 2,106 on 3.12**, breaking both the description-budget assertion and the
committed fingerprints. **All 25 governed writes were affected** on 3.11/3.12.

Composing from `inspect.getdoc(fn)` normalises first. Verified by hashing `inputSchema` +
`description` for all 100 tools under 3.12 and 3.14: **zero differences**.

Two guards added, both confirmed to **fail** on the reverted form under 3.12 — a unit test on the
wrapper, and a server-wide check that each governed write's description still reaches column 0 once
the appended block is removed. (The first attempt asserted "no deeply-indented line" and was wrong:
a two-level `Args:` continuation is legitimately 8 spaces after a correct dedent.)

**Note for the siblings:** this bug is invisible on Python 3.13+. Any server appending to a docstring
must normalise first, and must run CI on the oldest supported version to see it.

## v4.0.0 — the teaching receipt, and eight parameters that were never legitimately absent

**BREAKING** (§ 2 below). Implements the approved designed change
`2026-07-26-tool-receipts-and-parameter-tightening.md` §§ 2–3, as a **TRIAL on this server only** —
the three sibling MCP servers are explicitly gated on this release's debrief.

### 1. The teaching receipt (additive)

v3.3.0 shipped tiers 1 and 2 of the Tool Affordance Model and proved tier 3 **unreachable** on the
hosted client: Claude Desktop deletes an undeclared argument before the server sees it. That leaves
one real failure — a misspelt **optional modifier** on a governed write produces a **silent partial
write**: the item lands without the property, and success is reported. You cannot throw on what you
were never told, so this closes it from the other end by making the *outcome* impossible to misread.

Every one of the **25 governed `gtd_*` writes** now returns three additional fields:

| Field | Contract |
|---|---|
| `not_applied[]` | One entry per requested operation that produced **no write** — `{op, id, requested, reason, detail}`. **Always present, empty when everything landed** (zero-not-absent, so a consumer branches unconditionally). |
| `guidance` | One plain next step when the outcome was not a clean full success — rejection / partial batch / narrower-than-asked. `null` otherwise. |
| `advisory` | Set when the call arrived carrying **none** of the tool's optional value-bearing parameters, naming them. Never a rejection, never blocking. |

Attached **centrally** at registration (`tools/gtd.py::_tool` → `receipt.py`), not at 25 call sites —
the same one-place-cannot-drift reasoning as the `RejectUnknownParameters` middleware. A new
governed write gets a receipt by the act of being registered. Verified schema-transparent: input
schemas and descriptions are **byte-identical across all 100 tools** to the unwrapped functions
(measured against a v3.3.0 worktree, with a control proving the baseline really loaded).

Three new `ErrorCode` members form the `not_applied[].reason` vocabulary — the **fourth** scoped view
of the one registry: `no_change`, `no_durable_write`, `not_eligible`. They are **outcomes, not
failures**, and never appear as an `error.code`; the widening of the registry's meaning is deliberate
and recorded in `error_codes.py`.

**Two entries moved out of `applied[]`** in `gtd_engage_commit`, which is a visible change to that
array's contents (not to any field): a `keep` / `do_now` verdict, and a skipped duplicate STEER note
that literally sat in the *applied* list labelled `"(skipped, duplicate)"`. Both wrote nothing and
inflated the `"Applied N write(s)"` count with non-writes. They are now `not_applied[]` entries, and
the count is honest.

**Where a caller learns this exists** — three surfaces, none restating another: the server
`instructions` carry the imperative (*"Check `not_applied[]` before reporting success"*, held at
**2,046 bytes**, unchanged, by trimming tool enumerations that `rtm_tool_help()` serves on demand);
each governed write's description carries a ~190-byte block; and `rtm_tool_help("<tool>")` carries the
full contract with no budget pressure. `gtd_surface_resolve` and `gtd_dependency_link` cross the 2 KB
description budget **solely** because of that shared block and are added to the exemption list with
that reason stated.

### 2. Eight parameters tightened to required — BREAKING

Each permitted a call that was never legitimate. A previously-accepted call now errors:

| Tool | Now required | What the old call did |
|---|---|---|
| `gtd_engage_commit` | `items` | empty commit |
| `gtd_inbox_drain` | `dispositions` | no-op |
| `gtd_waiting_for_sweep` | `verdicts` | no-op |
| `gtd_cluster_consolidate` | `moves` | no-op |
| `gtd_item_transition_batch` | `items` | no-op |
| `gtd_project_create` | `frame` | malformed project |
| `gtd_note_add` | `body` | **a note with a title and no content** |
| `gtd_inbox_item_close` | `derived_refs` | closed without naming what it derived |

Justified because every such call already produced an empty or wrong outcome, and the new failure is
loud and immediate. **Not tightened**, deliberately: `gtd_item_create`'s `due` / `energy` / `comms`
and similar genuine facets, where absence is legitimate — those are what § 1 covers.

### 3. Measured during the trial

- **The advisory fired on 82% of governed-write calls** on first implementation — two real bugs, both
  caught by measuring rather than reasoning: it fired on *any* absent optional instead of *all*, and
  the wrapper read `kwargs` directly, so arguments passed positionally were reported absent.
  Corrected: **17.3%**.
- **Tightening and the advisory interact.** Once the eight payloads became required, the only
  optionals left on `gtd_engage_commit` and `gtd_note_add` were control flags, so both fired on
  **100%** of legitimate calls. Excluding booleans (`receipt.is_facet`) took both to 0%. This is a
  correctness rule, not tuning: a stripped boolean gets the call rejected or changes documented
  default behaviour — it can never be the silently-lost value the advisory exists for.

### Activation

Vault-free, no new tag, no strict-tag interaction. **All 100 fingerprints churn** — structural, from
the `ErrorCode` enum being inlined into every `ErrorBody.code` plus the output-schema and description
additions; it is not 100 tools changing behaviour. To go live: restart the server on v4.0.0. § 1 is
additive and § 2 is a revert, so there is no one-way door.

## v3.3.0 — the Tool Affordance Standard: front-loaded selection, help on demand, teaching rejections

Implements the family Tool Affordance Standard (git-ops `mcp-tool-documentation-standard.md`
§§ 4.1a / 9 / 10). Additive: no tool changes behaviour, capability, write safety, or return shape,
and no new tag or `ErrorCode` is introduced. **100 tools** (99 + `rtm_tool_help`).

**The gap it closes.** The six-surface standard was excellent on *what* a tool's documentation
contains and silent on *how much of it the client actually shows the model*. Measured here on
2026-07-26 and reproduced exactly in this repo: **18 of 99 tool descriptions exceeded the ~2 KB the
client keeps** (worst: `gtd_canvas_commit` at 4,893 bytes, losing 58% — its governance contract),
and the server `instructions` block was **30,506 bytes, of which ~93% was discarded** — leaving the
RTM legal disclaimer where the tool-family routing keywords should have been. A Google-style
docstring puts `Returns` / operator tables / caveats *last*, so the discarded tail was precisely
the correct-usage material, on the highest-stakes governed writes.

**Three tiers, keyed to what guarantees the read.**

| Tier | Surface | Carries |
|---|---|---|
| 1 — select | `name` + description front block + `instructions` front | purpose, when-NOT, write-safety posture, domain marker |
| 2 — detail | `rtm_tool_help` | combination rules, worked examples, full Returns, error catalogue, chain edges |
| 3 — teach | the guided rejection | purpose, typed params, nearest-name guess, violated rule, help pointer |

**`instructions`: 30,506 → 2,046 bytes.** The ~400-line per-tool catalogue is gone; the front now
carries what-the-server-is, the two-family split with routing keywords, and a pointer to
`rtm_tool_help()`. The legal disclaimer moved to the end. The catalogue's genuinely non-obvious
facts (default-list resolution, smart lists being read-only, strict-tag mode) live in the owning
tools' descriptions, where a caller of *that tool* actually sees them.

**New tool `rtm_tool_help(tool_name=None)`** — read-only and **offline** (zero RTM calls, like
`gtd_item_shape`). No argument returns the whole-server index: one purpose line per tool, grouped
by family. A name returns that tool's full contract. It is **generated as a projection** of the
live advertised schema, never hand-written — parameters come from `inputSchema`, posture from
`annotations`, `Returns` from the docstring, and the error catalogue from the codes the description
names (which `TestAdvertisedErrorContract` already guarantees is complete). Only four small tables
are authored: combination rules, worked examples, chain edges, and the BFF set.

**Teaching rejections.** The v3.2.0 gate named the valid parameters and nothing else. It now names
them *with* types, required/optional and enums, plus the tool's own purpose (the original defect was
a wrong-*tool* case — capture was simply the wrong tool for tagging), a nearest-name guess for a
probable typo, the combination rules a JSON schema cannot express, and a pointer to the help
payload. Built through one shared generator (`guided_rejection.py`) that converges the two
pre-existing shapes — `strict_tags.guided_error`'s `how_to_proceed` and `engage_commit.validate`'s
closest-legal suggestion — so the paths speak with one voice. It still writes nothing.

**Front-loading.** All 55 `gtd_*` tools already opened as `<Domain> — purpose`; all 44
non-conforming descriptions were exactly the generic primitives, which now carry the `RTM — `
marker. That marker is also the model-readable half of the taxonomy: `_meta` is **not** rendered to
the model on this client, so ordinary description text is the only place a skill can actually
select on. `list_tasks` gained the read-only invariant and the smart-list `status:incomplete`
caveat in its front block.

**Nineteen descriptions remain over budget, deliberately and on a reasoned, asserted exemption
list.** The constraint is local and outranks the brief: CONTRIBUTING § 7 *requires* a multi-case
`Returns` and an `Args:` section in every docstring, and the `_FullDocstringMCP` shim advertises the
whole docstring. For a genuinely complex governed write, "fit 2 KB" and "obey § 7" cannot both
hold. So the load-bearing guarantee is enforced instead: a test asserts that **every** exempt
tool states its read/write posture *inside the front block that survives truncation* — a caller
never learns what a tool does to their account only from a discarded tail.

**Fingerprints: 1 added, 44 moved, 55 unchanged.** The churn is exactly the 44 primitives that
gained the domain marker, plus the new tool — not a blanket re-hash.

**Tests: 1,653 (+38).** `TestSelectionSurfaceBudgets` pins both budgets, the exemption list's
freshness (a stale exemption fails), the posture-in-front guarantee, and the `<Domain> — purpose`
shape. New `tests/test_tool_help.py` holds the projection-agreement contract: every tool resolves
in the index, its purpose is a leading substring of its own description, its contract's parameters
equal the advertised `inputSchema`, and its error catalogue claims only codes the `ast`-derived
reachable set allows. That last guard caught a real error during the build — an authored chain edge
naming `assign_location`, a tool on the *official* RTM connector rather than this server.

To go live: restart the server on v3.3.0. Rollback is a revert.

## v3.2.0 — unknown tool parameters are rejected

> **⚠ CORRECTED 2026-07-26.** This entry's premise — "previously it was accepted silently" — is
> measured **false**. On the pinned stack (fastmcp 3.4.4 / pydantic 2.12.5) a server with **no**
> middleware already rejects an undeclared argument at call-schema binding, before the tool body;
> v3.1.0 was executed over raw JSON-RPC and refuses the exact historical argument shape. **v3.2.0
> replaced a pydantic dump with a teaching rejection; it did not add a gate and closed no
> silent-success hole.** The silence in the motivating incident was the *client's*: the Claude
> Desktop host strips undeclared keys before the wire (a JSON-Schema→zod converter that reads only
> `properties`/`required` and forwards the parsed, strip-mode object). The rejection is therefore
> unreachable through that host — a sweep of 2,517 transcripts found no caller ever receiving it.
> The change is still worth having (a far better message, and a backstop for unmeasured callers),
> but it cannot be credited with preventing the incident that prompted it. See `CLAUDE.md`
> § "Unknown-parameter rejection" and `middleware.py` for the measurements.

A tool call carrying a parameter the tool does not define now returns an error and performs no
write. Previously it was accepted silently: the extra argument was discarded and nothing said so.

**Why this is a minor bump and not a major one.** No advertised contract changed — no signature,
no envelope, no output schema; every tool fingerprint is byte-identical. A caller that conforms to
the advertised schema is unaffected by construction. The only calls that break are ones that were
already violating the schema and being tolerated, which is the defect. That said, the cost is real
and worth naming: **strict rejection couples client and server versions.** A skill written against
a newer server that passes a parameter an older server lacks now hard-fails rather than degrading.
Accepted because both sides here move together and because the failure announces itself
immediately — but if that stops being true, this is the decision to revisit.

**Rejection, not a warning.** The alternative considered was a `warnings[]` entry in the response
with the call proceeding. Rejected: a warning in a response body is exactly the class of signal
that gets ignored, and this defect exists *because* a silent success let a wrong conclusion stand.

**How it was found, which is the argument for fixing it.** `gtd_inbox_capture` was called with
`type_tags: ["improvement_candidate"]` — a parameter it does not have, and deliberately so
(capture stages raw; classifying is clarify-time work). The call returned a success whose
`applied[]` carried `capture:tags` — the server correctly applying its own `#ai_conversation`
pipeline tag — which was read as the tag write having landed. A false defect report against the
server followed. The tool told the truth; the missing feedback let a wrong story survive. The
dangerous version is quieter: a misspelt *optional* on `gtd_item_create` or
`gtd_item_set_properties` writes the item without that property and reports success, with nothing
in `applied[]` or `errors[]` marking the discarded intent.

The asymmetry that made this worth closing: required parameters were already validated strictly —
omitting `text` returns a missing-argument error naming the path. The strictness existed; it just
did not run in this direction.

**Implementation.** One `on_call_tool` middleware (`middleware.py`), registered once in
`server.py`, covering all 99 tools — not per-tool `extra="forbid"`, which would be 99 things to
keep in step as tools are added. The valid-name set is the tool's own advertised
`parameters["properties"]`, so it cannot drift from what clients are told. The error message names
both the unknown parameter(s) and the full accepted set, because naming the accepted parameters is
what turns a rejection into the answer.

Not changed: required-parameter validation, and `gtd_inbox_capture` still has no tag parameter.

## v3.1.0 — the deprecated aliases are removed (breaking)

**26 deprecated surfaces → 0.** The 25 renamed aliases and the `gtd_query` dispatcher shipped at
v3.0.0 for exactly one release and are gone. Calling one now returns a tool-not-found. **The tool
count is unchanged at 55** — nothing was added or removed from the live surface.

**This table is the migration path.** With the aliases gone it is the only one, which raises its
importance rather than lowering it: if you hit a tool-not-found, the replacement is here.

| Removed at v3.1.0 | Call instead |
|---|---|
| `gtd_add_note` | `gtd_note_add` |
| `gtd_annotate_clarification` | `gtd_inbox_item_annotate` |
| `gtd_apply_canvas_commit` | `gtd_canvas_commit` |
| `gtd_apply_engage_commit` | `gtd_engage_commit` |
| `gtd_attach_contribution` | `gtd_contribution_attach` |
| `gtd_attach_output` | `gtd_note_attach_output` |
| `gtd_batch_transition` | `gtd_item_transition_batch` |
| `gtd_capture` | `gtd_inbox_capture` |
| `gtd_chase_sweep` | `gtd_waiting_for_sweep` |
| `gtd_close_inbox_item` | `gtd_inbox_item_close` |
| `gtd_complete_action` | `gtd_item_complete` |
| `gtd_consolidate_apply` | `gtd_cluster_consolidate` |
| `gtd_context` | `gtd_item_context` |
| `gtd_create_item` | `gtd_item_create` |
| `gtd_create_project` | `gtd_project_create` |
| `gtd_edit_note` | `gtd_note_edit` |
| `gtd_health_check` | `gtd_health_report` |
| `gtd_inbox_zero` | `gtd_inbox_drain` |
| `gtd_item_classify` | `gtd_item_shape` |
| `gtd_link_dependency` | `gtd_dependency_link` |
| `gtd_query` | `gtd_item_today / gtd_next_actions / gtd_focus_projects` |
| `gtd_set_properties` | `gtd_item_set_properties` |
| `gtd_set_redaction` | `gtd_item_set_redaction` |
| `gtd_stamp_tokens` | `gtd_item_stamp_tokens` |
| `gtd_topic_clusters` | `gtd_cluster_candidates` |
| `gtd_transition_state` | `gtd_item_transition` |

`gtd_query`'s `perspective` was a **mode** parameter — it changed which other parameters were
valid, the row shape, and the error branches — so it was a tool boundary. Each replacement takes
only the parameters its own view needs.

### The naming check is now blocking

`make naming` runs `--strict` and is part of `make lint`. It ran report-only through v3.0.x
because it *could not* block: the deprecated aliases **were** the non-conformant names, so it
fired on all 26 by construction. With them gone: **52 ok, 3 exempt, 0 findings, 0 unclassifiable.**

### Also removed

- `GTD_QUERY_OUTPUT` (`models.py`) and `VALID_PERSPECTIVES` (`gtd_reads.py`) — dead with the
  dispatcher. The three perspectives are three tools now, so a vocabulary naming them has nothing
  left to validate.
- Stale pointers in **user-facing strings**, found by a new test rather than by reading: two
  runtime error messages and the server's own advertised instructions were still directing callers
  at `gtd_query`. Those would have survived the rename indefinitely — no test had ever asserted on
  them.

### How removal was judged safe

Not by watching a log. By **enumerating the callers**: the marketplace repo (0 live call sites),
the scheduled-task specs (0 — thin launchers name no tools), and the **rendered live artifacts**.
That last one is the reason it was worth doing — the standing board held four old names in both
its code *and* its `mcpTools` allowlist, seven days after the template had moved on. **A rendered
artifact is a frozen copy of its template, so it is a live caller no repo grep can see.**

## v3.0.1 — make the records emit

**Six of nine log statements never reached a handler.** There was no logging configuration
anywhere in the repo: every module called `logging.getLogger(__name__)` and logged, but Python's
root logger defaults to `WARNING` and with no handler the `lastResort` fallback emits only
`WARNING` and above. Every `INFO` and `DEBUG` record was discarded before a handler saw it.

Silent until now:

| Record | Was |
|---|---|
| `strict_tags` — a rejected tag write | `INFO`, discarded |
| `note_shape` — a rejected/observed note title | `INFO`, discarded |
| `list_targets` — a rejected write target | `INFO`, discarded |
| the deprecated-alias record (×2) | `INFO`, discarded |
| `client` raw API response | `DEBUG`, discarded — **correctly**, and left alone |

**All three write-boundary gates logged their rejections into nothing.** Callers still got their
structured errors, so behaviour was intact — but "how often is the note-shape gate firing, and on
what?" was unanswerable.

### `RTM_STRICT_NOTES=warn` was a complete no-op

`warn` mode does not block a malformed note title; its *only* effect is the record. With the
record discarded, the observe-before-enforce mode did nothing observable at all — anyone who set
it to gather evidence before enabling `shape` collected silence and would have concluded the
estate was clean. It now warns, and the record names the outcome
(`ALLOWED (observe-before-enforce)` vs `REJECTED`).

### What changed

- **`server.configure_logging()`**, called from `main()`. Scoped to the `rtm_mcp` logger tree so
  importing this package never hijacks a host application's logging. Level `INFO`, overridable
  with **`RTM_LOG_LEVEL`**. Idempotent.
- **The handler writes to stderr, never stdout** — this is a stdio MCP server and stdout carries
  the JSON-RPC stream. A test asserts no handler is on stdout.
- **The five records are now `WARNING`, not `INFO`.** A refused write and a call to a name that
  disappears next release are both exceptional, and `WARNING` emits through `lastResort` with no
  configuration at all — so losing the configuration again cannot silence them. The configuration
  still matters for formatting (timestamp, level, logger name) and for `DEBUG`.
- **`client.get_account_tags` now warns when it caches an empty allow-list.** Found by a sweep for
  controls whose failure produces no record: a failed `rtm.tags.getList` cached an empty set, so
  the strict-tag gate rejected *every* tag write while telling the caller its tags did not exist —
  true of an empty set, and wholly misleading about the cause.

### Why it matters beyond observability

The alias-removal gate was originally *"the alias-invocation log shows zero hits across a full
scheduled-task cycle"*, and before this release that log could not have recorded a hit if one
occurred — everything logged before v3.0.1 was unmeasured, not clean. **The gate was subsequently
dropped as disproportionate for a single-user tool** and removal was judged by enumerating callers
instead (v3.1.0). The logging fix stands on its own: three write-boundary gates and a mode that
did nothing observable.

## v3.0.0 — the GTD tool rename (breaking)

**25 tools renamed, `gtd_query` split into three, one new area. 55 GTD tools, all conformant to
the naming standard in `CONTRIBUTING.md` § 2.**

**Nothing changed behaviour.** Every renamed tool does exactly what it did — same parameters, same
return shape, same error branches. This release is a name change and nothing else.

### Migration — you probably need to do nothing yet

**Superseded by v3.1.0, which removed them.** At v3.0.0 all 25 old names remained callable as
deprecated aliases, alongside `gtd_query`; each registered the same function under the old name
and advertised a byte-identical schema, so a caller saw no difference. They are gone as of
v3.1.0 — see that entry for the migration table.

Aliases exist for **cross-repo sequencing**, not for external callers: the server and its
consumers live in separate repos behind an async hand-off, so one is always ahead of the other —
and *either* order breaks without them. *(The alias-invocation log was originally intended as the
removal gate. In the event removal was judged by enumerating callers instead — cheaper, and it
found a caller no log would have shown. See v3.1.0.)*

### The renames

Four ⚠ names actively misled about what the tool does; the rest are consistency.

| Old name | New name | Note |
|---|---|---|
| `gtd_add_note` | `gtd_note_add` | |
| `gtd_annotate_clarification` | `gtd_inbox_item_annotate` | |
| `gtd_apply_canvas_commit` | `gtd_canvas_commit` | |
| `gtd_apply_engage_commit` | `gtd_engage_commit` | |
| `gtd_attach_contribution` | `gtd_contribution_attach` | new `contribution` area |
| `gtd_attach_output` | `gtd_note_attach_output` | stays under `note` — see below |
| `gtd_batch_transition` | `gtd_item_transition_batch` | |
| `gtd_capture` | `gtd_inbox_capture` | |
| `gtd_chase_sweep` | `gtd_waiting_for_sweep` | |
| `gtd_close_inbox_item` | `gtd_inbox_item_close` | |
| `gtd_complete_action` | `gtd_item_complete` | ⚠ handled all three item kinds despite saying *action* |
| `gtd_consolidate_apply` | `gtd_cluster_consolidate` | |
| `gtd_context` | `gtd_item_context` | |
| `gtd_create_item` | `gtd_item_create` | |
| `gtd_create_project` | `gtd_project_create` | |
| `gtd_edit_note` | `gtd_note_edit` | |
| `gtd_health_check` | `gtd_health_report` | ⚠ read as an imperative; it is a read |
| `gtd_inbox_zero` | `gtd_inbox_drain` | ⚠ read as a state; it writes |
| `gtd_item_classify` | `gtd_item_shape` | ⚠ imperative verb on a read-only tool |
| `gtd_link_dependency` | `gtd_dependency_link` | |
| `gtd_set_properties` | `gtd_item_set_properties` | |
| `gtd_set_redaction` | `gtd_item_set_redaction` | |
| `gtd_stamp_tokens` | `gtd_item_stamp_tokens` | |
| `gtd_topic_clusters` | `gtd_cluster_candidates` | |
| `gtd_transition_state` | `gtd_item_transition` | |

### `gtd_query` splits into three

`perspective` was a **mode** parameter, not a scope one: `context` was valid only for one
perspective and `focus` only for another, the rows carried different fields per perspective, and
`focus_not_found` applied to a single branch. Three tools wearing a trenchcoat.

| Perspective | Now |
|---|---|
| `todays_field` | `gtd_item_today` — no parameters |
| `next_actions_by_context` | `gtd_next_actions` — keeps `context` as a genuine scope parameter |
| `focus_projects` | `gtd_focus_projects` — keeps `focus` |

Each takes only the parameters its own view needs, so an invalid combination is now
*unrepresentable* rather than merely rejected. `gtd_query` remained as a deprecated dispatcher
delegating to all three, and was removed at v3.1.0.

### Two amendments to the frozen rename map

**`gtd_item_classify` → `gtd_item_shape`.** The standard drifted within four days of being
frozen: Wave 1b shipped an imperative verb on a read-only tool, in a wave whose own brief claimed
conformance. *Shape* is the domain's own word (`shape-patterns.md`), so this is not a coinage.

**`contribution` becomes an area (the twelfth).** `gtd_contribution_attach` and
`gtd_contribution_transition` are two operations on one domain object; splitting them across
`note` and `contribution` would have put siblings in different places — the precise outcome
aggregate grouping exists to prevent. A contribution has a lifecycle (the six-state machine);
the note is its *storage*, not its identity.

**`gtd_note_attach_output` stays under `note`, and the asymmetry is deliberate.** An output has no
lifecycle — it is filed, journalled, and done. There is no state machine to hang an aggregate on.

### New: the D9 naming-conformance check

`scripts/check-tool-naming.py` (`make naming`) flags any tool whose name form disagrees with its
`readOnlyHint` annotation. **Report-only at v3.0.0, blocking at v3.1.0** — it cannot block while
the aliases are exposed, because the aliases *are* the non-conformant names.

A name matching neither lexicon is reported `unclassifiable` and **never silently passes**. First
run against v3.0.0: 52 ok, 3 exempt, 26 deprecated, **0 findings, 0 unclassifiable**. Promoted to
blocking at v3.1.0.
