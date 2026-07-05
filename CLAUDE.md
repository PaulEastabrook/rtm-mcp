# RTM MCP Server - Developer Documentation

> **Conventions & standards live in [CONTRIBUTING.md](CONTRIBUTING.md)** — the canonical source
> for coding, testing, and documentation rules (source style, tool patterns, the enriched
> docstring shape, the documentation-lockstep rule, versioning, and the add-a-tool checklist).
> This file owns **architecture, RTM API quirks, and per-feature deep-dives**.

## Architecture Overview

```
src/rtm_mcp/
├── server.py           # FastMCP server, lifespan, tool registration
├── client.py           # Async RTM API client with signing, retry, settings caching (timezone + default list)
├── config.py           # Pydantic settings (env + file + rate limits + connection retry)
├── parsers.py          # RTM response parsing, formatting, normalization, analysis
├── response_builder.py # MCP response envelope + transaction recording
├── lookup.py           # Shared name-to-ID resolution for tasks and lists
├── strict_tags.py      # Strict-tag mode: existence gate for tag writes (on by default)
├── project_plan.py     # Pure project-plan-seed/3.1 envelope builder (backs gtd_project_plan)
├── order_note.py       # Pure ORDER-note contract (order-note/1): make/parse/resolve/from_envelope — durable manual plan-order intent (DC-4)
├── project_index.py    # Pure active-#project portfolio roll-up + counts + foci + action index (backs gtd_project_index)
├── canvas_seed.py      # Pure envelope→canvas-seed mapper (port of gtd build-canvas-seed.py)
├── plan_graph.py       # Pure deterministic plan-graph engine (port of gtd plan_graph.py)
├── canvas_overlay.py   # Pure seed+graph merge (apply_graph) + lean transform (lean_seed)
├── canvas_commit.py    # Pure closed tag-mapping + commit validators (backs gtd_apply_canvas_commit)
├── canvas_create.py    # Pure create-side tags (project/life/finalise) + validators (backs gtd_create_project)
├── gtd_chat.py         # Pure CHAT-note grammar (title/mode-footer/turn/thread parsing) + turn attachments (FILING/LINK parse + correlation; project-scope descendant scan) + drain-signal tags + cross-project inflight roll-up (backs gtd_chat_post/gtd_chat_thread/gtd_chat_inflight)
├── companion.py        # Read-only vault locate (cross-platform) + companion .md/.yaml reader → canvas file.meta
├── tool_params.py      # Shared MCP complex-param coercion + clean-schema Annotated types
├── urls.py             # Web UI URL construction + task hierarchy walking
├── rate_limiter.py     # Token bucket rate limiter + diagnostics stats
├── exceptions.py       # RTMError hierarchy + ERROR_GUIDANCE recovery hints
├── tools/
│   ├── tasks.py        # Task CRUD + metadata + hierarchy (19 tools)
│   ├── lists.py        # List management (7 tools)
│   ├── notes.py        # Note operations (4 tools)
│   ├── utilities.py    # Tags, locations, settings, undo, timeline, diagnostics, URLs (14 tools)
│   └── gtd.py          # GTD domain compositions — gtd_project_plan, gtd_project_canvas, gtd_project_index, gtd_apply_canvas_commit, gtd_create_project, gtd_chat_post, gtd_chat_thread, gtd_chat_inflight, gtd_set_redaction (9 tools)
└── scripts/
    └── setup_auth.py   # Interactive auth setup CLI
```

### Module Responsibilities

| Module | Single Responsibility |
|--------|----------------------|
| `client.py` | HTTP transport: signing, connection pooling, rate limiting, retry, settings caching (timezone + default list) |
| `parsers.py` | Translate RTM's quirky API responses into clean Python dicts |
| `response_builder.py` | Wrap tool output in the standard MCP response envelope |
| `lookup.py` | Resolve human-readable names (task name, list name) to RTM IDs |
| `strict_tags.py` | Strict-tag mode policy: normalize/split tags, extract SmartAdd `#tokens`, and gate tag writes against the account's existing tag set |
| `project_plan.py` | Pure (no IO) reconstruction of the `project-plan-seed/3.1` envelope from parsed tasks — byte-compatible with the gtd plugin's `rtm_fetch.py` reference. Also the home of the `REDACTED_TAG` constant and emits the additive `header.project.redacted` flag + the additive per-note `id` (every envelope note object carries the RTM note id — the ORDER-note resolver tie-breaks on it) + the additive `3.1` repeating-templated-project signals `is_repeating`/`taskseries_id` on every row and `header.project` (True when the task's own parent taskseries recurs — an `rrule`; the gtd `series_guard` detection gate reads them; repeating-templated-project Wave B) |
| `order_note.py` | Pure (no IO) ORDER-note contract (`order-note/1`) — byte-compatible port of the gtd plugin's `order_note.py` (`make`/`parse`/`resolve`/`from_envelope`; the CLI shim is dropped). The ORDER note on the RTM **project task** is the single durable record of manual plan-order intent (DC-4); the body is strict self-verifying JSON (`count` + `sha256` fail closed — an invalid note is IGNORED, never an error), resolution is deterministic latest-valid-wins (`at` desc → note id desc → checksum desc). Writer: `gtd_apply_canvas_commit` (`source: "board-commit"`); readers: `gtd_project_canvas` (the thin plan-graph `manual_order` bias) and gtd's enriched overlay refresh — one grammar, both membrane sides |
| `project_index.py` | Pure (no IO) active-`#project` portfolio roll-up backing `gtd_project_index` — `build_index` (per-project rows: selection (incomplete, `#project`, not `#test`; `#hold`/`#someday` policy), life + parent Area-of-Focus resolution, and counts `open_count`/`blocked_count`/`next_tickle` + AI-progressible tallies `ai_quick`/`ai_now`/`ai_later` (canvas `quick_ready` + `map_prog`) + conversation counts `chat_count`/`chat_review_count` (`#ai_chat` / `#ai_output_review_needed`) + engage-filter count `waiting_count` (`#waiting_for`) via `project_plan.build_envelope` + the thin `plan_graph.build_graph`), `build_foci` (every `#focus` area incl. project-less ones), and `build_actions` (every incomplete child under an active project — with `type` (canvas `r.k`) + `due`/`priority`/`blocked` urgency signal for the What's-hot band and find-result glyphs — for cockpit search). Project rows, action rows, and foci rows all carry the `redacted` viewing-curtain flag (`#redacted`). Vault-free |
| `canvas_seed.py` | Pure mapper: `project-plan-seed/3` envelope → canvas `{mode, frame, seed}` shape — byte-compatible port of the gtd plugin's `build-canvas-seed.py`. `map_redacted` emits the per-item + `frame.redacted` viewing-curtain flag (additive) |
| `plan_graph.py` | Pure deterministic plan-graph engine (DAG, blocked/quick judgement, tiered timeline order with the within-tier MoSCoW band tie-break `Must→Should→Could→untriaged-last` from the RTM priority field, cycles, fingerprint) — byte-compatible port of the gtd plugin's `plan_graph.py` |
| `canvas_overlay.py` | Pure merge of the plan-graph overlay onto the seed (`apply_graph`) + the lean/inline transform (`lean_seed`) — port of the gtd plugin's `build_canvas.py` helpers |
| `canvas_commit.py` | Pure closed canonical classifier→tag mapping + commit validators (`validate_commit`, `collect_commit_tags`) for `gtd_apply_canvas_commit` |
| `canvas_create.py` | Pure create-side helpers for `gtd_create_project`: the project's own tags (`project_tags` — life + `#project` + `#ai_conversation` + the `#ai_project_needs_finalise` mark), `collect_create_tags`, `validate_create`, and `item_id` (in-draft id ↔ dep mapping). Imports the shared classifier→tag taxonomy from `canvas_commit` — no duplicate taxonomy |
| `gtd_chat.py` | Pure (no IO) helpers for the in-board AI conversation surface (the `CHAT` note class) backing `gtd_chat_post`/`gtd_chat_thread`/`gtd_chat_inflight`: the title grammar (`format_chat_title`/`parse_chat_title` — `YYYY-MM-DD HH:MM — CHAT — <role> — <scope>`), the `me`-turn posture **mode** body-footer round-trip (`append_mode_footer`/`parse_body`), `parse_turn`/`build_thread` (oldest-first, non-CHAT excluded, `since` filter), the **turn attachments** (`parse_filings`/`parse_output_note`/`parse_links`/`_attach_filings` — server-derived `files[]` from OUTPUT-note `FILING:` lines time-correlated to `ai` turns + `links[]` from `LINK:` trailer lines; note-shape-catalogue § 3 / chat-reply-style § 2 mirrored server-side; for a `#project` target the scan also covers the descendant tree via `project_descendants`, entries carrying `item_id`/`item_name` provenance), `build_inflight` (the cross-project live-band roll-up — incomplete `#ai_chat` items with status/scope/nearest-`#project`-ancestor/last-activity), `local_stamp` (tz-localised wall-clock), and the account-provisioned status/drain-signal tag constants (`AI_CHAT_REQUESTED`/`AI_CHAT`/`AI_OUTPUT_REVIEW_NEEDED`). gtd owns the canonical grammar; this mirrors it server-side. Vault-free |
| `companion.py` | The vault file-IO seam: locate the read-only AI Memory vault root (cross-platform; `AI_MEMORY_DIR`/host default + `memory/_index.md` marker), resolve each filed artefact's companion (`.md`/`.yaml`) frontmatter, and enrich `gtd_project_canvas` file objects with a `meta` block. Mirrors file-store's `query_outputs.py` by contract (stdlib-only). Graceful: every IO failure → no `meta`, never raises |
| `tool_params.py` | Shared coercion for complex (array/object) MCP params: a `coerce_json` `BeforeValidator` + `Annotated` types presenting a clean single-typed JSON schema (no `anyOf`/null) so clients that stringify union-typed params still interoperate |
| `exceptions.py` | Map RTM error codes to typed exceptions with recovery hints |
| `urls.py` | Build RTM web UI deep-link URLs; walk parent_task_id chain for hierarchy |
| `rate_limiter.py` | Token bucket pacing + rolling-window diagnostics |
| `tools/*.py` | Register MCP tools — thin glue between `client`, `parsers`, and `response_builder` |

## Key Patterns

### Tool Registration

Tools are registered via functions that receive the mcp instance and a client getter:

```python
def register_task_tools(mcp: Any, get_client: Any) -> None:
    @mcp.tool()
    async def list_tasks(ctx: Context, filter: str | None = None) -> dict:
        client: RTMClient = await get_client()
        result = await client.call("rtm.tasks.getList", filter=filter)
        return build_response(data=parse_tasks_response(result))
```

### Response Format

All tools return a consistent envelope:

```python
{
    "data": {...},                    # Main response data
    "analysis": {"insights": [...]},  # Optional insights (e.g. list_tasks)
    "metadata": {
        "fetched_at": "ISO timestamp",
        "transaction_id": "...",       # Write ops only — for undo
        "transaction_undoable": True,  # Write ops only
        "timeline_id": "...",          # Write ops only
    }
}
```

### HTTP Transport

Reads use GET with query parameters. Writes (`require_timeline=True`) use POST with form data — RTM silently ignores some parameters (e.g. `note_title`) on GET.

```python
client = RTMClient(config)
result = await client.call("rtm.tasks.add", require_timeline=True, name="Task")
```

The client provides:
- **MD5 request signing** via `sign_request()` (shared by `RTMClient` and `RTMAuthFlow`)
- **Timeline management** for write operations
- **Token bucket rate limiting** (burst to 3 RPS, sustain ~0.9 RPS)
- **HTTP 503 retry** with escalating backoff (2s → 5s, max 2 retries)
- **Connection retry** for transient errors (timeout, DNS, TCP reset) with configurable backoff
- **Settings caching** via `client._get_settings()` — fetches `rtm.settings.getList`
  once per session; `get_timezone()` and `get_default_list_id()` both read from this
  single cached dict (one API call serves both)
- **Account-tag caching** via `client.get_account_tags()` — normalized (trim + lower)
  set of existing account tags from `rtm.tags.getList`, cached with a short TTL
  (`ACCOUNT_TAGS_TTL_SECONDS`, 5 min); `force_refresh=True` bypasses the cache. Backs
  strict-tag mode's allow-list (see below)
- **Error code mapping** to typed exceptions with recovery hints

### Rate Limiting and Connection Retry

Uses a **token bucket** (`rate_limiter.py`) matching RTM's stated limits:

| Parameter | Default | Env var |
|-----------|---------|---------|
| Bucket capacity | 3 tokens | `RTM_BUCKET_CAPACITY` |
| Safety margin | 10% | `RTM_SAFETY_MARGIN` |
| Refill rate | 0.9 tokens/sec (= 1.0 - margin) | Derived |
| Max 503 retries | 2 | `RTM_MAX_RETRIES` |
| First 503 retry delay | 2s | `RTM_RETRY_DELAY_FIRST` |
| Subsequent 503 retry delay | 5s | `RTM_RETRY_DELAY_SUBSEQUENT` |
| Max connection retries | 3 | `RTM_CONN_MAX_RETRIES` |
| First connection retry delay | 1s | `RTM_CONN_RETRY_DELAY_FIRST` |
| Subsequent connection retry delay | 3s | `RTM_CONN_RETRY_DELAY_SUBSEQUENT` |

**Connection retries** are handled by `_attempt_http()` which wraps the HTTP dispatch:
- `ConnectError` (TCP, DNS) — retried for both reads and writes (connection never established)
- `ConnectTimeout` / `PoolTimeout` — retried for both reads and writes (connect-phase timeouts:
  the request never left the client, so a write cannot have been processed)
- `TimeoutException` on reads — retried (safe to replay)
- `TimeoutException` on writes — **not retried** (request may have been processed, risking duplication)
- Mid-flight `TransportError` (`ReadError`, `RemoteProtocolError` — e.g. a TCP reset during the
  response) — retried on reads; on writes raised immediately as `RTMNetworkError` (ambiguous,
  same rationale as the write timeout). Nothing transport-shaped escapes as a raw httpx
  exception; a non-JSON 200 body also raises `RTMNetworkError`.
- TLS certificate errors — never retried
- Connection retries do **not** consume additional rate limit tokens

Request classification uses `require_timeline` as a proxy: `True` = write, `False` = read. This correlates 100% with actual read/write status across all tools. `RateLimitStats` tracks the split (`reads_session` / `writes_session`, surfaced by `get_rate_limit_status`).

**Once-per-session fetches are lock-guarded:** `get_timeline()` and `_get_settings()` use
`asyncio.Lock` double-checks, so concurrent first writes share one timeline (undo depends on the
transaction log matching the timeline the writes executed under). A failed settings fetch is
**not** cached — the next consumer retries, so one transient blip can't disable timezone
localisation for the whole session (`get_account_tags` already re-fetches after its TTL).

### Error Handling

Two layers of error handling:

**RTM API errors** — `raise_for_error()` in `exceptions.py` maps RTM error codes to exception classes (`RTMAuthError`, `RTMValidationError`, `RTMNotFoundError`, etc.) and appends recovery guidance from `ERROR_GUIDANCE`:

```python
# exceptions.py
ERROR_GUIDANCE: dict[int, str] = {
    98: "Re-run rtm-setup to get a fresh auth token.",
    340: "Call get_lists to see available list names.",
    341: "Call list_tasks to find the correct task name or IDs.",
    4040: "Subtask features require an RTM Pro account.",
    # ... 18 codes total
}

def raise_for_error(code: int, message: str) -> None:
    error_class = ERROR_CODE_MAP.get(code, RTMError)
    guidance = ERROR_GUIDANCE.get(code)
    full_message = f"{message} — {guidance}" if guidance else message
    raise error_class(full_message, code)
```

**Application-level errors** — `resolve_task_ids` and `resolve_list_id` (in `lookup.py`) and tool functions return actionable error messages via `build_response(data={"error": ...})` that guide agents to the correct next step:

```python
{"error": "Task not found: 'Buy milk'. Use list_tasks to search by filter or check spelling."}
{"error": "Provide either task_name (for search) or all three: task_id, taskseries_id, and list_id. Get these from list_tasks."}
{"error": "List 'Projects' not found. Use get_lists to see available list names."}
```

### Task and List Identification

RTM uses three IDs for task operations:
- `list_id`: Which list the task is in
- `taskseries_id`: The task series (for recurring tasks)
- `task_id`: The specific task instance

Tools accept either `task_name` (fuzzy search) or all three IDs. **Fuzzy matching** (`lookup.py:find_task`) searches incomplete tasks, preferring exact matches over substrings and more recently modified tasks over stale ones. All tool docstrings include a caution that fuzzy matching may hit unintended tasks.

List tools accept `list_name` which is resolved to `list_id` via `lookup.py:resolve_list_id`.

### Subtask Hierarchy

RTM supports parent/child task relationships (Pro required, max 3 levels):

- **`parent_task_id`** is extracted from the `taskseries` element (not `task`) and appears as empty string for top-level tasks — the parser normalises this to `None`
- Subtasks are sibling taskseries entries under the same list, NOT nested inside their parent
- **`subtask_count`** is computed client-side from the current result set via `_apply_subtask_counts()` — it does not make a secondary API call
- `list_tasks` accepts a `parent_task_id` parameter: it injects `isSubtask:true` into the server-side filter, then applies client-side filtering by parent ID
- `add_task` accepts `parent_task_id` to create a task as a subtask
- `set_parent_task` reparents a task or promotes it to top-level (pass empty `parent_task_id`)
- If the parent is in a different list, the task is **implicitly moved** to that list
- Repeating tasks cannot be parents or children of other repeating tasks
- `isSubtask:true` is an **undocumented** RTM filter — client-side filtering by `parent_task_id` is the reliable fallback
- RTM error codes: 4040 = Pro required, 4050 = invalid parent, 4060 = max nesting exceeded, 4070 = repeating task conflict, 4080 = due date before start date, 4090 = self-parenting

### Strict-Tag Mode (existence gate)

A control (`config.strict_tags`, env `RTM_STRICT_TAGS`, **on by default**; set
`RTM_STRICT_TAGS=0` to disable) that refuses any tag write which would introduce a tag not
already present in the RTM account. RTM auto-creates a tag on first use, so this is the
chokepoint that stops accidental tag minting via the MCP.

**Design — deliberately decoupled.** The runtime allow-list is simply the account's
current tag set (`client.get_account_tags()`), read live from RTM. The server has **no
knowledge of any canonical taxonomy and needs no sync** — "is this an *allowed* tag?"
(canonical policing) stays plugin-side; the server only enforces "does this tag *exist*?".

**Components:**
- `strict_tags.py` — pure policy: `normalize_tag` (trim + lower), `split_tags`
  (comma-split → normalized, de-duped), `extract_smartadd_tags` (regex `#tokens` from a
  SmartAdd name), `guided_error` (the self-documenting rejection), and
  `enforce_strict_tags(client, requested, *, tool)` → returns a guided-error dict to
  reject or `None` to allow.
- `client.get_account_tags()` — the TTL-cached, normalized allow-list (see HTTP Transport).

**`enforce_strict_tags` flow:**
1. `if not client.config.strict_tags: return None` — zero-cost when off (no API call).
2. Normalize (trim + lower) and drop empties; no tags → allow (defensive: the allow-list is normalized, so the comparison is like-for-like even for an un-normalized caller).
3. Compare requested against `get_account_tags()`. On a miss, **re-fetch live**
   (`force_refresh=True`) and recompare — cache-miss safety so a tag created moments ago
   out-of-band isn't falsely rejected.
4. Still offending → `logger.info(...)` and return `guided_error(offending)`; else allow.

**Wiring (`tools/tasks.py`):** `add_task` (when `parse=True`, on `extract_smartadd_tags(name)`),
`add_task_tags` and `set_task_tags` (on `split_tags(tags)` — for `setTags` the resulting set
*is* the passed tags). `remove_task_tags` is **never** gated (removal reduces entropy).

**Caveats:**
- `extract_smartadd_tags` is a documented best-effort approximation of RTM's SmartAdd tag
  tokenizer. Over-matching a stray `#word` is intentional (it's the accidental-minting case);
  the guided error tells the caller to re-issue with `parse=False` or fix the name.
- **Testing gotcha:** the `mock_client` is an `AsyncMock`, so `client.config.strict_tags`
  is a *truthy Mock* unless set — the `test_task_tools.py` fixture sets
  `client.config = MagicMock(strict_tags=False)` so tag-write tests behave as today; strict
  tests flip it True and stub `client.get_account_tags`.

### GTD domain tools & the `gtd_project_plan` envelope

`gtd_project_plan` (`tools/gtd.py`) is the server's first **domain-composition** tool — it
speaks a consuming domain's language (a GTD "project plan") rather than mapping 1:1 to an RTM
method. **Naming convention:** generic RTM primitives stay bare verbs (`add_task`,
`list_tasks`); domain compositions carry a `<domain>_` prefix (`gtd_<concept-noun>`), so the
tool list self-documents the split and a future lift of all `gtd_*` tools into a separate
server is mechanical. Document new domain tools the same way.

**Read-only:** the tool issues one `rtm.tasks.getList`
(`filter="status:incomplete OR status:completed"`, optionally `list_id`-scoped) — no timeline,
no writes (a test asserts the tool makes no extra direct calls) — then resolves the project and
reconstructs the tree in memory. It also calls `client.get_timezone()` (a **session-cached**
`rtm.settings.getList`, shared with every other tz/default-list consumer) so the envelope's date
fields are localised to the account timezone before truncation (see the tz fix below).

**`project_plan.py` (pure) is byte-compatible with the gtd plugin's `rtm_fetch.py`** reference
(`reconstruct`/`to_ndjson`), the frozen `project-plan-seed/3` contract the canvas mapper
consumes — **except** the tz date-localisation below, a deliberate correctness divergence.
Originally verified by feeding one live `getList` response to both pipelines → identical
envelope. Server-port adaptations (the first three preserve output; the last fixes a bug):
- note bodies via `parsers.extract_note_body` (server notes carry the body in `$t`, not `body`);
- `name`/`estimate`/`url` coerced to `""` (server parsing yields `None` for empties);
- permalinks reuse `urls.build_task_url` with an **id-based** ancestor chain (`_ancestor_chain`)
  that includes an ancestor even when its row isn't in the fetched set — NOT
  `urls.walk_parent_chain`, which truncates at a missing parent and would drop the top segment.
- **tz localisation (date off-by-one fix):** RTM returns timestamps in **UTC** — a London-BST
  date-only due of 22 Jun arrives on the wire as `2026-06-21T23:00:00Z`, so a raw `[:10]`
  truncation rolls every BST/DST date back a day (Paul hit this live: a 22 Jun tickle showed
  21 Jun). `_norm_date(iso, timezone)` now converts to the account zone (via
  `parsers._convert_rtm_date`) **before** truncating, applied to every date field
  (`due`/`start`/`completedDate` + note dates). The gtd read tools pass `client.get_timezone()`;
  with no tz (settings read failed) it falls back to the raw `[:10]` (never raises). This
  **diverges** from the raw-UTC reference `rtm_fetch.py` for BST/DST dates — the reference was
  itself emitting the wrong local day; upstream parity (localising there too) is a follow-up.

### Canvas tools (`gtd_project_canvas` / `gtd_apply_canvas_commit`)

The project-plan **canvas** (a live artifact in the gtd plugin) reads and writes RTM through two
`gtd_` domain tools — the read-sibling and write-counterpart of `gtd_project_plan`.

**`gtd_project_canvas` (read-only)** returns the *rendered-shape* seed the canvas template
consumes directly, so the page never re-implements GTD ordering/blocking. It runs the same single
read-only `rtm.tasks.getList` as `gtd_project_plan`, then composes three **pure, byte-compatible
ports** of the gtd plugin's scripts:
- `canvas_seed.build_seed` ← `build-canvas-seed.py` — envelope → `{mode, frame, seed}`. Each row
  also carries an optional `prog` ("now" from `#ai_progress_requested` / "later" from
  `#ai_progress_deferred`; omitted when neither, "now" wins if both) via `canvas_seed.map_prog` —
  the read-side mirror of the commit's execute write, so the canvas pill reflects committed state
  on reload. Server-emitted field, additive to the reference (upstream parity is a follow-up).
- `plan_graph.build_graph` ← `plan_graph.py` — the deterministic DAG/judgement/order overlay
  (mechanical-only: no vault, so `outputs_index=None` — edges come from active DEPENDS-ON notes
  alone). Since DC-4, `manual_order` is the **latest valid ORDER note** on the project
  (`order_note.from_envelope` over the envelope's `header.project.notes` — vault-free, same
  one-call read), so the board seed shows the dragged order immediately on reload. Clamping
  semantics are identical to gtd's enriched engine (the parity-pinned `_timeline_order`): the pin
  biases cosmetic tiering only, never topology — a consumer never sorts before its producer;
  unlisted ids fall to the end of their ready cohort; ids not in the plan are pruned. An invalid
  note fails closed (resolution falls back to the next-latest valid; none → no bias).
- `canvas_overlay.apply_graph` / `lean_seed` ← `build_canvas.py` helpers — merge + inline profile.

  The merge stamps **only** `quick` (when `quick_ready`) and sibling `deps` (sorted) and reorders
  `seed[]` by the timeline order. It does **NOT** add a `blocked` or integer `order` field — the
  canvas template derives `blocked` from `deps[]`. (`lean=True`, the default, drops note bodies
  and caps notes per item with an honest `nc` — byte-compatible with `build_canvas --emit
  html-lean`.) Read-only invariant: only `rtm.tasks.getList`; no timeline, no writes.

  **Companion metadata (`file.meta`) + `frame.files`.** After the overlay/lean pass, `companion.py`
  enriches every file object — per-action `seed[*].files[]` **and** project-level `frame.files` —
  with a `meta` block: the artefact's companion (`.md`/`.yaml`) frontmatter (title/type/status/
  dates/authors/tags/decision/…), read from the **read-only AI Memory vault**. `meta` is a full
  pass-through of present top-level fields — **never** vocabulary-validated (real `type` values like
  `form-prefilled` pass through verbatim). Backward-compatible: `n/ext/kind/path` are unchanged;
  `meta` is added only where a companion exists, omitted otherwise. The reader mirrors file-store's
  `query_outputs.py` by contract, extended to resolve multiple companion forms (`X.meta.md` →
  `X.md` (non-md) → `X.companion.md` → `.companion/X.yaml` → `X.metadata.yaml`) and to read list
  fields (`authors`/`tags`) the reference parser skips. `frame.files` is the project-level
  support-material roll-up: filed paths scraped from the **project's own** notes
  (`project_plan.build_envelope` now also emits `header.project.files`, additive to the
  `project-plan-seed/3` envelope — `rtm_fetch.py` parity is an upstream follow-up), mapped via
  `parse_file` in the `outputs_index is None` branch.

  **Vault resolution (`companion.resolve_vault_root`)** mirrors the agent-memory plugins,
  cross-platform via `pathlib` (macOS + Windows, no OS branching): explicit override
  `config.vault_root` (env `RTM_VAULT_ROOT`, preferred, or the shared `AI_MEMORY_DIR`) → Cowork
  sandbox mount (`/sessions/*/mnt/AI Memory`) → host default `~/Documents/AI Memory`; each
  validated by the `memory/_index.md` marker. An explicit-but-invalid override does **not**
  fall through (honest no-op). Unset/absent vault ⇒ no `meta`, no error — the read-only invariant
  holds (companion reads are filesystem-only; still only `rtm.tasks.getList` hits the API).

**`gtd_apply_canvas_commit` (constrained write)** is the single governed write surface for a
canvas commit — safe by construction (artifacts call connectors without prompting). It runs
**validate-then-apply**:
- *Validate (no writes):* one read of the project tree → `plan_ids`; resolve the `Processed`
  list (must exist and be non-smart); `canvas_commit.validate_commit` collects rejections
  (cross-project id, unconfirmed `completes`/`removes`, unknown add type, invalid execute value,
  smart-list target); a single `enforce_strict_tags` existence-gate pass over
  `collect_commit_tags(ops)`. Any rejection → return with **nothing written**.
- *Apply (durable-first):* `adds` (create on `Processed` → tags → priority → due → reparent
  last), `edits`, `execute` (a **durable now/later split**: `now`/`quick` write
  `#ai_progress_requested`; `later` writes `#ai_progress_deferred` — the two are mutually
  exclusive, so switching state drops the stale sibling via `removeTags` so an item never carries
  both; `#ai_deferred_pending_unblock` is still added when the item is blocked — it does **not**
  execute AI work), `notes`, then `completes` / `removes` (RTM soft-delete), then — when the commit
  carries a non-empty `order` — the **ORDER note** (DC-4, see below), then a `COMMIT` audit
  note on the project, and finally — on **any** non-empty commit — the **overlay-refresh mark**
  `#ai_overlay_refresh_needed` (`addTags`) is stamped on the project (Piece 0b; inside `if applied:`,
  so a zero-apply commit stamps nothing — an order-only commit IS non-empty since the note landed).
  Each write records its transaction (so `batch_undo`
  works); per-op failures are captured and the batch continues. (`#ai_progress_deferred` is a **new**
  tag — under strict-tag mode a `later` commit is rejected with a guided error until it's provisioned
  in RTM; the gate requires it only when a `later` is actually present, so `now`/`quick` commits stay
  backward-compatible. `gtd_project_canvas` mirrors this on read via `canvas_seed.map_prog` → the
  per-row `prog` field.)
- *ORDER note (DC-4 — durable reorder):* RTM has no sibling-order field, so a board drag is
  persisted as an **ORDER note on the project task** (`order_note.make` — title
  `YYYY-MM-DD HH:MM — ORDER — <n> items` in the account wall-clock, body one strict JSON object
  `{schema: "order-note/1", order, count, sha256, source: "board-commit", at}`); every consumer
  derives order from the **latest valid** note (this server's thin plan-graph on canvas read;
  gtd's enriched `plan_graph_refresh` from the same envelope notes), making RTM the single source
  of truth for order intent. Append-only: superseded notes are retained (latest-valid-wins makes
  pruning unnecessary); the note write is transaction-recorded like every other op, so
  `batch_undo` reverts it with the commit. Write ordering: the ORDER note lands **before** the
  overlay-refresh stamp, so a finalise fired off the mark can never read a commit whose note
  hasn't landed. The return flips `order_persisted` from `false` to the string `"order-note"`
  (naming the mechanism, deliberately not `true` — the board gates its optimistic "order saved"
  chip on exactly this value; an old board ignores it, a new board on an old server sees `false`
  and stays silent). No new tag — a note write, not a tag write; the strict-tag gate is untouched
  (though `collect_commit_tags` now counts `order` as an actionable op for the overlay-refresh
  mark, since an order-only commit stamps it).
- *Overlay-refresh mark (Piece 0b):* the enriched plan-graph overlay (the persisted AI-Memory DAG,
  written gtd-side by `plan_graph_refresh.py`) goes stale after a commit that carries no `execute`
  (a pure edit / reorder / note / complete / remove), because the progression engine drains the
  `#ai_progress_requested` work-list and stops on an empty list without refreshing. So every
  non-empty commit stamps `#ai_overlay_refresh_needed` (`collect_commit_tags` includes it in the
  up-front gate); the gtd-side `gtd-project-finalise` engine drains it (recompute + persist the
  overlay, then `removeTags`). The commit-path twin of `canvas_create.FINALISE_MARK` — same
  blackboard pattern, server stays vault-free. It is a **new** tag: under strict-tag mode it must be
  provisioned in RTM **before this server version is activated**, else the gate rejects every
  non-empty commit. (Only the *enriched* tier is affected — the thin graph is always recomputed
  server-side on read.)
- *Discipline:* tag writes use a **closed canonical classifier→tag mapping** (`canvas_commit`) +
  the strict-tag existence gate — the server holds no taxonomy (see Strict-Tag Mode). `order` ids
  are membership-checked like every other op and persisted via the ORDER note (the v1 no-op was
  retired by DC-4). Created/edited items carry `#ai_conversation`.
- *Complex-param contract:* the ops params (`order`/`edits`/`adds`/`completes`/`removes`/`execute`/
  `notes`) use the `tool_params` `Annotated` types — a **clean single-typed JSON schema** (no
  `anyOf`/null union, which some MCP clients serialise as a JSON string) plus a `coerce_json`
  `BeforeValidator`, with an in-body `coerce_json` belt-and-braces for callers that bypass
  pydantic. So the tool accepts both structured JSON and a JSON-string for any op.

**`gtd_create_project` (constrained write)** is the **create-sibling** of the commit tool: where
commit edits an existing project, create builds a brand-new one from a canvas draft. Same
validate-then-apply discipline, reusing the commit's tag taxonomy (`classifiers_to_tags`,
`execute_progress_tags`), strict-tag gate, `#ai_conversation` stamp, per-write transaction
recording (so `batch_undo` works), and batch-resilient `_write` helper. Payload: `frame`
(`{life, focus, name, outcome}`) + `items[]` + project-level `notes[]`.
- *Resolve + validate (no writes):* one read (`status:incomplete`) → `project_plan.resolve_focus`
  maps `frame.focus` to the destination **Area of Focus** (areas carry no marker tag — they are the
  parents of `#project` tasks; an explicit area id is also accepted; ambiguous name →
  `{candidates}`, miss → actionable `{error}`, **never create loose**). Then
  `canvas_create.validate_create` (missing_name, invalid_life, unknown_add_type, invalid_execute,
  unknown_dep) + one `enforce_strict_tags` pass over `collect_create_tags`. Any rejection → return
  with **nothing written**.
- *Order:* a **thin deterministic graph** — `build_graph` over synthesised rows carrying the items'
  in-draft `deps` — gives the dependency-respecting creation order and the per-item `blocked`
  judgement (used for the execute path). No vault access.
- *Apply (durable-first):* the project task is created **directly under the area** (`rtm.tasks.add`
  with `parent_task_id`, inheriting the area's list — **no `Processed` staging/reparent**, since
  create then attaches notes to the new tasks and a reparent would invalidate the add-response
  `list_id`) → `project_tags` (life + `#project` + `#ai_conversation` + the `#ai_project_needs_finalise`
  mark). Each child is created under the project (in graph order) → tags → priority → due → start →
  estimate. Then a second pass writes the **`DEPENDS-ON` notes** mapping each in-draft producer id to
  its created RTM id (the exact body `project_plan._extract_deps_and_files` round-trips, so the
  canvas shows the dependency graph on first reload), `execute` progression tags (mirroring commit;
  blocked items also get `#ai_deferred_pending_unblock`), per-item notes, create-then-complete for
  `done` items, project-level notes, and an `INCEPTION` audit note (with the outcome + counts).
- *The finalise mark:* `#ai_project_needs_finalise` is stamped on **every** created project — the
  durable signal the gtd-side discipline tail (vault folder / `context.md` / progression fan-out)
  drains. It is a **new** tag: under strict-tag mode it must be provisioned in RTM or every create
  is rejected up-front by the existence gate (unlike `later`'s `#ai_progress_deferred`, which is
  gated only when present, the finalise mark is unconditional). The progression **fan-out** itself
  is gtd-side; the server only writes the durable execute tags + the finalise mark.
- *Complex-param contract:* `frame`/`items`/`notes` use the same `tool_params` `Annotated` types +
  in-body `coerce_json` as the commit tool, so each accepts structured JSON or a JSON-string.

### Portfolio index (`gtd_project_index`)

`gtd_project_index` (`tools/gtd.py`, backed by the pure `project_index.py`) is the **read-only
portfolio roll-up** that powers the project-plan-canvas **navigator** (the Phase C cockpit picker) —
the third gtd read tool alongside `gtd_project_plan` / `gtd_project_canvas`. It answers "what's the
whole active-project landscape, and where does each project stand?" in ONE read.

**Read-only, one `getList`.** The tool issues a single `rtm.tasks.getList(filter="status:incomplete")`
(plus the session-cached `get_timezone`) — no timeline, no write — then hands the parsed tasks to the
three pure builders. That comprehensive read (the same posture as `gtd_project_plan`) carries every
project, every `#focus` area, AND every child in one response, so all three collections — and the
per-project counts — need no N+1 fan-out.

**Response shape `{projects, foci, actions}` (since v1.10.0).** The tool returns an object, not a bare
list. It is **backward-compatible** for the shipped navigator, which reads `data.projects` (the old
bare list became the `projects` key); the updated navigator additionally reads `foci` to render empty
focus areas and `actions` for fast search / jump-to. The three builders share one lifecycle gate
(`_active`: not completed, not `#test`, `#hold` always excluded, `#someday` opt-in) layered with the
membership tag (`#project` / `#focus`):
- `build_foci` — every active Area of Focus (incomplete `#focus`, same gate) as `{focus_id, focus,
  life}`, sorted `life → focus`. Sourced from the `#focus` tag directly so a focus with **zero active
  projects** still appears (the per-project `projects` rows can never surface one) — the gap that
  motivated the change (Paul noticed empty foci like a line-management area missing from the cockpit).
- `build_actions` — every incomplete child under an active project (actions + waiting-fors + calendar
  entries, all jumpable; an individual child tagged `#test` is skipped) as `{action_id, name,
  project_id, project, focus, life, type, due, priority, blocked}`, sorted `life → focus → project →
  name`. Reuses `project_plan.build_envelope` for each active project's rows, so attribution matches
  the canvas; every row carries a real project (no dangling-project rows; a top-level project's
  actions inherit `focus="(unfiled)"`). The kind + urgency fields come from work already done:
  `type` is the canvas's own `r.k` classification (`canvas_seed.map_kind` → `"action"|"waiting_for"|
  "calendar"`, since v1.12.0, for the find-result glyph); `due` the row's localised own date (`""`
  when none); `priority` the `"1"|"2"|"3"|""` encoding shared with the project rows; and `blocked`
  the per-row judgement of the **same thin `plan_graph.build_graph`** that feeds each project's
  `blocked_count` (so they agree by construction — an open `DEPENDS-ON` upstream within the project's
  own rows). `due`/`priority`/`blocked` shipped v1.11.0; `type` added v1.12.0.

**`build_index` (pure).** For each project — incomplete, `#project`, **not** `#test`; `#hold` always
excluded and `#someday` excluded unless `include_someday=True` — it reuses the **parity-pinned**
engines so the navigator's numbers match the canvas exactly: `project_plan.build_envelope` (children +
localised dates + active `DEPENDS-ON` `deps`) and the **thin** `plan_graph.build_graph` (the blocked
judgement). It emits one row per project: `{life, focus, focus_id, project, project_id, priority,
open_count, blocked_count, next_tickle, updated, ai_quick, ai_now, ai_later}`, sorted
`life → focus → project`. Decisions:
- `open_count` = **all** incomplete children (actions + waiting-fors + calendar entries — the read
  only fetches incomplete, so it's `len(rows)`); `blocked_count` = children the thin graph judges
  `blocked` (an open `DEPENDS-ON` upstream **within the project's own rows** — cross-project /
  completed upstreams don't count, consistent with `gtd_project_canvas`).
- `next_tickle` = the earliest open `due` across the project's rows **including overdue** (`""` when
  none) — no clock dependency, so the builder stays deterministic.
- `ai_quick`/`ai_now`/`ai_later` (since v1.13.0) = the navigator's AI-progressible sort lens, tallied
  off the **same** classification the canvas uses so the index and an open plan can't disagree:
  `ai_quick` = rows the thin graph judges `quick_ready` (the canvas's `r.quick` — unblocked 2-minute
  `#quick_win` actions, stamped by `canvas_overlay.apply_graph`); `ai_now`/`ai_later` = rows whose
  `canvas_seed.map_prog(tags)` is `"now"`/`"later"` (the `#ai_progress_requested` / `#ai_progress_deferred`
  signal, the canvas's `r.prog`). `now` excludes blocked defensively; `later` may be blocked
  (queued-until-unblocked). Always present (`0` when none).
- `chat_count`/`chat_review_count` (since v1.16.0) = the per-project conversation counts for the
  navigator's conversation chip + "Conversations" sort lens — a standing count the artifact can't
  derive for a **non-open** project (it only loads the open project's rows). `chat_count` = incomplete
  items tagged `#ai_chat` (a conversation is underway); `chat_review_count` = incomplete items tagged
  `#ai_output_review_needed` (AI replied — Paul's turn). Review is a **subset** signal counted
  independently (the chip shows the total, tints amber when review > 0); the project task itself counts
  when it carries the tag (a project-scoped conversation). Incomplete-only (guarded on the row's
  `completed`, so a completed `#ai_chat` item never counts). Always present (`0` when none). Twin of
  the live-band `gtd_chat_inflight`: that is the real-time cross-project fleet, this is the standing
  per-project count in the index.
- `waiting_count` (since v1.18.0) = the engage-filter roll-up for the navigator's **Focus pill** —
  incomplete `#waiting_for` items in the project (the canvas's `r.k` `"waiting_for"` classification via
  `canvas_seed.map_kind`, so it matches the board glyph), unlocking the pill's deferred "waiting-for"
  segment. Same row set + completed-guard as the counts above; always present (`0` when none). Its
  sibling **`decision_count`** (the pill's "decisions" segment) is **not yet emitted** — the gtd tag
  taxonomy has no per-item "needs-you decision" marker (decisions live in the separate `AI_Questions`
  list, not as a `#decision`-tagged plan item), so the tag/rule is an open question for the gtd side
  (see the v1.18.0 handback debrief). The board reserves the segment slot and lights it up on a later
  additive bump with no board change.
- `focus`/`focus_id` come from the project's **parent** Area-of-Focus task; a top-level project is
  kept as `focus="(unfiled)"`, `focus_id=""` (never dropped). `priority` is the project's raw RTM
  priority coerced to `"1"|"2"|"3"|""`; dates are localised to the account tz (the BST off-by-one
  fix, via `project_plan._norm_date`).

**Vault-free (the membrane).** Counts derive only from the server's thin plan-graph — the enriched
AI-Memory overlay stays gtd-side, exactly as for the canvas/commit tools. Purely additive and
read-only: **no new tag, no strict-tag-gate interaction**, so no activation-ordering hazard.

### Conversation surface (`gtd_chat_post` / `gtd_chat_thread`)

The project-plan-canvas's **in-board AI conversation surface** — at the project level and on each
plan item Paul types an instruction (discuss / progress / query); a `runScheduledTask`-spawned
**headless worker** session acts on it and replies. The board's JS can call connector MCP tools but
not desktop-internal ones, so the board and worker converse through **RTM notes** (the system of
record), not a live session. The conversation is a new journalled note class, **`CHAT`**, attached
to the target task. These two `gtd_` tools are the efficient post + poll path; the full thread also
flows unchanged through `gtd_project_canvas` / `gtd_project_plan` as ordinary notes.

**The CHAT grammar (gtd owns the canonical definition; `gtd_chat.py` mirrors it server-side).** One
turn = one RTM note on the target task, title `YYYY-MM-DD HH:MM — CHAT — <role> — <scope>`
(space-em-dash-space separators; timestamp localised to the account tz). `<role>` ∈ `me` (Paul) |
`ai` (worker reply); `<scope>` is a display label (the attachment task is the real scope). Body =
the message; a `me` turn's posture `mode` (`discuss`|`act`) is a trailing `Mode: <mode>` footer line
that round-trips on read. **The title is the FIRST LINE of the note body, not a separate field** —
the RTM API has no note-title field, so the write stores `title\nmessage` in the single body field and
`rtm.tasks.getList` returns an empty `title`. A note is a CHAT turn iff its **body's first line**
matches `^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — CHAT — (me|ai) — ` (line 1 = title, lines 2..N = message);
`parse_turn` splits the body on the first newline accordingly — robust to notes authored by either
tool (the worker may use `add_note` directly with the same grammar). (Parsing the always-empty
`title` field instead was the v1.14.1 bug that returned an empty thread.)

**`gtd_chat_post` (governed write).** Validate-then-apply, nothing written on rejection. It
validates `role`/`mode`, resolves the task by id from **one** `rtm.tasks.getList` (`status:incomplete`
— chat lives on active work; `taskseries_id`/`list_id` resolved internally so the caller passes only
the id it has), then — for a `me` turn — runs the strict-tag existence gate over the two drain-signal
tags before any write. It writes the CHAT note, then manages the signal: `me` → `addTags`
`#ai_chat_requested` (the worker's durable work-list signal) + `#ai_chat` (has-a-thread marker); `ai`
→ `removeTags` `#ai_chat_requested` (the turn is answered), leaving `#ai_chat`. Each write records
its transaction (undoable via `batch_undo`); the helper is batch-resilient (per-op failures captured
in `errors`). The two tags are a **new** pair — under strict-tag mode they must be provisioned in RTM
account-side **before** activation, exactly as `#ai_overlay_refresh_needed` was for Piece 0b (the gate
requires `#ai_chat_requested`/`#ai_chat` only on the `me`-turn add path; the `ai` removal is never
gated). Tag removal reduces entropy, so it is never gated (CONTRIBUTING.md § 6).

**`gtd_chat_thread` (read).** The cheap poll path vs re-reading the whole canvas: **one**
`rtm.tasks.getList`, no write, no timeline, **no settings read** (so the read-only call surface is
exactly `["rtm.tasks.getList"]`). Since v1.16.1 the resolve read spans **`status:incomplete OR
status:completed`** — a prior conversation stays viewable after the task is done (CHAT notes persist),
so the board can offer "view prior thread" on a completed item without falling back to a misleading
empty state. It resolves the task by id, parses its CHAT notes into turns oldest-first (`build_thread`
— non-CHAT notes excluded, optional `since` ISO-8601 incremental filter), and reports `requested` =
whether `#ai_chat_requested` is currently set (so the board shows a "thinking…" state without a second
call) — naturally `False` for a completed task (no pending worker), so its history renders read-only.
Per-turn `created` is RTM's value (UTC, not re-localised — the localised display stamp lives in the
note title the canvas already renders). **Posting still requires an incomplete task**: `gtd_chat_post`
stays `status:incomplete`-only (the worker only drains `#ai_chat_requested` on incomplete items), and
on a miss does a second `status:completed` lookup so a completed target gets a clear "conversation is
read-only — reopen to continue" error instead of the generic not-found.

**Turn attachments (`files[]` / `links[]`, since v1.19.0; project-scope descendant scan since v1.20.0 — board-chat enrichment stages 2/2b).** Every
turn additionally carries server-derived attachments, **always present** (`[]` when none —
zero-not-absent, matching the index counts). `files` = `[{path, label, note_id}]`: the authoritative
record of a filed artefact is the **OUTPUT note's `FILING:` line on the same task**
(note-shape-catalogue § 3 — both the single-line `FILING: <vault-relative path> (+ .meta.md)` form
and the labelled continuation, where the FILING line ends with a dash and the path sits on the next
line). The selector is the note's **title type** (the body's first line, like CHAT): only
OUTPUT-typed notes are scanned — historic `FILING`-typed notes predate the convention and must not
match. The path passes through **verbatim** (companion marker stripped); an absolute or backslashed
path is malformed and skipped, never "repaired" (the gtd notes-audit owns flagging those). The
verbatim path is the client's **dedup guarantee**: it compares equal to a `FILED:` trailer echo in
the turn text, so the board prefers `files[]` and suppresses its own `FILED:` parse when the key is
present. *Time-correlation is conservative* (designed change § 2.8): an OUTPUT note attaches to the
**earliest `ai` turn created at-or-after it** — the worker files first, then writes the reply, so
the filing falls in the window `(previous ai turn, this ai turn]`; an OUTPUT note after the last
`ai` turn (or with no `created`) attaches to **nothing** (unattached is correct, never guess).
*Scope* (stage 2b, since v1.20.0): for an **item** target the scan covers the task's own notes only
(the v1 shape, byte-identical — no extra fields); for a **`#project`** target it additionally covers
the project's **descendant tasks** (`gtd_chat.project_descendants` — the same ≤3-level
`parent_task_id` tree `gtd_project_plan` walks, breadth-first; deleted excluded, **completed
included** — a completed action's filed output is still a project output), because a project's
artefacts are filed against its child actions. Each descendant-filed entry carries two extra
provenance fields `item_id`/`item_name` (the descendant that filed it; an OUTPUT note on the project
task itself keeps the plain three-field shape). The gate is the `#project` tag, not subtask
presence, and the same one-call read serves it — the broad `getList` already carries the children,
so the call surface stays exactly `["rtm.tasks.getList"]`. Correlation runs
over the **full** thread before the `since` filter, so incremental polls see the same attachments.
`label` = the OUTPUT note's title summary; `note_id` = the OUTPUT note (provenance). Only `ai` turns
carry files. `links` = `[{url, label}]`: `LINK: <url> — <label>` trailer lines parsed from the
turn's own text (line-anchored, uppercase keyword; em/en-dash or spaced-hyphen separator — the same
split the board's `chatParseTrailer` uses; no separator → label `""`). The trailer lines are left
**in** `text` — the board strips them client-side, and removing them server-side would break the
stage-1 fallback contract on older boards.

**`gtd_chat_inflight` (read, since v1.15.0).** The conversation cockpit's **cross-project live band**
(the F3 horizon): every incomplete item carrying an open CHAT thread (`#ai_chat`), across all
lists/projects, in ONE read — the "all my agents working right now" view the per-project canvas can't
produce. Same read posture as `gtd_chat_thread`: **one** `rtm.tasks.getList(status:incomplete)`, no
write/timeline/settings (call surface exactly `["rtm.tasks.getList"]`). The **broad** incomplete read
(not a `tag:ai_chat`-filtered one) is deliberate — each item's enclosing project is resolved by
walking `parent_task_id` (`project_plan._ancestor_chain`) to the nearest `#project`, and those
ancestor project tasks don't carry `#ai_chat`, so they must be in the result set. `build_inflight`
(pure) selects incomplete `#ai_chat` non-`#test` tasks and emits `{task_id, name, scope
("item"|"project"), status, project_id, project_name, last_activity}` per item, sorted status →
recency → name: `status` from tags (`#ai_chat_requested` → `in_flight`; else
`#ai_output_review_needed` → `awaiting_review`; else `open`), `scope` from `#project`, `last_activity`
= the most-recent CHAT note's `created` via the same `build_thread` (`""` when none). A loose item
with no `#project` ancestor keeps `project_id=""` (chip shows; can't load).

**Membrane / activation.** Vault-free — no AI-Memory awareness, pure RTM. The server introduces **no
new tag itself** (it *reads/sets* `#ai_chat_requested` / `#ai_chat`, and *reads* the account-
provisioned `#ai_output_review_needed`), so no activation-ordering hazard beyond provisioning those
tags + restarting the server on v1.14.0 (`gtd_chat_post`/`gtd_chat_thread`) / v1.15.0
(`gtd_chat_inflight`) so the tools are exposed. The gtd-side consumers (the
`project-plan-artifact.html` compose row + the F3 live band + the `gtd-chat-agent` scheduled task)
ship in parallel and hide entirely when a tool is absent/errors, so the board behaves exactly as
before until the server is on the matching version.

### Redaction surface (`redacted` read flag + `gtd_set_redaction`, since v1.17.0)

The project-plan-canvas's **viewing curtain**: a project or item tagged `#redacted` renders as a
locked placeholder (privacy for casual over-the-shoulder viewing). The sandboxed board may call only
`gtd_*` tools — not `list_tasks` / `add_task_tags` / `remove_task_tags` — so this adds the minimal
governed surface to *learn* and *set* redaction, keeping the "board never raw-writes RTM" discipline.

**Read side (additive, derived boolean).** `#redacted` surfaces as a `redacted` bool with **no new
tag, no strict-tag interaction on read**:
- `gtd_project_canvas` — each `seed[*]` item carries `redacted` (always emitted, from the item task's
  tag via `canvas_seed.map_redacted`), and `frame.redacted` carries the project's own state (from
  `project_plan.build_envelope`, which now also emits `header.project.redacted` — additive to the
  `project-plan-seed/3` envelope, so `gtd_project_plan`'s header carries it too; rtm_fetch.py parity
  is an upstream follow-up, same pattern as the earlier `files`/`prog` additions).
- `gtd_project_index` — each project row, each action row, **and** each `foci[]` row carries `redacted`
  (the board redacts at all three levels), derived in `project_index.build_index` / `build_actions` /
  `build_foci` from the task's own tag. The focus flag (since v1.17.1) lets the navigator collapse a
  whole Area of Focus — name + its projects hidden — to a single "Redacted Area of Focus" row; the
  cascade onto that focus's projects/actions is client-side.

The tag constant `REDACTED_TAG = "redacted"` is defined once in `project_plan.py` (the low membership-
tag layer, alongside `_PROJECT_TAG`/`_TEST_TAG`) and imported upward (`canvas_seed`, `project_index`,
`tools/gtd`) — the same convention as those tags. No server-side name stripping: redaction is a
viewing-layer curtain (the plaintext still flows to the board), **not** a vault; hardening to null
names/notes of redacted rows is a deliberate out-of-scope follow-up.

**Write side (`gtd_set_redaction`, constrained write).** Keyed by `task_id` (the board always has it
from the index/seed — no fragile name resolution). Resolves the task's full triple from **one**
`rtm.tasks.getList(status:incomplete OR status:completed)` (done items redact too), then a single tag
write: `redacted=true` → `addTags #redacted` (behind the strict-tag existence gate — `#redacted` is
account-provisioned, so it passes; a missing tag yields the guided error with nothing written);
`redacted=false` → `removeTags #redacted` (**never gated** — removal reduces entropy, CONTRIBUTING § 6).
The transaction is recorded (undoable via `undo`/`batch_undo`). It carries **no** `#ai_conversation`
stamp — this is a user viewing-state change, not an AI write. Returns `{task_id, redacted}`.

**Membrane / activation.** Vault-free, pure RTM. The server introduces **no new tag** — `#redacted`
already exists in the account, so there is **no activation-ordering hazard** (unlike the finalise /
overlay-refresh marks). Purely additive + backward-compatible: absence of the flag on older rows reads
as not-redacted; the board degrades cleanly (redaction shows nothing / marking no-ops) until the server
is on v1.17.0 and restarted.

## RTM API Quirks

### Response Normalization

RTM returns single items as dicts and multiple items as arrays. Use `ensure_list()` from `parsers.py`:

```python
from rtm_mcp.parsers import ensure_list

data = ensure_list(result.get("locations", {}).get("location", []))
# Always returns a list, even for single-item or empty responses
```

RTM also wraps arrays in dict containers (e.g. `{"tag": ["a", "b"]}`). Use `parse_nested_list()`:

```python
from rtm_mcp.parsers import parse_nested_list

tags = parse_nested_list(ts.get("tags", []), "tag")
# Handles: {"tag": "single"}, {"tag": ["a","b"]}, [], None
```

### Write Response Format

RTM returns different JSON structures for reads vs writes:
- **Read** (`getList`): `{"tasks": {"list": [...]}}`
- **Write** (`add`, `complete`, `setTags`, etc.): `{"list": {...}}`

`parse_tasks_response` handles both via fallback:
```python
task_lists = result.get("tasks", {}).get("list", [])
if not task_lists and "list" in result:
    task_lists = result["list"]
```

### Default List Resolution (tasks.add ignores settings.defaultlist)

RTM's `rtm.tasks.add` ignores the account's default-list setting when called without a
`list_id` — the task lands in the built-in Inbox (`7271150`), **not** `settings.defaultlist`
(the web UI's quick-add honors it; the API does not). `add_task` compensates: when no
`list_name` is given **and** the task is not a subtask, it calls `client.get_default_list_id()`
and passes the result as `list_id`. Subtasks are skipped (the parent's list governs). Falls
back to RTM's built-in Inbox only when no default is configured. The default is read from the
user's RTM settings, never hardcoded.

### List Flag Coercion (smart / locked / archived)

RTM returns list flags as the strings `"1"`/`"0"`. `parse_lists_response` coerces them to
bools, but `format_list` is **also** called directly on *raw* write responses (`add_list`,
`rename_list`, `archive_list`, `unarchive_list`). It therefore uses `_is_true()`, which accepts
both the raw string and an already-parsed bool — so the formatter is correct whether fed parsed
dicts (the `get_lists` path) or raw RTM dicts (the write-tool path). A naive `== "1"` check broke
the `get_lists` path because the value was already a bool there.

### Timeline Requirement

All write operations require a timeline:

```python
await client.call("rtm.tasks.complete", require_timeline=True, ...)
```

### Transaction Log and Undo

All write tools record their transaction in an in-memory log on `RTMClient` via `record_and_build_response()`. This helper extracts the transaction ID and undoable flag, records the entry, and builds the response envelope in one call:

```python
return record_and_build_response(client, result, data={...}, tool_name="add_task")
```

The transaction log (`client.get_all_transactions()`) enables:
- `get_timeline_info` — inspect the session's full write history
- `batch_undo` — undo multiple operations in reverse chronological order
- `undo` — marks the transaction as undone in the log after successful undo

Key classes:
- `TransactionEntry` (dataclass in `client.py`): `transaction_id`, `method`, `undoable`, `undone`, `summary`
- `record_and_build_response` (in `response_builder.py`): combines `get_transaction_info` + `client.record_transaction` + `build_response`

### Note Body Extraction

RTM stores note body text in `$t` (XML text node) or `body` depending on context. Use `extract_note_body()`:

```python
from rtm_mcp.parsers import extract_note_body
body = extract_note_body(note)  # Handles both "$t" and "body" keys
```

## Testing

Test-writing conventions (the respx + `FakeMCP`/`mock_client` patterns, the read-only
call-surface assertion, strict-tag rejection setup) are canonical in
[CONTRIBUTING.md](CONTRIBUTING.md) § 8. Run with `make test` (= `uv run pytest`).

### Test-suite inventory

This inventory is the canonical per-file test count (keep it in sync — CONTRIBUTING.md § 9).

Test files (781 tests total):
- `tests/test_client.py` — client signing, API calls, settings + account-tag caching (incl. failure-not-cached + concurrent-timeline lock), transaction log, 503 retry, connection retry incl. connect-phase-timeout-on-write retry + mid-flight ReadError wrap + non-JSON response, POST/GET split (46 tests)
- `tests/test_config.py` — config load/save, file fallback (corrupt/wrong-type/unreadable JSON), RTM_AUTH_TOKEN env + token/auth_token kwargs, safety-margin bounds, 0600 save permissions, strict-tag toggle (22 tests)
- `tests/test_strict_tags.py` — strict-tag guard: normalize/split/SmartAdd-extract + enforce_strict_tags (off / reject / live-refetch / input normalization) (13 tests)
- `tests/test_project_plan.py` — project-plan-seed/3 envelope builder: header/row mapping, priority word-form, id-based permalink (absent ancestor), deps/files extraction, project-level `header.project.files`, None→"" coercion, tz date-localisation (BST off-by-one fix, GMT-unaffected, no-tz fallback, completed/note dates), resolve_project disambiguation, resolve_focus (by id/name/substring, area-from-project-parents, ambiguity, miss, project-less area), header.project.redacted flag, envelope note objects carry the RTM note id, seed-3.1 repeating signals (is_repeating/taskseries_id default-false on rows + header.project; surface True from the parsed rrule flag) (31 tests)
- `tests/test_project_index.py` — portfolio builders: `build_index` (selection (incomplete/#project/not-#test; #hold always excluded; #someday default-out/opt-in; completed-project excluded; empty), field-set shape, life-from-tag, focus/focus_id from parent (+ top-level → `(unfiled)` not dropped), priority mapping (1/2/3 and N→""), `updated` tz-localisation (BST), open_count = all incomplete children, blocked_count from a DEPENDS-ON edge, next_tickle earliest incl. overdue (+ empty), life→focus→project sort); AI-progressible counts (ai_quick unblocked #quick_win actions, excludes blocked + waiting-for; ai_now #ai_progress_requested excl. blocked; ai_later #ai_progress_deferred incl. blocked; zero-not-absent; canvas-seed parity); conversation counts (chat_count incomplete #ai_chat + chat_review_count #ai_output_review_needed; completed excluded; review subset-not-additive; project-scoped counts the project; zero-not-absent); engage counts (waiting_count incomplete #waiting_for, canvas-kind parity, completed excluded, zero-not-absent); `build_foci` (all #focus areas incl. project-less; field-set; life-from-tag; #test/#hold excluded; #someday gated; untagged area not a focus; life→focus sort); `build_actions` (incomplete children of active project; field-set + attribution incl. type/due/priority/blocked; #test child excluded; excluded-project child not emitted (+#someday opt-in); top-level → `(unfiled)`; deterministic grouped sort); action kind + urgency fields (type matches canvas r.k incl. default; due carried + localised + empty; priority encoding; blocked matches plan-graph (+ false on absent/cross-project upstream); waiting-for/calendar due); redaction (project-row + action-row + focus-row `redacted` from `#redacted`); completed-row guards (counts/next_tickle/actions exclude completed children when fed a broader parsed set) (62 tests)
- `tests/test_canvas_seed.py` — canvas mapper: kind/priority/context/comms, `map_prog` tri-state + per-row `prog` emit, parse_note (dash/colon forms, body-omit), parse_file filtering, map_row, `map_redacted` + per-item `redacted` always-emitted + `frame.redacted` from project, build_seed frame + sibling-deps + history placement + v1 `frame.files` from project files (23 tests)
- `tests/test_plan_graph.py` — plan-graph engine: DEPENDS-ON edges + blocked, quick-from-tag (and blocked/waiting-for guards), tiered topological order, cycle fallback, fingerprint stability; manual-order pin (clamping parity with the gtd suite one-for-one: pin reorders independent siblings, cannot violate topology, unpinned fall after pinned, cleaned to current ids, no-pin unchanged, excluded from fingerprint); MoSCoW band within-tier sort (parity with the gtd suite one-for-one: Must>Should>Could>untriaged-last, untriaged after Could, numeric "1"/"2"/"3" surface accepted, band-beats-date, tier-outranks-band, never-violates-topology, pin-outranks-band, band change flips fingerprint incl. band→absent) (26 tests)
- `tests/test_canvas_overlay.py` — apply_graph (reorder + quick + sorted deps, no blocked/order field) and lean_seed (body-strip, cap, honest nc) (5 tests)
- `tests/test_canvas_commit.py` — closed classifier→tag mapping, `execute_progress_tags` now/later split, collect_commit_tags (later pulls deferred into gate; now-only stays backward-compatible), overlay-refresh gate (present for each actionable op incl. completes/removes-only and order-only (DC-4); absent for empty ops), validate_commit rejection paths (cross-project, destructive-confirm, unknown type, invalid execute, smart-list) (19 tests)
- `tests/test_canvas_create.py` — create-side pure helpers: `item_id` (explicit/index/empty), `project_tags` (life + project + ai_conversation + finalise mark), `collect_create_tags` (project tags; later pulls deferred into gate; now-only backward-compat; no-execute omits progress tags), `validate_create` rejection paths (missing_name, invalid_life, unknown_add_type, invalid_execute, unknown_dep, dep-by-index, duplicate_id incl. explicit-vs-positional collision, self_dep) (22 tests)
- `tests/test_gtd_chat.py` — CHAT-note pure helpers: `format_chat_title`/`parse_chat_title` round-trip (+ non-CHAT/`ai`-role/empty/bad-role → None), `append_mode_footer`/`parse_body` round-trip (with/without mode; footer only on the final line; discuss), `parse_turn` (title from the body's FIRST LINE — real getList shape, title field empty/ignored; CHAT vs non-CHAT, mode present omits-key-when-absent, `$t` vs `body` body keys, single-line body → empty text, mode footer on realistic shape), `build_thread` (filters non-CHAT, oldest-first sort, out-of-order input, `since` filter, empty, single-dict normalised), `build_inflight` (selection incomplete/#ai_chat/not-#test/not-completed; status precedence in_flight>awaiting_review>open; scope project-vs-item; nearest-#project ancestor incl. deep-nested + nested-project-attributes-to-nearest (not topmost) + loose→""; last_activity latest CHAT note + empty; status→recency→name ordering; empty→{items:[],count:0}), turn attachments (`parse_filings` single-line + labelled-continuation + companion-marker-optional + absolute/backslashed skipped + multiple + none; `parse_output_note` OUTPUT-title selector incl. timestamped variant + non-OUTPUT/`FILING`-typed ignored + no-filing → None + label from title summary; `parse_links` em/en-dash + spaced-hyphen separators + no-separator → empty label + line-anchored uppercase only + ordering; `build_thread` correlation: OUTPUT before/equal ai turn attached, after last ai turn unattached, two-ai-turn windows, never on me turns, LINK parsed + retained in text, empty arrays default, since-filter keeps full-thread correlation; item-scope entries carry no provenance fields), project-scope attachments (`project_descendants` BFS children+grandchildren, completed included, deleted + cycle excluded, project itself excluded, no-descendants → []; `build_thread(descendants=...)` child filing attached with `item_id`/`item_name`, grandchild included, after-last-ai-turn unattached, two-window discipline across children, own-note entry keeps plain shape, descendant CHAT notes never become turns), `local_stamp` (shape + tz fallback), tag constants (75 tests)
- `tests/test_companion.py` — companion reader: parse_frontmatter (scalars/quote-strip, block + inline lists, empty-scalar drop, closing-fence stop), companion_candidates ordering, resolve_vault_root (explicit/host-default/marker), resolve_companion_meta (5 forms + precedence + containment + non-artefact skip + non-UTF-8 companion → no meta / falls through), enrich_files (32 tests)
- `tests/test_tool_params.py` — shared complex-param coercion: `coerce_json` (parse/passthrough/blank/invalid) + Annotated types (string→structured via BeforeValidator, clean single-typed schema, no `anyOf`) (11 tests)
- `tests/test_tools/test_gtd_tools.py` — gtd_project_plan + gtd_project_canvas (seed shape, read-only call surface, lean cap, name/ambiguity/not-found, per-row `prog` from progression tags, BST due renders local day + no-tz fallback, companion `file.meta` + `frame.files` from a tmp vault, no-meta-when-absent) + gtd_apply_canvas_commit (staged-commit apply, JSON-string ops defensive path, now/later execute split + stale-sibling drop both directions, `later` strict-gate rejection + `now` backward-compat, all four rejection-without-write paths, overlay-refresh mark stamped on successful commit + not on zero-apply) + ORDER note / DC-4 (commit with `order` writes a conformant order-note/1 note on the project + returns order_persisted:"order-note" + records the tx + COMMIT note still lands; note written strictly BEFORE the overlay-refresh stamp; commit without order writes no note + order_persisted:false; order-only commit stamps the mark; canvas seed honours the latest valid ORDER note in ONE read; invalid note ignored → default order; pin clamped so a producer never follows its consumer) + gtd_create_project (project + children in dep order under the area, DEPENDS-ON note → producer's new id, finalise-mark + life + #project on the project, INCEPTION note, undoable; create-then-complete; now/later execute split + blocked→deferred; JSON-string params; focus ambiguity/miss without writes; missing-name + finalise-mark-absent strict rejection without writes; now-only backward-compat; reads once before writing) + gtd_project_index ({projects, foci, actions} object shape, project-row field-set + life/focus/focus_id + open/blocked counts + ai_quick/ai_now/ai_later + chat_count/chat_review_count + waiting_count, foci incl. empty focus area, actions under active project field-set + attribution + type/due/priority/blocked, read-only call surface + no transaction, include_someday passthrough) + gtd_chat_post (me-turn posts a CHAT note with the title grammar + adds #ai_chat_requested,#ai_chat; ai-turn removes #ai_chat_requested and never adds; task_id resolves series/list internally; mode footer round-trips into gtd_chat_thread; invalid role/mode + task-not-found (two reads) + completed-task read-only rejection rejected without writing; strict-tag rejection writes nothing) + gtd_chat_thread (only CHAT turns oldest-first, since filter, `requested` reflects the tag, empty thread, reads a COMPLETED task's thread with requested:false + filter spans incomplete OR completed, read-only call surface + no transaction, server-derived turn attachments: FILING continuation form → files[] on the correlated ai turn verbatim + LINK trailer → links[] retained in text + me-turn empty arrays, OUTPUT after last ai turn stays unattached; project-scope target aggregates descendant filings — open child + COMPLETED child + grandchild — with item_id/item_name provenance on the correlated ai turn in ONE read; non-#project target with a subtask stays same-task-only) + gtd_chat_inflight (cross-project roll-up: two projects' chat items with status/scope/project attribution + last_activity, #test excluded, empty portfolio, read-only call surface + no transaction) + project chat_count/chat_review_count (non-zero across the index) + redaction (canvas seed-item + frame.redacted; index project-row + action-row + focus-row redacted) + gtd_set_redaction (add-path addTags #redacted + records tx; remove-path removeTags; unknown id errors without write; strict-tag rejection writes nothing; round-trips on a focus-shaped task id) + gtd_chat_post note-write-failure (signal tags skipped, me and ai turns) + gtd_create_project duplicate-in-draft-id rejection without writes via FakeMCP (89 tests)
- `tests/test_exceptions.py` — error code mapping including subtask codes 4040-4090 + transient 102 → RTMNetworkError (17 tests)
- `tests/test_rate_limiter.py` — token bucket acquire/refill/pause (tokens_available honest during pause), rate limit stats incl. read/write session split (17 tests)
- `tests/test_response_builder.py` — envelope builder, transaction info, record_and_build_response, parsers (incl. `is_repeating` from the taskseries `rrule`) (43 tests)
- `tests/test_lookup.py` — find_task disambiguation, resolve_task_ids, resolve_list_id (16 tests)
- `tests/test_tools/test_task_tools.py` — all 19 task tools via FakeMCP, incl. strict-tag-mode gating, unknown-list_name error paths (add_task/list_tasks), user-filter parenthesization, day-scale estimates (79 tests)
- `tests/test_tools/test_tasks.py` — `_apply_subtask_counts` and `analyze_tasks` helpers (17 tests)
- `tests/test_tools/test_list_tools.py` — all 7 list tools via FakeMCP, incl. set_default_list transaction recording (18 tests)
- `tests/test_tools/test_note_tools.py` — all 4 note tools via FakeMCP, incl. get_task_notes name-lookup spanning completed tasks (15 tests)
- `tests/test_urls.py` — URL builders and parent chain walking incl. depth-exhaustion truncation warning (16 tests)
- `tests/test_tools/test_utility_tools.py` — all 14 utility tools via FakeMCP, incl. batch_undo JSON-string ids coercion + undo session-log validation (unknown id / already-undone rejected without an API call) (44 tests)
- `tests/test_tools/test_lists.py` — list response filtering and sorting (3 tests)
- `tests/test_order_note.py` — ORDER-note contract (order-note/1): make/parse round-trip (+ singular title, unknown source), fail-closed conformance (checksum/count/title-count mismatch, duplicates, non-JSON, wrong schema, bad `at`), title-line-in-body tolerance (the RTM storage reality), resolve (latest-valid-wins by `at`, note-id tie-break, invalid-latest fallback, non-ORDER ignored, input-order determinism), from_envelope (header.project.notes + empty) — mirrors the gtd suite case-for-case (19 tests)
- `tests/test_plan_graph_parity.py` — golden-file parity pin for the plan-graph port (1 test)

### Integration Testing

Use MCP Inspector:

```bash
make inspect
# or
npx @modelcontextprotocol/inspector uv run rtm-mcp
```

### Manual Testing

```python
# Quick API test
python -c "
import asyncio
from rtm_mcp.config import RTMConfig
from rtm_mcp.client import RTMClient

async def test():
    config = RTMConfig.load()
    client = RTMClient(config)
    result = await client.test_echo()
    print(result)
    await client.close()

asyncio.run(test())
"
```

## Adding New Tools

The canonical step-by-step checklist is [CONTRIBUTING.md](CONTRIBUTING.md) § 12 (with the tool
pattern in § 3 and the enriched-docstring shape in § 7). The worked example below shows the
pattern in context.

Example:

```python
from ..lookup import resolve_task_ids
from ..response_builder import build_response, record_and_build_response

@mcp.tool()
async def set_task_location(
    ctx: Context,
    location_id: str,
    task_name: str | None = None,
    task_id: str | None = None,
    taskseries_id: str | None = None,
    list_id: str | None = None,
) -> dict[str, Any]:
    """Assign a saved location to a task. Use get_locations to find location IDs.
    Use list_tasks with filter "location:name" to find tasks at a location.

    Identify the task by either task_name or all three IDs.

    Caution: task_name uses fuzzy matching across all tasks. For common names,
    prefer passing task_id + taskseries_id + list_id to avoid matching an
    unintended task.

    Returns:
        {"message": "Location set"} with transaction_id for undo.
    """
    client: RTMClient = await get_client()
    ids = await resolve_task_ids(client, task_name, task_id, taskseries_id, list_id)
    if "error" in ids:
        return build_response(data=ids)

    result = await client.call(
        "rtm.tasks.setLocation",
        require_timeline=True,
        location_id=location_id,
        **ids,
    )

    return record_and_build_response(
        client, result,
        data={"message": "Location set"},
        tool_name="set_task_location",
    )
```

## Deployment

### PyPI Release

```bash
uv build
uv publish
```

### Docker

```bash
docker build -t rtm-mcp .
docker push ghcr.io/pauleastabrook/rtm-mcp
```

## Common Issues

### "RTM not configured"

Run `rtm-setup` or set environment variables.

### Rate Limiting

Client uses a token bucket (burst to 3, sustain ~0.9 RPS). HTTP 503 responses trigger automatic retry with backoff. Use `get_rate_limit_status` to diagnose. If 503s occur regularly, increase `RTM_SAFETY_MARGIN` (default 0.1).

### Connection Failures

Transient connection errors (TCP timeout, DNS, connection reset) are retried automatically up to `RTM_CONN_MAX_RETRIES` (default 3). Write timeouts are **not** retried to avoid duplicates. Check `connection_retries_last_60s` in `get_rate_limit_status` output.

### Token Expiry

RTM tokens don't expire, but can be revoked. Re-run `rtm-setup` if needed.
