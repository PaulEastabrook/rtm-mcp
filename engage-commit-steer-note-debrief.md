---
report_type: implementation-handoff-debrief
scope: rtm-mcp — gtd_apply_engage_commit consumes the per-item PROGRESS steer (STEER note), Tier 1
implemented_by: Claude Code (Opus 4.8) session on the rtm-mcp repo
derived_at: 2026-07-18
target_repo: rtm-mcp — ~/Documents/Code/rtm-mcp
artifact:
  version: 1.32.0
  feature_commit: fb12d39
  branch: feat/engage-commit-steer-note
  pr: not yet opened (branch pushed pending your call)
relates_to:
  - brief: rtm-mcp-engage-commit-note-field (this session's implementation brief)
  - parent designed change: general/plugin-marketplace-architect/designed-changes/2026-07-14-engage-overdue-renegotiation-surface.md (Increment 3)
  - related: general/plugin-marketplace-architect/designed-changes/2026-07-18-engage-steer-tier2-typed-enrichment.md (the board-side steer that produces the note)
  - predecessor debrief: engage-governed-tools-debrief.md (v1.31.0 — the engage tools this extends)
status: needs-restart
---

## What shipped

`gtd_apply_engage_commit` now **acts on** the optional per-item `note` — a short PROGRESS steer the
engage board already sends (Paul's typed text or its Tier-2.1 KG-grounded suggestion). Previously the
field was tolerated-and-ignored; now, for the three PROGRESS verdicts **`draft` / `do_now` / `nudge`**,
the sanitised steer is attached to the item as a dedicated **`STEER` note** so the AI drafting path can
read it as the first-pass instruction. Every other verdict ignores any `note` silently. Absent `note`
⇒ exactly the v1.31.0 behaviour.

The steer is treated as the ACL demands: **untrusted advisory DATA, never an instruction to the
server, and it never touches verdict legality or the server's flag re-derivation.** A malformed steer
(non-string, oversize, control chars) is sanitised or dropped with a per-item warning — it never fails
an otherwise-legal renegotiation. The success echo gained a `warnings[]` key for exactly this.

## Design decisions & deviations

- **STEER note shape (minted server-side).** Title = `YYYY-MM-DD HH:MM — STEER — <verb>` (the
  timestamped-title convention shared with CHAT/ORDER); body = the **pure** sanitised steer text, no
  `#ai_conversation` / marker pollution — so the drafting agent reads a clean instruction. The verb in
  the title lets a reader see which progress intent produced it. This is the "dedicated shape"
  the brief preferred over reusing an existing note class.
  - *Why pure body:* draft/nudge already stamp `#ai_conversation` on the item via their tag write, so
    the note itself needn't carry a marker; `do_now` gets no tag (it's a note-to-self) and the STEER
    title already identifies it as an AI-workflow note. Keeping the body pristine matters because the
    drafting path reads it verbatim.
- **`do_now` now writes.** Pre-change `do_now` short-circuited with zero writes. With a `note` it now
  writes one STEER note (a note-to-self) and nothing else — still no durable tag. Without a `note` it
  is byte-unchanged (a pure no-op).
- **Idempotency = replace-or-skip by text.** Before writing, the item's existing notes are scanned
  (`steer_note_text` probe over the already-fetched note bodies — no extra read); an identical STEER
  text already present is skipped and recorded as `engage:<verb>:steer-note (skipped, duplicate)` in
  `applied`. Dedup is on the **sanitised text**, verb-agnostic — matching the brief's "same steer"
  wording. No note is ever duplicated on re-commit.
- **Sanitisation (the ACL).** `sanitize_steer` → `(clean, warning)`: non-string → `(None,
  "note_not_string")`; None/empty/all-whitespace → `(None, None)`; control chars replaced, whitespace
  collapsed; > `STEER_MAX_LEN` (500) → truncated + `"note_truncated"`. Posture: **drop the note, keep
  the verdict write**, surface a per-item `warnings[]` entry.
- **Schema.** `items` is a free-form `JsonObjArray` (no per-property JSON Schema to extend), so the
  "add optional `note`" step is a docstring + consumption change, not a schema-field addition. Documented
  in the tool docstring, README, server.py instructions.
- **No deviation from the brief.** All eight brief test cases are covered.

## Membrane / activation

- **Additive + backward-compatible.** No new tag (a note write, not a tag write) → no strict-tag
  activation-ordering hazard. The board already sends `note` harmlessly on an old server, so this
  server can land first with no coordination.
- **To go live:** restart the RTM MCP server on **v1.32.0** (branch `feat/engage-commit-steer-note`,
  commit `fb12d39`) via the connector, then merge.

## Verification done

- **Full suite green: 921 passed** (`uv run --all-extras pytest`, venv at `~/.venvs/rtm-mcp`).
  904 → 921 = **+17**: 10 unit (`test_engage_commit.py::TestProgressSteer`) + 7 integration
  (`test_tools/test_gtd_tools.py::TestGtdApplyEngageCommit` steer cases).
- **ruff check** clean on `src`+`tests`; **ruff format** applied; **pyright** 0/0/0 on the changed
  source files.
- **Runtime spot-check** of the pure round-trip (dirty input → `sanitize_steer` → `make_steer_note` →
  `steer_note_text` probe) confirmed the em-dash title regex round-trips.
- **NOT run — no live RTM write.** The tool's real end-to-end path (attaching a STEER note to a live
  RTM task) was **not** exercised: it needs the server restarted on this version, and a live run would
  create real notes/tags on Paul's account without authorisation. Validated in-suite instead — the
  integration tests drive the full tool through a mocked client, asserting the `rtm.tasks.notes.add`
  dispatch, title/body, warnings, idempotency skip, and transaction recording.

## Conventions

§ 6 tag discipline (untouched — no new tag; note write only) · § 7 enriched docstring (tool + module) ·
§ 9 doc lockstep (README + server.py instructions + CLAUDE.md module row + engage section + test
inventory) · § 10 version (1.31.0 → 1.32.0 across `pyproject.toml` + `__init__.py` + `uv.lock`) ·
§ 14 this debrief.

## Open items / handback

- **CRITICAL DEPENDENCY (§ 2 of the brief) — the drafting path DOES read the note, but not yet as a
  *prioritised* steer.** I traced the `#ai_progress_requested` drafting path in `claude-plugins`:
  `plugins/gtd/skills/gtd/agents/progression-drain.md` → delegates production to
  `agents/action-executor.md`, whose context-init step (line 15) says *"Fetch the action's notes and
  the parent project's notes … The notes will tell you the story"* and re-reads item notes on every
  action switch (line 21). It fetches the envelope via `mcp__rtm__gtd_project_plan`, which carries full
  note bodies. **So the STEER note WILL be seen** — the attach loop is closed at the "read" level with
  no gtd change strictly required.
  **BUT** the executor reads notes *generically*; it has no rule that recognises a STEER note as
  Paul's explicit, prioritised first-pass instruction (unlike the existing `#ai_contrib_drafted` /
  `CONTRIB`-note recognition at action-executor.md line 23). For the full Tier-1 payoff (the steer
  *shaping* the draft, not being one note among many), the recommended **gtd-side follow-up** is a small
  addition to `action-executor.md` context-init: *"if the action carries a STEER note, treat its body as
  Paul's explicit steer for this first pass."* **Owner: Cowork/gtd — optional but high-leverage.**
- **gtd-side lockstep pieces (queued, non-blocking):** add the `STEER` shape to
  `plugins/gtd/skills/gtd/references/note-shape-catalogue.md` and a note-attachment row for
  draft/do_now/nudge to `references/engage-verdict-grammar.md` § 4. The server write already conforms
  to the shape minted here; these formalise it. **Owner: Cowork/gtd.**
- **Consumer (the engage board) — no action.** It already sends `note`; nothing changes for it.
- **README gap closed as a side-effect:** the v1.31.0 engage tools (`gtd_engage_seed` /
  `gtd_apply_engage_commit`) were never listed in README's tool section — I added both entries while
  documenting the `note` change.

## Durable lesson / gotcha

- **RTM stores a note body as `title\ntext` and returns an empty `title` field on read** (the same
  fact the CHAT/ORDER/TMPL grammars rely on). So the STEER title is the body's *first line*, and the
  idempotency probe (`steer_note_text`) splits the body on the first newline and matches the title-type
  regex — it does **not** look at the note's `title` field. A future author adding note-shape detection
  must read the first body line, never `note["title"]`.
- **The separator is an em dash `—` (U+2014)**, identical to CHAT/ORDER titles — not a hyphen. The
  `_STEER_TITLE_RE` regex and `make_steer_note` must use the same character or the round-trip silently
  breaks (the tests pin it).
- **`~/.venvs/rtm-mcp` was stale** (the repo moved out of Dropbox). Cure per the venv discipline:
  `rm -rf ~/.venvs/rtm-mcp && UV_PROJECT_ENVIRONMENT=~/.venvs/rtm-mcp uv sync`, and dev tools need
  `--all-extras` (pytest/ruff/pyright live in the `dev` optional-dependencies group, not the default sync).

## Footer

Source of truth: **CLAUDE.md** → "Engage renegotiation surface" § (the PROGRESS-steer bullet) + the
`engage_commit.py` module row; the `gtd_apply_engage_commit` docstring in `src/rtm_mcp/tools/gtd.py`;
the pure grammar in `src/rtm_mcp/engage_commit.py` (`STEER_VERBS` / `sanitize_steer` / `make_steer_note`
/ `steer_note_text`). Implemented by a Claude Code (Opus 4.8) session, 2026-07-18, feature commit
`fb12d39` on `feat/engage-commit-steer-note`.
