# RTM MCP Server

A production-quality [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for [Remember The Milk](https://www.rememberthemilk.com/) task management.

Enables Claude to manage your tasks through natural language conversation.

## Features

- **Full RTM API Coverage**: 42 tools covering tasks, lists, tags, notes, and more
- **Subtask Hierarchy**: Full parent/child task support with `parent_task_id`, subtask counts, and nesting up to 3 levels
- **Smart Add Syntax**: Natural language task creation (`"Call mom ^tomorrow !1 #family"`)
- **Default-List Aware**: `add_task` without a list routes to your configured RTM default list (not the built-in Inbox); `get_lists` surfaces the `smart`/`locked`/`archived` flags so callers can pick a writable target
- **Strict-Tag Mode** (on by default): the server refuses to apply any tag that doesn't already exist in your account — stopping accidental tag creation at the source, with a guided error that tells the caller how to recover. Set `RTM_STRICT_TAGS=0` to disable.
- **Batched project read** (`gtd_project_plan`): a whole project plan — project, all descendant items, and every note — in one read-only call (vs `1+N`), as the `project-plan-seed` envelope the GTD canvas consumes. The first of the server's `gtd_`-prefixed domain compositions.
- **Project-plan canvas tools** (`gtd_project_canvas` + `gtd_apply_canvas_commit` + `gtd_create_project`): a read-only canvas seed with the deterministic plan-graph overlay applied (ordering, blocking, quick-wins), a single governed write surface that validates a whole canvas commit up-front and writes nothing if anything is rejected, and a create-sibling that builds a brand-new project (task + dependency-ordered children + notes/tags + finalise mark) from a canvas draft in one governed call.
- **Portfolio index** (`gtd_project_index`): a read-only roll-up of every active `#project` — life, parent Area-of-Focus, and at-a-glance open/blocked counts + next tickle — in one call, backing the canvas navigator (the Phase C cockpit project picker).
- **In-board conversation surface** (`gtd_chat_post` + `gtd_chat_thread`): the governed post + cheap-poll path for the project-plan-canvas's AI chat — a new `CHAT` note class on the target task, with the worker's drain-signal tags managed in the same signed call. The board and a headless worker session converse through RTM notes (the system of record), not a live session.
- **Undo and Batch Undo**: All write operations return transaction IDs; undo one or many operations with `batch_undo`
- **Timeline Introspection**: Session transaction log with `get_timeline_info` for reviewing write history
- **Token Bucket Rate Limiting**: Burst to 3 RPS, sustain ~0.9 RPS with configurable safety margin
- **Automatic 503 Retry**: Escalating backoff (2s → 5s) with configurable retry budget
- **Connection Resilience**: Automatic retry on transient network errors (timeout, DNS, TCP reset) with write-safety — timeouts on writes surface ambiguity rather than risk duplication
- **Async Performance**: Built on httpx with connection pooling
- **Type Safety**: Full Pydantic models and type hints

## Installation

### Using uvx (Recommended)

```bash
uvx rtm-mcp
```

### Using pip

```bash
pip install rtm-mcp
```

### From Source

```bash
git clone https://github.com/PaulEastabrook/rtm-mcp.git
cd rtm-mcp
uv sync
```

> **Upstream**: This is a fork of [ljadach/rtm-mcp](https://github.com/ljadach/rtm-mcp) with additional features including undo/batch undo, timeline introspection, token bucket rate limiting, and subtask hierarchy support.

## Setup

### 1. Get RTM API Credentials

RTM API keys are issued through a separate developer portal (not your account settings):

1. Go to [RTM API Key Registration](https://www.rememberthemilk.com/services/api/keys.rtm) — you may need to log in first
2. Click **"Apply for an API Key"**
3. Fill in the form — app name (e.g. "Claude MCP"), description, anything works
4. After submitting, you'll see your **API Key** and **Shared Secret** — save both

### 2. Run Setup

```bash
rtm-setup
```

This will:
- Prompt for your API credentials
- Open your browser for authorization
- Save the auth token to `~/.config/rtm-mcp/config.json`

### 3. Configure Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rtm": {
      "command": "uvx",
      "args": ["rtm-mcp"]
    }
  }
}
```

## Usage

Once configured, you can ask Claude to manage your tasks:

- *"Show my tasks due today"*
- *"Add a task to buy groceries tomorrow, high priority"*
- *"Complete the grocery task"*
- *"What high priority tasks do I have?"*
- *"Move the meeting prep task to my Work list"*
- *"Add a note to the project task"*
- *"Show me the subtasks of my Project Alpha task"*
- *"Create a subtask under the Website Redesign task"*
- *"Move the research task under the Q2 Planning parent"*
- *"Replace all tags on the report task with #review and #urgent"*
- *"Bump the priority of the deployment task up one level"*
- *"Undo that last operation"*
- *"Show me what changes I've made this session"*
- *"Undo the last 3 operations"*

## Smart Add Syntax

When adding tasks, use RTM's Smart Add syntax:

| Symbol | Meaning | Example |
|--------|---------|---------|
| `^` | Due date | `^tomorrow`, `^next friday` |
| `!` | Priority | `!1` (high), `!2` (medium), `!3` (low) |
| `#` | Tag | `#work`, `#urgent` |
| `@` | Location | `@home`, `@office` |
| `=` | Estimate | `=30min`, `=2h` |
| `*` | Repeat | `*daily`, `*every monday` |

Example: `"Review report ^friday !1 #work =1h *weekly"`

## Subtask Hierarchy

Tasks support parent/child relationships up to 3 levels deep (RTM Pro required):

- **`parent_task_id`** is included in every task response, linking children to their parent
- **`subtask_count`** on each task shows how many subtasks appear in the current result set
- **Create subtasks** by passing `parent_task_id` to `add_task`
- **Reparent or promote** tasks with `set_parent_task` (pass empty `parent_task_id` to promote to top-level)
- **Filter by parent** using the `parent_task_id` parameter on `list_tasks`

## Lists and the Default List

### Default list resolution

When `add_task` is called **without** a `list_name`, the task goes to your account's
configured default list (RTM **Settings → General → Default List**), surfaced as
`default_list_id` by `get_settings`.

> **Why this matters:** RTM's raw `tasks.add` API ignores your default-list setting
> when no list is given and drops the task in the built-in **Inbox**. This server
> instead reads `settings.defaultlist` and passes it explicitly, so captures land
> where you expect. It falls back to the built-in Inbox only if no default is set.

**Setup tip:** to make no-list captures land in a specific list, set that list as your
Default List in RTM's web settings. Pass an explicit `list_name` to override per call.

### Smart lists are read-only

`get_lists` returns a `smart` flag per list. Smart lists are saved-search **views**,
not containers — you **cannot** `add_task` or `move_task` into one. Use a regular list
(`smart=false`), or call `get_lists(include_smart=false)` to see only writable lists.
The `locked` flag marks system lists (Inbox, Sent) that cannot be renamed or deleted.

## Strict-Tag Mode

An **existence gate** that stops the server from ever creating a new RTM tag.
RTM auto-creates a tag the first time it's used, so undisciplined callers (or a stray
SmartAdd `#token`) can quietly grow tag entropy. Strict mode closes that door at the
one chokepoint every tag write flows through.

**The rule:** with strict mode on, you may only apply a tag that **already exists in
your RTM account**. The allow-list is simply your current account tag set, read live
from RTM — the server has no knowledge of any "canonical" tag list and needs no external
config or sync. It just refuses to mint new tags.

### Toggling it

**On by default.** Re-applying tags that already exist (canonical or legacy) keeps
working; only the creation of *new* tags through the MCP is blocked. To disable it (and
allow new tags again), set the env var to a falsey value and restart the server:

```bash
RTM_STRICT_TAGS=0
```

In a Claude Desktop MCP entry, control it under `env`:

```json
"rtm": {
  "command": "uv",
  "args": ["run", "--project", "/path/to/rtm-mcp", "rtm-mcp"],
  "env": { "RTM_STRICT_TAGS": "0" }
}
```

### What it gates

| Tool | Strict-mode behaviour |
|---|---|
| `add_task` (`parse=True`) | SmartAdd `#tokens` in the name are validated; a `#token` naming a non-existent tag is rejected. |
| `add_task_tags` | Rejected if any tag being added doesn't exist. |
| `set_task_tags` | The **complete resulting** tag set is validated; rejected if any member doesn't exist. Clearing tags (empty string) is always allowed. |
| `remove_task_tags` | **Never blocked** — removing tags only reduces entropy. |
| `get_tags`, all reads | Unaffected. |

Comparison is case-insensitive (tags are trimmed + lower-cased to match RTM). Re-applying
an existing *legacy* (non-canonical) tag is allowed — the server judges only **existence**,
not whether a tag is the "right" one (that's a separate, plugin-side concern).

### The guided error

On rejection the write is **not performed** and the tool returns a self-documenting error
that teaches recovery:

```json
{
  "error": "strict_tag_mode: write rejected — tag does not exist in the account",
  "rejected_tags": ["waitingfor"],
  "reason": "Strict mode blocks creating new tags via this server. Only tags that already exist in your RTM account may be applied.",
  "how_to_proceed": "Use an existing tag (call get_tags to see the available set). If you genuinely need a NEW tag, create it deliberately and out-of-band (codify it, then create it in the RTM native client), then retry.",
  "strict_tag_mode": true
}
```

### Deliberate creation of a genuinely-new tag

Strict mode blocks only *implicit* creation. To add a new tag: create it deliberately in
the RTM **native client** (mobile/web) — the same place tags are renamed/deleted during
housekeeping. Once it exists in the account, the server accepts it. The account tag set is
cached for ~5 minutes; a rejection triggers a **live re-fetch before failing**, so a tag
you just created elsewhere is picked up without waiting for the cache to expire.

## Available Tools

### Tasks
- `list_tasks` - List tasks with filters (supports `parent_task_id` to fetch subtasks of a specific parent)
- `add_task` - Create a new task (omit `list_name` to use your RTM default list; supports `parent_task_id` to create as subtask, `external_id` for external tracking)
- `complete_task` / `uncomplete_task` - Mark done or reopen
- `delete_task` - Remove a task
- `postpone_task` - Move due date by one day
- `move_task` - Move to different list
- `set_parent_task` - Move a task under a parent or promote to top-level
- `set_task_name` - Rename task
- `set_task_due_date` - Change due date
- `set_task_priority` - Set priority level
- `move_task_priority` - Shift priority up or down by one level
- `set_task_recurrence` - Set repeat pattern
- `set_task_start_date` - Set start date
- `set_task_estimate` - Set time estimate
- `set_task_url` - Attach URL
- `add_task_tags` / `remove_task_tags` - Manage tags incrementally (adds are gated by Strict-Tag Mode when enabled; removes never are)
- `set_task_tags` - Replace all tags on a task in one call (resulting set gated by Strict-Tag Mode when enabled)

### Notes
- `add_note` - Add note to task
- `edit_note` - Edit existing note
- `delete_note` - Remove note
- `get_task_notes` - View all notes

### Lists
- `get_lists` - List all lists (each entry reports `smart`/`locked`/`archived`; smart lists are read-only views)
- `add_list` - Create new list
- `rename_list` - Rename list
- `delete_list` - Delete list
- `archive_list` / `unarchive_list` - Archive management
- `set_default_list` - Set default list

### Undo and Timeline
- `undo` - Undo a single write operation
- `batch_undo` - Undo multiple operations in reverse chronological order
- `get_timeline_info` - View session timeline and full transaction history

### Utilities
- `test_connection` - Test API connectivity
- `check_auth` - Verify authentication
- `get_tags` - List all tags
- `get_locations` - List saved locations
- `get_settings` - View user settings
- `get_contacts` - List contacts for task sharing
- `get_groups` - List contact groups with member counts
- `parse_time` - Parse natural language time
- `get_rate_limit_status` - View rate limiter state and request statistics

### GTD (domain compositions)
- `gtd_project_plan` - **Read-only.** Return a whole project plan — the project, all
  descendant items, and every note (full bodies) — as the `project-plan-seed` envelope
  consumed by the GTD canvas, in a single `rtm.tasks.getList` (plus a session-cached
  `rtm.settings.getList` so dates render in the account timezone, not UTC). Identify by
  `project_id` or `project_name` (ambiguous names return a candidate list). See *Tool naming
  convention*.
- `gtd_project_canvas` - **Read-only.** The read-sibling of `gtd_project_plan`: returns the
  *canvas-ready* seed (`{mode, frame, seed}`) with the deterministic plan-graph overlay already
  applied — `quick` (from `#quick_win`), sibling `deps`, and a dependency-respecting timeline
  order — so the canvas never re-implements GTD ordering/blocking. Each row also carries an
  optional `prog` (`"now"` from `#ai_progress_requested` / `"later"` from `#ai_progress_deferred`)
  so the execute pill reflects committed state on reload, and `redacted` (bool, from the item's
  `#redacted` tag) so the board can lock the row; `frame.redacted` is the project's own state (set
  or clear it via `gtd_set_redaction`). Date fields (`d`, `cd`, note dates) are
  localised to the account timezone (RTM returns UTC, so BST/DST dues would otherwise render a day
  early). Byte-compatible with the GTD plugin's `build_canvas --emit html-lean` seed. Filed-artefact
  file objects (per-action and the
  project-level `frame.files`) gain a `meta` block from the artefact's companion metadata
  (title/type/status/dates/authors/tags) when a read-only AI Memory vault is configured
  (`RTM_VAULT_ROOT` / `AI_MEMORY_DIR`, or the host default); absent vault or companion → no `meta`.
- `gtd_project_index` - **Read-only.** The active-project **portfolio** that backs the canvas
  navigator (the Phase C cockpit picker). Returns an object `{projects, foci, actions}` — all three
  collections sourced from one `rtm.tasks.getList` (plus the session-cached settings read for the
  timezone); no write, no timeline.
  - `projects`: one row per `#project` (incomplete, not `#test`; `#hold` always excluded, `#someday`
    excluded unless `include_someday=True`) with `life`, the parent Area-of-Focus (`focus` /
    `focus_id`; a top-level project is kept as `"(unfiled)"`, never dropped), `priority`,
    `open_count` (incomplete children), `blocked_count` (children blocked by an open `DEPENDS-ON`
    upstream — the same thin `plan_graph` judgement `gtd_project_canvas` applies), `next_tickle`
    (earliest open due date, including overdue, or `""`), `updated`, the AI-progressible tallies
    `ai_quick` / `ai_now` / `ai_later` (counts of unblocked 2-minute quick wins / `progress-now` /
    `progress-later` items — the same classification `gtd_project_canvas` applies, so the navigator's
    4th "AI" sort lens ranks on their sum), and the conversation counts `chat_count` /
    `chat_review_count` (incomplete items tagged `#ai_chat` / `#ai_output_review_needed` — the
    navigator conversation chip + "Conversations" sort lens; review is a subset signal, the project
    task itself counts when tagged); sorted `life` → `focus` → `project`.
  - `foci`: every active Area of Focus (`#focus`, same `#test`/`#hold`/`#someday` gate) as
    `{focus_id, focus, life, redacted}` — **including foci with zero active projects**, which the
    per-project rows can never surface; sorted `life` → `focus`. `redacted` is the area's own
    `#redacted` state, so the navigator can collapse a whole focus to one "Redacted Area of Focus"
    row (set it via `gtd_set_redaction` with the focus id).
  - `actions`: every incomplete child under an active project (actions, waiting-fors and calendar
    entries — all jumpable; not `#test`) as `{action_id, name, project_id, project, focus, life,
    type, due, priority, blocked}` for fast cockpit search / jump-to **and the "What's hot" band** —
    `type` (`"action"|"waiting_for"|"calendar"`, the same `gtd_project_canvas` `r.k` classification,
    so a cross-project result gets the right glyph), `due` (own due/chase/calendar date, localised,
    `""` if none), `priority` (`"1"|"2"|"3"|""`), `blocked` (open `DEPENDS-ON` upstream, same
    thin-graph judgement as `blocked_count`) and `redacted` (the action's `#redacted` state); sorted
    `life` → `focus` → `project` → `name`. Project rows likewise carry `redacted`.

  Counts are vault-free — the enriched overlay stays gtd-side. The response is an object (was a bare
  list pre-1.10.0) but backward-compatible for the existing navigator, which reads `data.projects`.
- `gtd_apply_canvas_commit` - **Constrained write.** The single governed write surface for a
  canvas commit (adds / edits / completes / removes / execute / notes). `execute` is a durable
  now/later split: `now`/`quick` write `#ai_progress_requested`; `later` writes
  `#ai_progress_deferred` (the two are mutually exclusive — switching state drops the stale
  sibling). Validates the whole commit up-front and writes nothing if anything is rejected
  (cross-project id, non-canonical tag via the strict-tag gate, smart-list target, unconfirmed
  destructive op), then applies durable-first and records each transaction. On any successful
  (non-empty) commit it also stamps `#ai_overlay_refresh_needed` on the project — the durable signal
  the gtd-side finalise engine drains to recompute the persisted plan-graph overlay (so a pure
  edit/reorder/note commit refreshes the enriched tier too, not only `execute` commits). That tag
  must exist in the RTM account under strict-tag mode. Identify the project by `project_id`.
- `gtd_create_project` - **Constrained write.** The create-sibling of `gtd_apply_canvas_commit`:
  builds a **new** project from a canvas draft (`frame` `{life, focus, name, outcome}` + `items[]`).
  Resolves the destination Area of Focus from `frame.focus` (a name — matched against the parents of
  existing `#project` tasks — or an area task id; ambiguous names return a candidate list, and an
  unknown focus is rejected rather than creating loose), then creates the project task under it and
  each child item parented in dependency order, with tags / priorities / dates / estimates,
  `DEPENDS-ON` notes (in-draft `deps` → the created RTM ids, so the canvas shows the dependency
  graph on first load), `execute` progression signals, create-then-complete for already-`done`
  items, an `INCEPTION` note, and the `#ai_project_needs_finalise` mark that triggers the gtd-side
  discipline tail. Validates up-front (strict-tag gate, item types / execute values / deps) and
  writes nothing if rejected; records each transaction (undoable via `batch_undo`). Children are
  created directly under their parent (`rtm.tasks.add` with `parent_task_id`), so no staging list is
  used. **Note:** `#ai_project_needs_finalise` must exist in the RTM account (strict-tag mode), or
  every create is rejected — provision it once.
- `gtd_chat_post` - **Constrained write.** Post one turn of the in-board AI conversation surface
  (the **`CHAT`** note class) to a task and manage the worker's drain signal in one signed call.
  Paul types an instruction (`role` `"me"`); a headless worker session replies (`role` `"ai"`) —
  they converse through RTM notes, the system of record, not a live session. The turn is one note
  titled `YYYY-MM-DD HH:MM — CHAT — <role> — <scope>` (localised to the account tz), body = the
  message; a `"me"` turn's `mode` (`discuss`|`act`) is recorded as a body footer. A `"me"` turn also
  stamps `#ai_chat_requested` (the worker's work-list signal) + `#ai_chat` (has-a-thread marker); an
  `"ai"` turn removes `#ai_chat_requested` and leaves `#ai_chat`. Pass only `task_id` (series/list
  resolved internally from one read). Tag adds pass the strict-tag gate — `#ai_chat_requested` /
  `#ai_chat` must exist in the account (provision once); a missing tag rejects with nothing written.
- `gtd_chat_thread` - **Read-only.** The cheap poll path for the conversation surface (vs
  re-reading the whole canvas) and the read-sibling of `gtd_chat_post`. One `rtm.tasks.getList`
  (spanning **incomplete + completed**, so a prior conversation stays viewable after the task is
  done); no write, no timeline. Returns `{task_id, turns: [{note_id, role, scope, mode?, text,
  created}], requested}` — turns oldest-first, non-`CHAT` notes excluded; `requested` is whether
  `#ai_chat_requested` is currently set (naturally `False` for a completed task — no pending worker —
  so the board shows the history read-only). `since` (ISO-8601) returns only turns created after it,
  for incremental polling. (Posting still requires an incomplete task — `gtd_chat_post` rejects a
  completed one with a read-only error.)
- `gtd_chat_inflight` - **Read-only.** The conversation cockpit's **cross-project live band**: every
  incomplete item with an open CHAT thread (`#ai_chat`), across all lists/projects, in one
  `rtm.tasks.getList` (no write, no timeline, no settings read). Returns `{items: [{task_id, name,
  scope ("item"|"project"), status ("in_flight"|"awaiting_review"|"open"), project_id, project_name,
  last_activity}], count}`, sorted status → recency → name. `status` derives from the item's tags
  (`#ai_chat_requested` → in_flight; else `#ai_output_review_needed` → awaiting_review; else open);
  `project_id`/`project_name` are the nearest `#project` ancestor. No new tag — reads the existing
  chat signals; vault-free.
- `gtd_set_redaction` - **Constrained write.** Mark or unmark a task's `#redacted` viewing curtain —
  the single governed surface the sandboxed board is given for redaction (it may not call the bare
  `add_task_tags` / `remove_task_tags` primitives). Resolves the task's triple by `task_id` from one
  `rtm.tasks.getList` (spanning incomplete + completed, so done items can be redacted too), then
  `redacted=true` → `addTags #redacted` (strict-tag gated — `#redacted` must exist in the account),
  `redacted=false` → `removeTags #redacted` (never gated). Records the transaction (undoable). Pairs
  with the derived `redacted` field on `gtd_project_canvas` / `gtd_project_index`. Redaction is a
  viewing-layer curtain (the plaintext still flows to the board), not a server-side vault.

#### Tool naming convention
Bare verbs (`add_task`, `list_tasks`, `get_task_notes`) are **generic RTM primitives** —
each maps 1:1 to an RTM API method (RTM's own language). A **`gtd_` prefix** marks a
**domain composition** — a GTD-shaped view over RTM data (e.g. a "project plan"), not an RTM
primitive. Format: `<domain>_<concept-noun>` (reads are the default; use
`<domain>_<verb>_<noun>` only when a domain needs an explicit verb). Reading the tool list,
the split is instant — no prefix = RTM primitive, `gtd_` = GTD view — which also keeps a
future lift of all `gtd_*` tools into a separate server a clean, mechanical move.

## Configuration

### Environment Variables

```bash
# Required
RTM_API_KEY=your_api_key
RTM_SHARED_SECRET=your_shared_secret
RTM_AUTH_TOKEN=your_token

# Rate limiting (optional, sensible defaults)
RTM_BUCKET_CAPACITY=3          # Max burst size (tokens)
RTM_SAFETY_MARGIN=0.1          # 10% below RTM's 1 RPS limit
RTM_MAX_RETRIES=2              # Retries on HTTP 503
RTM_RETRY_DELAY_FIRST=2.0      # Seconds before first retry
RTM_RETRY_DELAY_SUBSEQUENT=5.0 # Seconds before 2nd+ retry

# Tag discipline (on by default)
RTM_STRICT_TAGS=1              # default on; set 0/false to allow tags not already in the account (see Strict-Tag Mode)

# Companion metadata (optional) — read-only AI Memory vault for gtd_project_canvas file.meta
RTM_VAULT_ROOT=~/Documents/AI Memory   # preferred; or set the shared AI_MEMORY_DIR. Unset → host
                                        # default ~/Documents/AI Memory if its memory/_index.md marker
                                        # exists, else companion resolution is off (no meta, no error)
```

### Config File

`~/.config/rtm-mcp/config.json`:
```json
{
  "api_key": "your_api_key",
  "shared_secret": "your_shared_secret",
  "token": "your_token"
}
```

## Response Format

All tools return a consistent JSON structure:

```json
{
  "data": { ... },
  "metadata": {
    "fetched_at": "2026-04-02T12:00:00Z"
  }
}
```

Write operations include additional metadata for undo support:

```json
{
  "data": { "task": { ... }, "message": "Created task: Buy groceries" },
  "metadata": {
    "fetched_at": "2026-04-02T12:00:00Z",
    "transaction_id": "123456",
    "transaction_undoable": true,
    "timeline_id": "987654"
  }
}
```

Task listing includes optional analysis:

```json
{
  "data": { "tasks": [ ... ], "count": 5 },
  "analysis": {
    "insights": ["3 tasks due today", "2 high-priority tasks"]
  }
}
```

## Error Handling

The server maps RTM API error codes to descriptive exception types and appends recovery guidance so that AI agents can self-correct:

| Code | Type | Meaning | Recovery Guidance |
|------|------|---------|-------------------|
| 98 | Auth | Invalid auth token | Re-run `rtm-setup` to get a fresh token |
| 99 | Auth | Insufficient permissions | Token needs `delete` permission — re-run `rtm-setup` |
| 101 | Validation | Invalid API key | Check `RTM_API_KEY` env var or config file |
| 114 | Auth | User not logged in | Re-run `rtm-setup` to authenticate |
| 340 | Not Found | List not found | Call `get_lists` to see available list names |
| 341 | Not Found | Task not found | Call `list_tasks` to find the correct task name or IDs |

### Subtask and Hierarchy Errors

| Code | Meaning | Recovery Guidance |
|------|---------|-------------------|
| 4040 | Pro account required | Subtask features require RTM Pro |
| 4050 | Invalid parent task | Call `list_tasks` to verify the parent task ID exists |
| 4060 | Nested too deep | RTM allows max 3 levels — promote an intermediate task first |
| 4070 | Repeating task conflict | A repeating task cannot be a parent or child of another repeating task |
| 4080 | Date constraint | Due date must be after start date (or vice versa) — check both dates |
| 4090 | Self-parenting | A task cannot be its own parent |

Application-level errors (e.g., task not found by name, missing IDs) return actionable messages suggesting the next tool to call:

```json
{"error": "Task not found: 'Buy milk'. Use list_tasks to search by filter or check spelling."}
```

## RTM Pro Requirements

Some features require an RTM Pro subscription:

- **Subtask creation**: `add_task` with `parent_task_id`
- **Reparenting tasks**: `set_parent_task`
- **Subtask nesting**: Maximum 3 levels deep
- **Subtask filtering**: `list_tasks` with `parent_task_id` parameter

All other tools (42 total) work with free RTM accounts.

## Rate Limiting

The server uses a **token bucket** algorithm to stay within RTM's API limits:

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| Bucket capacity | 3 | `RTM_BUCKET_CAPACITY` | Max burst size (requests) |
| Safety margin | 10% | `RTM_SAFETY_MARGIN` | Buffer below RTM's 1 RPS limit |
| Effective rate | ~0.9 RPS | — | Derived from 1.0 - safety margin |
| Max 503 retries | 2 | `RTM_MAX_RETRIES` | Retry budget for HTTP 503 |
| First retry delay | 2s | `RTM_RETRY_DELAY_FIRST` | Backoff before first retry |
| Subsequent delay | 5s | `RTM_RETRY_DELAY_SUBSEQUENT` | Backoff before 2nd+ retry |

**Burst vs sustained**: You can make up to 3 rapid requests (burst), after which the rate settles to ~0.9 requests/second. HTTP 503 responses trigger automatic retry with escalating backoff.

**Diagnostics**: Use `get_rate_limit_status` to inspect current token availability, request counts, and 503 error history. If `http_503_count_session` is non-zero, increase `RTM_SAFETY_MARGIN` (e.g., from 0.1 to 0.15).

## Troubleshooting

### "RTM not configured"

Run `rtm-setup` or set the `RTM_API_KEY`, `RTM_SHARED_SECRET`, and `RTM_AUTH_TOKEN` environment variables.

### Authentication Errors

RTM tokens don't expire, but can be revoked. If you get auth errors, re-run `rtm-setup` to obtain a fresh token.

### Rate Limit Issues

If you see HTTP 503 errors or slow responses:

1. Run `get_rate_limit_status` to check `http_503_count_session`
2. If non-zero, increase `RTM_SAFETY_MARGIN` (e.g., `RTM_SAFETY_MARGIN=0.15`)
3. For batch operations, the server automatically paces requests

### Subtask Errors

- **Error 4040**: Subtask features require an RTM Pro account
- **Error 4060**: Maximum 3 nesting levels — promote an intermediate task to reduce depth
- **Error 4070**: Repeating tasks cannot be nested under other repeating tasks

## Development

Coding, testing, and documentation standards are in [CONTRIBUTING.md](CONTRIBUTING.md) — the
canonical conventions doc. Architecture and RTM API quirks are in [CLAUDE.md](CLAUDE.md).

```bash
# Install dev dependencies
make dev

# Run linting
make lint

# Run tests
make test

# Run with coverage
make test/coverage

# Format code
make format
```

## Docker

```bash
docker build -t rtm-mcp .
docker run -it --rm \
  -e RTM_API_KEY \
  -e RTM_SHARED_SECRET \
  -e RTM_AUTH_TOKEN \
  rtm-mcp
```

Claude Desktop config for Docker:
```json
{
  "mcpServers": {
    "rtm": {
      "command": "docker",
      "args": ["run", "-i", "--rm",
        "-e", "RTM_API_KEY",
        "-e", "RTM_SHARED_SECRET",
        "-e", "RTM_AUTH_TOKEN",
        "rtm-mcp"]
    }
  }
}
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Disclaimer

This product uses the Remember The Milk API but is not endorsed or certified by Remember The Milk.

## Acknowledgments

- [Remember The Milk](https://www.rememberthemilk.com/) for the excellent task management service
- [FastMCP](https://github.com/jlowin/fastmcp) for the MCP framework
- [Anthropic](https://anthropic.com/) for Claude and the MCP specification
