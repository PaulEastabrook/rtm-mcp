---
report_type: feature-debrief
scope: rtm-mcp — gtd_chat_thread reads completed tasks (view prior conversations) + gtd_chat_post completed-task error polish
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-02
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #25 (feature commit 1623cc4), rtm-mcp v1.16.0 → v1.16.1
relates_to: brief "gtd_chat_thread — read completed tasks (view prior conversations)"; sibling
            gtd_chat_post / gtd_chat_inflight (v1.14–1.15); the CHAT note class (gtd journaling-lifecycle.md);
            CONTRIBUTING §14 (this debrief is the required handback)
status: DONE (server half) — needs the MCP server restarted on v1.16.1; gtd-side read-only-compose
        companion change lands separately (see Open items)
---

# Debrief — `gtd_chat_thread` now reads completed tasks (v1.16.1)

Built and tested: rtm-mcp **v1.16.1**, PR #25 (feature commit `1623cc4`). `main` green: **630 tests**,
`make lint` (ruff check + format + pyright) clean. Read-only widen + a write-tool error-message polish.

## What shipped

A completed plan item can carry the exchange that got it done — its CHAT notes persist after
completion, and the board deliberately shows a "has-a-conversation" glyph on completed items. But
`gtd_chat_thread` resolved the task against a `status:incomplete`-only `getList`, so a completed task
came back **"not found"** and the panel fell back to a misleading "No messages yet". (Reproduced live
in the brief on item `1212421129`.) The glyph was truthful; the reader refused the task.

- **`gtd_chat_thread`** now resolves against **`status:incomplete OR status:completed`**, so a
  completed item's prior thread is returned. Everything downstream is unchanged: `build_thread` parses
  the CHAT notes into turns; `requested` is naturally `False` for a completed task (no pending
  worker), so the board renders the history **read-only** without a "thinking…" state. Still one
  signed `rtm.tasks.getList`, read-only, no timeline — only the filter broadened.
- **`gtd_chat_post`** stays `status:incomplete`-only for posting (the `gtd-chat-agent` worker only
  drains `#ai_chat_requested` on incomplete items, so a `me` turn on a completed task would never get
  a reply). Its error is now **honest**: on a resolve miss it does a second `status:completed` lookup
  and, if the task is a completed one, returns *"Task … is completed — its conversation is read-only
  (view it with gtd_chat_thread). Reopen the task to continue the thread."* instead of the generic
  "not found among active tasks".

## Design decisions & deviations

- **Followed the brief's two-lookup design for the post polish**, not a single widened read. The brief
  explicitly lists `gtd_chat_post` under "what NOT to change: stays incomplete-only", so I kept its
  primary resolve at `status:incomplete` (happy path = one `getList`) and only do the second
  `status:completed` read on the miss path (nothing is written on either miss). A single
  `incomplete OR completed` read would have been marginally fewer calls but would have widened the
  post path's read against the brief's stated intent.
- **Consequence for the call surface:** `gtd_chat_post`'s *not-found* path is now **two** reads
  (incomplete then completed); its happy path and every write path are unchanged at one read. The
  `gtd_chat_thread` call surface stays exactly `["rtm.tasks.getList"]` (one read, wider filter).
- **`gtd_chat_inflight` untouched** — it is the "in flight now" cross-project view; completed items are
  correctly out of scope (still `status:incomplete`).

## Membrane / activation

Additive and backward-compatible; the board degrades gracefully until the server is updated (completed
items just keep showing the empty state). No tag writes, no new tag, no strict-tag interaction, no
activation-ordering hazard. **Operational step: restart the MCP server on v1.16.1** so the board picks
it up.

## Verification done

`make lint` + `make test` green on `main` (**628 → 630**). New tool tests
(`tests/test_tools/test_gtd_tools.py`):
- `TestGtdChatThread::test_reads_completed_task_thread` — a completed task with two CHAT notes returns
  the two turns, `requested: False`, and asserts the resolve filter is
  `status:incomplete OR status:completed`.
- `TestGtdChatPost::test_completed_task_rejected_read_only` — a `me` turn to a completed task returns
  the read-only error after two reads, **nothing written**.
- `TestGtdChatPost::test_task_not_found` updated: a genuine miss now makes two reads (incomplete →
  completed) before the generic error.
- Existing incomplete-item thread/post tests stay green.

Acceptance criteria 1–4 from the brief are covered by these tests. A **live** read against the account
(the brief's item `1212421129`) was **not** run — the session's MCP server is still on v1.16.0, so live
calls would exercise the old code; the fix is verified in-suite. After the restart, `gtd_chat_thread`
on a completed item with CHAT notes should return its turns rather than the not-found error.

## Conventions (CONTRIBUTING.md)

§1/§3 thin-tool change, read path via `build_response`. §6 no tag writes. §8 tool tests + the
read-only call-surface assertion; inventory kept accurate. §9 lockstep (README, server instructions,
CLAUDE.md Conversation-surface section + test-count inventory). §10 read-only widen → **patch** bump
1.16.0 → 1.16.1 (`pyproject` / `uv.lock` / `__init__`). §14 this debrief.

## Open items / handback

1. **Restart the RTM MCP server on v1.16.1.**
2. **gtd-side companion (separate change):** render a completed item's thread **read-only** — show the
   prior turns but hide the compose row + suggestions, because `gtd_chat_post` refuses a completed task
   (and the worker won't reply). Cross-reference this brief in that gtd change.

## Durable lesson

The two chat tools now diverge on purpose: **reading** a thread spans completed (history is viewable),
**posting** does not (a completed task can't get a worker reply). Keep that asymmetry — widening the
post path to accept completed tasks would create threads the worker silently never answers.

---
*Handback from the rtm-mcp implementation session (2026-07-02). As-built source of truth: `CLAUDE.md`
§ Conversation surface (`gtd_chat_thread` / `gtd_chat_post`) + the tool docstrings. Consumer:
claude-plugins project-plan artifact — the per-item conversation panel's "view prior thread".*
