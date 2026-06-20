<!-- conventions-doc: marketplace/v1 -->
# Contributing to rtm-mcp — standards & conventions

This is the **canonical, single source of truth** for how code, tests, and documentation are
written in this repository. If you are adding a tool, porting a module, or changing behaviour,
read the relevant section first and conform to it.

`CLAUDE.md` is the companion document: it owns **architecture, RTM API quirks, and per-feature
deep-dives** (the module-responsibility table, the response/transport patterns, the
`gtd_project_plan` / Strict-Tag / Canvas write-ups). This file owns the **rules**. Where a rule
needs architectural background, it links into `CLAUDE.md` rather than duplicating it.

> The HTML comment on line 1 (`conventions-doc: marketplace/v1`) is a machine-detectable marker
> identifying this as a marketplace conventions document with the stable section structure
> below. Keep it on line 1.

## Development setup

```bash
git clone https://github.com/ljadach/rtm-mcp.git
cd rtm-mcp
make dev      # install with dev dependencies
make setup    # set up RTM credentials
make run      # run the MCP server
make inspect  # run the MCP Inspector
```

---

## 1. Project layout & module responsibilities

The package lives under `src/rtm_mcp/`. Every module has a **single responsibility**; the
authoritative table is in `CLAUDE.md` § "Module Responsibilities". The rule that matters when
contributing:

- **`tools/*.py` are thin glue.** A tool resolves identifiers, calls the client, parses the
  response, and builds the envelope — nothing more. Transport lives in `client.py`, response
  shaping in `parsers.py`, the envelope in `response_builder.py`, name→id resolution in
  `lookup.py`, tag policy in `strict_tags.py`. Pure (no-IO) domain logic lives in its own
  top-level module (e.g. `project_plan.py`, `canvas_seed.py`, `plan_graph.py`) so it is
  unit-testable without a client.

When you add a new module, add a one-line entry to the `CLAUDE.md` architecture tree and the
module-responsibility table (see § 9, Documentation lockstep).

## 2. Naming conventions

- **Bare verbs are generic RTM primitives** — each maps 1:1 to an RTM API method and speaks
  RTM's own language: `add_task`, `list_tasks`, `get_task_notes`, `set_task_priority`.
- **A `<domain>_` prefix marks a domain composition** — a domain-shaped view over RTM data that
  does *not* map 1:1 to an RTM method. Current domain: `gtd_` (`gtd_project_plan`,
  `gtd_project_canvas`, `gtd_apply_canvas_commit`).
  - Format: **`<domain>_<concept-noun>`** for reads (the default — e.g. `gtd_project_plan`).
  - Use **`<domain>_<verb>_<noun>`** only when a domain genuinely needs an explicit verb
    (e.g. `gtd_apply_canvas_commit`).
- Reading the tool list, the split is instant: no prefix = RTM primitive, `<domain>_` = domain
  view. This keeps a future lift of all `<domain>_*` tools into a separate server a clean,
  mechanical move. New domain compositions **must** follow this and be documented alongside the
  existing ones.

## 3. Tool implementation pattern

Tools are registered by a `register_<group>_tools(mcp, get_client)` function and decorated with
`@mcp.tool()`. The body always starts by acquiring the client:

```python
def register_<group>_tools(mcp: Any, get_client: Any) -> None:
    @mcp.tool()
    async def my_tool(ctx: Context, ...) -> dict[str, Any]:
        """<enriched docstring — see § 7>"""
        client: RTMClient = await get_client()
        ...
        return build_response(data=...)            # reads
        # return record_and_build_response(client, result, data=..., tool_name="my_tool")  # writes
```

- **Reads** use `client.call("rtm.<method>", **params)` (GET). **Writes** use
  `client.call("rtm.<method>", require_timeline=True, **params)` (POST + timeline). RTM silently
  ignores some params on GET, so a write **must** set `require_timeline=True`.
- **Identify tasks** with `resolve_task_ids(...)` from `lookup.py` (accepts `task_name` *or* the
  three ids; returns `{task_id, taskseries_id, list_id}` or `{"error": ...}`). **Identify lists**
  with `resolve_list_id(...)`.
- Tools accept `task_name` (fuzzy) **or** explicit ids; document the fuzzy-match caution.

## 4. Response envelope

Every tool returns the standard envelope via `response_builder.py`:

```python
{
    "data": {...},                      # main payload (or {"error": ...})
    "analysis": {"insights": [...]},    # optional
    "metadata": {
        "fetched_at": "<ISO>",
        "transaction_id": "...",        # write ops only
        "transaction_undoable": True,   # write ops only
        "timeline_id": "...",           # write ops only
    },
}
```

- Reads: `return build_response(data=...)`.
- Writes: `return record_and_build_response(client, result, data=..., tool_name="...")` — this
  extracts the transaction, records it on the client (for `undo`/`batch_undo`/`get_timeline_info`),
  and wraps the envelope in one call. Never hand-roll the transaction fields.

## 5. Error handling

Two layers (background in `CLAUDE.md` § "Error Handling"):

- **Transport** — `raise_for_error()` in `exceptions.py` maps RTM error codes to typed
  exceptions (`RTMAuthError`, `RTMValidationError`, `RTMNotFoundError`, …) via `ERROR_CODE_MAP`
  and appends recovery hints from `ERROR_GUIDANCE`.
- **Application** — resolver and tool functions return **actionable** error dicts that name the
  next tool to call, surfaced through `build_response(data={"error": ...})`:

  ```python
  {"error": "Task not found: 'Buy milk'. Use list_tasks to search by filter or check spelling."}
  ```

  Never return a bare `{"error": "not found"}` — say what to do next.

## 6. Tag-write discipline

Tag writes go through the **strict-tag existence gate** (`strict_tags.py`; background in
`CLAUDE.md` § "Strict-Tag Mode"):

- Gate **add/set** tag writes with `enforce_strict_tags(client, requested, *, tool=...)`; on a
  rejection return `build_response(data=err)` **without** calling RTM.
- **Never** gate tag *removal* (it reduces entropy).
- The server holds **no canonical taxonomy and needs no sync** — the gate only enforces "does
  this tag already exist in the account?". Canonical-taxonomy policing stays plugin-side. Do not
  add a taxonomy or import one into the server.

## 7. Source style

- **Python ≥ 3.11.** Use native unions and builtin generics (`str | None`, `dict[str, Any]`,
  `list[str]`). **Do not** add `from __future__ import annotations` — no existing `src` module
  uses it.
- **Lint/type:** ruff (`E,F,I,UP,B,SIM,RUF`, line-length 100, `E501` ignored) and pyright
  (`basic`, over `src`). Run `make lint` (= `uv run ruff check src tests` + `uv run pyright src`)
  and `make format` before pushing. Async/await for all I/O.
- **Module docstring:** every module opens with a one-paragraph single-responsibility docstring.
  A module ported from elsewhere cites its lineage (see § 13).
- **Tool docstrings are enriched** (the docstring *is* the API surface). Follow the shape of
  `gtd_project_plan`:
  - Opening sentence: the domain tag + what the tool does and *when* to use it
    (e.g. `GTD — return a whole project plan …`).
  - State the read-only / no-timeline invariant for read tools; the rejection contract and
    "carries `transaction_id` for undo" for write tools.
  - For identifier choices: an **"Identify … by EXACTLY ONE of:"** block.
  - An `Args:` section for the remaining parameters.
  - A **multi-case `Returns`**: `Returns (on success): … Returns (on ambiguity): … Returns
    (on miss / bad input): …`.
  - The fuzzy-match caution where `task_name` is accepted.

## 8. Testing

- **Pure modules** are tested by calling their functions directly (cf. `tests/test_project_plan.py`).
- **Tools** are tested with the **`FakeMCP` / `FakeContext`** pattern and the `mock_client`
  `AsyncMock` fixture (`client.call`, `client.record_transaction`, `timeline_id` PropertyMock,
  `client.config = MagicMock(strict_tags=...)`). Build RTM responses with the `_ts` / `_getlist`
  helpers (see `tests/test_tools/test_gtd_tools.py`).
- **HTTP-level** client tests use **respx** to mock `RTM_API_URL`.
- Test classes are `TestXxx`; async tests use `@pytest.mark.asyncio` (`asyncio_mode = auto`).
- **Read-only tools assert their call surface:**
  `assert [c.args[0] for c in client.call.call_args_list if c.args] == ["rtm.tasks.getList"]`.
- **Strict-tag rejection tests** flip `client.config = MagicMock(strict_tags=True)` and stub
  `client.get_account_tags` (cf. `tests/test_strict_tags.py`, `tests/test_task_tools.py`).
- Run with `make test` (= `uv run pytest`); coverage via `make test/coverage`.
- **Keep the test-count inventory in `CLAUDE.md` accurate** for every file you add or change
  (it tracks per-file counts and the total).

## 9. Documentation lockstep

A new or changed tool is documented in **four** places, updated together:

1. **`README.md`** → the relevant "Available Tools" subsection (e.g. `### GTD (domain
   compositions)`).
2. **`src/rtm_mcp/server.py`** → the `instructions=` string block for that group.
3. **`CLAUDE.md`** → the architecture tree + module-responsibility table, and a feature section
   for non-trivial tools.
4. **`CLAUDE.md`** → the **test-count inventory** under § Testing.

A tool is not "done" until all four are in sync.

## 10. Versioning & release

- **SemVer** in `pyproject.toml`: new tools/features → minor bump; fixes → patch; breaking
  envelope/signature changes → major.
- Honour the fork/upstream **version-lockstep** (this repo tracks an upstream; keep versions
  aligned per that convention before publishing).
- Release: `uv build` / `uv publish`; Docker image per `README.md`.

## 11. Quality gate

Before hand-off / commit, all of these must pass:

```bash
make lint     # uv run ruff check src tests  +  uv run pyright src
make test     # uv run pytest
```

## 12. Adding a new tool — checklist

1. Identify the RTM API method (or the domain composition shape).
2. Add the tool to the appropriate `tools/*.py` `register_*` function.
3. Write an **enriched docstring** (§ 7).
4. `require_timeline=True` for writes; `record_and_build_response()` for write tools.
5. Resolve ids via `resolve_task_ids()` / `resolve_list_id()` (§ 3).
6. Return **actionable** error messages (§ 5).
7. If the tool **adds/sets tags**, gate with `enforce_strict_tags()` (§ 6) — never gate removal.
8. Add tests (pure-helper tests + FakeMCP tool tests), including the read-only call-surface
   assertion for read tools and every rejection path for write tools (§ 8).
9. Update all four documentation touchpoints + the test-count inventory (§ 9).
10. Bump the version (§ 10) and pass the quality gate (§ 11).

## 13. Porting a plugin-side reference into the server (byte-compat pattern)

When a behaviour must stay **byte-compatible** with a reference implementation maintained
elsewhere (e.g. a `claude-plugins` script), port rather than re-derive:

- **Copy the logic verbatim** into a pure `src/rtm_mcp/*.py` module; drop only CLI/IO shims the
  server doesn't need.
- **Add type annotations** to match the rest of `src` (§ 7) — the *output* must stay identical,
  not the source.
- **Cite the lineage** in the module docstring (which reference, which functions, what makes the
  output identical) — exactly as `project_plan.py` cites the gtd plugin's `rtm_fetch.py`.
- **Prove it with a diff test:** feed one real input through both pipelines and assert the
  outputs are identical.

---

## Pull request process

1. Fork the repository.
2. Create a feature branch (`git checkout -b feat/<short-name>`).
3. Make your changes, conforming to the conventions above.
4. Pass the quality gate: `make test && make lint`.
5. Keep documentation in lockstep (§ 9) and bump the version (§ 10).
6. Commit with a clear, conventional message; push to your fork; open a Pull Request.

Open an issue for discussion before making major changes.
