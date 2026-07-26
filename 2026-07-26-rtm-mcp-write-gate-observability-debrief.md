---
report_type: handback-debrief
scope: write-boundary gate observability — a log sink that survives, and both dormant gates switched on
implemented_by: Claude Code (rtm-mcp session, 2026-07-26)
derived_at: 2026-07-26
target_repo: rtm-mcp
artifact: branch `feat/write-gate-observability`, v5.1.0
relates_to: >-
  brief "Hand-off brief — write-boundary gate observability" (2026-07-26);
  designed change general/plugin-marketplace-architect/designed-changes/2026-07-26-write-boundary-gate-observability.md;
  predecessors 2026-07-19-rtm-mcp-write-boundary-gates-debrief.md, 2026-07-25-rtm-mcp-wave3a-logging-debrief.md
status: needs-restart
---

# Handback debrief — write-gate observability (v5.1.0)

## What shipped

Three stages, in the order the brief set, because each is the prerequisite for the next.

**Stage 1 — a log sink that survives.** A bounded `RotatingFileHandler` (1 MiB × 3 backups) at
`~/.config/rtm-mcp/logs/rtm-mcp.log`, attached **alongside** the existing stderr handler.
Location overridable with the new `RTM_LOG_DIR`; `RTM_LOG_LEVEL` still governs both channels,
because the level lives on the tree and both handlers sit at `NOTSET`. An unopenable sink warns
and continues.

**Stage 2 — `RTM_STRICT_LIST_TARGETS` on by default.** `add_task` / `move_task` now refuse a
caller-named `smart` or `locked` destination. `add_task`'s default-list fallback stays ungated.

**Stage 3 — `RTM_STRICT_NOTES` defaults to `shape`.** A note title written through the generic
`add_note` (or a title-changing `edit_note`) must parse as `YYYY-MM-DD [HH:MM] — TYPE — summary`.
Shape only — an off-vocabulary TYPE still passes.

All three gates are now enabled. Nothing else changed behaviour: no new tag, no new `ErrorCode`,
no schema, signature or return-shape change.

## Design decisions & deviations

**No deviations from the brief.** Everything below is either a decision the brief left open or a
finding worth carrying forward.

**The test is the deliverable, not the handler.** The brief said the `/dev/null` test is what
proves the change, and that is right in a sharper way than it may read: an in-process assertion
that "the record was emitted" **passes today, against a server with no sink at all** — the exact
vacuity CONTRIBUTING § 7a already warns about. So the load-bearing test runs a real gate in a
**child process with fd 2 redirected to `/dev/null`** and asserts the file received it. Beside it
is a **counterfactual** the brief did not ask for: the same probe with the sink unopenable,
asserting the gate still fires, still rejects, and **leaves no trace anywhere** — the pre-v5.1.0
server, reproduced mechanically rather than described in prose.

**Confirmed the test fails without the sink** (brief § 9). Stubbing `_build_file_handler` to
return `None` — the pre-change server — fails 4 tests including the load-bearing one; the
counterfactual correctly still passes. Reverted immediately; this was a manual check, not a
committed fixture.

**`RTM_LOG_DIR` is new, and it is not only for tests.** Without it the suite writes into the
operator's live sink — mixing test noise into the one channel a headless run depends on. An
autouse fixture in `tests/conftest.py` points the whole suite at a tmp dir. (Test probes did reach
the real `~/.config/rtm-mcp/logs/rtm-mcp.log` during development; that file has been deleted. The
directory remains — it is the production sink.)

**A blank `RTM_LOG_DIR` falls back rather than writing to the working directory.** `Path("")` is
`.`, so an empty env var would silently put the sink wherever the server happened to start.
Asserted.

**Recovery guidance had to flip with the defaults, and this is the easiest thing to miss.** Both
guided errors told the caller to *unset* the env var to disable the gate — accurate while the
default was off, and after the flip it is advice to do the exact thing that leaves the gate **on**.
Now `RTM_STRICT_NOTES=off` / `RTM_STRICT_LIST_TARGETS=0`, each asserted by a test that rejects the
word "unset". Added to CONTRIBUTING § 6 as a standing rule for the next person who flips a gate.

**Four advertised docstrings changed, deliberately.** `add_note` and `edit_note` said nothing
about the grammar; `add_task` and `move_task` said the list-target codes were "raised only when the
gate is enabled", which now reads as *this is inert*. A caller learns a tool's contract from its
description, so leaving them would have made the tier-1 surface actively misleading. Measured
before → after, in bytes: `add_note` 968 → 1,407; `edit_note` 1,032 → 1,332; `move_task` 835 →
**832** (the replacement sentence is terser than the one it replaced); `add_task` 2,704 → 2,750,
already on the reasoned `OVER_BUDGET_EXEMPTIONS` list for its Smart Add table. The three
non-exempt tools remain well inside the 2 KB tier-1 budget.

**Version — minor (5.1.0), with the counter-argument recorded.** § 10 reserves **major** for
"breaking envelope/signature changes"; there is none, and the four fingerprint changes are
description-only. The designed change specifies minor independently. **The counter-argument,
stated plainly:** a consumer that today writes a free-form note title through `add_note`, or
targets a smart list, gets a hard failure after upgrading with no change on its side — under a
strict SemVer reading that is breaking, and v5.0.0 took major for a comparable "previously-legal
call now errors" change. It ships as minor because that change altered which *calls* are valid,
unconditionally and irreversibly, whereas this changes a *configuration default* that reverts with
one env var — and because the gates and their error codes shipped in v2.2.0, so only the defaults
moved. If you disagree, the fix is a version bump and a CHANGELOG heading; nothing in the code
depends on it.

## The note-shape blast radius, measured (brief § 9)

**The gate is wired into `add_note` and `edit_note` only.** All **37** `gtd_*` note writes call
`rtm.tasks.notes.add` / `.edit` directly and never reach it — verified, not assumed (`gtd.py`
imports `validate_add_note` / `validate_edit_note` from `gtd_writes`, which are gtd's own grammar
validators, not the gated tool bodies).

An AST sweep of all 36 `note_title=` write sites in `src/` classifies them as: 5 built by
`gtd_writes.format_note_title` (conformant by construction), 26 computed, and 5 literal or
f-string. Of those, **four are bare marker titles that this grammar would reject** —

| Title | Site | Status |
|---|---|---|
| `DEPENDS-ON` | `gtd.py:1702` (`gtd_project_create`) | correct as-is |
| `INCEPTION` | `gtd.py:1769` | correct as-is |
| `TMPL-STAMP` | `gtd.py:1973` | correct as-is |
| `REDACTION` | `gtd.py:2422` | correct as-is |

**These must not be "fixed".** They are load-bearing: `project_plan._extract_deps_and_files`
round-trips on the `DEPENDS-ON` marker. The trap for a future author is to read "the note-shape
gate is on now" and wire it into the gtd write paths for consistency — that would break the plan
graph. The boundary is recorded in `note_shape.py`'s module docstring, in CONTRIBUTING § 6, and in
CLAUDE.md.

**Live data is untouched.** The gate judges new writes and title-changing edits only; no existing
note is re-written or re-validated. The three legacy `ACTIVITY` spellings the designed change
remediated in-session (§ 3.2) would have **passed** the shape gate anyway — a space is legal in a
TYPE token — so that remediation was for the *vocabulary* promotion still to come, not for this
change. `ACTIVITY_REPORT` (underscore) is the one spelling that fails, and it was verified absent
from live data before the flip.

**Which agent paths are affected:** exactly those that write notes through the generic `add_note`.
In-repo there are none. Any gtd-side caller that hand-writes a note via `add_note` with a
non-grammar title will now be rejected — see Open items.

## Membrane / activation

Vault-free, pure RTM. **No new tag, no new `ErrorCode`**, no strict-tag interaction, so there is
**no activation-ordering hazard**.

**To go live: restart the MCP server on v5.1.0.** Both gates take effect on restart with no env
changes.

**Rollback is one env var per gate**, each asserted by test: `RTM_STRICT_NOTES=off`,
`RTM_STRICT_LIST_TARGETS=0`. No one-way door.

Fingerprint churn is **4 tools** — `add_note`, `edit_note`, `add_task`, `move_task` —
description-only. (Contrast v4.0.0, where a new `ErrorCode` churned all 100 structurally.)

## Verification done

| Gate | Result |
|---|---|
| `make test` (Python 3.14) | **1741 passed** (was 1710; +31) |
| `make test` on 3.11 and 3.12 | 1741 passed on each |
| `make lint` | ruff check + `ruff format --check` + pyright `0 errors` — all clean |
| `make naming --strict` | no findings, 52 ok / 3 exempt |
| fingerprints | regenerated at `source_version 5.1.0`; `--check` reports current |
| the `/dev/null` test | passes; **verified to FAIL when the sink is stubbed out** |
| stdio wire-verify | see below |

**Wire-verify — raw JSON-RPC over the real server's stdin/stdout**, child stderr at `/dev/null`,
`RTM_LOG_DIR` pointed at a scratch path:

1. `initialize` succeeded.
2. `add_note` with title `"just a heading"` → `note_shape_rejected` **over the wire**, nothing set
   in the environment.
3. `add_task` targeting the live smart list `"AI Output Approved"` → `smart_list_target`.
4. **Both records were in the sink file**, with stderr discarded.
5. Every stdout line parsed as a JSON-RPC frame — the probe aborts on any non-JSON line, so this
   also re-confirms no handler leaked onto the protocol stream.

**What was NOT run, explicitly:**

- **No live RTM write.** Both wire-verify writes were refused by their gate; the note-shape gate
  returns before `resolve_task_ids`, so it made **zero** RTM calls. The only live API traffic was
  one `get_lists` read (to find a real smart list) plus the `add_task` list resolution. Nothing was
  created, modified or deleted in the account.
- **No observation of a real headless run.** The payoff — a scheduled worker's gate rejection
  appearing in the sink at 06:45 — cannot be verified until the server is restarted and a
  scheduled task runs. The wire-verify reproduces the *condition* (fd 2 at `/dev/null`) but not the
  *occasion*.
- **No measurement of how often the gates fire in practice.** That is Stage 4, which rides the
  teaching-receipt trial and is out of scope here.
- **No gtd-side change.** The free-text rule is recorded server-side; adopting it in the
  notes-audit is a marketplace-repo change (see Open items).

## Conventions

§ 6 (write gates — the mechanical/vocabulary membrane, the reversibility rule, and two new
standing rules added by this change); § 7a (logging — the sink, and testing emission under the
condition that motivated it); § 9 (lockstep: README, `server.py` instructions unchanged as no tool
was added or renamed, CLAUDE.md architecture + module table + feature section, CLAUDE.md test
inventory, fingerprints regenerated); § 10 (SemVer — minor, reasoning above); § 11 (quality gate);
§ 14 (this debrief).

## Open items / handback

1. **Restart the MCP server on v5.1.0** — the only step needed to activate. *(Paul)*
2. **gtd — adopt the free-text rule in the notes-audit.** The discriminator is normative and now
   recorded in `note_shape.py`: *no date prefix → informational, never a finding; date-prefixed but
   off-vocabulary TYPE → agent-written, that is the finding.* Without it the audit reports Paul's
   own RTM-app notes as drift. *(marketplace repo)*
3. **gtd — any caller hand-writing a note through the generic `add_note` must use the grammar.**
   Nothing in this repo does; a sweep of gtd skills/scheduled tasks for `add_note` calls with
   free-form titles would confirm the estate. Wave 1b already removed the one known bypass (the
   `chat-worker` transport rule, replaced by `clear_signal`). *(marketplace repo)*
4. **The note-vocabulary promotion is now unblocked** — its own designed change, extending the
   server-owned note types from 13 (`JOURNAL_NOTE_TYPES` + `SURFACE_BODY_NOTE_TYPE`) to all 27 in
   `note-shape-catalogue.md` § 2. Note the boundary shift it implies: it would move the
   off-vocabulary judgement server-side for **all** paths including the `add_note` escape hatch.
5. **The `§ 3.2` legacy-title sweep remains outstanding** (~15 of 18 candidate tasks unexamined).
   Not blocking: those titles pass the shape gate. It only matters once item 4 lands.
6. **Sibling MCP servers** — the fd-2 finding applies to all four. The sink pattern here is ~50
   lines in `configure_logging` and ports directly. *(gated on this landing cleanly)*

## Durable lessons / gotchas

**1. A `.pth` file with the macOS `UF_HIDDEN` flag is silently ignored by Python 3.14 — the
editable install vanishes with no error.** This cost real time mid-session. `import rtm_mcp` began
failing with `ModuleNotFoundError` even though `.venv/lib/python3.14/site-packages/_editable_impl_rtm_mcp.pth`
existed, contained the correct absolute path, and that path existed. Cause: Python 3.14's
`site.addpackage` skips any `.pth` whose `st_flags` carry `stat.UF_HIDDEN`, and **all three** `.pth`
files in the venv were flagged `hidden` (visible only via `ls -lO`, not `ls -la`). Cure:

```bash
chflags nohidden .venv/lib/*/site-packages/*.pth
```

This supersedes the existing "stale venv" folklore (`rm -rf .venv && uv sync`) — that works only
because it recreates the files unflagged, and it breaks again as soon as whatever sets the flag
runs. The failure mode is silent and total: pytest cannot collect, `make fingerprints` dies, and
nothing anywhere says why.

**2. `configure_logging()` removes every existing handler before it adds its own**, so a probe
handler attached to the `rtm_mcp` tree beforehand is gone by the time any record fires. Observe it
with `caplog` (root-attached, propagation is on) instead. Cost one failing test to learn.

**3. A gate that is off and a gate that never fires are indistinguishable** — and that is the whole
justification for this change, worth restating because it generalises. Before v5.1.0 an inert gate
returned no error *and* wrote no log. There was no observation anyone could make to tell the two
apart. When you add a control, ask what its *liveness* looks like from outside, not just its
*firing*.

**4. `warn` modes are worthless when the log sink is dead**, and this is a sequencing trap.
`note_shape`'s designed rollout was `off → warn → shape`, but `warn` is log-and-allow: with stderr
at `/dev/null` it neither blocked nor recorded. Anyone who set `warn` to gather evidence before
enabling `shape` would have collected **silence** and concluded the estate was clean. Fix the sink
before trusting an observe-before-enforce stage.

---
*Source of truth: `CLAUDE.md` § "Write-gate observability — a log sink that survives, and both
gates on (since v5.1.0)" and § "Note-shape mode + list-target mode"; `CONTRIBUTING.md` §§ 6 / 7a;
the `server.configure_logging` / `note_shape` / `list_targets` module docstrings. Provenance: the
2026-07-26 hand-off brief and its designed change; live wire-verify against the production RTM
account (reads and rejected writes only).*
