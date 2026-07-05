---
report_type: feature-debrief
scope: rtm-mcp — repeating-templated-project Wave B, token STAMPING (the write side; switches the v1.24.0 resolver from dormant to live)
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-05
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: feature branch feat/repeating-templated-project (stacked on the v1.19–v1.22 DC-4+MoSCoW stack), rtm-mcp v1.24.0 → v1.25.0
relates_to: handback brief "rtm-mcp — Wave B token stamping" (2026-07-05-repeating-templated-project-wave-b-stamping-RTM-MCP-brief.md);
            ratified grammar note-shape-catalogue § 5b (TMPL-CHILD note + token-space references);
            predecessor debriefs repeating-templated-project-seed-debrief.md (v1.23.0) + repeating-templated-project-resolver-debrief.md (v1.24.0, the READ side this write side feeds);
            landed marketplace half — gtd v0.133.0 (resolver) + v0.134.0 (conversational-addition stamping);
            CONTRIBUTING § 14 (this debrief is the required handback)
status: DONE (Wave B token stamping) + LIVE BACK-FILL EXECUTED (60 writes across 10 recurring projects,
        0 errors; idempotency + resolver confirmed on live data). Remaining: merge the unmerged
        DC-4+MoSCoW stack, restart the MCP server on v1.25.0 (supersedes the pending v1.24.0 restart),
        optionally push the branch.
---

# Debrief — repeating-templated-project token stamping (v1.25.0)

## What shipped

The **write** half of the repeating-templated-project feature. v1.24.0 taught the thin plan-graph to
*resolve* token-space references, but nothing wrote tokens, so it was dormant on live data. This ships
the stamping that writes them — the last piece that makes recurring-project dependencies survive
recurrence end-to-end.

A repeating templated project re-keys every occurrence's children with fresh `task_id`/`taskseries_id`,
so a DEPENDS-ON dep authored against a prior occurrence's raw id goes stale. The fix rides RTM's
verbatim note-copy: each child gets a **TMPL-CHILD note** carrying an 8-hex token (`tmpl-child/1`), and
each DEPENDS-ON gains a `Template-child-id:` line. RTM copies those notes onto every new occurrence, so
a token stamped **once** propagates forward — the read side then maps the token to the live id.

Three pieces:
1. **`tmpl_child.py`** (new, pure) — the write grammar: `new_slug` (`secrets.token_hex(4)`),
   `make_tmpl_child_note`, the DEPENDS-ON re-author helpers (`is_active_depends_on` /
   `depends_on_upstream_id` / `has_token_line` / `add_token_line`), and `plan_backfill` — the
   idempotent planner that assigns a fresh unique slug per unstamped open child, keeps existing tokens,
   and authors token-space dep lines when the upstream slug resolves among siblings.
2. **`gtd_stamp_tokens`** (new tool) — the governed back-fill: `project_id` (validate `is_repeating`) or
   omit to sweep all repeating projects; `dry_run` previews. Per unstamped open child a TMPL-CHILD note;
   per active DEPENDS-ON a re-author adding the token line; a `TMPL-STAMP` audit note. Idempotent —
   already-stamped children/notes are skipped, so a re-run is a no-op.
3. **`gtd_apply_canvas_commit` adds** — a child added to a repeating project is stamped a TMPL-CHILD note
   after the reparent. `gtd_create_project` is unchanged (it never creates a recurring project; back-fill
   covers one that later becomes recurring).

## Design decisions & deviations

- **Housed the back-fill as a dedicated governed tool** (`gtd_stamp_tokens`), per the brief's
  recommendation of "a bounded, idempotent governed op the finalise engine can fire." Rejected folding
  it into the finalise/commit path as the *primary* home: the back-fill is a distinct, rerunnable
  migration with its own preview/sweep ergonomics, and only the server can write these notes. The gtd
  finalise engine can still call it per-project.
- **Idempotency is the load-bearing invariant.** A child already carrying a `tmpl-child/1` token is
  never re-slugged — re-slugging would break the identity RTM has already propagated across occurrences.
  Detection reuses the exact shapes the reader matches (`note_child_token`, `is_active_depends_on`), so
  the write side and read side agree by construction.
- **The token line REPLACES the raw id as the dep entry** (already true in `_extract_deps_and_files`,
  v1.24.0) — so I keep the raw `task_id:` line in the note body as the human/fallback reference and only
  *append* `Template-child-id:`. A dep whose upstream isn't a stamped open sibling (e.g. a completed
  upstream) keeps its raw id — the line is authored only when the upstream slug is known.
- **RTM note storage reality drove the edit path.** Verified live: `notes.add`/`.edit` store the body as
  `<note_title>\n<note_text>` and return an EMPTY title field on read (the same fact CHAT/ORDER grammars
  rely on — the v1.14.1 CHAT bug). So to append a line to a DEPENDS-ON note I split the read body on the
  first newline (line 1 = title), and re-write via `notes.edit(note_title=line1, note_text=rest+line)`.
  A probe task confirmed the round-trip before I wrote the path.
- **No new tag → no activation hazard.** The TMPL-CHILD body is strict `tmpl-child/1` JSON, not a tag
  write; the `#ai_conversation` marker rides the `TMPL-STAMP` audit note body (keeping the JSON bodies
  pure). So there is zero strict-tag interaction — unlike the finalise / overlay-refresh / chat marks,
  nothing must be provisioned account-side before activation.
- **Stamp OPEN children only** (per the brief's "open children"). A dep onto a completed upstream keeps
  its raw id; acceptable (a completed upstream isn't a live blocker).
- **Version v1.24.0 → v1.25.0** (additive minor). Still stacked on the unmerged DC-4+MoSCoW stack.

## Membrane / activation

- **Additive + backward-compatible + vault-free.** Until stamped, a recurring project's deps stay in
  raw-id space (the pre-Wave-B behaviour); one-off projects are byte-unchanged (never stamped).
- **To go live:** merge the DC-4+MoSCoW stack, restart the MCP server on v1.25.0 (supersedes the pending
  v1.24.0 restart), then run `gtd_stamp_tokens` (a sweep, or per project) over the existing recurring
  projects. After that the feature is end-to-end.

## Verification done

- `make test`: **816 passed** (791 → 816: +16 `test_tmpl_child.py` pure helpers + `plan_backfill`; +9
  `test_gtd_tools.py` — 7 `gtd_stamp_tokens` (back-fill stamps + dep-line re-author + audit note;
  idempotent no-op; not-repeating skipped; dry_run no writes; bad id; sweep-selects-only-repeating;
  getList-first) + 2 commit-adds (repeating stamps a TMPL-CHILD note; one-off stamps none)).
- `make lint`: ruff check + format + pyright all clean.
- **Live dry-run (read-only)** first validated the plan: the sweep found **10 repeating projects**
  (Bambu cycles ×6, two File-company-accounts occurrences, Weekly GTD review, Wales pipeline) and
  computed dep-lines correctly.
- **Live back-fill EXECUTED** (Paul chose to fire it this session): the sweep wrote **60 ops across the
  10 projects, 0 errors** (per-project: 3/3/3/3/2/2/3/4/12/8 TMPL-CHILD notes + dep-line edits + audit
  notes). Confirmed end-to-end on live data:
  - **Idempotency** — an immediate re-run wrote **0 writes** (already-stamped children/notes skipped).
  - **Token surfaced** — `gtd_project_plan(1124622244)` now shows each child's `template_child_id`
    populated and its deps in **token-space** (`1124622254` → `['c9e46b4a']`, `1124622245` →
    `['e14a0d27']`), not raw ids.
  - **Resolver live** — `gtd_project_canvas(1124622244)` maps those tokens back to the current
    occurrence's ids (`1124622245` deps `['1124622255']`, `1124622254` deps `['1124622245']`), so the
    dependency chain is intact and will survive the next occurrence via RTM's note copy.
- **Undo caveat (honest verification boundary):** the live back-fill was driven by invoking the tool
  function through a **throwaway `RTMClient`** (the connector server isn't yet on v1.25.0). The 60 note
  writes are durable in RTM and additive/inert, but their transaction log lived in that ephemeral client
  — so they are **NOT** reversible via the running server's `batch_undo`. Nothing is destructive; they
  only need manual removal if ever unwanted. When the server is on v1.25.0, real board/finalise-fired
  runs record transactions normally.

## Conventions

§ 9 documentation lockstep (CLAUDE.md: architecture tree + module table for `tmpl_child.py`; the gtd tool
count 9→10; a new "Template-child token stamping" deep-dive; test inventory `test_tmpl_child.py` 16 +
`test_gtd_tools.py` 89→98 + total 791→816), § 10 version (1.25.0 in pyproject + `__init__` + uv.lock),
§ 12 add-a-tool checklist (enriched docstring, `require_timeline`/transaction recording, actionable
errors; no complex params; no strict-tag gate since no tag is written; server.py GTD-tools instructions),
§ 14 this debrief.

## Open items / handback

**Consumer / operator — remaining:** merge the DC-4+MoSCoW stack, restart the MCP server on v1.25.0 (so
the connector exposes `gtd_stamp_tokens` to the board/worker and the running server resolves tokens),
optionally push the branch. The live back-fill over the 10 recurring projects is **already done** this
session (see Verification) — the tokens are on live data and confirmed resolving; the real remaining
end-to-end signal is watching a recurring project's blocked/order stay correct **across its next actual
occurrence**. Any future run is idempotent (a no-op if nothing new to stamp); `dry_run=True` previews.

**Still open (out of scope, unchanged):** per-occurrence overlay keying in agent-memory
`plan_graph_store` — so two concurrently-open occurrences of the same recurring project (e.g. the two
File-company-accounts / two Bambu-cycle rows the sweep surfaced) get separate coherent enriched overlays.
This write side gives each existing occurrence internally-consistent tokens; cross-occurrence overlay
identity is the follow-on. Also offered but not done: the order-flow behavioural eval.

## Durable lesson / gotcha

- **RTM notes round-trip as `title\ntext` with an empty title field on read.** Any note EDIT must split
  the read body on the first newline and pass line 1 back as `note_title` — else you either drop the
  title or double it. Verified with a throwaway probe task before trusting it. This is the same storage
  reality behind the CHAT first-line-of-body grammar and the ORDER title-line tolerance.
- **The note-copy mechanism makes back-fill the whole migration.** Because RTM copies a child's notes
  verbatim onto each new occurrence, you stamp ONCE and recurrence carries the token forward — no
  per-occurrence re-stamp. Idempotency then guarantees a re-run (or a finalise-fired run) is a no-op.
- **A live recurring project can have multiple open occurrences at once.** The sweep surfaced two rows
  each for File-company-accounts and the Bambu cycles. Each is its own lineage and is stamped
  independently (internally consistent); that's correct for the resolver, and the cross-occurrence story
  is the deferred overlay-keying item.

---
*Source of truth: CLAUDE.md → "Template-child token stamping" section + the module table row for
`tmpl_child.py` + the `gtd_stamp_tokens` docstring. Canonical grammar gtd-side in
`references/note-shape-catalogue.md` § 5 + § 5b. Provenance: Wave B stamping brief
2026-07-05-repeating-templated-project-wave-b-stamping-RTM-MCP-brief.md; read-side predecessor
repeating-templated-project-resolver-debrief.md (v1.24.0); implemented 2026-07-05 in this session,
server write side only per the brief's scoping.*
