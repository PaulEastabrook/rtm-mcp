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
git clone https://github.com/PaulEastabrook/rtm-mcp.git
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
`@mcp.tool(annotations=..., output_schema=...)`. Every tool carries the **six documentation
surfaces** (below). The body always starts by acquiring the client:

```python
def register_<group>_tools(mcp: Any, get_client: Any) -> None:
    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=MY_TOOL_OUTPUT)
    async def my_tool(
        ctx: Context,
        name: Annotated[str, Field(description="…one line…")],
    ) -> dict[str, Any]:
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

### The six documentation surfaces

Every tool is documented so a calling LLM can *choose, call, chain, and recover* from the schema
alone. This is the family-wide **MCP tool-documentation standard**
(`mcp-tool-documentation-standard.md` in the git-ops plugin references — the normative source;
`agent-memory-mcp` is the reference implementation). All six are **additive schema metadata**:
they never change tool behaviour, returns, capability, or write safety. Enforced by
`tests/test_tool_schemas.py` (§ 8).

1. **Enriched docstring** (§ 7) — the primary contract.
2. **Per-parameter description** — every param except `ctx` is
   `Annotated[T, Field(description="…")]`. FastMCP does not lift the docstring `Args:` into the JSON
   schema, and clients render the schema, so a bare-typed param is undocumented to the model. For a
   **complex (array/object) coercion param**, `WithJsonSchema` *replaces* the field schema and drops
   a sibling `Field(description=…)`, so bake the description (and any nested enum) into the schema
   via the `tool_params.coerced_*_schema(...)` builders — never revert to a plain `Field` there (see
   § 12 step 8).

   **An optional SCALAR param must be single-typed too** — use a `tool_params.optional_*` builder,
   not `Field(...)`: `Annotated[str | None, optional_string("…")] = None`. Pass `enum=` /
   `pattern=` as keyword arguments so a vocabulary stays sourced from its canonical constant. The
   annotation and the `= None` default stay exactly as they are; only the *advertised* schema
   changes, and optionality is still carried by absence from `required`.

   *Why it is a rule.* `Annotated[T | None, Field(...)]` serialises to `anyOf`, and MCP clients
   that simplify schemas before showing them to the model flatten that to a bare `{}` — losing
   type, description **and** enum. Measured 2026-07-19: this server had 110 such params across 32
   tools. The complex-param builders above already existed for the same reason; this is the same
   fix for scalars. `TestSingleTypedParameters` pins it, and carries an explicit allowlist for the
   one legitimate *value-type* union (`set_task_priority.priority`, a required `str | int`) so the
   exception can never grow silently.
3. **Behaviour annotations** — `@mcp.tool(annotations=…)` via the three constants in
   `response_builder.py`: `READ_ONLY_ANNOTATIONS` (reads), `ADDITIVE_WRITE_ANNOTATIONS` (creates /
   additive field-tag updates / undo path), `DESTRUCTIVE_WRITE_ANNOTATIONS` (deletes and reachable
   removes — e.g. the canvas/engage commit tools, even though `undo` can reverse them; classify
   honestly and put the undo path in the docstring). `openWorldHint=True` everywhere (RTM is SaaS).
   Hints are signals, **not** enforcement — the strict-tag gate / `confirm_destructive` / actionable
   errors stay the sole safety authority.
4. **Input constraint metadata** — for a closed-vocabulary / bounded / structured param, add
   `json_schema_extra={"enum": …}` (a module-level `dict[str, Any]`, required by pyright) **sourced
   from the canonical constant** it validates against (`PRIORITY_INPUT_CODES`, `MOVE_DIRECTIONS`,
   `VALID_SCOPES`, `VALID_ROLES`, `VALID_MODES`, `VALID_EXECUTE_COMMIT`, `VERDICT_FAMILY`), so the
   advertised set can never drift from the handler. **Ownership rule:** only advertise vocabularies
   the *server* owns — **never** a tag enum (deliberately non-canonical server-side; gtd's
   `tag-taxonomy.md` owns it) or a list-name enum (account data).
5. **Output schema** — `output_schema=` from `models.py` (schema-only Pydantic models; NOT used at
   runtime). `data` is always advertised as the `success | ErrorData` union (`anyOf`). Match models
   to the actual returns; leave genuinely-open payloads (`raw`, evolving envelope rows) open.
6. **Typed errors (recovery half)** — this server's error shape is the free-text
   `{"error": "<actionable prose>"}` string (§ 5), modelled as `ErrorData` (`extra="allow"`) so the
   structured siblings ride along (`strict_tag_mode`/`how_to_proceed`; `candidates`; the commit
   engines' `rejected[].reason` enums). **Document what exists; do not invent codes** in an additive
   pass — a full typed-code vocabulary is a return-value change (SemVer), captured as an improvement
   candidate.

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
    (on miss / bad input): …` — naming the error discriminator the tool actually returns (this
    server's `data.error` string contract + any structured siblings, e.g. `strict_tag_mode` /
    `rejected[].reason`).
  - The fuzzy-match caution where `task_name` is accepted.
- The docstring is **surface 1** of the six-surface standard (§ 3); it is complemented by the
  per-parameter `Field(description=…)` (surface 2). Both are model-facing — keep them consistent.

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
- **The six documentation surfaces (§ 3) are enforced by `tests/test_tool_schemas.py`**, which
  introspects the REAL server (`from rtm_mcp.server import mcp` → `await mcp.get_tools()` →
  `to_mcp_tool()`): every tool + param is described; annotations are correct per behaviour class;
  closed-vocabulary enums are asserted **equal to the canonical constants** (drift-proof); complex
  params expose a clean single-typed schema; every tool's `outputSchema.properties.data` is a
  `success | error` union. A new tool that skips a surface fails this suite. **FakeMCP doubles** in
  `tests/test_tools/*.py` accept the decorator kwargs via `def tool(self, *_args, **_kwargs)`.
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

**Schema fingerprints.** Any change to a tool's schema (docstring, params, annotations, or output
schema) changes its fingerprint, so regenerate the committed `tool-fingerprints.json` with
`make fingerprints` — the freshness test in `tests/test_tool_schemas.py` fails CI until you do (it
recomputes the map from the live server and asserts equality). The file feeds the architect's weekly
tool-detection scan (family standard § 5); the repo keeps it fresh, the consumer only reads it.

## 10. Versioning & release

- **SemVer** in `pyproject.toml`: new tools/features → minor bump; fixes → patch; breaking
  envelope/signature changes → major.
- Release: `uv build` / `uv publish`; Docker image per `README.md`.

(Historical note: this repo began as a fork of ljadach/rtm-mcp and once kept a version
lockstep with it; the codebases have fully diverged and the repo is now standalone —
versioning is governed by this section alone.)

## 11. Quality gate

Before hand-off / commit, all of these must pass (this is exactly what CI runs):

```bash
make lint     # ruff check + ruff format --check + pyright (src tests / src)
make test     # uv run pytest
```

`make lint` includes `ruff format --check` so a format-only drift can't slip past local
checks and fail CI. Dev tooling (`ruff`, `pyright`) is **exact-pinned** in `pyproject.toml`
so lint/format/type rules don't drift between machines; bump those pins deliberately (and
re-run `make format` if a ruff bump changes formatting).

## 12. Adding a new tool — checklist

1. Identify the RTM API method (or the domain composition shape).
2. Add the tool to the appropriate `tools/*.py` `register_*` function.
3. Ship **all six documentation surfaces** (§ 3): enriched docstring (§ 7); a
   `Field(description=…)` on every non-`ctx` param; the right `annotations=` constant; a canonical-
   constant-sourced `json_schema_extra` enum for any closed-vocabulary param; an `output_schema=`
   model in `models.py` whose `data` is the `success | ErrorData` union; the actionable-error shape.
4. `require_timeline=True` for writes; `record_and_build_response()` for write tools.
5. Resolve ids via `resolve_task_ids()` / `resolve_list_id()` (§ 3).
6. Return **actionable** error messages (§ 5).
7. If the tool **adds/sets tags**, gate with `enforce_strict_tags()` (§ 6) — never gate removal.
8. For any **complex (array/object) parameter**, keep the coercion machinery AND carry a
   description: annotate inline as `Annotated[list[...] | None, BeforeValidator(coerce_json),
   WithJsonSchema(coerced_*_schema("…description…", …))]` (the `tool_params.coerced_str_array_schema`
   / `coerced_obj_array_schema` / `coerced_object_schema` builders emit the clean single-typed schema
   — no `anyOf`/null union some MCP clients stringify — with the description, and an optional nested
   `item_schema`/`extra` for a value/element enum). Also call `coerce_json()` on the param in-body as
   belt-and-braces. (The bare `JsonObjArray` / `JsonStrArray` / `JsonObject` / `JsonStrArrayRequired`
   aliases remain but carry NO description — do not use them for a documented tool param.)
9. Add tests (pure-helper tests + FakeMCP tool tests), including the read-only call-surface
   assertion for read tools and every rejection path for write tools (§ 8). The schema-contract
   suite (`tests/test_tool_schemas.py`) auto-covers the six surfaces — extend its enum/spot-check
   assertions for any new closed vocabulary.
10. Update all four documentation touchpoints + the test-count inventory (§ 9).
11. Bump the version (§ 10) and pass the quality gate (§ 11).
12. Write a **handback debrief** (§ 14) — required when the change ships behaviour a consumer or a
    future session depends on.

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

## 14. Handback debrief (required)

This repo's work arrives as a **hand-off brief** and should leave as a **handback debrief** — a
self-contained `<scope>-debrief.md` at the repo root, written for whoever picks up the thread next.
It is a **requirement**, not a courtesy: in the brief → implement → handback loop the consumer is
usually a *different* session (often another agent, e.g. the `claude-plugins` artifact author), who
has the brief and the code but **not** your session's context. The debrief closes that loop.

**When required.** Any change that ships behaviour a downstream consumer or a future session depends
on — a new/changed tool, a bug fix a consumer was blocked on, an additive field another artifact
reads. **Not required for** pure-internal refactors, formatting, or a change with no external
consumer (a clear commit message suffices). When in doubt, write one.

**A debrief is not a restatement of the diff or the commit message.** Four properties make it good:

1. **Honest about its verification boundary.** State what was actually run (which tests, lint) *and*,
   explicitly, what was **not** (e.g. a live smoke that needs a server restart, so you validated
   in-suite instead). Never imply a check that didn't happen — an overclaiming debrief is worse than
   none. This is the integrity core.
2. **Readable cold.** Self-contained; assume the reader has the brief and the code but none of your
   context.
3. **About decisions and gotchas, not the diff.** The compounding value is the *why* — especially any
   **deviation from the brief and why it's still correct** — and the non-obvious trap for the next
   author (e.g. "`DEPENDS-ON` upstream ids are matched by a digits-only regex, so blocked-test
   fixtures need numeric ids"; "a CHAT turn's title is the first line of the body, never a title
   field").
4. **Actionable at the seams.** The operational steps to activate it (restart, tag provisioning,
   ordering hazards) and what remains open — say **"consumer — no action"** explicitly when that's
   true.

**Shape** (frontmatter + these sections; drop any that don't apply — mirrors the § 7 enriched-docstring
shape):

- **Frontmatter** — `report_type`, `scope`, `implemented_by`, `derived_at`, `target_repo`, `artifact`
  (PR # + merge & feature commit + version), `relates_to` (the brief / designed-change / predecessor
  debriefs), `status` (`DONE` / `needs-restart` / `blocked`).
- **What shipped** — the behaviour delivered, in the consumer's language; a one-paragraph headline.
- **Design decisions & deviations** — the *why*, and any departure from the brief with its
  justification.
- **Membrane / activation** — steps to go live + any ordering hazard; whether it is additive /
  backward-compatible.
- **Verification done** — the gate that passed (test count, lint) **and** what was not run, with the
  reason.
- **Conventions** — a one-line map to the §§ that governed the change (esp. § 6 tag discipline, § 9
  lockstep, § 10 version).
- **Open items / handback** — what remains and who owns it.
- **Durable lesson / gotcha** — the trap the next author should not re-hit.
- **Footer** — the source-of-truth pointer (`CLAUDE.md` section + the relevant docstrings) + provenance.

Keep it **scannable**: a reader should get status + open items in ~10 seconds and the decisions in
~a minute. The debrief is a deliverable of the change (checklist item § 12.12) — commit it with the
change (or note in the PR why none is needed) and reference it in the PR description.

---

## Pull request process

1. Fork the repository.
2. Create a feature branch (`git checkout -b feat/<short-name>`).
3. Make your changes, conforming to the conventions above.
4. Pass the quality gate: `make test && make lint`.
5. Keep documentation in lockstep (§ 9) and bump the version (§ 10).
6. Write a handback debrief (§ 14) when the change is consumer-facing — commit it with the change (or
   note in the PR why none is needed) and reference it in the PR description.
7. Commit with a clear, conventional message; push to your fork; open a Pull Request.

Open an issue for discussion before making major changes.
