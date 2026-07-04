---
report_type: feature-debrief
scope: focus-level redaction — `redacted` flag on `gtd_project_index` foci[] rows
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-03
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: branch not yet raised to a PR; feature commit pending; version 1.17.0 → 1.17.1
relates_to: the focus-level redaction brief; redaction-debrief.md (the v1.17.0 project/item redaction
            surface this stacks on — same pattern, one level up); the gtd v0.115.x navigator
            "Redacted Area of Focus" collapse (the consumer)
status: needs-restart — code + tests + docs DONE on the branch; the navigator's focus-collapse goes
        live only after the server is rebuilt/reactivated on 1.17.1
---

# Debrief — focus-level redaction (`redacted` on `gtd_project_index` foci[])

The navigator can now detect a redacted **Area of Focus** across reloads and collapse the whole area
to a single "Redacted Area of Focus" row. This is the one missing half: *marking* a focus already
worked (a focus is a task, so `gtd_set_redaction(task_id=<focus_id>, …)` tags it), but the board had no
way to *learn* the redacted set for foci because `gtd_project_index` didn't emit `redacted` on `foci[]`.

## What shipped

One derived field. `build_foci` (`project_index.py`) now emits `redacted: bool` on each `foci[]` row,
from the Area-of-Focus task's own `#redacted` tag — exactly the pattern the v1.17.0 project/item flag
uses, one level up. Nothing else changed: `gtd_set_redaction` and `gtd_project_canvas` are untouched.

## Design decisions & deviations

- **No deviation.** Every acceptance point met as written.
- **No server-side cascade.** The brief called it optional; I left the flag off the `projects[]` rows
  for a focus (a project already carries its *own* `#redacted` state). The board does the
  focus→projects/actions collapse client-side. Keeping the server flag strictly "this task's own tag"
  avoids two sources of truth for a project row's `redacted`.
- **Reused `REDACTED_TAG`** (single-sourced in `project_plan.py`, already imported into
  `project_index.py` for the project/action flags) — no new constant.
- **Version 1.17.0 → 1.17.1** (patch, one additive derived field). Note this **stacks on the still-
  uncommitted v1.17.0 redaction work** on the same branch — the working tree now carries both changes
  and reads 1.17.1; the eventual single PR/commit ships them together at 1.17.1.

## Membrane / activation

- **Additive + backward-compatible.** Older consumers ignore the new boolean; a redacted focus simply
  doesn't collapse until the board reads the flag.
- **No new tag, no ordering hazard** — `#redacted` is already provisioned; the strict-tag gate is not
  even on the read path.
- **Go-live: rebuild/restart the MCP server on 1.17.1**, then gtd v0.115.x lights up focus-collapse.

## Verification done

- **Ran:** `make test` → **644 passed** (was 642; +2 new — a pure `build_foci` redaction test and a
  `gtd_set_redaction` focus-id round-trip test; one existing gtd_tools index-redaction test was widened
  to also assert the focus row). `make lint` → ruff check + `ruff format --check` + `pyright src` all
  clean. The two field-set assertions that pin the exact `foci[]` shape (pure + tool) were updated to
  include `redacted`.
- **NOT run:** no live RTM smoke and no in-app navigator test — both need the server on 1.17.1 and a
  running board, which this session can't do. Validated in-suite (FakeMCP + mocked client), the repo's
  standard. Acceptance #2 (marking a focus round-trips) is asserted directly via a focus-shaped task id.

## Conventions

- §6 tag discipline: read-only field, no gate interaction. §9 lockstep: README, `server.py`
  instructions, CLAUDE.md (Redaction-surface feature section + module table + test inventory) all
  updated. §10 version: patch bump 1.17.0 → 1.17.1.

## Open items / handback

- **Consumer (gtd v0.115.x navigator): no action to stay safe** — degrades cleanly; reads `foci[*].
  redacted` to enable the collapse. That's the board's side.
- **Server operator (Paul): rebuild/restart on 1.17.1.**
- **Not raised to a PR yet** — the branch carries both the v1.17.0 and this v1.17.1 change; open the PR
  and reference both `redaction-debrief.md` and this file.

## Durable lesson / gotcha

- **Two field-set assertions pin the `foci[]` shape** — the pure `TestFoci.test_field_set`
  (`set(f) == {...}`) and the tool `test_foci_includes_empty_focus_area` (exact-dict `==`). Any future
  additive field on foci rows must update **both**, or they fail. (Same trap the project/action rows
  have — exact-set/exact-dict assertions are the intended tripwire for silent shape drift.)

## Footer

Source of truth: `CLAUDE.md` § "Redaction surface" (the focus paragraph) and the `build_foci` docstring
in `src/rtm_mcp/project_index.py` + the `gtd_project_index` docstring in `src/rtm_mcp/tools/gtd.py`.
Provenance: implemented from the focus-redaction brief in one rtm-mcp host session; verified via
`make test` (644) + `make lint` (clean) on 2026-07-03.
