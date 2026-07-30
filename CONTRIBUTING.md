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

**This section is design of record, and as of v3.0.0 the whole suite conforms to it.** It was
frozen ahead of the Wave 1 build (designed change `2026-07-25-gtd-milkscript-retirement`, D6–D14)
so new tools are born conformant rather than renamed later; the 25 pre-existing non-conformant
names were renamed in Wave 2 (v3.0.0), where `gtd_query` also split into three. Those 25 old names
shipped as deprecated aliases for one release and were **removed at v3.1.0** (§ 2.8 keeps the
policy for the next rename).

**A conformance check enforces this, and it is not optional** (§ 2.7). The standard drifted within
four days of being frozen — `gtd_item_classify` shipped in Wave 1b as an imperative verb on a
read-only tool, in a wave whose own brief claimed conformance. It is `gtd_item_shape` from v3.0.0.
An unenforced convention is a remembered one, and this programme's whole thesis is that remembered
discipline fails silently.

### 2.1 The domain split (unchanged)

- **Bare verbs are generic RTM primitives** — each maps 1:1 to an RTM API method and speaks
  RTM's own language: `add_task`, `list_tasks`, `get_task_notes`, `set_task_priority`.
- **A `<domain>_` prefix marks a domain composition** — a domain-shaped view over RTM data that
  does *not* map 1:1 to an RTM method. Current domain: `gtd_`.
- Reading the tool list, the split is instant: no prefix = RTM primitive, `<domain>_` = domain
  view. This keeps a future lift of all `<domain>_*` tools into a separate server a clean,
  mechanical move.

### 2.2 CQS is the grammar (D6)

Meyer's Command–Query Separation, with the CQRS naming convention: **commands are named for the
operation, queries for the thing returned.** The name must answer *will this change my data*
before the description is read.

### 2.3 Noun-first, aggregate-grouped (D7, D12)

**`gtd_<area>_<operation>`.** At 40-plus tools and growing, *finding* a name beats *reading* one,
so related operations sit adjacent alphabetically (as AWS and Stripe do at this cardinality).

The first segment names a domain **area**, which may be an aggregate root (`item`, `project`,
`note`, `surface`, `canvas`, `chat`, `engage`, `dependency`, `cluster`) **or a lifecycle stage**
(`inbox`, `waiting_for`) — a deliberate decision (D12), not an inconsistency: grouping follows how
the work is actually done, which is what a reader scanning for a tool is looking for.

The acknowledged cost, recorded as a trade rather than an oversight: `gtd_inbox_capture` (was
`gtd_capture`) gives up the best name in the suite by ubiquitous-language standards — Allen's own
verb, reading exactly as Paul would say it — to buy grouping.

**Twelve areas**, one added after the standard was frozen: `contribution`.
`gtd_contribution_attach` and `gtd_contribution_transition` are two operations on one domain
object, and splitting them across `note` and `contribution` would have put siblings in different
places — the precise outcome aggregate grouping exists to prevent. A contribution has a
**lifecycle** (the six-state machine in `contribution.py`), which is what D12 asks of an area; the
note is its *storage*, not its identity.

**`gtd_note_attach_output` stays under `note`, and the asymmetry is deliberate.** An output has no
lifecycle — it is filed, journalled, and done. There is no state machine to hang an aggregate on,
so grouping it with the note machinery is correct rather than inconsistent.

### 2.4 Granularity is explicit (D10)

**The test every name must pass: from the name alone, can you tell whether it touches one thing or
many?** Aggregate grouping improves findability and regresses scope legibility — `gtd_inbox_close`
(one item) and `gtd_inbox_drain` (the whole list) would sit adjacent looking like siblings. On the
write side that is the more dangerous confusion: mistaking a query for a command wastes a call;
mistaking a single-item close for a list drain empties the inbox.

| Scope | Marker | Examples |
|---|---|---|
| One entity | entity segment, where the area noun alone is ambiguous | `gtd_inbox_item_close`, `gtd_item_create`, `gtd_surface_create` |
| Many entities (write) | `_batch`, or an inherently-plural verb (*sweep*, *drain*) | `gtd_item_transition_batch`, `gtd_inbox_drain`, `gtd_waiting_for_sweep` |
| Collection (read) | result-noun suffix — `_queue`, `_state`, `_index`, `_candidates`, `_report`, `_gaps` | `gtd_surface_queue`, `gtd_inbox_state`, `gtd_focus_index`, `gtd_engine_report` |

The collection-read tier already conformed before the standard existed — that convention emerged
unaided and every query obeys it. The gap was entirely on the write side.

### 2.5 `item` is an umbrella — use it only when the tool is genuinely one (D13)

`gtd_item_create`'s own schema settles the vocabulary: `kind: action | waiting_for |
calendar_entry`, with *"(A project is created with `gtd_project_create`.)"*. **Item** means those
three kinds; **project** is a peer, not a member.

> Use `item` only when the tool genuinely spans item kinds. Use the specific entity noun
> (`action`, `project`, `waiting_for`, `calendar_entry`, `focus`) when it does not.

Applying it found errors in both directions. `gtd_complete_action` handled all three kinds despite
its name and became **`gtd_item_complete`** — a correctness fix, not a style change. And a
context-organised next-actions read must **not** claim the umbrella (a waiting-for is not a next
action), so `gtd_next_actions` keeps its bare form as a deliberate ubiquitous-language exception,
like the `*_candidates` family: *Next Actions* is the canonical GTD list name and prefixing it
degrades it.

### 2.6 A scope parameter is fine; a mode parameter is a tool boundary (D11)

> If changing a parameter changes (a) which *other* parameters are valid, (b) the *return shape*,
> or (c) the *error branches* — it is a tool boundary, not a parameter.

`gtd_surface_queue(surface: questions | activity | both)` **passes**: one row shape, one parameter
set, one error set, and `both` is load-bearing because the scan processes both lists per run.
`gtd_query(perspective: …)` **fails all three** — `context` is valid only for one perspective,
`focus` only for another, rows carry different fields per perspective, and `focus_not_found`
applies to one branch. It is three tools wearing a trenchcoat, and Wave 2 splits it.

The same rule is why an aggregation is a `_report` and a row list is not: `gtd_workload_report`
returns life-context × workflow-state totals, not rows, so it belongs beside `gtd_health_report`
and `gtd_engine_report` rather than as a `gtd_query` perspective.

### 2.7 Enforcement (D9) — `scripts/check-tool-naming.py`

Conventions without enforcement drift; the pre-existing exceptions were the proof, and
`gtd_item_classify` drifting four days after the freeze is the proof that the proof was not
enough. The check flags any tool whose **name form disagrees with its `readOnlyHint` annotation**
— an imperative verb segment on a read, or a result-noun suffix on a write.

Run it with `make naming` (or `uv run python scripts/check-tool-naming.py`). It introspects the
live server, so it can never drift from what is actually advertised.

**Blocking since v3.1.0**, and part of `make lint`. It ran report-only through v3.0.x because it
could not block: the deprecated aliases *were* the non-conformant names, so it fired on all 26 by
construction. With them gone, `--strict` exits non-zero on any finding.

**The rule that matters most: a name matching neither lexicon is reported as `unclassifiable`, and
NEVER silently passes.** A check that quietly passes what it does not recognise is the same silent
control this programme has now found five times over, and it is exactly how a novel verb would
escape. `tests/test_tool_naming.py` asserts the check FIRES on a known-bad fixture and on an
unrecognised one — a conformance check that reports zero findings because it skipped everything is
worse than no check at all.

### 2.8 Deprecated aliases — the policy, and the one time it was used

**No aliases are live.** The 25 renames plus `gtd_query` shipped as deprecated aliases at v3.0.0
and were removed at v3.1.0. This section is the policy for the next rename, not a description of
anything currently exposed.

When a rename does happen, retain the old name for **exactly one release**:

- An alias is a **thin registration of the same function** under the old name
  (`mcp.tool(name=…)`), never a copied body. One code path per tool.
- Its description opens `DEPRECATED — renamed to <new> in vX.Y.0; this alias is removed in
  vX.(Y+1).0.`
- Aliases are **excluded from every tool count** — README tables, spec inventories, architecture
  docs.
- Every alias invocation logs at `WARNING` (§ 7a).
- **Removal is gated on enumerating the callers, not on watching a log.** The v3.1.0 removal
  checked the marketplace repo, the scheduled-task specs, and — decisively — the *rendered* live
  artifacts. A rendered artifact is a **frozen copy** of its template, so it is a live caller that
  no repo grep can see: the standing board held four old names in both its code and its
  `mcpTools` allowlist, seven days after the template had moved on. **Ask "rendered or source?"
  before concluding a rename has no callers.**
- Why they exist at all: not for external callers but for **cross-repo sequencing**. Server and
  consumers live in separate repos behind an async hand-off, so one is always ahead of the other
  — and *either* order breaks without them.

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

**Since v3.3.0 the six surfaces sit inside the three-tier Tool Affordance Model** (family standard
§§ 4.1a / 9 / 10 — *description budget & front-loading*, *server-level surfaces*, *the affordance
model*). The six surfaces say what the documentation CONTAINS; the affordance model adds *which
surface a fact belongs on*, ranked by what guarantees the model reads it:

| Tier | Surface | Carries | Budget |
|---|---|---|---|
| **1 — select** | `name`, the description's **front block**, `instructions`' front | `<Domain> — purpose`; when-NOT / "use X instead"; **write-safety posture**; a one-line combination hint | ~2 KB is all the client keeps |
| **2 — detail** | the description's tail, the fetched schemas, `rtm_tool_help` | full multi-case `Returns`; combination rules; worked examples; operator tables | ≤ 25 KB result |
| **3 — teach** | the one guided-rejection shape | purpose, typed params, nearest-name guess, violated rule, help pointer | the rejection body |

Three rules follow, and they are enforced by `TestSelectionSurfaceBudgets`:

- **Front-load.** Order every description (and `instructions`) by *need-to-select-and-call-safely*
  first, *need-to-get-the-details-right* second. Legal disclaimers and exhaustive `Returns` go last.
- **Safety in the front block.** A destructive / irreversible / governed fact must appear inside the
  first ~2 KB — **never only in `annotations`**, which this client does not render to the model.
  Where a description must exceed the budget (see below), this is the guarantee that replaces it.
- **The budget yields to § 7, on the record.** § 7 requires a multi-case `Returns` and an `Args:`
  section, and the `_FullDocstringMCP` shim advertises the whole docstring — so a complex governed
  write cannot both fit 2 KB and obey § 7. § 7 wins; add the tool to `OVER_BUDGET_EXEMPTIONS` in
  `tests/test_tool_schemas.py` **with its reason**, and the posture-in-front assertion still applies.
  Do not delete § 7-mandated content to hit the number.

**Never author a fact twice across tiers.** `rtm_tool_help` is a *projection* of the live advertised
schema (`tool_help.py`), and `tests/test_tool_help.py` asserts the projections agree. If you add a
tool, you add no help record — the index and contract derive themselves, provided the description
opens `<Domain> — <purpose>`. Only genuinely new material is authored: a combination rule, a worked
example, a chain edge, or BFF membership.

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
   fix for scalars, and **zero union-advertising params now remain** — `TestSingleTypedParameters`
   pins that unconditionally. The last holdout was `set_task_priority.priority`, a required
   `str | int` (genuine: `priority_to_code` does `str(priority).lower()`). It now advertises the
   STRING form via `tool_params.required_string` — narrower than what the handler accepts, never
   wider, so schema-conformant calls all work and the integer aliases keep working. Narrowing the
   *annotation* would have been breaking: pydantic rejects `int` under a bare `str`.
3. **Register through the shim, never the raw `mcp`.** `server.py` wraps the FastMCP instance in
   `_FullDocstringMCP`, which passes each tool's full `inspect.getdoc(fn)` as `description=`.
   Without it, FastMCP 3.x keeps only the docstring's first text section and drops `Args:` /
   `Returns:` / the caveat blocks — **42% of this server's tool documentation** (see `CLAUDE.md`
   § "FastMCP 3.x"). A new tool group registered against `mcp` directly silently loses its prose.
4. **Behaviour annotations** — `@mcp.tool(annotations=…)` via the three constants in
   `response_builder.py`: `READ_ONLY_ANNOTATIONS` (reads), `ADDITIVE_WRITE_ANNOTATIONS` (creates /
   additive field-tag updates / undo path), `DESTRUCTIVE_WRITE_ANNOTATIONS` (deletes and reachable
   removes — e.g. the canvas/engage commit tools, even though `undo` can reverse them; classify
   honestly and put the undo path in the docstring). `openWorldHint=True` everywhere (RTM is SaaS).
   Hints are signals, **not** enforcement — the strict-tag gate / `confirm_destructive` / actionable
   errors stay the sole safety authority.
5. **Input constraint metadata** — for a closed-vocabulary / bounded / structured param, add
   `json_schema_extra={"enum": …}` (a module-level `dict[str, Any]`, required by pyright) **sourced
   from the canonical constant** it validates against (`PRIORITY_INPUT_CODES`, `MOVE_DIRECTIONS`,
   `VALID_SCOPES`, `VALID_ROLES`, `VALID_MODES`, `VALID_EXECUTE_COMMIT`, `VERDICT_FAMILY`), so the
   advertised set can never drift from the handler. **Ownership rule:** only advertise vocabularies
   the *server* owns — **never** a tag enum (deliberately non-canonical server-side; gtd's
   `tag-taxonomy.md` owns it) or a list-name enum (account data).
6. **Output schema** — `output_schema=` from `models.py` (schema-only Pydantic models; NOT used at
   runtime). `data` is always advertised as the `success | ErrorData` union (`anyOf`). Match models
   to the actual returns; leave genuinely-open payloads (`raw`, evolving envelope rows) open.
6. **Typed errors (recovery half)** — every failure carries a stable `code` from the canonical
   `error_codes.ErrorCode` registry (§ 5), modelled as `ErrorData` → `ErrorBody`
   (`{code, message, rtm_code, details}`, `extra="forbid"`). Recovery material rides under
   `details` (`strict_tag_mode`/`how_to_proceed`; `candidates`), and the commit engines'
   `rejected[].reason` enums are drawn from the same registry. **Reuse an existing code wherever
   one fits; add a new member only for a genuinely new failure** — and never rename a shipped one
   (additive-only).

## 4. Response envelope

Every tool returns the standard envelope via `response_builder.py`:

```python
{
    "data": {...},                      # main payload (or {"error": {code, message, …}} — § 5)
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

### 4.1 The teaching receipt (governed `gtd_*` writes, since v4.0.0)

Every governed write's **success** payload additionally carries three fields. They are attached
**centrally** by `tools/gtd.py::_tool` (via `receipt.py`), so you do not write them — but you must
know they exist, because one of them is yours to populate:

```python
{"not_applied": [{"op", "id", "requested", "reason", "detail"}],   # always present, [] when clean
 "guidance": "…next step…" | None,                                  # derived from the payload
 "advisory": "…no optional parameter arrived…" | None}              # derived from the call
```

**Why it exists.** The hosted client deletes an undeclared argument before this server sees it
(`middleware.py`), so a misspelt *optional modifier* produces a silent partial write: the item lands
without the property and success is reported. Nothing server-side can detect that — so the receipt
makes the **outcome** unmissable instead of trying to catch the input.

Rules when writing or changing a governed write:

- **Populate `not_applied[]` wherever the tool knowingly writes nothing** for something the caller
  asked for — a tag already present, an idempotent skip, a verdict with no durable write. Use
  `receipt.not_applied_entry(...)`, put the list in your `data`, and the wrapper leaves it alone.
  If you find yourself appending to `applied[]` with `transaction_id: None`, that entry belongs in
  `not_applied[]`: `applied[]` means *a write happened*.
- **`reason` comes from `receipt.RECEIPT_REASONS`** (`no_change` / `no_durable_write` /
  `not_eligible`) — the fourth scoped view of the one `ErrorCode` registry (§ 5). These are
  **outcomes, not failures**; never let one reach an `error.code`. A test derives the call sites
  from source and fails on any other code.
- **Never gate on the receipt.** It is advisory data. A caller that ignores all three fields must
  still get a correct, complete result — that is an invariant, not a preference, and
  `tests/test_receipt.py` pins that the module is a pure leaf with no async and no client import.
- **An error envelope carries no receipt.** `data.error` is the `success | error` discriminator and
  a failure already teaches; `receipt.attach` returns it untouched.
- **Reads get nothing.** "Did what I asked for land?" has no meaning for a tool that writes nothing.
- **Documentation is already handled** — the description block, the `rtm_tool_help` contract and the
  `outputSchema` all derive. Use `models._write_envelope_schema` (not `_envelope_schema`) for a new
  governed write's output schema and the three fields appear; a test iterating the real server
  fails if you forget.

## 5. Error handling — the typed vocabulary

Since **v2.0.0** every envelope error is a **structured object** carrying a stable,
machine-branchable `code` from the canonical registry in **`error_codes.py`**:

```python
{"error": {"code": "task_not_found",
           "message": "Task not found: 'Buy milk'. Use list_tasks to search by filter…",
           "rtm_code": None,
           "details": {"query": "Buy milk"}}}      # details omitted entirely when empty
```

**Never construct this by hand** — use the single constructor so the shape cannot drift:

```python
from ..error_codes import ErrorCode
from ..response_builder import build_error, error_from_exception

return build_response(data=build_error(
    ErrorCode.TASK_NOT_FOUND,
    f"Task not found: '{name}'. Use list_tasks to search by filter or check spelling.",
    query=name,                       # **details — any optional per-family keys
))
# in an `except` block, to map the RTM numeric automatically:
return build_response(data=error_from_exception(exc))
```

Rules:

- **`code` is the contract.** Consumers branch on it. It is a member of `ErrorCode`, never a
  string literal at the call site.
- **`message` is for humans and must never be parsed.** Keep it **actionable** — name the next
  tool to call. Never a bare "not found"; say what to do next. (Prose is free to be reworded in a
  patch release precisely *because* nothing branches on it.)
- **`rtm_code`** carries the originating RTM numeric where there is one, so the transport fact
  survives without leaking into the semantic code name.
- **Optional keys go under `details`** (`candidates`, `how_to_proceed`, `strict_tag_mode`,
  `query`, …). `ErrorBody` is `extra="forbid"` — the top level is a closed four-field contract.
- **The registry holds OUTCOMES, not only failures** (v4.1.0). It also carries the receipt's
  `not_applied[].reason` vocabulary (`no_change` / `no_durable_write` / `not_eligible`), which
  describes operations that wrote nothing on an otherwise-**successful** call. **The
  discriminator is the field, not the registry:** a code in `not_applied[].reason` is an
  outcome; a code in `error.code` is a failure. Never let an outcome member reach `error.code` —
  `tests/test_receipt.py` enforces it.
- **The registry is ADDITIVE-ONLY.** A new outcome gets a new member; a shipped code is never
  renamed or removed. (The v2.0.0 envelope restructure was a one-time break, not a licence to
  mutate the registry.)
- **Two error shapes, one governed here.** This section covers the *envelope* error and the
  commit engines' `rejected[].reason`. It does **not** cover the per-op `data.errors[]` list that
  batch tools attach to an otherwise-*successful* envelope (`{"op", "id", "error": str(exc)}`) —
  a different contract reporting partial failure. Leave it flat.

The transport layer is unchanged underneath: `raise_for_error()` in `exceptions.py` maps RTM
numerics to typed exceptions (`RTMAuthError`, `RTMValidationError`, …) via `ERROR_CODE_MAP` and
appends recovery hints from `ERROR_GUIDANCE`. `error_codes.RTM_CODE_MAP` maps the same numerics to
semantic codes; a test asserts the two key sets stay equal, so neither can fall behind the other.

**One vocabulary, three scoped views.** The commit engines each advertise a closed
`rejected[].reason` enum (`COMMIT_REJECT_REASONS`, `CREATE_REJECT_REASONS`,
`ENGAGE_REJECT_REASONS`). These are frozensets **of `ErrorCode` members**, declared next to their
handlers so per-tool scoping stays honest while any given reason is spelled exactly once. Three of
them (`off_enum`, `unknown_kind`, `type_illegal`) are **grammar-bound** — they mirror gtd's
`validate-engage-verdict.py` under the ratified `engage-verdict-grammar.md`, so re-spelling them is
a lockstep change to both repos. Never edit one side alone.

## 6. Write gates

Three deterministic **write-boundary gates** refuse a malformed write at the server, so the
discipline becomes an invariant no agent, session, or scheduled engine can forget. They share
one shape: a pure-policy module, a config flag, an early return before any RTM call.

| Gate | Module | Flag | Default | Codes |
|---|---|---|---|---|
| Tag existence | `strict_tags.py` | `RTM_STRICT_TAGS` | **on** | `strict_tag_rejected` |
| Note-title grammar | `note_shape.py` | `RTM_STRICT_NOTES` | **`shape`** (since v5.1.0) | `note_shape_rejected` |
| List-target writability | `list_targets.py` | `RTM_STRICT_LIST_TARGETS` | **on** (since v5.1.0) | `smart_list_target`, `locked_system_list` |

**All three are now enabled.** The two that shipped off were switched on in v5.1.0, once the file
sink (§ 7a) made an inert gate distinguishable from a working one that never fires — until then
they were identical in every observable respect, which is a poor state to leave a control in.
`strict_notes` went **straight to `shape`, skipping the designed `warn` stage**: `warn` is
log-and-allow, so with stderr at `/dev/null` it neither blocked nor recorded and the middle step
did not exist in production. The live sample justified the skip — every agent-written title in it
already parses, including the legacy `ACTIVITY` / `AR` / `ACTIVITY REPORT` spellings (a space is
legal in a TYPE token).

**Enabling a gate does not change where it is wired, and that boundary is load-bearing.**
`note_shape` governs the generic `add_note` / `edit_note` **only** — the escape hatch, which is
where drift enters. Every `gtd_*` tool writes notes by calling `rtm.tasks.notes.add` directly, and
several legitimately write a bare marker title (`DEPENDS-ON`, `INCEPTION`, `REDACTION`,
`TMPL-STAMP`) that this grammar would reject. Do **not** "fix" that by widening the wiring: those
titles are round-tripped by `project_plan._extract_deps_and_files`.

**The governing rule — the server enforces mechanical SHAPE; the plugin owns VOCABULARY.**
This is the § 4.4 ownership split, and it is the reason each gate stops where it does:

- Tags — the server checks a tag **exists in the account**; whether it is the *canonical* tag is
  gtd's `validate-tags.py`. (Tag canonicality is a deliberate **non-goal** here, not an omission.)
- Notes — the server checks the title **parses** as `YYYY-MM-DD [HH:MM] — TYPE — summary`;
  whether TYPE is a *canonical* type is gtd's `note-shape-catalogue.md` § 2 +
  `validate-note.py`. A well-shaped title with an unknown TYPE **passes here by design**.
- List targets — the server refuses a list RTM itself flags `smart` or `locked`; whether a
  *writable* list is the **right** target (Inbox_Stuff as sole capture point, Processed as
  gtd-internal) is gtd's `list-catalogue.md` + `validate-list-target.py`.

If implementing a check would require the server to know a gtd-owned value, it belongs
plugin-side — stop and flag it. Do not add a taxonomy or import one into the server.

**Rules when adding to or wiring a gate:**

- Gate **before** the RTM call and before any resolver that costs an API call, and return
  `build_response(data=err)`. A gate that still writes is not a write boundary — assert the
  zero-call property in the test.
- **Never** gate an operation that *reduces* entropy (tag removal is the standing example).
- **Default off** for a *new* gate, and ship the enable decision separately (v5.1.0 is what that
  second step looks like). Flags-off must reproduce prior behaviour byte-for-byte **for the life
  of the gate**, not just during the bake-in: that revert is the whole rollback plan for an
  enabled gate, so it is asserted per gate rather than assumed.
- **A gate's recovery guidance names its own default.** When you flip one, the `how_to_proceed`
  text flips with it — both gates shipped v5.1.0 telling callers to *unset* the env var to
  disable, which after the flip is advice to do the thing that leaves it on. Asserted by test.
- **Reject deterministically and recoverably**: a stable `error.code` plus `how_to_proceed`
  under `error.details`, never prose alone. Point recovery at the plugin for vocabulary.
- **Reuse an existing `ErrorCode`** where the concept already has one (the list-target gate
  reuses `smart_list_target` / `locked_system_list`). Minting a synonym recreates exactly the
  drift the unified registry removed.
- Register any new gate helper in `_HELPER_CODES` (`tests/test_tool_schemas.py`) so the
  advertised-error-contract guard knows which codes it surfaces on a caller's behalf.
- Test three paths per gate: **accept**, **reject** (correct code + guidance + nothing written),
  and **flag-off inert**.

## 7. Source style

- **Python ≥ 3.11.** Use native unions and builtin generics (`str | None`, `dict[str, Any]`,
  `list[str]`).
- **`from __future__ import annotations` — allowed in pure modules, NEVER in a schema surface.**

  | Layer | Rule |
  |---|---|
  | **Pure, no-IO builders** (`gtd_writes`, `gtd_reads`, `detectors`, `engage_*`, `companion`, `surface_queue`, `engine_report`, `tag_report`, `gtd_reports`) | **Allowed** — the established convention; match the file you are working beside |
  | **Schema surfaces** (`tools/*.py`, `models.py`, `server.py`, `tool_params.py`) | **Do not add it** |

  *Why the split is real, and why it is not the reason this rule originally gave.* PEP 563 turns
  every annotation into a string, and FastMCP/pydantic must resolve those at runtime to build the
  advertised JSON schema. Resolution happens against **module** globals — so a **function-scoped**
  annotation becomes an unresolvable forward reference. Every tool is registered *inside*
  `register_<group>_tools(...)`, which makes that scope the normal place to define a shared
  `Annotated` alias, and the failure is immediate:

  ```
  NameError: name 'LocalRef' is not defined      # raised from list_tools() → schema generation
  ```

  Measured 2026-07-25 on fastmcp 3.4.4: a module-level annotation resolves fine under the import
  (injecting it into `tools/gtd.py` produced **byte-identical** advertised schemas), and a
  function-scoped alias raises. So the risk is latent rather than theoretical — the tool modules
  work today only because their `Annotated` params happen to reference module-level names, and the
  first function-scoped alias anyone adds breaks registration.

  It fails **loudly**, which is the one mercy — but it fails at server start, so keep the import
  out of the schema surfaces rather than relying on catching it. (The rule previously read *"do
  not add it — no existing `src` module uses it"*, which was true when written on 2026-06-20 and
  had been overtaken by six modules; it also pointed at the wrong hazard.)
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

## 7a. Logging

Configured once in `server.configure_logging()`, called from `main()`. Scoped to the **`rtm_mcp`
logger tree**, not root, so importing this package as a library never hijacks a host
application's logging. Level `INFO`, overridable with **`RTM_LOG_LEVEL`**.

**The handler writes to `stderr`. Never `stdout`.** This is a stdio MCP server: stdout carries the
JSON-RPC protocol stream, and a handler there corrupts it and breaks the server outright.
`logging.StreamHandler()` defaults to stderr, so call it with no argument — the failure mode is
only if someone passes `sys.stdout`. `tests/test_logging.py` asserts this.

**…and stderr alone reaches nobody, so there is also a file sink (v5.1.0).** On a Desktop-spawned
server **fd 2 is `/dev/null`** (measured with `lsof` + `stat`), so every record the stderr handler
writes is destroyed. Interactively that is merely redundant — the caller already gets a typed
error — but in a **headless flow** the error goes to an *agent*, which handles or retries it, and
Paul never learns it happened. A gate firing repeatedly inside a 06:45 scheduled worker was
invisible.

So a bounded `RotatingFileHandler` (1 MiB × 3 backups) writes to **`~/.config/rtm-mcp/logs/`** —
a sibling of the existing `config.json` state, overridable with **`RTM_LOG_DIR`**. Deliberately
**not** the repo clone: the launch config is `uv run --project <clone>`, so the process *can*
write there, but logs in a working tree mean `.gitignore` maintenance, `git status` noise, and a
real chance of committing them. It is attached **alongside** stderr, never instead of it, and an
unopenable sink degrades to a WARNING rather than stopping the server.

**Test the sink under the condition that motivated it.** An in-process test asserting "the record
was emitted" passes against a server with no sink at all — the same vacuity § 7a already warns
about one paragraph down. `tests/test_logging.py` runs a real gate in a **child process with fd 2
redirected to `/dev/null`** and asserts the file received it, plus the counterfactual: with the
sink unopenable the gate still fires and leaves no trace anywhere.

**Choose the level by asking what happens if the configuration is lost.** `INFO` and `DEBUG`
require configuration to exist in order to emit; `WARNING` and above emit through logging's
`lastResort` fallback with none. That is not academic — **this repo shipped with no logging
configuration at all until v3.0.1**, and six of nine log statements were silent for their entire
lives, including all three write-boundary gates and the deprecated-alias record that gates a
release decision.

So:

- **A record that is a control's ONLY output belongs at `WARNING`.** The three gates and the alias
  records are the current examples: nothing else observes them, so a level that needs
  configuration makes the control unobservable and its silence indistinguishable from a clean
  estate.
- **`DEBUG` is for genuine noise** — `client.py`'s raw API responses are the example, and are
  deliberately left there.
- **`INFO` for routine operational records** that have another observable effect anyway.

**Test emission, never existence.** A test asserting the call site exists, or grepping the source
for the message, passes against a server that records nothing — that is the bug's exact shape.
Assert on the record reaching a handler (`caplog`), and do **not** call `caplog.set_level` for the
logger under test: setting the level configures the very thing being tested, so the test would
pass against a broken configuration.

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
3a. **Meet the affordance obligations** (§ 3, the three-tier model). Open the docstring
   `<Domain> — <purpose>` (`RTM — ` for a primitive, `GTD — ` for a domain composition) — the tier-1
   shape is asserted, and it is what makes the tool appear correctly in `rtm_tool_help()`'s index
   with no help record to write. Put the write-safety posture in the **front ~2 KB**, not only in
   `annotations`. If the description must exceed the budget, add a reasoned
   `OVER_BUDGET_EXEMPTIONS` entry rather than cutting § 7-mandated content. Author a
   `tool_help.COMBINATION_RULES` entry for any rule the JSON schema cannot express, and an
   `EXAMPLES` entry if a parameter is nested or JSON-coerced. A new `ErrorCode` also needs a
   `tool_help.RECOVERY` hint (asserted).
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
