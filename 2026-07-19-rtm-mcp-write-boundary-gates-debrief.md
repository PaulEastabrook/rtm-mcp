---
report_type: handoff-debrief
scope: rtm-mcp-write-boundary-gates
derived_at: 2026-07-19T23:30:00+01:00
target_repo: rtm-mcp
designed_change: general/plugin-marketplace-architect/designed-changes/2026-07-19-validators-to-write-boundary-gates.md
candidate_id: "1217340684"
rtm_project_task_id: "1217576662"
rtm_brief_action_id: "1217576751"
status: debriefed
schema_version: 1.0
---

# Debrief — rtm-mcp write-boundary gates (note-shape + list-target)

Companion to `2026-07-19-rtm-mcp-write-boundary-gates-handoff-brief.md`. Stage 1 (server) is
complete on a branch; stage 2 (marketplace) is listed in § 5 and has **not** been actioned.

**Verification boundary — read this first.** Everything in § 3 was verified by running the
suite, the linters, and the type checker locally. **Nothing was verified against the live RTM
API**, and neither gate has been exercised against real data: both ship **off by default**, so
what is proven is that the gates behave correctly *in tests* and that the flags-off path is
unchanged. The live-behaviour question the brief asked me to investigate (§ 3.4) was answered
from repository evidence, **not** by probing RTM — I judged a probe to be a write to Paul's
production account that I had no authorisation to make. Treat § 3.4 as a well-grounded
inference with a named residual uncertainty, not a measurement.

---

## 1. What landed

| | |
|---|---|
| Branch | `feat/write-boundary-gates` (**not** merged, **not** pushed) |
| Commit | `03d7a45` |
| Version | 2.1.1 → **2.2.0** (minor: new opt-in behaviour, additive code, no break) |
| Tests | 1003 → **1075** (+72), all green |
| Quality gate | ruff check + format clean; pyright 0 errors |

**New modules** (both pure policy, sync, zero API calls — each mirrors `strict_tags.py`):

- `src/rtm_mcp/note_shape.py` — gate A. `check_title` / `effective_title` / `guided_error` /
  `enforce_note_shape`. Modes `off` | `warn` | `shape`.
- `src/rtm_mcp/list_targets.py` — gate B. `check_target` / `guided_error` /
  `enforce_list_target`. Boolean flag.

**Tool surfaces + the codes each now advertises** (all four docstrings updated, per the v2.1.0
self-advertising contract, and enforced by the `TestAdvertisedErrorContract` guard):

| Tool | Codes added to its advertised contract |
|---|---|
| `add_note` | `note_shape_rejected` |
| `edit_note` | `note_shape_rejected` |
| `add_task` | `smart_list_target`, `locked_system_list` |
| `move_task` | `smart_list_target`, `locked_system_list` |

**Registry:** exactly one new member, `note_shape_rejected` (governance family). The
list-target gate **reuses** `smart_list_target` and `locked_system_list`, which already shipped
— see § 2.1.

**Config:** `RTM_STRICT_NOTES` (`off` default) and `RTM_STRICT_LIST_TARGETS` (`false` default).

**Docs:** `CONTRIBUTING.md` § 6 renamed *Tag-write discipline* → **Write gates** (now covers all
three, with the ownership rule and a rules-for-adding-a-gate list); `CLAUDE.md` gains the module
tree entries, two module-table rows, a deep-dive section, and an updated test inventory;
`.env.example` documents all three flags.

---

## 2. Deviations from the brief

Four. Each is a decision I made and would like reviewed, not an oversight.

### 2.1 Only ONE new error code was needed — the other two already existed

The brief asked for three additions: `note_shape_rejected`, `smart_list_target`,
`locked_system_list`. The latter two **were already in the registry** — `smart_list_target` from
`gtd_apply_canvas_commit`'s `Processed`-target validation, `locked_system_list` from
`delete_list`. I reused them rather than adding.

This is the additive-only discipline doing its job: minting a `list_target_rejected` synonym
would have recreated precisely the two-names-for-one-concept drift that v2.0.0 removed.
`tests/test_error_codes.py::TestWriteBoundaryGateCodes` pins the reuse, including a test that no
synonym exists.

**Consequence for the marketplace side:** any recovery contract keyed on "all four codes"
(§ 5) is keyed on **three new-to-the-caller codes plus one genuinely new one**, and two of them
can already be emitted today by tools unrelated to these gates. A consumer must branch on
`code` *and* tolerate the same code arriving from a different tool — which the typed vocabulary
already implies, but it is worth stating explicitly in `tag-write-recovery.md`'s successor.

### 2.2 Warn-mode WAS implemented (the brief made it optional)

`RTM_STRICT_NOTES` is tri-state `off` | `warn` | `shape` rather than a boolean. The brief said to
add warn-mode "only if it costs little" — with a string field it cost about three lines, so I
did. It gives a genuine observe-before-enforce stage: `warn` logs every malformed title at INFO
with the tool and the offending title, and writes anyway.

I did **not** add a warn-mode to the list-target gate. Its judgement is binary and the
population is tiny (a handful of lists), so the enumeration `get_lists` already provides is a
better survey than a log-and-wait period.

**Added safety this made necessary:** a tri-state read via `getattr(..., "off")` fails *open* on
a typo — `RTM_STRICT_NOTES=shpae` would silently leave the gate inert while the operator
believed it was on. That is worse than no gate. So `config.strict_notes` has a `field_validator`
that **rejects an unknown mode at load** (server refuses to start) and normalises case/whitespace.

### 2.3 Legacy body-only edits: resolved, with an accepted hole

The brief flagged this as a known unknown that must resolve. It resolves as follows.

`edit_note` is gated **only when `note_title` is non-empty** — that is the title-changing path.
An edit supplying no `note_title` is a body-only edit and is never judged.

The reasoning is forced by RTM's storage model. RTM has no note-title field: the body is stored
as `title\ntext`. So for `add_note` the gate falls back to judging the body's **first line** when
no explicit title is given — otherwise a caller authoring the grammar inline (which is what the
CHAT / ORDER / TMPL-CHILD writers do) would bypass the gate trivially. But applying that same
fallback to `edit_note` would judge the *legacy* first line of any pre-grammar note, and block
its body from ever being corrected. The invariant wins.

**The accepted hole:** a caller who rewrites a title *inline, through `edit_note`'s body*, is not
gated. The server cannot distinguish "line 1 is a title I am changing" from "line 1 is legacy
content I am preserving" — they are the same bytes. I chose to strand no legacy note rather than
close a bypass that only a deliberately-evasive caller would use. `validate-note.py` still covers
it call-site. Test:
`test_tools/test_note_tools.py::TestNoteShapeGate::test_legacy_body_only_edit_is_never_blocked`.

### 2.4 The list-target gate judges caller-named targets only

`add_task`'s **default-list fallback is deliberately ungated**; only an explicit
`list_name=` / `to_list_name=` is judged.

Reason: RTM's built-in Inbox is a **locked** list. An account whose configured default list is
the Inbox would, with the gate on, have *every bare `add_task("...")` rejected* — a behaviour
change the caller never requested and cannot fix from the call site (the target isn't in the
call). Gating the caller's stated intent, not the server's fallback, keeps the gate a boundary
on what was *asked for*.

I also chose **not** to gate `archived` lists: RTM still accepts items into an archived list, so
refusing one would be policy the server does not own. Both decisions are pinned by tests.

---

## 3. Test results

### 3.1 Suite

**1075 passed, 0 failed** (from 1003; +72). ruff check and format clean, pyright 0 errors.

| File | Tests | Covers |
|---|---|---|
| `tests/test_note_shape.py` (new) | 33 | grammar accept/reject, real-calendar-date and wall-clock validation, en-dash tolerance, **unknown TYPE passes**, `effective_title` fallbacks, three modes, guided error |
| `tests/test_list_targets.py` (new) | 13 | smart/locked verdicts, precedence, **archived not gated**, on/off flow, guided error |
| `test_tools/test_note_tools.py` | 15 → 22 | accept / reject-without-writing / flag-off / warn-writes / title-in-body gated / edit gates a title change / **legacy body-only edit never blocked** |
| `test_tools/test_task_tools.py` | 79 → 86 | add + move accept/reject-without-writing for smart and locked, **default-list fallback ungated**, flag-off inert |
| `tests/test_config.py` | 22 → 31 | both flags default off, mode vocabulary + normalisation, **typo fails loudly** |
| `tests/test_error_codes.py` | 25 → 28 | new code present, reuse pinned, no synonym minted |
| `tests/test_tool_schemas.py` | 23 → 27 | the two new gate helpers registered in `_HELPER_CODES` |

Every rejection test asserts **nothing was written** (`client.call.assert_not_awaited()`, or that
no `rtm.tasks.add` / `rtm.tasks.moveTo` appears in the await list). A gate that still writes is
not a write boundary.

### 3.2 Fingerprints — all 56 churned, and the reason matters

`tool-fingerprints.json` regenerated: **every one of the 56 tools changed**, including tools I
never touched (`test_connection`, `get_contacts`, …).

This is structural, not a 56-tool behaviour change. `models.ErrorBody.code` is typed as the
`ErrorCode` **enum**, and FastMCP 3.x inlines `$defs` rather than referencing them — so the full
registry is embedded in every tool's `outputSchema`. **Any additive `ErrorCode` member rewrites
every fingerprint.** I verified this by stashing the change and confirming the committed file
matched on a clean tree with the same interpreter.

This is worth knowing before the next registry addition, and it means the architect's weekly
tool-detection scan will see 56 `schema-changed` events for what is one new error code. It is
the same class of event as the FastMCP 3.x migration already documented in CLAUDE.md.

### 3.3 An environment trap worth recording

Mid-session the suite began failing with `ModuleNotFoundError: No module named 'rtm_mcp'`, then
silently ran under **pytest 7.4.4** — a system pytest, not the venv's 9.0.2. Cause: plain
`uv sync` **drops the `dev` extra**, because dev deps are declared under
`[project.optional-dependencies]`, not a dependency group. `uv run pytest` then fell through to
a pytest outside the environment.

`make dev` (`uv sync --all-extras`) is the correct command; plain `uv sync` will silently
half-break the test environment. This compounds the already-recorded stale-venv failure mode.
The venv also rebuilt on **Python 3.14.3** — the suite is green there, but that is a change from
whatever it was on before and is worth being aware of.

### 3.4 List-target gate: formalise vs add — inference, not measurement

The brief asked where the gate formalises an existing RTM failure and where it adds a new
rejection. **I did not probe the live API** (a probe means writing to Paul's production RTM). What
the repository establishes:

- **Smart lists — almost certainly formalising.** `add_task` and `move_task` docstrings have
  asserted "Cannot add to / move to Smart Lists (read-only)" since long before this change. More
  tellingly, `gtd_apply_canvas_commit` **already performs this exact check client-side**
  (`tools/gtd.py:700` gates on `(processed.get("list") or {}).get("smart")`, rejecting with
  `smart_list_target`). So gate B is not a novel idea in this server — it generalises a pattern
  the commit engine established for one tool to the two generic primitives.
- **Locked lists — likely genuinely new for `add_task`.** RTM's own Inbox is locked and is the
  documented fallback target for `tasks.add`, which strongly implies RTM *accepts* item writes
  into a locked list (locking constrains list-level operations — delete/rename, which
  `delete_list` already guards with `locked_system_list` — not item writes). So the locked branch
  probably **adds** a rejection rather than formalising one. This is the branch that most needs a
  live check before the flag is turned on anywhere, and it is exactly why § 2.4 exempts the
  default-list fallback.
- **No RTM numeric maps to either condition** in `RTM_CODE_MAP`, and the commit engine chose to
  pre-check rather than rely on RTM's response — weak evidence that RTM's own rejection (where it
  happens) is not cleanly typed. Which is the case for a typed, guided gate regardless.

**Residual uncertainty, stated plainly:** whether RTM rejects a smart-list write, and whether it
accepts a locked-list write, is inferred. Before enabling `RTM_STRICT_LIST_TARGETS` anywhere,
one deliberate manual probe against a scratch list would settle both (see follow-up F1).

---

## 4. Discoveries & follow-ups

| # | Finding | Disposition |
|---|---|---|
| **F1** | Smart/locked live RTM behaviour is inferred, not measured (§ 3.4). One manual probe per condition against a scratch list settles it. | **Not captured** — needs Paul's decision on where to probe. Recommend doing this *before* enabling the flag. |
| **F2** | Any additive `ErrorCode` churns all 56 fingerprints (§ 3.2). | **Captured in CLAUDE.md** (deep-dive section). No action; worth flagging to the architect so the weekly scan's 56 events are read correctly. |
| **F3** | Plain `uv sync` drops the dev extra and lets a system pytest run the suite (§ 3.3). | **Not captured** — candidate for a CONTRIBUTING note or a `make test` that depends on `make dev`. I did not change the Makefile (out of scope). |
| **F4** | `gtd_apply_canvas_commit` still has its own inline smart-list check (`tools/gtd.py:700`) which now duplicates `list_targets.check_target`. | **Deliberately not refactored.** The commit engine's check is unconditional; the gate is flag-gated. Unifying them would make a governed commit path depend on an opt-in flag — a regression. Revisit only if gate B ever becomes default-on. |
| **F5** | The inline-title `edit_note` bypass (§ 2.3) is uncloseable server-side. | **Accepted, documented** in CLAUDE.md and the test docstring. `validate-note.py` retains call-site coverage — a reason for stage 2 to *narrow* that validator's scope rather than retire it. |

None of these were written to Inbox_Stuff — this session had no authorisation to write to RTM. F1
and F3 are the two that need capturing; I'd suggest doing so when the branch is reviewed.

---

## 5. Marketplace-side lockstep (stage 2 — NOT actioned here)

Confirmed still required, to land via `/marketplace commit` after the gates have baked in:

1. **gtd SKILL.md** — slim the note-write and list-write call-site discipline to reflect that the
   server now enforces shape mechanically. Do this **only after** the flags are enabled, not on
   merge of this branch: until then the server is inert and the discipline is all there is.
2. **`tag-write-recovery.md` → a general write-rejection recovery contract** keyed on
   `strict_tag_rejected`, `note_shape_rejected`, `smart_list_target`, `locked_system_list`. Note
   § 2.1: the last two are **pre-existing** codes also emitted by `gtd_apply_canvas_commit` and
   `delete_list`, so the contract must key on code *and* tolerate multiple emitters.
3. **`validate-note.py` — narrow, do not retire.** The server now covers title grammar; the
   validator retains TYPE vocabulary, body-block checks, and the § 2.3 inline-edit path the
   server cannot see.
4. **`validate-list-target.py` — narrow, do not retire.** The server covers smart/locked; the
   validator retains canonical writability (Inbox_Stuff sole capture point, Processed
   gtd-internal, caller-scope).
5. **`validate-tags.py` — untouched.** Tag canonicality is a recorded **non-goal**, not drift.
   Worth stating in the Standard so a later audit does not read the asymmetry as an omission.
6. **Standard § 4.4 worked example** — the three-gate table in `CONTRIBUTING.md` § 6 (server
   enforces shape / plugin owns vocabulary, per gate) is written to be liftable as that example.

---

## 6. State on handback

- Branch `feat/write-boundary-gates` at `03d7a45`, **not pushed, not merged, no PR**.
- Both gates **off**; a server on v2.2.0 behaves exactly as v2.1.1 until a flag is set.
- To go live: review → merge → restart the MCP server on v2.2.0 → **then** enable one gate at a
  time, `RTM_STRICT_NOTES=warn` first.
- Recommended enable order: `RTM_STRICT_NOTES=warn` (observe the log) → `=shape` →
  `RTM_STRICT_LIST_TARGETS=1` **after** F1 is settled.
- Closure needs: this debrief reviewed, F1 + F3 captured, stage-2 edits landed.

*Session-drafted, 2026-07-19. Local verification only — no live RTM call was made, and neither
gate has run against real data.*
