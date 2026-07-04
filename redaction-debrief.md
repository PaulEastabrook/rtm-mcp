---
report_type: feature-debrief
scope: redaction — `redacted` derived flag on the read tools + `gtd_set_redaction` governed write
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-03
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: branch not yet raised to a PR; feature commit pending; version 1.16.1 → 1.17.0
relates_to: the redaction brief (redacted flag + gtd_set_redaction governed write); the gtd v0.113.x
            client-side redaction curtain (the consumer); the earlier additive-field pattern
            (`files` / `prog` on the same read tools); CONTRIBUTING §6 (tag discipline), §9 (lockstep)
status: needs-restart — code + tests + docs DONE on the branch; the board goes live only after the
        server is rebuilt/reactivated on 1.17.0
---

# Debrief — redaction (`redacted` read flag + `gtd_set_redaction`)

The project-plan board can now **learn** which tasks are redacted and **set/clear** redaction, entirely
through governed `gtd_*` tools — closing the gap where the sandboxed artifact (which may not call
`list_tasks` / `add_task_tags` / `remove_task_tags`) had no way to do either. Additive and
backward-compatible; no new tag; no activation-ordering hazard.

## What shipped

Three parts, exactly per the brief:

1. **`gtd_project_index`** — every project row **and** every action row gains a derived
   `redacted: bool` (from the task's own `#redacted` tag). The board redacts at both levels.
2. **`gtd_project_canvas`** — each `seed[*]` item gains `redacted: bool` (always emitted), and
   `frame.redacted` carries the project task's own state so an open-but-redacted project renders its
   locked screen without a second lookup.
3. **`gtd_set_redaction(task_id, redacted)`** — new governed write. Resolves the task's triple by id
   from one `getList` (incomplete **or** completed), then `redacted=true` → `addTags #redacted`
   (strict-tag gated), `redacted=false` → `removeTags #redacted` (never gated). Records the
   transaction (undoable). Returns `{task_id, redacted}`.

## Design decisions & deviations

- **No deviation from the brief.** Every acceptance point is met as written.
- **Constant home = `project_plan.py`.** `REDACTED_TAG = "redacted"` lives in `project_plan.py`
  alongside `_PROJECT_TAG` / `_TEST_TAG` (the low membership-tag layer) and is imported *upward* into
  `canvas_seed`, `project_index`, `tools/gtd`. This matches the existing convention (those tags are
  already imported up into `project_index`) and keeps a single source of truth. The brief left the
  home open ("`canvas_seed` / `project_plan` … same row mapper"); `project_plan` is the cleaner layer.
  **No import cycle:** `canvas_seed` → `project_plan` is one-directional (`project_plan` imports only
  `config`/`parsers`/`urls`, none of which touch `canvas_seed`).
- **Frame flag routed through `build_envelope`.** `header.project` now carries `redacted` (mirroring
  the earlier `header.project.files` addition); `build_seed` reads it into `frame.redacted`. This means
  `gtd_project_plan` also exposes `header.project.redacted` — harmless and additive.
- **Item flag is *always* emitted** (`redacted: false` when absent), unlike `prog` (omitted when off).
  That's deliberate — the brief says "each seed[*] item object gains `redacted: bool`", and a
  guaranteed boolean is simpler for the board than presence-testing.
- **No `#ai_conversation` stamp on `gtd_set_redaction`.** Redaction is a *user viewing-state* change,
  not an AI write — the brief explicitly recommended against it. So this write records a transaction but
  adds no journaling tag.
- **Curtain, not vault (v1).** No server-side name/notes stripping — the plaintext still flows to the
  board; redaction is a viewing-layer concern. Hardening (null the `name`/notes of redacted rows in the
  read tools) is a deliberate out-of-scope follow-up noted in the brief.

## Membrane / activation

- **Additive + backward-compatible.** Absence of the flag on older rows reads as not-redacted. The board
  already degrades cleanly (redaction shows nothing / marking no-ops) until the tools are present.
- **No new tag, no ordering hazard.** `#redacted` is already provisioned in the account, so the
  strict-tag existence gate passes the add path today. This is *unlike* the finalise / overlay-refresh
  marks (which had to be provisioned before activation) — there is nothing to provision here.
- **Go-live step: rebuild/reactivate the MCP server on 1.17.0**, then the board (gtd v0.113.x) can flip
  redaction from inert to live. Nothing else.

## Verification done

- **Ran:** `make test` → **642 passed** (was 630; +12 new); `make lint` → ruff check + `ruff
  format --check` + `pyright src` all clean (0 errors). New tests cover: `map_redacted`; per-item +
  `frame.redacted` in `canvas_seed`; `header.project.redacted` in `project_plan`; project-row +
  action-row `redacted` in `project_index`; and `gtd_set_redaction` add-path (tags + tx recorded),
  remove-path, unknown-id error (one read, no write), and strict-tag rejection (nothing written).
- **NOT run:** no live RTM smoke against a real account, and no in-app board test — both need the server
  rebuilt on 1.17.0 and a running board, which this session can't do. Validated in-suite instead
  (FakeMCP + mocked client), which is the repo's standard for tool behaviour. The strict-gate *pass*
  path for `#redacted` (tag already exists) is asserted only indirectly (the gate is off in the default
  fixture); the *reject* path (tag absent) is asserted directly.

## Conventions

- §6 tag discipline: add path gated via `enforce_strict_tags`; removal never gated. §2 naming:
  `gtd_set_redaction` = `<domain>_<verb>_<noun>` (a domain composition with an explicit verb). §9
  lockstep: README, `server.py` instructions, CLAUDE.md (architecture tree + module table + a new
  "Redaction surface" feature section + test inventory) all updated. §10 version: minor bump
  1.16.1 → 1.17.0 (new tool + additive read fields). §7 docstrings: enriched shape on the new tool.

## Open items / handback

- **Consumer (gtd board): no code change needed to stay safe** — it already degrades cleanly. To light
  redaction up: ensure it declares `mcp__rtm__gtd_set_redaction` in its allowlist and reads the new
  `redacted` fields. That's the board's side, tracked in gtd v0.113.x.
- **Server operator (Paul): rebuild/restart the MCP server on 1.17.0** so the new tool is exposed and
  the read tools emit the flag.
- **Not raised to a PR yet** — the branch has the change; open the PR and reference this debrief.
- **Follow-ups (out of scope, unchanged):** rtm_fetch.py upstream parity for the additive envelope
  fields; optional threat-hardening to strip names/notes of redacted rows server-side.

## Durable lesson / gotcha

- **`redacted` is always present on seed items** (a guaranteed boolean), whereas `prog` is omitted when
  off. Don't "fix" the item mapper to omit `redacted: false` — the board and a test both rely on it
  being present.
- **The frame's redaction comes from `header.project.redacted`, not the seed rows** — it's the
  *project task's own* tag, plumbed through `build_envelope`. A future author touching `build_seed`'s
  frame must keep reading `proj.get("redacted")`, not infer it from any child row.
- **`REDACTED_TAG` is single-sourced in `project_plan.py`** and imported up. Don't re-introduce a second
  `"redacted"` literal in `canvas_seed` / `project_index` — import the constant.

## Footer

Source of truth: `CLAUDE.md` § "Redaction surface (`redacted` read flag + `gtd_set_redaction`)" and the
`gtd_set_redaction` / `gtd_project_canvas` / `gtd_project_index` docstrings in
`src/rtm_mcp/tools/gtd.py`. Provenance: implemented from the redaction brief in one rtm-mcp host
session; verified via `make test` (642) + `make lint` (clean) on 2026-07-03.
