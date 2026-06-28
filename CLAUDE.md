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
├── project_plan.py     # Pure project-plan-seed/3 envelope builder (backs gtd_project_plan)
├── project_index.py    # Pure active-#project portfolio roll-up + counts + foci + action index (backs gtd_project_index)
├── canvas_seed.py      # Pure envelope→canvas-seed mapper (port of gtd build-canvas-seed.py)
├── plan_graph.py       # Pure deterministic plan-graph engine (port of gtd plan_graph.py)
├── canvas_overlay.py   # Pure seed+graph merge (apply_graph) + lean transform (lean_seed)
├── canvas_commit.py    # Pure closed tag-mapping + commit validators (backs gtd_apply_canvas_commit)
├── canvas_create.py    # Pure create-side tags (project/life/finalise) + validators (backs gtd_create_project)
├── companion.py        # Read-only vault locate (cross-platform) + companion .md/.yaml reader → canvas file.meta
├── tool_params.py      # Shared MCP complex-param coercion + clean-schema Annotated types
├── urls.py             # Web UI URL construction + task hierarchy walking
├── rate_limiter.py     # Token bucket rate limiter + diagnostics stats
├── types.py            # Pydantic models for type safety
├── exceptions.py       # RTMError hierarchy + ERROR_GUIDANCE recovery hints
├── tools/
│   ├── tasks.py        # Task CRUD + metadata + hierarchy (19 tools)
│   ├── lists.py        # List management (7 tools)
│   ├── notes.py        # Note operations (4 tools)
│   ├── utilities.py    # Tags, locations, settings, undo, timeline, diagnostics, URLs (14 tools)
│   └── gtd.py          # GTD domain compositions — gtd_project_plan, gtd_project_canvas, gtd_project_index, gtd_apply_canvas_commit, gtd_create_project (5 tools)
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
| `project_plan.py` | Pure (no IO) reconstruction of the `project-plan-seed/3` envelope from parsed tasks — byte-compatible with the gtd plugin's `rtm_fetch.py` reference |
| `project_index.py` | Pure (no IO) active-`#project` portfolio roll-up backing `gtd_project_index` — `build_index` (per-project rows: selection (incomplete, `#project`, not `#test`; `#hold`/`#someday` policy), life + parent Area-of-Focus resolution, and counts `open_count`/`blocked_count`/`next_tickle` + AI-progressible tallies `ai_quick`/`ai_now`/`ai_later` (canvas `quick_ready` + `map_prog`) via `project_plan.build_envelope` + the thin `plan_graph.build_graph`), `build_foci` (every `#focus` area incl. project-less ones), and `build_actions` (every incomplete child under an active project — with `type` (canvas `r.k`) + `due`/`priority`/`blocked` urgency signal for the What's-hot band and find-result glyphs — for cockpit search). Vault-free |
| `canvas_seed.py` | Pure mapper: `project-plan-seed/3` envelope → canvas `{mode, frame, seed}` shape — byte-compatible port of the gtd plugin's `build-canvas-seed.py` |
| `plan_graph.py` | Pure deterministic plan-graph engine (DAG, blocked/quick judgement, tiered timeline order, cycles, fingerprint) — byte-compatible port of the gtd plugin's `plan_graph.py` |
| `canvas_overlay.py` | Pure merge of the plan-graph overlay onto the seed (`apply_graph`) + the lean/inline transform (`lean_seed`) — port of the gtd plugin's `build_canvas.py` helpers |
| `canvas_commit.py` | Pure closed canonical classifier→tag mapping + commit validators (`validate_commit`, `collect_commit_tags`) for `gtd_apply_canvas_commit` |
| `canvas_create.py` | Pure create-side helpers for `gtd_create_project`: the project's own tags (`project_tags` — life + `#project` + `#ai_conversation` + the `#ai_project_needs_finalise` mark), `collect_create_tags`, `validate_create`, and `item_id` (in-draft id ↔ dep mapping). Imports the shared classifier→tag taxonomy from `canvas_commit` — no duplicate taxonomy |
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
- `TimeoutException` on reads — retried (safe to replay)
- `TimeoutException` on writes — **not retried** (request may have been processed, risking duplication)
- TLS certificate errors — never retried
- Connection retries do **not** consume additional rate limit tokens

Request classification uses `require_timeline` as a proxy: `True` = write, `False` = read. This correlates 100% with actual read/write status across all tools.

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
2. Drop empties; no tags → allow.
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
  (v1 is mechanical-only: no vault, so `outputs_index=None`, `manual_order=[]` — edges come from
  active DEPENDS-ON notes alone).
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
  execute AI work), `notes`, then `completes` / `removes` (RTM soft-delete), then a `COMMIT` audit
  note on the project, and finally — on **any** non-empty commit — the **overlay-refresh mark**
  `#ai_overlay_refresh_needed` (`addTags`) is stamped on the project (Piece 0b; inside `if applied:`,
  so a zero-apply commit stamps nothing). Each write records its transaction (so `batch_undo`
  works); per-op failures are captured and the batch continues. (`#ai_progress_deferred` is a **new**
  tag — under strict-tag mode a `later` commit is rejected with a guided error until it's provisioned
  in RTM; the gate requires it only when a `later` is actually present, so `now`/`quick` commits stay
  backward-compatible. `gtd_project_canvas` mirrors this on read via `canvas_seed.map_prog` → the
  per-row `prog` field.)
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
  the strict-tag existence gate — the server holds no taxonomy (see Strict-Tag Mode). `order` is
  accepted but a **v1 no-op** (RTM has no sibling-order field; the `manual_order` pin needs vault
  write access — a later DC). Created/edited items carry `#ai_conversation`.
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
- `focus`/`focus_id` come from the project's **parent** Area-of-Focus task; a top-level project is
  kept as `focus="(unfiled)"`, `focus_id=""` (never dropped). `priority` is the project's raw RTM
  priority coerced to `"1"|"2"|"3"|""`; dates are localised to the account tz (the BST off-by-one
  fix, via `project_plan._norm_date`).

**Vault-free (the membrane).** Counts derive only from the server's thin plan-graph — the enriched
AI-Memory overlay stays gtd-side, exactly as for the canvas/commit tools. Purely additive and
read-only: **no new tag, no strict-tag-gate interaction**, so no activation-ordering hazard.

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

Test files (571 tests total):
- `tests/test_client.py` — client signing, API calls, settings + account-tag caching, transaction log, 503 retry, connection retry, POST/GET split (39 tests)
- `tests/test_config.py` — config load/save, file fallback, corrupt JSON, strict-tag toggle (12 tests)
- `tests/test_strict_tags.py` — strict-tag guard: normalize/split/SmartAdd-extract + enforce_strict_tags (off / reject / live-refetch) (12 tests)
- `tests/test_project_plan.py` — project-plan-seed/3 envelope builder: header/row mapping, priority word-form, id-based permalink (absent ancestor), deps/files extraction, project-level `header.project.files`, None→"" coercion, tz date-localisation (BST off-by-one fix, GMT-unaffected, no-tz fallback, completed/note dates), resolve_project disambiguation, resolve_focus (by id/name/substring, area-from-project-parents, ambiguity, miss, project-less area) (27 tests)
- `tests/test_project_index.py` — portfolio builders: `build_index` (selection (incomplete/#project/not-#test; #hold always excluded; #someday default-out/opt-in; completed-project excluded; empty), field-set shape, life-from-tag, focus/focus_id from parent (+ top-level → `(unfiled)` not dropped), priority mapping (1/2/3 and N→""), `updated` tz-localisation (BST), open_count = all incomplete children, blocked_count from a DEPENDS-ON edge, next_tickle earliest incl. overdue (+ empty), life→focus→project sort); AI-progressible counts (ai_quick unblocked #quick_win actions, excludes blocked + waiting-for; ai_now #ai_progress_requested excl. blocked; ai_later #ai_progress_deferred incl. blocked; zero-not-absent; canvas-seed parity); `build_foci` (all #focus areas incl. project-less; field-set; life-from-tag; #test/#hold excluded; #someday gated; untagged area not a focus; life→focus sort); `build_actions` (incomplete children of active project; field-set + attribution incl. type/due/priority/blocked; #test child excluded; excluded-project child not emitted (+#someday opt-in); top-level → `(unfiled)`; deterministic grouped sort); action kind + urgency fields (type matches canvas r.k incl. default; due carried + localised + empty; priority encoding; blocked matches plan-graph (+ false on absent/cross-project upstream); waiting-for/calendar due) (48 tests)
- `tests/test_canvas_seed.py` — canvas mapper: kind/priority/context/comms, `map_prog` tri-state + per-row `prog` emit, parse_note (dash/colon forms, body-omit), parse_file filtering, map_row, build_seed frame + sibling-deps + history placement + v1 `frame.files` from project files (20 tests)
- `tests/test_plan_graph.py` — plan-graph engine: DEPENDS-ON edges + blocked, quick-from-tag (and blocked/waiting-for guards), tiered topological order, cycle fallback, fingerprint stability (11 tests)
- `tests/test_canvas_overlay.py` — apply_graph (reorder + quick + sorted deps, no blocked/order field) and lean_seed (body-strip, cap, honest nc) (5 tests)
- `tests/test_canvas_commit.py` — closed classifier→tag mapping, `execute_progress_tags` now/later split, collect_commit_tags (later pulls deferred into gate; now-only stays backward-compatible), overlay-refresh gate (present for each actionable op incl. completes/removes-only; absent for empty ops), validate_commit rejection paths (cross-project, destructive-confirm, unknown type, invalid execute, smart-list) (19 tests)
- `tests/test_canvas_create.py` — create-side pure helpers: `item_id` (explicit/index/empty), `project_tags` (life + project + ai_conversation + finalise mark), `collect_create_tags` (project tags; later pulls deferred into gate; now-only backward-compat; no-execute omits progress tags), `validate_create` rejection paths (missing_name, invalid_life, unknown_add_type, invalid_execute, unknown_dep, dep-by-index) (18 tests)
- `tests/test_companion.py` — companion reader: parse_frontmatter (scalars/quote-strip, block + inline lists, empty-scalar drop, closing-fence stop), companion_candidates ordering, resolve_vault_root (explicit/host-default/marker), resolve_companion_meta (5 forms + precedence + containment + non-artefact skip), enrich_files (30 tests)
- `tests/test_tool_params.py` — shared complex-param coercion: `coerce_json` (parse/passthrough/blank/invalid) + Annotated types (string→structured via BeforeValidator, clean single-typed schema, no `anyOf`) (11 tests)
- `tests/test_tools/test_gtd_tools.py` — gtd_project_plan + gtd_project_canvas (seed shape, read-only call surface, lean cap, name/ambiguity/not-found, per-row `prog` from progression tags, BST due renders local day + no-tz fallback, companion `file.meta` + `frame.files` from a tmp vault, no-meta-when-absent) + gtd_apply_canvas_commit (staged-commit apply, JSON-string ops defensive path, now/later execute split + stale-sibling drop both directions, `later` strict-gate rejection + `now` backward-compat, all four rejection-without-write paths, overlay-refresh mark stamped on successful commit + not on zero-apply) + gtd_create_project (project + children in dep order under the area, DEPENDS-ON note → producer's new id, finalise-mark + life + #project on the project, INCEPTION note, undoable; create-then-complete; now/later execute split + blocked→deferred; JSON-string params; focus ambiguity/miss without writes; missing-name + finalise-mark-absent strict rejection without writes; now-only backward-compat; reads once before writing) + gtd_project_index ({projects, foci, actions} object shape, project-row field-set + life/focus/focus_id + open/blocked counts + ai_quick/ai_now/ai_later, foci incl. empty focus area, actions under active project field-set + attribution + type/due/priority/blocked, read-only call surface + no transaction, include_someday passthrough) via FakeMCP (49 tests)
- `tests/test_exceptions.py` — error code mapping including subtask codes 4040-4090 (16 tests)
- `tests/test_rate_limiter.py` — token bucket acquire/refill/pause, rate limit stats (14 tests)
- `tests/test_response_builder.py` — envelope builder, transaction info, record_and_build_response, parsers (40 tests)
- `tests/test_lookup.py` — find_task disambiguation, resolve_task_ids, resolve_list_id (16 tests)
- `tests/test_tools/test_task_tools.py` — all 19 task tools via FakeMCP, incl. strict-tag-mode gating (72 tests)
- `tests/test_tools/test_tasks.py` — `_apply_subtask_counts` and `analyze_tasks` helpers (17 tests)
- `tests/test_tools/test_list_tools.py` — all 7 list tools via FakeMCP (16 tests)
- `tests/test_tools/test_note_tools.py` — all 4 note tools via FakeMCP (14 tests)
- `tests/test_urls.py` — URL builders and parent chain walking (15 tests)
- `tests/test_tools/test_utility_tools.py` — all 14 utility tools via FakeMCP, incl. batch_undo JSON-string ids coercion (42 tests)
- `tests/test_tools/test_lists.py` — list response filtering and sorting (3 tests)

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
docker push ghcr.io/ljadach/rtm-mcp
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
