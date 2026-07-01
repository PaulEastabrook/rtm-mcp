---
report_type: feature-debrief
scope: rtm-mcp — gtd_chat_inflight (the conversation cockpit's cross-project live-band read, F3) — SHIPPED
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-30
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #22 (merged to main, merge commit 4d65d48; feature commit d5fbc61), rtm-mcp v1.14.1 → v1.15.0
relates_to: brief "gtd_chat_inflight — the cross-project read behind the cockpit's live band (F3)";
            designed-change 2026-06-29-gtd-conversation-cockpit.md § 2.5; sibling gtd_chat_post /
            gtd_chat_thread (v1.14.x); the v1.14.1 empty-thread fix (title-from-body-first-line)
status: server half DONE on main; gtd consumer already shipped (gtd v0.111.0, hides band on absence) —
        only needs the MCP server restarted on v1.15.0 to expose the tool and light up F3
---

# Debrief — `gtd_chat_inflight` shipped (v1.15.0): the cockpit's cross-project live band

Built, tested, merged: rtm-mcp **v1.15.0**, PR [#22](https://github.com/PaulEastabrook/rtm-mcp/pull/22)
→ `main` (merge `4d65d48`, feature `d5fbc61`). Merged `main` is green: **622 tests**, `make lint`
(ruff check + format + pyright) clean. Additive, read-only, vault-free — a new `gtd_` read tool.

## 1. What shipped

`gtd_chat_inflight()` — the F3 live band's cross-project read: every incomplete item carrying an open
CHAT thread (`#ai_chat`), across all lists/projects, in one call. The per-project `gtd_project_canvas`
can only see its own project; this is the "all my agents working right now" view. (F1/F2 are
render-only off the per-item `tags[]` the seed already carries — no server change; only F3 had a
server dependency.)

```jsonc
{ "items": [ { "task_id", "name", "scope": "item"|"project",
              "status": "in_flight"|"awaiting_review"|"open",
              "project_id", "project_name", "last_activity": "<ISO|"">" } ], "count": <int> }
```

- **Selection**: incomplete, `#ai_chat`, NOT `#test` (the thread lives on active work — mirrors
  `gtd_chat_thread`).
- **status** (precedence): `#ai_chat_requested` → `in_flight`; else `#ai_output_review_needed` →
  `awaiting_review`; else `open`.
- **scope**: `project` when the task itself carries `#project`, else `item`.
- **project_id / project_name**: the nearest `#project` ancestor (the task itself when it is a
  project). A loose item with no `#project` ancestor keeps `project_id=""` (chip shows; can't load).
- **last_activity**: the most-recent CHAT note's `created` (RTM's UTC value, not re-localised), `""`
  when there are no CHAT turns. Optional urgency signal for ordering.

Sorted **status → most-recent activity → name** (deterministic, no clock dependency).

## 2. Implementation — reuse, not re-derive

- **Pure `build_inflight(parsed)`** in `src/rtm_mcp/gtd_chat.py` (the CHAT-domain module) — reuses
  `project_plan._ancestor_chain` for the `parent_task_id` walk (finding the nearest `#project`) and
  the **v1.14.1-fixed `build_thread`** for `last_activity` (so it reads the CHAT title from the body's
  first line, not the always-empty title field). Tags normalised via `strict_tags.normalize_tag`.
- **Thin tool `gtd_chat_inflight`** in `tools/gtd.py` mirrors `gtd_chat_thread`: one
  `client.call("rtm.tasks.getList", filter="status:incomplete")` → `parse_tasks_response` →
  `build_response(data=build_inflight(...))`. No timeline, no settings read.
- New constant `AI_OUTPUT_REVIEW_NEEDED = "ai_output_review_needed"` — a **read-only** status signal
  (account-provisioned, never minted here), alongside the existing `AI_CHAT` / `AI_CHAT_REQUESTED`.

## 3. The one broad getList (a deliberate, documented choice)

The brief's §2/§4 describe "one getList filtered to `tag:ai_chat`". I use the **broad**
`getList(status:incomplete)` and filter in-memory instead — because resolving each item's
`project_id`/`project_name` means walking up to the enclosing project task, and **those ancestor
project tasks don't carry `#ai_chat`**, so a tag-filtered read wouldn't contain them. The broad read:
- keeps the read-only call surface **exactly `["rtm.tasks.getList"]`** (one call, no second lookup);
- makes ancestors available for resolution in the same pass;
- is the identical posture the siblings already take (`gtd_chat_thread` at gtd.py, `gtd_project_index`).

The brief explicitly permits this ("a second getList or the cached hierarchy is acceptable"); a single
broad read is the cheapest way to satisfy the ancestor requirement. The band renders occasionally
(cockpit open + manual refresh), not hot-polled, so the full incomplete read is fine.

## 4. Membrane & activation — no hazard

Vault-free, pure RTM. Reads `#ai_chat` / `#ai_chat_requested` / `#ai_output_review_needed` (all
account-provisioned) — **writes nothing, introduces no new tag, no `enforce_strict_tags` interaction,
no activation-ordering hazard**. The only operational step is **rebuild/restart the MCP server on
v1.15.0**. The gtd consumer (gtd v0.111.0) already declares `mcp__rtm__gtd_chat_inflight`, calls it
`try/catch`-wrapped, and hides the band on absence/error/empty — so the tool landed independently with
zero risk to the live board.

## 5. Conventions (CONTRIBUTING.md)

- §1/§2: pure logic in `gtd_chat.py`; thin `gtd_`-prefixed read tool in `tools/gtd.py`.
- §3/§4: one GET, `build_response(data=...)`, no timeline. §6: reads tags only — no write, no gate,
  no new tag. §7: enriched docstring; native unions; `make format` clean.
- §8/§11: pure-helper + tool tests incl. the read-only call-surface assertion; `make lint` + `make
  test` green; test-count inventory kept accurate.
- §9 lockstep: README, server instructions, CLAUDE.md (architecture tree + `(7 tools)`→`(8 tools)`,
  `gtd_chat.py` module row, the Conversation-surface feature section, and the inventory).
- §10: new tool → **minor** bump v1.14.1 → v1.15.0 (`pyproject.toml`, `uv.lock`, `__init__.py`
  re-aligned). Upstream `ljadach` is at v1.0.0 — fork-only surface, no numeric lockstep.

## 6. Verification done

`make lint` + `make test` green on merged `main` (**607 → 622**). Coverage:
- **Pure** (`tests/test_gtd_chat.py::TestBuildInflight`, 12): selection (incomplete + `#ai_chat`,
  excludes `#test` + completed); status precedence incl. in_flight-wins-over-review; scope
  project-vs-item; ancestor resolution (item → nearest `#project`, project → itself, **deep-nested**
  walk-up, **loose** → `""`); `last_activity` latest CHAT note (+ empty when none); status→recency→name
  ordering; empty → `{items:[],count:0}`.
- **Tool** (`tests/test_tools/test_gtd_tools.py::TestGtdChatInflight`, 3): cross-project roll-up with
  status/scope/project attribution + `last_activity`, `#test` excluded; empty portfolio; the read-only
  call-surface assertion + no transaction. Fixtures use the **real getList shape** (tags on the task,
  CHAT title in the body's first line — the v1.14.1 lesson).

A live read against the account was **not** run — the session's MCP server is still on the old build,
so live calls would only exercise the old code. The realistic-shape tests reproduce the cross-project
path in-suite.

## 7. Acceptance gate (after restart) + open items

**Restart the MCP server on v1.15.0**, then per the brief: post a `me` turn on an incomplete item in
project A and another in B → `gtd_chat_inflight()` returns both with correct `project_id`/`status`;
`gtd_chat_post(role="ai")` on one → its status flips off `in_flight` (stays `open` while `#ai_chat`
remains); complete the item → it drops out. Then open the cockpit: the live band shows both chips;
clicking one loads that project and opens the thread.

**Consumer — no action.** claude-plugins (gtd v0.111.0) is already wired; the band lights up the moment
the tool is live.

## 8. Note for future authors

`last_activity` and any CHAT parsing go through `build_thread`, which reads the title from the **body's
first line** (RTM has no note-title field — the v1.14.1 fix). Keep writing fixtures to real `getList`
output (`title=""`, grammar in `$t` line 1), not a populated-`title` convenience shape. Ancestor
resolution reuses `project_plan._ancestor_chain`; `#project` is the membership marker for a plan's top.

---
*Handback from the rtm-mcp implementation session (2026-06-30). As-built source of truth: rtm-mcp
`CLAUDE.md` § Conversation surface (`gtd_chat_inflight`) + the `gtd_chat_inflight` / `build_inflight`
docstrings. Siblings: gtd_chat_post / gtd_chat_thread (v1.14.x). Consumer: claude-plugins
`project-plan-artifact.html` F3 live band (gtd v0.111.0).*
