---
report_type: handback-debrief
scope: rtm-mcp — tool-documentation uplift (the six-surface LLM-effectiveness standard)
implemented_by: Claude Code (Opus 4.8) — session 2026-07-18
derived_at: 2026-07-18
target_repo: ~/Documents/Code/rtm-mcp (github.com/pauleastabrook/rtm-mcp)
artifact:
  branch: feat/tool-documentation-uplift  # based on feat/engage-commit-steer-note (v1.32.0)
  commits:
    - 07f768b  # six-surface uplift on all 56 tools (models.py, annotations, Field descs, enums, test)
  version: 1.32.0  # UNCHANGED — additive schema metadata, no behaviour/return/capability change
status: shipped-branch-green   # 938 tests, ruff+pyright clean, stdio wire-verified; awaiting CI on push
audience: a Cowork session / the gtd wrapping skill — see § "Behavioural implications" + § "Wrapper delta list"
---

# Handback debrief — rtm-mcp tool-documentation uplift

## Status in 10 seconds

All **56** `rtm-mcp` tools now expose the **full six-surface model-facing documentation surface** —
rich descriptions, per-parameter descriptions, behaviour annotations, input constraint metadata
(enums sourced from the canonical constants), and **output schemas** (`data` = `success | error`
union) — so a calling LLM can choose, call, chain, and recover from the schema alone, and the gtd
wrapper can **cite** the advertised schema instead of maintaining shadow docs. **Additive schema
metadata only: no runtime/return change, no new capability, no version bump (stays 1.32.0),
backward-compatible** (the legacy text-JSON result block is still emitted alongside the new
`structuredContent`). 938 tests (was 921 — +17 schema-contract tests), ruff + `ruff format --check`
+ pyright clean, **stdio JSON-RPC wire-verified**. **No Claude Desktop restart is required for
correctness**, but a restart refreshes the schemas a client has cached (so annotations/enums/output
schemas reach the model).

## Verification boundary (what ran; what didn't)

**Ran, green:**
- `uv run pytest` — **938 passed** (the 921 pre-existing tests unchanged — returns are identical —
  plus `tests/test_tool_schemas.py`, 17 tests, pinning all six surfaces + enum equality to the
  canonical constants).
- `uv run ruff check src tests` — all passed; `uv run ruff format --check src tests` — clean;
  `uv run pyright src` — **0 errors, 0 warnings**. (Dev tooling is exact-pinned `ruff==0.14.14`,
  identical to CI.)
- **Stdio JSON-RPC wire check** (subprocess `uv run rtm-mcp`, raw JSON-RPC): `tools/list` returns
  56 tools carrying annotations (readOnly on reads, destructive on the commit tools), enums
  (`priority`, `execute` value space), clean single-typed complex-param schemas with descriptions,
  and an `outputSchema` whose `data` is an `anyOf` union. `tools/call` emits BOTH the legacy
  `content[0].text` JSON block AND `structuredContent`, and **they agree** — on a real success
  (`get_lists`, 38 lists via the live RTM API) AND on a graceful error (`gtd_project_plan` with no
  args → `isError:false`, `data.error` present, both blocks agree).

**Not run:** the live RTM write/undo smokes (behaviour unchanged; the schema layer is additive and
FastMCP does not validate returns). **Not done:** no in-app Claude Desktop exercise (the raw
JSON-RPC covers the wire). CI has not yet run at time of writing (push pending); every step CI runs
was reproduced locally on the pinned toolchain.

## The six surfaces — mechanisms

| # | Surface | Mechanism | Where |
|---|---------|-----------|-------|
| 1 | Enriched description | pre-existing § 7-shape docstrings (verified, not rewritten) | tool docstrings |
| 2 | Per-parameter description | `Annotated[T, Field(description=…)]`; complex coercion params bake the description into `WithJsonSchema` via new `tool_params.coerced_*_schema(...)` builders | tool signatures + `tool_params.py` |
| 3 | Behaviour annotations | three constants + `@mcp.tool(annotations=…)` | `response_builder.py` |
| 4 | Input constraint metadata | `json_schema_extra` enums sourced from canonical constants | tool signatures + `gtd.py`/`tasks.py` module constants |
| 5 | Output schema | `@mcp.tool(output_schema=…)`; schema-only Pydantic models | new `models.py` |
| 6 | Typed errors (recovery half) | `ErrorData` (`error: str`, `extra="allow"`) modelled as-is | `models.py` |

Enforced by `tests/test_tool_schemas.py` (introspects the REAL `rtm_mcp.server.mcp`). CONTRIBUTING
§ 3 (new six-surface subsection) + § 7 + § 8 + § 12 and CLAUDE.md (tree, module table, test
inventory) updated, citing the family standard.

### Behaviour annotations (surface 3) — per tool

Three module-level constants in `response_builder.py`; `openWorldHint=True` everywhere (RTM is
SaaS). `idempotentHint` is conservatively `False` on both write constants (a naturally-idempotent
write like `set_task_name` documents that in its docstring, not the annotation).

```
READ_ONLY (readOnly=T, idempotent=T)      : list_tasks, get_lists, get_tags, get_locations,
    get_settings, parse_time, get_timeline_info, get_contacts, get_groups, get_rate_limit_status,
    get_task_url, get_list_url, test_connection, check_auth, get_task_notes,
    gtd_project_plan, gtd_project_canvas, gtd_project_index, gtd_chat_thread, gtd_chat_inflight,
    gtd_engage_seed
ADDITIVE_WRITE (readOnly=F, destructive=F): add_task, complete_task, uncomplete_task, set_task_*,
    move_task_priority, postpone_task, move_task, add/remove/set_task_tags, set_parent_task,
    add_note, edit_note, add_list, rename_list, archive_list, unarchive_list, set_default_list,
    undo, batch_undo, gtd_create_project, gtd_stamp_tokens, gtd_chat_post, gtd_set_redaction
DESTRUCTIVE_WRITE (readOnly=F, destructive=T): delete_task, delete_list, delete_note,
    gtd_apply_canvas_commit, gtd_apply_engage_commit
```
The two commit tools are marked destructive because `completes`/`removes` (canvas) and `drop`
(engage) are reachable; both gate destruction behind `confirm_destructive` and the whole batch is
`batch_undo`-reversible — documented in the docstrings, not softened in the annotation.

### Input constraint metadata (surface 4) — enum sources

Every advertised enum is `sorted(<canonical constant>)`, so it can never drift from what the handler
validates (`tests/test_tool_schemas.py` asserts equality):

```
set_task_priority.priority        : sorted(parsers.PRIORITY_INPUT_CODES)   # 0/1/2/3/high/low/medium/n/none
move_task_priority.direction      : list(tasks.MOVE_DIRECTIONS)            # up, down
gtd_apply_canvas_commit.scope     : sorted(canvas_commit.VALID_SCOPES)     # instant, item, plan, project
gtd_apply_canvas_commit.execute   : additionalProperties enum = sorted(VALID_EXECUTE_COMMIT)  # later,now,off,quick
gtd_chat_post.role / .mode        : sorted(gtd_chat.VALID_ROLES) / sorted(gtd_chat.VALID_MODES)
gtd_apply_engage_commit.items[]   : items.properties.verdict enum = sorted(engage_commit.VERDICT_FAMILY)
```
Enabling refactor: `priority_to_code`'s local `mapping` lifted to the module constant
`parsers.PRIORITY_INPUT_CODES` (behaviour-preserving — the function reads from it now). The read-side
word/code maps (`canvas_seed._PRIORITY`, `project_plan._PRIORITY_WORD`, `project_index._PRIORITY_CODES`)
were left alone: they convert RTM's stored word-forms, a different fact — not copies of the input
vocabulary. **No tag enum and no list-name enum** are advertised (plugin-owned taxonomy / account
data — the ownership rule).

### Output schema (surface 5) — the envelope + success payloads

Every tool advertises `{"data": <success> | ErrorData, "metadata": Metadata, "analysis"?: {...}}`.
`data`'s `anyOf` is asserted for all 56 tools. `ErrorData` = `{error: str}` with `extra="allow"` (so
`strict_tag_mode`/`how_to_proceed`/`candidates`/`rejected` siblings ride along truthfully). Models
live in `src/rtm_mcp/models.py`, are **schema-only** (never used at runtime), and keep deeply-nested
/ versioned-external / evolving payloads open (`extra="allow"` / `dict[str, Any]`). Highest-value
success shapes (the wrapper's citation targets):

```
gtd_project_plan   : ProjectPlanEnvelope | Candidates  — {header: PlanHeader{type, schema
                     ("project-plan-seed/3"), projectId, project{id,name,life,listId,permalink,
                     notes[],files[],redacted,is_repeating,taskseries_id}, rowCount},
                     rows: [PlanRow{type,id,name,priority,completed,completedDate,due,tags[],
                     permalink,deps[],files[],noteCount,notes[],estimate,start,url,is_repeating,
                     taskseries_id,template_child_id}]}
gtd_project_canvas : CanvasSeedResult | Candidates  — {mode, frame{life,focus,name,url,redacted,
                     notes?,files?}, seed:[CanvasSeedRow{id,k,t,redacted,+short keys}]}
gtd_project_index  : {projects:[ProjectRow], foci:[FocusRow], actions:[ActionRow]} (full field lists
                     match the docstrings; ActionRow carries the engage fields estimate/contexts/
                     energy/exec + redacted)
gtd_apply_canvas_commit : CommitResult{project_id?, applied[], errors[], rejected?:[CommitRejection
                     {reason ENUM: cross_project|destructive_unconfirmed|unknown_add_type|
                     invalid_execute|smart_list_target|invalid_scope, …}], order_persisted
                     ("order-note"|false), message}
gtd_create_project : CreateProjectResult{project_id,url,created[],completed[],progressed{},applied[],
                     errors[], rejected?:[CreateRejection{reason ENUM: missing_name|invalid_life|
                     duplicate_id|unknown_add_type|invalid_execute|unknown_dep|self_dep}], message} | Candidates
gtd_stamp_tokens   : {projects:[{project_id,project_name,is_repeating,stamped[],dep_lines[],
                     skipped_reason}], dry_run, applied[], errors[], message}
gtd_chat_post      : {note{id,title,created}, task_id, role, tag_changes[], errors[]}
gtd_chat_thread    : {task_id, turns:[{note_id,role,scope?,mode?,text,created,files[],links[]}], requested}
gtd_chat_inflight  : {items:[{task_id,name,scope,status,project_id,project_name,last_activity}], count}
gtd_set_redaction  : {task_id, redacted}
gtd_engage_seed    : {items:[{id,name,kind,has_deadline,blocked,postponed,suggested,redacted,due}],
                     current_date, count}
gtd_apply_engage_commit : {applied[], errors[], warnings[], rejected?[], count, message}
list_tasks         : {tasks:[Task], count}          (Task = parsers.format_task shape)
<task writes>      : {task: Task, message}          (all except delete_task)
delete_task/note/list, set_default_list : {message}
add_note/edit_note : {note{id,title,body,created?/modified?}, message}
get_task_notes     : {task_name, notes:[NoteObject], count}
get_lists          : {lists:[ListObject{id,name,smart,archived,locked}], count}
<list writes>      : {list: ListObject, message}    (add/rename/archive/unarchive)
utilities          : per-tool models (settings/auth/tags/locations/contacts/groups/rate-limit/
                     timeline/parse_time/undo/batch_undo/get_task_url/get_list_url)
```

### Structured input params (surface 2/4 for complex params)

`gtd_apply_canvas_commit` (`order`/`edits`/`adds`/`completes`/`removes`/`execute`/`notes`),
`gtd_create_project` (`frame`/`items`/`notes`), `gtd_apply_engage_commit` (`items`), and
`batch_undo` (`transaction_ids`) keep their `coerce_json` coercion + clean single-typed schema (no
`anyOf`/null union that some clients stringify) AND now carry a description — via the new
`tool_params.coerced_str_array_schema` / `coerced_obj_array_schema` / `coerced_object_schema`
builders (a sibling `Field(description=…)` is silently dropped by `WithJsonSchema`; the description
must live inside the schema dict). `execute` types its value space with the closed enum; the engage
`items[]` element schema surfaces the `verdict` enum.

## Behavioural implications for a calling LLM (what the wrapper should assume now)

- **Capability, endpoints, and write safety are UNCHANGED** — metadata only. Existing behaviour
  (validation, strict-tag gate, `confirm_destructive`, ORDER-note persistence, the read-only-except-
  writes posture) is identical.
- **Reads are safe to call speculatively.** All 20 read tools advertise `readOnlyHint +
  idempotentHint`; a gating client no longer needs to guard them. The five destructive tools are
  flagged (`destructiveHint=True`) even though `undo`/`batch_undo` can reverse them.
- **Valid calls can be built from the schema alone** — closed-vocabulary params expose their enums
  (priority, direction, scope, role, mode, execute value space, engage verdict), and the commit /
  create / engage complex params expose their structure. Expect fewer bad-value round-trips.
- **Off-vocabulary values still fail gracefully.** The enums are advisory `json_schema_extra`, so a
  bad value reaches the handler and returns the actionable `data.error` (and the commit engines
  return `rejected[].reason` from the modelled set) — the model can self-correct.
- **Results are chainable from the output schema.** e.g. `gtd_project_plan.header.project.id` /
  `rows[].id` → the commit/chat/redaction tools; `list_tasks.tasks[].{id,taskseries_id,list_id}` →
  every task write; `parse_time.parsed` → `set_task_due_date`/`set_task_start_date`;
  `<write>.metadata.transaction_id` → `undo`/`batch_undo`. Read `structuredContent` when present;
  fall back to the text block's JSON.
- **`data` is always `success | error`.** Branch on `data.error` (this server's discriminator is the
  free-text string, not a typed code) before assuming a success shape; the ambiguity branch is
  `{candidates: […]}` on the resolvers.

## Wrapper delta list (gtd citation pass — seeds the follow-up)

Passages in the gtd wrapper that can now **cite** the advertised schema instead of re-describing it
(one truth per fact). A separate Cowork session lands these against the marketplace repo; this
debrief is its input.

- `project-plan-canvas-integration.md` — the prose describing the **project-plan-seed/3** envelope
  (header + row field lists) and the **canvas seed** `{mode, frame, seed}` shape → cite
  `gtd_project_plan` / `gtd_project_canvas` `outputSchema` (`PlanHeader`/`PlanRow`/`CanvasSeedResult`).
- Wherever the wrapper documents the **commit `scope`** (instant/item/project/plan) or the **execute**
  values (now/later/quick/off) → cite `gtd_apply_canvas_commit`'s `scope` enum + `execute` value enum.
- The **canvas/create commit rejection reasons** the wrapper hand-lists → cite the
  `CommitRejection.reason` / `CreateRejection.reason` enums in the commit/create output schemas.
- The **engage verdict grammar** enum the board/wrapper enumerate → cite
  `gtd_apply_engage_commit.items[].verdict` (sourced from `engage-verdict-grammar.md` §§ 1-4 — still
  the *semantic* owner; the schema now advertises the *set*).
- `tag-write-recovery.md` already keys off `strict_tag_mode: true` — no change, but note the
  `ErrorData` extra siblings are now advertised.
- The **gtd_project_index** row shapes (projects/foci/actions field lists) the navigator docs mirror
  → cite `ProjectIndexResult`.

## Improvement candidates raised (not done here — out of an additive pass)

1. **Typed error-code vocabulary** (return-value change → SemVer, likely major for the envelope):
   introduce a stable `data.error.code` discriminator (as `agent-memory-mcp` has) so wrapper
   recovery contracts key on codes, not prose. Today rtm-mcp has: free-text `data.error`; typed RTM
   *numeric* codes only at the transport layer (`exceptions.py`); string `reason` codes only in the
   commit engines; the `strict_tag_mode` flag. Generalising the `tag-write-recovery.md` pattern.
2. **Reject-reason canonical constants** — the commit/create `rejected[].reason` sets are currently
   Literal-typed in `models.py` (documentary). If they grow, promote them to frozensets in
   `canvas_commit.py`/`canvas_create.py` (single source) and assert schema-equality like the input
   enums. Engage-commit `rejected[]` is modelled open (its reason vocabulary wasn't confirmed here).
3. **Upstream envelope parity** — `models.py` documents server additions to `project-plan-seed/3`
   (`redacted`/`is_repeating`/`template_child_id`/`files`/`prog`) that `rtm_fetch.py` (gtd reference)
   doesn't yet emit; the standing "rtm_fetch.py parity is an upstream follow-up" note now has a
   schema to reconcile against.
4. **Schema fingerprinting** (marketplace side) — the architect's tool-detection could hash each
   tool's description+inputSchema+annotations+outputSchema so future schema drift is a detectable
   event (already tracked as a marketplace candidate).

## Family note

Update the standard document's § 7 rollout table: **rtm-mcp → shipped** (this session; no version
bump). The three annotation constants + `models.py` + `test_tool_schemas.py` + the
`coerced_*_schema` builders are the reusable pattern for the remaining SaaS repos (mindmeister-mcp,
meistertask-mcp): both are `openWorldHint=True`, and their status-integer / export-format
vocabularies are the prime enum sources (survey first per the brief).

---
*Source of truth: repo `CLAUDE.md` (architecture + `models.py`) + `CONTRIBUTING.md` § 3/§ 7/§ 8/§ 12
(the six-surface standard) + the tool docstrings. Schema models: `src/rtm_mcp/models.py`.
Enforcement: `tests/test_tool_schemas.py`. Commit: 07f768b on `feat/tool-documentation-uplift`.*
