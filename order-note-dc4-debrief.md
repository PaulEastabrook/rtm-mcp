---
report_type: feature-debrief
scope: rtm-mcp — DC-4 server half: durable reorder via the ORDER note (commit writes order-note/1; thin plan-graph honours the latest valid note; envelope notes carry ids)
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-05
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR TBD (feature branch feat/order-note-dc4, stacked on feat/project-scope-chat-filings / PR #30), rtm-mcp v1.20.0 → v1.21.0
relates_to: brief "rtm-mcp Claude Code brief — DC-4: durable reorder via the ORDER note" (2026-07-05, Option A rework);
            gtd-side landing in claude-plugins (order_note.py, plan_graph_refresh derivation, build_canvas derivation, finalise drain Part B, note-shape-catalogue § 4a);
            predecessor debrief project-scope-chat-filings-debrief.md (v1.20.0);
            CONTRIBUTING § 14 (this debrief is the required handback)
status: DONE (server half) — needs PRs #29/#30 merged first (this stacks on #30), then the MCP
        server restarted on v1.21.0; the live end-to-end (drag → commit → chip → finalise →
        re-seed pinned + clamped) is the Cowork side's acceptance run
---

# Debrief — DC-4 durable reorder via the ORDER note (v1.21.0)

## What shipped

A board drag now survives. `gtd_apply_canvas_commit` persists a non-empty `order` as an **ORDER
note on the project task** (`order-note/1` — strict-JSON body with `count`/`sha256` self-checks,
`source: "board-commit"`, account-wall-clock title) and returns `order_persisted: "order-note"`;
`gtd_project_canvas` derives the thin plan-graph's `manual_order` bias from the **latest valid**
ORDER note in the same one-call read, so the board seed shows the dragged order immediately on
reload, clamped identically to gtd's enriched engine (topology always wins). The
`project-plan-seed/3` envelope's note objects (header **and** rows) now carry the RTM note `id`,
so the gtd-side resolver's note-id tie-break works from this server's envelope. RTM is the single
source of truth for order intent on both membrane sides; the server stays vault-free.

## Design decisions & deviations

- **Version is v1.20.0 → v1.21.0, not the brief's v1.14.0 → v1.15.0.** The brief was drafted
  against a stale snapshot; five minors (chat surface, inflight, redaction, review sweep, chat
  attachments ×2) landed in between. Same SemVer class (additive minor), stacked on PR #30.
- **`src/rtm_mcp/order_note.py` is a byte-compatible port** of gtd's `order_note.py`
  (`make`/`parse`/`resolve`/`from_envelope`; CLI shim dropped, type hints added) — the unit suite
  mirrors gtd's `test_order_note.py` case-for-case so parity is provable, plus a server-specific
  case for the title-line-in-body tolerance (see the gotcha below).
- **No engine work was needed for Change 2.** The server's `plan_graph.py` was already a
  parity-pinned port carrying full `manual_order` support (pin-within-ready-cohort, topological
  clamp, prune, fingerprint exclusion) — it had simply never been fed. The change is one line in
  the canvas tool: `build_graph(..., manual_order=resolve_order_note(envelope)["order"])`. The
  gtd `TestManualOrder` suite is now mirrored in `tests/test_plan_graph.py` to pin that clamping
  parity explicitly.
- **`gtd_project_index` is untouched** — its counts don't depend on order and it exposes no
  ordering, so per the brief's own carve-out there is nothing to derive there.
- **Order-only commits became real commits.** Previously `order` was a v1 no-op, so an order-only
  commit applied nothing (no COMMIT note, no overlay-refresh stamp). Now the ORDER note lands →
  `applied` is non-empty → the COMMIT audit note and the `#ai_overlay_refresh_needed` stamp follow
  as for any commit. Consequence: `canvas_commit.collect_commit_tags` now counts `order` as an
  actionable op so the up-front strict-tag gate covers the stamp on the order-only path (gate
  consistency, not a new tag — see below).
- **Write ordering honoured as specified:** destructive ops → ORDER note → COMMIT note →
  overlay-refresh stamp. A finalise fired off the mark can never read a commit whose ORDER note
  hasn't landed (asserted by an explicit call-order test).
- **`order_persisted` names the mechanism** (`"order-note"`, never `true`) exactly as briefed; it
  stays `false` when the commit carries no order *or the note write itself failed* (the
  batch-resilient `_write` captures the failure in `errors` — the board should not show "order
  saved" for a note that didn't land).
- **The `at` body timestamp is `datetime.now(UTC)`** formatted `%Y-%m-%dT%H:%M:%SZ`; the title
  stamp reuses `gtd_chat.local_stamp` (account tz via the session-cached settings read — the same
  clock convention as CHAT/COMMIT titles). The two are sampled milliseconds apart; only `at`
  participates in resolution, so the skew is harmless.

## Membrane / activation

- **No new tag.** The ORDER note is a note write, not a tag write — the strict-tag gate is
  untouched and there is **no activation-ordering hazard** (unlike the finalise/overlay marks).
- **Additive + backward-compatible both ways.** An older board ignores `order_persisted:
  "order-note"`; the new board on an old server sees `false` and stays silent. The envelope's new
  per-note `id` and the seed's note-derived ordering are additive; absence of any ORDER note means
  no bias (behaviour is byte-identical to v1.20.0).
- **Append-only discipline:** superseded ORDER notes are never edited or pruned (latest-valid-wins
  makes pruning unnecessary); the note write is transaction-recorded so `batch_undo` reverts it
  with the rest of the commit.
- **To go live:** merge PRs #29 → #30 → this one; restart the MCP server on v1.21.0 (this ONE
  restart supersedes the pending v1.20.0 restart). Then the Cowork side re-bakes the artifact and
  runs the live end-to-end + the cross-membrane determinism eval (thin seed order vs gtd
  `plan_graph_read` order on the same project state).

## Verification done

- `make test`: **769 passed** (736 → 769; +19 `test_order_note.py`, +6 manual-order plan-graph
  parity cases, +1 envelope note-id, +7 commit/canvas integration). `make lint`: ruff check +
  format + pyright all clean.
- Parity is pinned by **mirroring the gtd suites case-for-case** (`test_order_note.py`,
  `TestManualOrder`), not by executing gtd's scripts in this repo's CI.
- **Not run:** the live drag → commit → finalise → re-seed loop (needs the server restart + the
  re-baked board — Cowork side owns it), the cross-membrane determinism eval against
  `plan_graph_read.py` (same reason), and any live-RTM write. Validation is in-suite via the
  mocked-client integration tests.

## Conventions

§ 3 tool pattern (governed write via `_write`), § 6 tag discipline (no new tag; gate untouched;
`collect_commit_tags` extended for the stamp), § 8 test patterns (FakeMCP + call-surface
assertions), § 9 documentation lockstep (README tool docs, CLAUDE.md module table + deep-dive +
test inventory), § 10 version (1.21.0 in pyproject + `__init__` + uv.lock), § 13 port lineage
(module docstring cites gtd's `order_note.py`; suites mirrored), § 14 this debrief.

## Open items / handback

- **Cowork/gtd side:** merge + restart as above; re-bake and push the live artifact; run the live
  end-to-end and the DC-4 determinism eval; complete the gtd landing (version bump + spec
  changelog referencing **v1.21.0**, not the brief's v1.15.0).
- **Upstream parity follow-up (pre-existing, now one item longer):** the reference `rtm_fetch.py`
  envelope doesn't emit per-note `id` (nor `files`/`prog`/`redacted`) — localising those additive
  fields upstream remains the standing follow-up.
- **Consumer — no action** beyond the board's existing gate on `order_persisted === "order-note"`
  (already shipped gtd-side per the brief).

## Durable lesson / gotcha

The RTM API has **no note-title field**: a note written as `note_title` + `note_text` comes back
from `rtm.tasks.getList` as a single body whose **first line is the title** (title field empty) —
the same trap as the CHAT v1.14.1 empty-thread bug. `order_note.parse` therefore tolerates exactly
one leading ORDER-title line in the body before its strict-JSON parse, and `from_envelope` feeds
it `summary` (the first line) as the title and the **full body** as the body. Any future note
grammar with a machine-readable body must budget for that leading title line — asserting
"body is pure JSON" against a getList read will always fail.

---
*Source of truth: CLAUDE.md → "Canvas tools" (ORDER-note bullet) + the `order_note.py` module
docstring; canonical grammar gtd-side in `note-shape-catalogue.md` § 4a. Provenance: DC-4 kickoff
brief (2026-06-28) reworked to Option A (2026-07-05); implemented 2026-07-05 in this session.*
