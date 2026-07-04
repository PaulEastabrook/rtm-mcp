---
report_type: feature-debrief
scope: rtm-mcp — server-side chat-turn attachments (files[]/links[] on gtd_chat_thread turns) — board-chat enrichment stage 2
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-04
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR TBD (feature branch feat/chat-turn-attachments), rtm-mcp v1.18.1 → v1.19.0
relates_to: brief "rtm-mcp stage 2 — server-side chat-turn attachments" (Cowork session 2026-07-04);
            designed change 2026-07-04-board-chat-enrichment § 2.8 (approved 2026-07-04);
            gtd note-shape-catalogue.md § 3 (FILING) / § 4 (CHAT); chat-reply-style.md § 2 (LINK);
            predecessor debriefs gtd-chat-surface / gtd-chat-thread-completed-read;
            CONTRIBUTING § 14 (this debrief is the required handback)
status: DONE (server half) — needs the MCP server restarted on v1.19.0; the board's
        "prefer server attachments" patch is the Cowork-side counterpart task
---

# Debrief — server-derived chat-turn attachments (v1.19.0)

Built and tested: rtm-mcp **v1.19.0**, branch `feat/chat-turn-attachments`. Suite green: **722 tests**
(was 694), `make lint` (ruff check + format + pyright) clean. Read-only extension; no new tag, no
strict-tag interaction, no activation-ordering hazard.

## What shipped

Every turn returned by `gtd_chat_thread` now carries two server-derived attachment collections,
**always present** (`[]` when none):

- **`files: [{path, label, note_id}]`** — the artefacts the worker filed, parsed from the same
  task's **OUTPUT notes' `FILING:` lines** (the authoritative record; both the single-line
  `FILING: <vault-relative path> (+ .meta.md)` form and the labelled continuation, where the
  FILING line ends with a dash and the path sits on the next line). Each filing is
  **time-correlated** to the earliest `CHAT — ai` turn created at-or-after the OUTPUT note
  (window `(previous ai turn, this ai turn]` — the worker files first, then replies). `path` is
  the vault-relative path **verbatim**, `label` the OUTPUT note's title summary, `note_id` the
  OUTPUT note (provenance). Only `ai` turns carry files.
- **`links: [{url, label}]`** — `LINK: <url> — <label>` trailer lines parsed from the turn's own
  text (line-anchored, uppercase keyword; em/en-dash or spaced-hyphen separator; no separator →
  label `""`). The trailer lines **stay in `text`**.

The dedup guarantee the board relies on holds: because `path` is verbatim, it compares equal
(`===`) to a `FILED:` trailer echo in the turn text, so the client can prefer `files[]` and
suppress its own `FILED:` parse when the key is present.

## Design decisions & deviations

- **Where the code went.** All parsing/correlation is pure, in `gtd_chat.py` (the existing chat
  domain module — the brief allowed either that or a new module; the grammars are CHAT-adjacent and
  share the "title is the body's first line" convention, so extension won). New helpers:
  `parse_filings`, `parse_output_note`, `parse_links`, `_attach_filings`, `_not_after`. The tool
  stays thin glue — it passes the same `task.get("notes")` collection it always fetched; OUTPUT
  notes were already in the payload, so the **call surface is unchanged**
  (`["rtm.tasks.getList"]`, no settings read, no write, no timeline — asserted in-suite).
- **Empty-arrays, not omitted keys.** The brief left the choice open; chose always-present `[]`
  (zero-not-absent), matching the `gtd_project_index` counts convention. Documented in CLAUDE.md.
- **OUTPUT-typed notes only.** The FILING scan runs only on notes whose title line (body first
  line) parses as an OUTPUT title. This is load-bearing: the live account contains **historic
  pre-convention notes** — a `FILING`-*typed* note and a malformed `2026-04-06 FILING: …` first
  line (task 1195789360) — that carry `FILING:`-ish lines with non-vault-relative payloads. The
  catalogue (§ 3) pins the grammar to OUTPUT notes; the type gate keeps the historic noise out.
  Verified against the live conformant evidence (task 1206177556's 2026-05-25 OUTPUT note, the
  labelled-continuation form) before writing the parser.
- **Correlation is conservative, exactly per § 2.8.** An OUTPUT note after the last `ai` turn — or
  with no `created` — attaches to nothing; unattached is correct, never guessed. Same-task only;
  the cross-child project-scope walk was **not** built (YAGNI, per the brief).
- **Correlation runs over the full thread before the `since` filter.** An incremental poll must
  not shift attachment windows by hiding earlier `ai` turns; `build_thread` now builds + correlates
  everything, then filters. (Tested.)
- **Malformed paths skipped, never repaired.** Absolute (leading `/`) or backslashed FILING paths
  are dropped silently — flagging them is the gtd notes-audit's job, and a "repaired" path would
  break the verbatim-compare dedup guarantee.
- **`links[]` is parsed on every turn, not just `ai` turns.** The grammar is role-agnostic and
  line-anchored; the board only renders trailers on `ai` turns, so a `me`-turn link is inert extra
  data, not a behaviour change. Files, by contrast, attach only to `ai` turns (the correlation rule
  is defined in `ai`-turn terms).
- **Separator split mirrors the board.** `_TRAILER_SPLIT_RE` is the same `value — label` split as
  the template's `chatParseTrailer` `splitVal` (em/en-dash or hyphen with surrounding whitespace),
  so server- and client-parsed values compare equal.
- **Deviation from the brief's pre-flight:** the stale-clone steps didn't apply — this Dropbox
  checkout (the real repo per the standing memory; the brief's `~/Documents/Code/rtm-mcp` is the
  stale copy) was already up to date with origin/main, and the stray
  `tests/plan_graph_parity_golden 2.json` duplicate does not exist here.

## Membrane / activation

- **Purely additive + backward-compatible.** Old clients ignore the two new keys; the stage-1
  client `FILED:`/`LINK:` parse still works because trailer lines remain in `text`. No new tag is
  read or written; strict-tag mode is untouched; vault-free (the FILING *line* is parsed from RTM
  notes — the server never opens the vault).
- **To go live:** restart the local MCP server on v1.19.0 (supersedes the pending v1.18.1
  restart — one restart covers both), then repeat on the other machines at their convenience.
- **Cowork counterpart:** the board template's "prefer server attachments, suppress duplicate
  FILED parse when `files` is present on the turn" patch — tracked as the counterpart task on the
  Cowork side; the stage-1 client parser stays as the documented fallback for older servers.

## Verification done

- `make lint` (ruff check + `ruff format --check` + pyright) clean; `make test` **722 passed**
  (+26 pure in `test_gtd_chat.py` → 63; +2 tool-level in `test_gtd_tools.py` → 80). Coverage:
  FILING single-line/continuation/companion-optional/absolute-skip/backslash-skip/multiple;
  OUTPUT-title selector (timestamped variant, non-OUTPUT ignored, no-filing → None); LINK
  em/en-dash + spaced-hyphen + no-separator + line-anchor; correlation before/equal/after/two-window/
  never-on-me; empty-array default; since-filter full-thread correlation; tool-level verbatim path +
  retained trailer + call-surface assertions.
- **Not run:** a live smoke against the real account (needs the server restart to expose the new
  turn shape to a host) — validated in-suite instead, with the parser grammar grounded against the
  live conformant OUTPUT note on task 1206177556 (read via the *running* v1.18.x server during
  design, before implementation). The RTM journalling step (OUTPUT/PROGRESS note on the
  Coworking project) was left to the session close-out — see Open items.

## Conventions

§ 3 thin tool / pure module split · § 7 enriched docstring (multi-case Returns) · § 8 FakeMCP +
read-only call-surface assertion · § 9 four-touchpoint lockstep (README, server.py instructions,
CLAUDE.md table + feature section + test inventory) · § 10 MINOR → 1.19.0 (pyproject + `__init__` +
uv.lock) · § 14 this debrief. Tag discipline (§ 6) untouched — no tag writes added.

## Open items / handback

- **Paul:** merge the PR; restart the MCP server on v1.19.0 (one restart also clears the pending
  v1.18.1 note).
- **Cowork side:** apply the board's prefer-server-attachments patch (consumer *action*, but the
  server is fully usable without it — degradation ladder holds either way).
- **gtd side (later increments, do not build speculatively):** cross-child project-scope filing
  walk (§ 2.8 caveat); upstream `rtm_fetch.py` parity items unchanged.
- **Journal:** an OUTPUT/PROGRESS note on the Coworking Productivity project (rtm:1195789348) per
  the brief's step 3, validated with `validate-note.py`.

## Durable lesson / gotcha

The live account's note history **predates the FILING convention**: there are `FILING`-typed notes
and free-form `FILING:` first-lines that are *not* catalogue-conformant. Any parser touching
`FILING:` must gate on the **OUTPUT title type first** (title = body's first line, as ever with RTM
notes) or it will ingest historic noise. And the vault-relative path must flow through byte-verbatim
— the client-side dedup is a string-equality on that path, so even a benign normalisation (trailing
slash, case) silently breaks the "one artefact, one card" guarantee.

---

Source of truth: `CLAUDE.md` § "Conversation surface" (turn-attachments paragraph) + the
`gtd_chat_thread` docstring in `src/rtm_mcp/tools/gtd.py` + the grammar helpers in
`src/rtm_mcp/gtd_chat.py`. Provenance: implemented 2026-07-04 from the Cowork stage-2 brief;
designed change `2026-07-04-board-chat-enrichment.md` § 2.8.
