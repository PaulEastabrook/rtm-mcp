---
report_type: bug-fix-debrief
scope: rtm-mcp — gtd_chat_thread returned an empty thread (read-path parsed the wrong field) — FIXED
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-28
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #21 (merged to main, merge commit bbc6155; fix commit 4a59215), rtm-mcp v1.14.0 → v1.14.1
relates_to: brief "fix gtd_chat_thread — parse the CHAT title from the note body's first line"; debrief
            "gtd_chat_post + gtd_chat_thread (the board's governed conversation surface)";
            designed-change 2026-06-28-gtd-ai-conversation-surface.md § 2.3; gtd journaling-lifecycle.md
status: FIXED on main; needs the MCP server restarted on v1.14.1 for the live round-trip to go green
---

# Debrief — `gtd_chat_thread` empty-thread bug fixed (v1.14.1)

Built, tested, merged: rtm-mcp **v1.14.1**, PR [#21](https://github.com/PaulEastabrook/rtm-mcp/pull/21)
→ `main` (merge `bbc6155`, fix commit `4a59215`). Merged `main` is green: **607 tests**, `make lint`
(ruff check + format + pyright) clean. Read-parser fix only — the write half was already correct.

## 1. The bug (as diagnosed)

`gtd_chat_post` wrote CHAT notes correctly, but `gtd_chat_thread` returned `turns: []` for those same
notes — the board rendered an empty thread. `parse_turn` (in `src/rtm_mcp/gtd_chat.py`) matched the
CHAT selector against the note's **`title` field, which RTM always returns empty**. The grammar title
actually lives as the **first line of the note body** (`title\nmessage` in the single body field — the
RTM API has no separate note-title field). So no real `rtm.tasks.getList` note ever matched.

`requested` was correct throughout because it is computed from the task's tag set, independent of note
parsing — which is exactly why the smoke test saw `{ turns: [], requested: <correct> }`.

## 2. Root cause — a mock-vs-reality gap

The unit tests passed because their fixtures fed `parse_turn` notes with the grammar in a **populated
`title` field** — a shape `rtm.tasks.getList` never returns. The parser had been written to that
fixture shape rather than to RTM's real storage model. The brief's `get_task_notes` evidence
(`title: ""`, grammar as `$t` line 1) is the real shape; that is now what the fixtures use.

## 3. The fix

`parse_turn` now derives the title from the body, not the `title` field:

```python
first_line, _, rest = (extract_note_body(note) or "").partition("\n")
parsed = parse_chat_title(first_line)   # line 1 = candidate title
if not parsed:
    return None
text, mode = parse_body(rest)            # lines 2..N = message (+ Mode: footer stripped as before)
```

- **Single-line body** (title only, no message) → `partition` gives `rest == ""` → a valid turn with
  empty `text`, **not dropped**.
- `extract_note_body` still handles the `$t` vs `body` shapes, so worker-authored notes (direct
  `add_note`) parse identically.
- A note whose **first body line** doesn't match the selector is excluded, same as before.

**Untouched** (all verified working in the brief's smoke test): the write path, the tag/drain-signal
management (`#ai_chat_requested` / `#ai_chat`), the title grammar, `requested`, and the `since` filter.

## 4. Regression coverage — the realistic shape is now the default

The test `_note` helper and the `gtd_chat_thread` tool fixtures now mirror real `getList` output
(`title=""`, grammar as the body's first line), so the whole existing suite exercises the real parser.
New cases pin the fix (`tests/test_gtd_chat.py`):
- the exact shape that returned `[]` (`title:""`, `$t: "…— CHAT — me — project\nhello there"`) → parsed;
- the **`title` field is ignored** — grammar in `title` but a plain body first line → **not** a turn
  (proves we read the body, not the title);
- single-line body → turn with empty `text`;
- `Mode: act` footer on the realistic shape → stripped from `text`, surfaced as `mode`.

The `gtd_chat_thread` tool test (`tests/test_tools/test_gtd_tools.py`) and the post→read round-trip
test both feed the realistic note shape through `build_thread` end-to-end. Suite 603 → **607**.

## 5. Versioning & conventions (CONTRIBUTING.md)

- Bug fix → **patch** bump **v1.14.0 → v1.14.1** (`pyproject.toml`, `uv.lock`); `__init__.py`
  re-aligned (it had drifted to `1.13.0`).
- §9 lockstep: the tool's external `{turns, requested}` contract is **unchanged**, so README and
  `server.py` instructions needed no edit; CLAUDE.md was updated — the CHAT-grammar section now states
  *the title is the first line of the body* (with the v1.14.1 bug noted), plus the test-count inventory.
- §6: read path only — no tag write, no new tag, no strict-tag interaction.
- §8/§11: pure-helper tests + the tool test; `make test` + `make lint` green.

## 6. Acceptance gate — needs a server restart (NOT run here)

The brief's §6 live re-smoke requires the MCP server running the fixed code. This session's RTM MCP
server is still on the old build, so I did **not** run live RTM calls — re-smoking against it would
only re-confirm the bug, not validate the fix. The realistic-shape regression test reproduces the
failing path through `build_thread` and asserts the turns return, so the fix is verified in-suite.

**To close the gate operationally:** rebuild/restart the RTM MCP server on **v1.14.1**, then on a fresh
`#test` task — (1) `gtd_chat_post(role="me")` → next `gtd_chat_thread` shows the `me` turn,
`requested:true`; (2) `gtd_chat_post(role="ai")` → `gtd_chat_thread` shows **both** turns oldest-first,
`requested:false`; (3) delete the `#test` task.

## 7. Open items for the coworker

1. **Restart the RTM MCP server on v1.14.1** (this also covers the original v1.14.0 activation step —
   still needs `#ai_chat_requested` / `#ai_chat` provisioned account-side for the `me`-turn write gate).
2. **Run the §6 re-smoke** to close the acceptance gate.
3. **Consumer — no action.** The claude-plugins / gtd consumer is already on the `{turns, requested}`
   contract (`c59466038`) and the board's raw-note fallback already parses title-from-body-first-line,
   so the two sides agree the moment the thread returns turns.

## 8. The durable lesson

A CHAT turn's title is the **first line of the body**, never a `title` field — RTM has no note-title
field (it returns `title\nmessage` in one body value, `title=""`). Any future note parser (server or
board) must read line 1 of the body. Write fixtures to **real `getList` output**, not to a convenient
populated-`title` shape — that gap is what let this ship green.

---
*Handback from the rtm-mcp implementation session (2026-06-28). Evidence: live smoke test against the
RTM account (notes 118061620 / 118061628 on throwaway task 1213331316, since deleted) + the
`get_task_notes` shape in the brief. Fix: rtm-mcp `src/rtm_mcp/gtd_chat.py` (`parse_turn`). As-built
source of truth: `CLAUDE.md` § Conversation surface + the `gtd_chat.py` / `parse_turn` docstrings.*
