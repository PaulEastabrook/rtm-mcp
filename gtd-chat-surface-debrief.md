---
report_type: implementation-debrief
scope: GTD in-board AI conversation surface — gtd_chat_post (write) + gtd_chat_thread (read) — BUILT (not yet committed)
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-28
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: branch feat/gtd-chat-surface (off main); rtm-mcp v1.14.0; NOT yet committed/PR'd
relates_to: 2026-06-28 hand-off brief "rtm-mcp — gtd_chat_post + gtd_chat_thread (the board's governed conversation surface)"; designed-change 2026-06-28-gtd-ai-conversation-surface.md § 2.3; the four 2026-06-28 capability spikes (blackboard-mediated round-trip); gtd journaling-lifecycle.md (CHAT note class); phase-c-gtd-project-index-ai-counts-debrief.md (v1.13.0, the prior gtd_* enrichment)
status: server half BUILT on a branch, tests + lint green, NOT yet committed; needs (a) Paul's commit/PR decision, (b) #ai_chat_requested/#ai_chat provisioning, (c) server restart on v1.14.0; gtd-side consumer ships in parallel and is backward-compatible
---

# Debrief — `gtd_chat_post` + `gtd_chat_thread` (the board's governed conversation surface)

Built and verified on branch **`feat/gtd-chat-surface`** (off `main`): rtm-mcp **v1.14.0**.
`make test` (**603 tests**) and `make lint` (ruff check + format + pyright) are green. Additive,
reversible, backward-compatible — can land ahead of the gtd-side consumer. **Not yet committed** —
held for Paul's commit/PR decision (per the host session's git discipline: branch, then stop).

## 1. What was built

Two new `gtd_`-prefixed tools backing the project-plan-canvas's **in-board AI conversation surface**
(the new **`CHAT`** journalled note class). The board and a `runScheduledTask`-spawned headless
worker converse through RTM notes — the system of record — not a live session (the four spikes
proved the worker is context-complete but headless, and the artifact's JS can call connector MCP
tools but not desktop-internal ones).

- **`gtd_chat_post` (governed write)** — post one CHAT turn to a task and manage the worker's drain
  signal in ONE signed call. Params `(task_id, text, role="me", scope?, mode?)`.
- **`gtd_chat_thread` (read)** — return just the CHAT turns for a task, cheap polling vs re-reading
  the whole canvas. Params `(task_id, since?)`.

The full thread also still flows unchanged through `gtd_project_canvas` / `gtd_project_plan` as
ordinary notes — these two tools are only the efficient post + poll path.

## 2. The CHAT note grammar (gtd owns the canonical definition; the server mirrors it)

One turn = one RTM note on the **target task** (the project task for project-scope; the item task
for item-scope), title:

```
YYYY-MM-DD HH:MM — CHAT — <role> — <scope>
```

- Space-em-dash-space separators; timestamp **localised to the account timezone** (same convention
  as every other gtd_* date — via `client.get_timezone()`).
- `<role>` ∈ `me` (Paul) | `ai` (worker reply); `<scope>` is a display label (defaults to the task
  name) — the *attachment task* is the real scope.
- Body = the message text. A `me` turn's posture `mode` (`discuss` | `act`) is appended as a final
  `Mode: <mode>` footer line and round-trips back out on read.
- Selector: a note is a CHAT turn iff its title matches
  `^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — CHAT — (me|ai) — ` — robust to notes authored by either the
  board (`gtd_chat_post`) or the worker (which may use `add_note` directly with the same grammar).

## 3. Behaviour — validate-then-apply, governed drain signal

**`gtd_chat_post`:**
1. Validate `role` / `mode` (actionable error on miss; `mode` honoured only for `me`).
2. Resolve the task by id from **one** `rtm.tasks.getList(status:incomplete)` —
   `taskseries_id`/`list_id` resolved internally, so the caller passes only the id it has (chat
   lives on active work; a completed item won't resolve, by design — see § 6).
3. **Strict-tag existence gate (me-turn only)** over `#ai_chat_requested` + `#ai_chat` — reject
   with the guided error and **nothing written** if either is missing.
4. Write the CHAT note (localised title + mode footer), then manage the signal:
   - `role: me` → `addTags ai_chat_requested,ai_chat` → `tag_changes: [+ai_chat_requested, +ai_chat]`.
   - `role: ai` → `removeTags ai_chat_requested` (the turn is answered), leaving `ai_chat` →
     `tag_changes: [-ai_chat_requested]`.
5. Each write records its transaction (undoable via `batch_undo`); the helper is batch-resilient
   (per-op failures captured in `errors`). Returns `{note:{id,title,created}, task_id, role,
   tag_changes, errors}` + the note's transaction_id.

**`gtd_chat_thread`:** one `rtm.tasks.getList(status:incomplete)`, **no settings read, no write, no
timeline** — so the read-only call surface is exactly `["rtm.tasks.getList"]`. Resolves the task by
id, parses its CHAT notes oldest-first (non-CHAT excluded; optional `since` ISO-8601 incremental
filter), and reports `requested` = whether `#ai_chat_requested` is currently set (so the board shows
a "thinking…" state without a second call). Per-turn `created` is RTM's value (UTC, not
re-localised — the localised display stamp lives in the note title the canvas already renders).

## 4. Membrane & activation — no hazard, BUT a tag-provisioning prerequisite

Vault-free — no AI-Memory awareness, pure RTM. The server introduces **no new tag of its own**: it
*reads/sets* `#ai_chat_requested` (the worker's durable work-list signal) and `#ai_chat` (has-a-
thread marker), which Paul provisions account-side first — **exactly the posture used for
`#ai_overlay_refresh_needed`** (A2.1 Piece 0b). Cost: `gtd_chat_post` = one getList + one note-add +
one tag add/remove; `gtd_chat_thread` = one getList. Tag *removal* (the `ai` turn) is never gated
(reduces entropy — CONTRIBUTING.md § 6); the existence gate applies only to the `me`-turn add path,
and only when a tag is actually being written — so there is no unconditional activation-ordering
hazard, **but** until the two tags exist a `me`-turn post is rejected with the guided error (surfaced,
not silently failed). Backward-compatible: if the tools are absent (server < v1.14.0) the board hides
the compose row and behaves exactly as today.

## 5. Implementation map

- **`src/rtm_mcp/gtd_chat.py`** (NEW, pure no-IO — the byte-of-truth for the grammar): tag constants
  `AI_CHAT_REQUESTED`/`AI_CHAT`, `VALID_ROLES`/`VALID_MODES`, `format_chat_title`/`parse_chat_title`,
  `append_mode_footer`/`parse_body` (the mode round-trip), `parse_turn`/`build_thread` (oldest-first,
  non-CHAT excluded, `since` filter), `local_stamp` (tz-localised wall-clock with UTC fallback).
  Mirrors the existing pure-module pattern (`canvas_seed.py`, `canvas_commit.py`).
- **`src/rtm_mcp/tools/gtd.py`**: the two tools appended to `register_gtd_tools` (now 7 gtd tools).
  `gtd_chat_post` reuses the commit tool's batch-resilient `_write` helper pattern + the strict-tag
  gate; `gtd_chat_thread` is a thin read.
- **Docs lockstep (all four touchpoints):** `README.md` (feature blurb + two tool bullets),
  `src/rtm_mcp/server.py` (instructions block), `CLAUDE.md` (architecture tree, module-responsibility
  table, new "Conversation surface" feature section, test-count inventory 571 → 603).
- **Version:** `pyproject.toml` (+ `uv.lock`) **1.13.0 → 1.14.0** (SemVer minor — two additive tools).
  No CHANGELOG file exists in the repo (version history lives in pyproject + git), so nothing else
  to bump.

## 6. Decisions a reviewer should know (and could push back on)

1. **Resolution filter `status:incomplete` (not `…OR status:completed`).** Both tools resolve the
   task by id from a single getList scoped to *incomplete* tasks — chat lives on active work, and
   this keeps the hot poll path (`gtd_chat_thread`) cheap (completed-history is the bulk of an
   account). Trade-off: a chat on an already-completed item won't resolve (returns an actionable
   not-found). (Contrast: `gtd_apply_canvas_commit` uses `incomplete OR completed`; the chat poll
   path deliberately does not.)
   **Reviewer note (accepted — consumer side):** this is fine as-is — the board degrades gracefully
   when it's ever hit, hiding the compose row via the capability probe, so there is **no breakage**
   on a completed item. If chat should later **survive item completion**, this is the single filter
   to widen (both tools, `status:incomplete` → `status:incomplete OR status:completed`) — at the
   cost of a heavier poll read. Logged as the known extension point, not a defect.
2. **Mode footer format = a literal final `Mode: <mode>` line.** Parsed only when it is the last
   non-empty line and matches `^Mode:\s*(discuss|act)\s*$` (case-insensitive); stripped from the
   returned `text`. A `Mode:` mid-message is left untouched. The gtd-side worker must mirror this
   exact convention when it authors `ai`/`me` notes directly.
3. **`created` returned as RTM UTC, not localised** — to keep `gtd_chat_thread` to a single getList
   (localising would need the settings read). The localised stamp is already in the note title.

## 7. Verification done

`make lint` + `make test` green on the branch: **603 tests** (up from 571), comprising:
- **`tests/test_gtd_chat.py`** (NEW, 19) — pure helpers: title format/parse round-trip (+ non-CHAT /
  `ai`-role / empty / bad-role → None); `append_mode_footer`/`parse_body` round-trip (with/without
  mode; footer only on the final line; discuss); `parse_turn` (`$t` vs `body` body keys; mode
  omit-when-absent); `build_thread` (filters non-CHAT, oldest-first, out-of-order input, `since`,
  empty, single-dict normalised); `local_stamp` shape + tz fallback; tag constants.
- **`tests/test_tools/test_gtd_tools.py`** (+13) — `gtd_chat_post`: me-turn posts a CHAT note with the
  title grammar + adds both tags; ai-turn removes `#ai_chat_requested` and never adds; task_id
  resolves series/list internally; mode footer **round-trips into `gtd_chat_thread`**; invalid
  role/mode + task-not-found rejected without writing; **strict-tag rejection writes nothing** (asserts
  `notes.add`/`addTags` never called). `gtd_chat_thread`: only CHAT turns oldest-first; `since`
  filter; `requested` reflects the tag; empty thread → `[]`; **read-only call surface** + no
  transaction.

A live read/write against the real account was **not** run — the tools aren't on the running server
until it is restarted on v1.14.0, and the two tags aren't provisioned yet. Recommended smoke after
both: `gtd_chat_post(role="me")` on a real project id → confirm the CHAT note + tags in RTM;
`gtd_chat_thread` → the turn returns with `requested: true`; `gtd_chat_post(role="ai")` →
`requested: false`, thread shows both turns oldest-first.

## 8. Open items for the coworker

**rtm-mcp side (Paul / ops):**
1. **Decide commit/PR** for branch `feat/gtd-chat-surface` (host session stopped at "branched, green,
   uncommitted"). Suggested Conventional Commit: `feat(gtd): add gtd_chat_post + gtd_chat_thread for
   the in-board AI conversation surface (CHAT note class)`.
2. **Provision `#ai_chat_requested` + `#ai_chat`** in the RTM account (native client) — the
   activation prerequisite, same as `#ai_overlay_refresh_needed` was. Until then a `me`-turn post is
   rejected with the guided error.
3. **Restart the RTM MCP server on v1.14.0** so the two tools are exposed.

**gtd / claude-plugins side (ships in parallel — no action in this repo):**
4. `project-plan-artifact.html`: a compose row (input + Send + discuss/act toggle) in the project
   top-matter and each item's expanded area → `callMcpTool('mcp__rtm__gtd_chat_post', {task_id, text,
   role:'me', scope, mode})` → `runScheduledTask(«CHAT_WORKER_TASK_ID»)`; then poll
   `gtd_chat_thread({task_id, since})` until the `ai` turn lands; render read-only (me right-aligned,
   ai left). Declare both tools in the artifact's `mcp_tools`. Gate the compose row on the tools'
   presence (server ≥ v1.14.0) for backward-compatibility.
5. `gtd-chat-agent` scheduled task: drain `#ai_chat_requested`, read the thread + context, act as a
   full GTD session, then `gtd_chat_post({…, role:'ai'})` to reply + clear the signal. **Must mirror
   the CHAT title grammar + `Mode:` footer convention** (§ 2 / § 6.2) when authoring notes directly.

---
*Handback from the rtm-mcp implementation session (2026-06-28). Source of truth for the as-built
behaviour: rtm-mcp `CLAUDE.md` (§ "Conversation surface (`gtd_chat_post` / `gtd_chat_thread`)") and
the two tool docstrings in `src/rtm_mcp/tools/gtd.py`. Predecessor: phase-c-gtd-project-index-ai-
counts-debrief.md (v1.13.0). Consumer: claude-plugins `project-plan-artifact.html` compose row +
the `gtd-chat-agent` scheduled task. Umbrella: designed-change 2026-06-28-gtd-ai-conversation-
surface.md § 2.3.*
