"""Tier-2 affordance surface — the pure projections behind `rtm_tool_help`.

The Tool Affordance Standard (git-ops `mcp-tool-documentation-standard.md` §§ 4.1a / 9 / 10)
splits a tool's documentation across three tiers by what guarantees the read:

* **tier 1 (select)** — `name` + the description's front block, the only channel every client
  puts in front of the model unprompted, and all that survives the client's ~2 KB budget;
* **tier 2 (detail)** — this module: the full contract, on demand;
* **tier 3 (teach)** — `guided_rejection.py`, the one moment the server *makes* a caller read.

**Defined by subtraction.** Help carries only what the other surfaces cannot or do not:
the combination rules JSON Schema cannot express (the family bans advertised `anyOf` on a
parameter, because clients flatten a union to a bare `{}` and lose type/description/enum),
worked examples of nested or coerced params, the multi-case `Returns` in prose, the
`annotations` facts rendered as prose (a client may consume annotations without ever showing
them to the model), the typed-error catalogue with recovery, and the mechanical chain edges.
It never re-dumps the JSON schema the client already fetched, and it never restates the
plugin-owned domain vocabulary — the membrane holds, so help emits a *pointer* to the gtd
skill rather than a copy of its taxonomy.

**One truth per fact.** Almost everything here is DERIVED from the tool's own advertised
schema, so help cannot drift from what callers are told:

| Fact | Source |
|---|---|
| purpose | the description's first block (tier 1) |
| parameters, types, enums | the advertised `inputSchema` |
| read/write/destructive posture | the advertised `annotations` |
| the multi-case `Returns` | the docstring's own `Returns` section |
| error catalogue | the codes NAMED in the description |
| `task_name` XOR the three ids, `confirm_destructive` | the parameter set itself |

Deriving the error catalogue from the description is sound rather than lazy: the shipped
`TestAdvertisedErrorContract` already asserts that every code a tool can reach is named in
its description, so scanning the description for registry members is guaranteed complete by
a test that fails the moment a new failure path is added without documenting it.

Only four tables below are authored, and each holds a fact no surface carries today:
`COMBINATION_RULES`, `EXAMPLES`, `CHAIN`, `BFF_TOOLS`. Pure and no-IO by design — the tool
layer does the introspection and hands the result in, which is also what makes every
projection unit-testable without a server.
"""

from __future__ import annotations

from typing import Any

from .error_codes import ErrorCode

#: The client keeps roughly this much of a description. Not a spec guarantee — a Claude
#: Code / Cowork implementation detail (measured 2026-07-26) — but the front-loading
#: discipline it implies is correct at any finite budget.
DESCRIPTION_BUDGET_BYTES = 2048

# --------------------------------------------------------------------------------------
# Authored tables — the only hand-written facts in this module.
# --------------------------------------------------------------------------------------

#: Parameter-combination rules, per tool. These are exactly the rules that CANNOT be
#: advertised structurally: JSON Schema would express them as `anyOf` / `oneOf` /
#: `dependentRequired`, and the family bans advertised unions on parameters. So they are
#: declared here once and projected onto the tier-1 hint, this tier-2 contract, and the
#: tier-3 rejection. The `task_name`-XOR-ids and `confirm_destructive` rules are NOT here:
#: they are derivable from the parameter set, and deriving beats authoring.
COMBINATION_RULES: dict[str, tuple[str, ...]] = {
    "gtd_note_attach_output": (
        "`filing_path` is required UNLESS `unfiled=True`, and the two are mutually exclusive: "
        "`unfiled=True` alongside a non-empty `filing_path` is rejected as `invalid_input`. "
        "You cannot claim both a filed artefact and no artefact, and silently preferring one "
        "would discard a stated intent.",
        "With a vault mounted, `filing_path` must resolve to an artefact that carries "
        "companion metadata, else the call is refused as `filing_unresolved` with NOTHING "
        "written. With NO vault mounted the gate is inert and the write proceeds — the "
        "receipt's `not_applied[]` says the filing went unverified.",
        "`unfiled=True` is for a deliverable that genuinely has no artefact (inline message "
        "text). It writes an `UNFILED:` marker and no `FILING:` line — deliberately, because a "
        "placeholder path would be scraped by `gtd_chat_thread` as a real artefact.",
        "`register=True` REBUILDS the project's OUTPUTS register from its OUTPUT notes rather "
        "than appending, so repeat calls are idempotent. It is a no-op when the item IS the "
        "project (a project cannot register against itself).",
    ),
    "gtd_item_stamp_tokens": (
        "Pass `project_id` to stamp ONE project, or omit it entirely to sweep every active "
        "repeating templated project. There is no 'all projects' flag — absence IS the sweep.",
        "`dry_run=True` returns the plan and writes nothing. Run it first on a sweep.",
    ),
    "gtd_item_create": (
        "Required fields depend on `kind` (the per-kind Definition of Ready, hard-gated): "
        "an `action` needs a context; a `waiting_for` needs the person waited on; a "
        "`calendar_entry` needs a date. A gap is rejected as `dor_not_met` naming the axis.",
        "`kind='project'` is not accepted here — a project has its own tool "
        "(`gtd_project_create`), because it carries a plan rather than a single item.",
    ),
    "gtd_engage_commit": (
        "Verdict legality depends on the item's kind, which the server RE-DERIVES from a "
        "fresh read — a client cannot smuggle a kind past the guards. An off-enum or "
        "type-illegal verdict is rejected with the closest legal verdict as a suggestion.",
        "A `has_deadline` item (a timed due — the GTD hard landscape) allows only "
        "`do_now` / `to_calendar` / `keep` / `drop`. `resurface` is legal ONLY when blocked.",
        "The date verdicts (`today`, `bump:+<n>d`, `defer_start:<phrase>`) need a "
        "`date_phrase`; it is resolved through RTM's own parser BEFORE any write, so an "
        "unparseable phrase fails the whole batch as `bad_date` rather than writing a guess.",
        "`drop` requires `confirm_destructive=True`. Any rejection writes NOTHING — the "
        "batch is all-or-nothing.",
    ),
    "gtd_canvas_commit": (
        "`execute` and `order` accept CHILD ids only. `edits` / `notes` / `completes` / "
        "`removes` additionally accept the `project_id` itself (rename, journal, complete or "
        "soft-delete the project entity). Any other non-child id is `cross_project`-rejected.",
        "`completes` and `removes` require `confirm_destructive=True`.",
        "`scope` is a LABEL only — it places the single audit note and changes nothing about "
        "validation, the strict-tag gate, or undo.",
        "Every ops parameter accepts either structured JSON or a JSON string.",
    ),
    "gtd_project_create": (
        "`frame.focus` must resolve to an existing Area of Focus — by id, name, or unique "
        "substring. An ambiguous name returns `candidates` and writes nothing; a miss is an "
        "error. A project is NEVER created loose.",
        "An item's `deps` reference other items in the same draft (by their in-draft id or "
        "index), not RTM ids — the tool maps them to real ids after creation.",
    ),
    "gtd_inbox_capture": (
        "Capture takes TEXT ONLY, deliberately. It does not tag, file, or classify — that is "
        "the clarify step (`gtd_inbox_drain` / `gtd_item_transition`). Passing a tag "
        "parameter here is rejected at the call boundary.",
    ),
    "gtd_chat_post": (
        "`mode` applies to a `me` turn only (it is the posture footer); an `ai` turn ignores "
        "it. An `ai` turn clears the worker signal unless `clear_signal=False` — pass False "
        "for an interim progress note, so the board keeps showing 'thinking'.",
        "Posting requires an INCOMPLETE task. A completed task's thread is readable via "
        "`gtd_chat_thread` but returns `conversation_read_only` here.",
    ),
    "list_tasks": (
        "`filter` is RTM's own search syntax, not a substring match. A bare word searches "
        "names; operators are `due:`, `tag:`, `list:`, `status:`, `priority:` and friends, "
        "combined with AND / OR / NOT.",
        "A smart-list filter needs an explicit `status:incomplete` — omitting it returns "
        "completed history too, which on a large account is tens of thousands of rows.",
    ),
    "add_task": (
        "With `parse=True` (the default) the NAME carries the metadata via Smart Add "
        "(`^due`, `!priority`, `#tag`, `@location`, `=estimate`, `*repeat`). With "
        "`parse=False` the name is taken literally and you set fields with the "
        "`set_task_*` tools afterwards.",
        "Smart Add `#tags` go through the strict-tag existence gate: a tag not already in "
        "the account is rejected rather than silently created. Re-issue with `parse=False`, "
        "or create the tag in RTM first.",
        "Omitting `list_name` routes to the account's configured default list (NOT RTM's "
        "built-in Inbox, which is what the raw API would do). A subtask ignores it — the "
        "parent's list governs.",
    ),
    "batch_undo": (
        "`transaction_ids` are undone in REVERSE order, newest first — that is what makes a "
        "multi-write commit reversible as a unit. Accepts a list or a JSON string.",
    ),
    "gtd_surface_create": (
        "The item type decides which fields are meaningful; an unknown type is rejected "
        "before any write.",
    ),
    "gtd_note_add": (
        "The note TITLE follows the journal grammar `YYYY-MM-DD [HH:MM] — TYPE — summary`. "
        "With `RTM_STRICT_NOTES=shape` a malformed title is rejected as "
        "`note_shape_rejected`; since v5.2.0 the default `vocabulary` mode ALSO refuses an "
        "unregistered TYPE, with `error.details.rejected_by` naming which check failed. gtd's "
        "note-shape catalogue remains the AUTHORITY — the server codifies it, so a genuinely "
        "new type is added there first.",
        "The BODY is assembled, not parsed: `narrative` → `--- Sources ---` → "
        "`--- AI Context ---`, each block emitted only when you pass content for it. `sources` "
        "and `ai_context` are independent optionals — either, both or neither. There is no "
        "argument that produces a different block order, so do not hand-write the delimiters "
        "into `narrative`; they would be emitted a second time and out of place.",
        "A `sources` / `ai_context` that arrives with only blank entries writes no block, and "
        "says so in the receipt's `not_applied[]` rather than failing the note.",
    ),
}

#: Worked examples, for the calls a schema alone does not make obvious — nested or
#: JSON-coerced params above all. Illustrative, not exhaustive.
EXAMPLES: dict[str, tuple[str, ...]] = {
    "list_tasks": (
        'list_tasks(filter="status:incomplete AND due:today")',
        'list_tasks(filter="status:incomplete AND tag:next_action AND NOT tag:someday")',
        'list_tasks(filter="status:incomplete", list_name="Work")',
    ),
    "add_task": (
        'add_task(name="Call the dentist ^tomorrow !2 #calls")',
        'add_task(name="Draft Q3 summary", parse=False, list_name="Work")',
        'add_task(name="Book the venue", parent_task_id="1234567")',
    ),
    "gtd_canvas_commit": (
        'gtd_canvas_commit(project_id="123", edits={"456": {"text": "Renamed action"}})',
        'gtd_canvas_commit(project_id="123", execute={"456": "now"})   # fire the '
        "progression engine on one child",
        'gtd_canvas_commit(project_id="123", execute={"456": "off"})   # clear the '
        "directive; idempotent, writes nothing if none is set",
        'gtd_canvas_commit(project_id="123", completes=["456"], confirm_destructive=True)',
        'gtd_canvas_commit(project_id="123", order=["456", "789"], scope="plan")',
        'gtd_canvas_commit(project_id="123", adds=[{"type": "action", '
        '"text": "Draft the migration note", "classifiers": {"context": "using_device", '
        '"priority": "must", "energy": "high_energy"}, "estimate": "30 minutes"}])   # the name '
        "is `text`, and energy/estimate are the two DoR designations an action needs",
    ),
    "gtd_project_create": (
        'gtd_project_create(frame={"life": "work", "focus": "Engineering", '
        '"name": "Migrate CI", "outcome": "CI runs on the new runner"}, '
        'items=[{"id": "a", "text": "Audit the current pipeline", "type": "action"}, '
        '{"id": "b", "text": "Cut over", "type": "action", "deps": ["a"]}])   # minimal — the '
        "item name is `text`, NOT `name`",
        'gtd_project_create(frame={"life": "work", "focus": "Engineering", '
        '"name": "Migrate CI", "outcome": "CI runs on the new runner"}, '
        'items=[{"id": "a", "text": "Audit the current pipeline", "type": "action", '
        '"classifiers": {"context": "using_device", "priority": "must", '
        '"energy": "high_energy"}, "estimate": "30 minutes"}, '
        '{"id": "b", "text": "Waiting for infra to confirm the runner", "type": "waiting_for", '
        '"classifiers": {"priority": "must"}, "chase": "next Friday", "deps": ["a"]}], '
        'notes=[{"type": "INCEPTION", "text": "Runner EOL forces the move."}])   # fully '
        "designated — this is the shape a real plan takes",
    ),
    "gtd_engage_commit": (
        'gtd_engage_commit(items=[{"id": "123", "verdict": "next_actions"}])   # clear a '
        "soft parked date — the commonest verdict",
        'gtd_engage_commit(items=[{"id": "123", "verdict": "bump:+3d", '
        '"date_phrase": "in 3 days"}])',
        'gtd_engage_commit(items=[{"id": "123", "verdict": "draft", '
        '"note": "focus on the cost section"}])   # steer the AI first pass',
        'gtd_engage_commit(items=[{"id": "123", "verdict": "drop"}], confirm_destructive=True)',
    ),
    "gtd_note_add": (
        'gtd_note_add(task_ref="123", note_type="PROGRESS", summary="drafted the brief", '
        'narrative="First pass is with Sam for comment.")   # narrative only — the common case',
        'gtd_note_add(task_ref="123", note_type="DECISION", summary="warehouse over lakehouse", '
        'narrative="Cost, not capability, decided it.", '
        'sources=["Allen, D. (2015). Getting Things Done, ch. 3", '
        '"Q4 budget summary — uploaded 2026-04-01"])',
        'gtd_note_add(task_ref="123", note_type="SESSION", summary="handoff", '
        'narrative="Covered the migration plan.", '
        'ai_context={"Blockers": "waiting on Raj\'s staging env", '
        '"Next executable": "draft the SLA benchmarks"})',
    ),
    "gtd_item_create": (
        'gtd_item_create(parent_ref="123", kind="action", name="Email Sam the figures", '
        'life_context="work", priority="must", action_context="using_device", '
        'comms="conversation_email", energy="low_energy", estimate="15 minutes")   # an action '
        "needs every Definition-of-Ready axis, or the create is rejected",
        'gtd_item_create(parent_ref="123", kind="waiting_for", '
        'name="Waiting for Sam to confirm the date", life_context="work", priority="should", '
        'due="next Friday")   # a waiting-for needs a chase date, not the execution axes',
    ),
    "gtd_chat_post": (
        'gtd_chat_post(task_id="123", role="me", text="Draft the reply", mode="act")',
        'gtd_chat_post(task_id="123", role="ai", text="Working on it — reading the '
        'notes now", clear_signal=False)   # interim note; board keeps polling',
    ),
    "batch_undo": ('batch_undo(transaction_ids=["987", "986", "985"])',),
    "gtd_item_stamp_tokens": (
        "gtd_item_stamp_tokens(dry_run=True)   # plan the whole sweep, write nothing",
        'gtd_item_stamp_tokens(project_id="123")',
    ),
}

#: Mechanical chain edges — which tool hands you the ids this one needs, and what you
#: typically call next. The tool graph, deliberately NOT the domain workflow (that is the
#: gtd skill's, and the membrane keeps it there).
CHAIN: dict[str, dict[str, tuple[str, ...]]] = {
    "gtd_canvas_commit": {
        "produced_by": ("gtd_project_canvas", "gtd_project_index"),
        "feeds_into": ("gtd_project_canvas", "batch_undo"),
    },
    "gtd_project_canvas": {
        "produced_by": ("gtd_project_index",),
        "feeds_into": ("gtd_canvas_commit",),
    },
    "gtd_project_index": {
        "produced_by": (),
        "feeds_into": ("gtd_project_canvas", "gtd_project_plan"),
    },
    "gtd_engage_commit": {"produced_by": ("gtd_engage_seed",), "feeds_into": ("batch_undo",)},
    "gtd_engage_seed": {"produced_by": (), "feeds_into": ("gtd_engage_commit",)},
    "gtd_chat_post": {
        "produced_by": ("gtd_chat_inflight", "gtd_project_index"),
        "feeds_into": ("gtd_chat_thread",),
    },
    "gtd_chat_thread": {"produced_by": ("gtd_chat_inflight",), "feeds_into": ("gtd_chat_post",)},
    "gtd_inbox_drain": {
        "produced_by": ("gtd_inbox_state", "gtd_inbox_capture"),
        "feeds_into": ("gtd_item_transition",),
    },
    "gtd_inbox_capture": {"produced_by": (), "feeds_into": ("gtd_inbox_state", "gtd_inbox_drain")},
    "gtd_surface_resolve": {"produced_by": ("gtd_surface_queue",), "feeds_into": ()},
    "gtd_note_attach_output": {
        "produced_by": ("gtd_note_filing_gaps",),
        "feeds_into": ("gtd_note_filing_gaps", "batch_undo"),
    },
    "gtd_note_filing_gaps": {
        "produced_by": (),
        "feeds_into": ("gtd_note_attach_output", "gtd_note_edit"),
    },
    "gtd_note_report": {"produced_by": (), "feeds_into": ("gtd_note_edit",)},
    "gtd_contribution_transition": {
        "produced_by": ("gtd_engine_report",),
        "feeds_into": ("gtd_engine_report",),
    },
    "undo": {"produced_by": ("get_timeline_info",), "feeds_into": ()},
    "batch_undo": {"produced_by": ("get_timeline_info",), "feeds_into": ()},
    "add_note": {"produced_by": ("list_tasks",), "feeds_into": ("get_task_notes",)},
    "edit_note": {"produced_by": ("get_task_notes",), "feeds_into": ()},
    "delete_note": {"produced_by": ("get_task_notes",), "feeds_into": ()},
    "move_task": {"produced_by": ("get_lists", "list_tasks"), "feeds_into": ()},
    "set_parent_task": {"produced_by": ("list_tasks",), "feeds_into": ("get_task_url",)},
}

#: The artifact-facing (BFF) tools — built for a specific board rather than for an agent in
#: chat. Naming cannot express this: the `gtd_` prefix separates 55 domain tools from 44
#: primitives, but BFF-ness sits INSIDE that prefix. Carried here (and rendered in prose by
#: `taxonomy`) rather than as a second prefix, because renaming twelve tools two releases
#: after the rename wave is not proportionate.
#:
#: **This table is descriptive, not enforced, and it has already drifted once.** It was authored
#: from the memory of which tools were written for the board, so a tool that *behaves* like a BFF
#: but was not written for one does not appear. `gtd_surface_queue` was exactly that: it returns
#: an unbounded collection with a strict row schema, and in chat on 2026-07-31 it both exceeded
#: the client's tool-result ceiling (65,127 characters on `surface="activity"`) and — via one
#: item's oddly shaped metadata — failed output validation outright, so `surface="questions"`
#: returned nothing at all. Nothing flagged it, because membership is remembered rather than
#: derived.
#:
#: The durable fix is to derive membership from a PROPERTY ("returns an unbounded collection" /
#: "the output schema is a frontend contract") and to assert it, so a new tool cannot be omitted
#: by forgetting. That is a designed change, not a line here.
BFF_TOOLS: frozenset[str] = frozenset(
    {
        "gtd_project_canvas",
        "gtd_project_index",
        "gtd_canvas_commit",
        "gtd_project_create",
        "gtd_engage_seed",
        "gtd_engage_commit",
        "gtd_chat_post",
        "gtd_chat_thread",
        "gtd_chat_inflight",
        "gtd_item_set_redaction",
        "gtd_project_plan",
        "gtd_item_stamp_tokens",
        "gtd_surface_queue",
    }
)

#: Tools a board reads but an agent can equally use — so `consumer` genuinely needs an
#: "either" value rather than a binary.
#:
#: `gtd_surface_queue` is here for a different reason from the other three, and the difference is
#: the point. They are board tools an agent may also call. It is an AGENT tool (its consumer is
#: `ai-surface-scan`, and no board reads it) that happens to be shaped like a BFF. Marking it
#: `consumer: artifact` would be simply false, so `either` is the least-wrong value the current
#: vocabulary offers — which is the tell that **shape and audience are two axes and this taxonomy
#: conflates them**. A tool can be collection-shaped and agent-consumed at once; today that cannot
#: be said. Splitting the axes is the designed change the comment on `BFF_TOOLS` points at.
DUAL_CONSUMER: frozenset[str] = frozenset(
    {"gtd_project_plan", "gtd_project_index", "gtd_project_canvas", "gtd_surface_queue"}
)

#: How to recover from each typed error. The `message` on a live error is already actionable
#: (CONTRIBUTING § 5 requires it to name the next step); this is the same guidance available
#: BEFORE the call, so a caller can pre-empt rather than only recover.
#:
#: **Written for the context the caller is actually in.** Most of these callers are not bare
#: agents — they are the `gtd` skill, a scheduled worker, or a board artifact, and a recovery
#: hint that ignores that is either useless or wrong. So where a failure is a governed-domain
#: one (an unmet Definition of Ready, an off-vocabulary verdict, a note TYPE, a tag that does
#: not exist), the hint names the mechanical fix AND points at the wrapping skill that owns
#: the judgement — a POINTER only, never a copy of gtd's vocabulary, because the membrane
#: keeps that vocabulary plugin-side. Where a failure is transport or identity, the hint stays
#: deliberately general, since it is equally right for every caller.
RECOVERY: dict[str, str] = {
    ErrorCode.AUTH_FAILED: "The stored token was rejected or revoked. Re-run `rtm-setup`.",
    ErrorCode.INVALID_SIGNATURE: "A transport-level signing fault. Retry; if it persists, re-run `rtm-setup`.",
    ErrorCode.INVALID_API_KEY: "The configured API key is not valid. Re-run `rtm-setup`.",
    ErrorCode.SERVICE_UNAVAILABLE: "RTM returned 503. The client already retried with backoff — retry later.",
    ErrorCode.SERVICE_NOT_FOUND: "An RTM endpoint fault, not a caller error. Retry later.",
    ErrorCode.METHOD_NOT_FOUND: "An internal mapping fault — report it rather than working around it.",
    ErrorCode.INVALID_FORMAT: "RTM rejected the response format. Retry; report if persistent.",
    ErrorCode.PRO_REQUIRED: "Subtask and hierarchy features need an RTM Pro account.",
    ErrorCode.INVALID_PARENT: "The parent id is not a valid task. Confirm it with `list_tasks`.",
    ErrorCode.NESTING_TOO_DEEP: "RTM allows three levels. Reparent higher up the tree.",
    ErrorCode.REPEATING_TASK_CONFLICT: "A repeating task cannot be a parent or child of another repeating task.",
    ErrorCode.DUE_BEFORE_START: "The due date precedes the start date. Move one of them.",
    ErrorCode.SELF_PARENTING: "A task cannot be its own parent. Pass a different `parent_task_id`.",
    ErrorCode.RATE_LIMITED: "The token bucket is empty. Pace the calls; `get_rate_limit_status` shows the state.",
    ErrorCode.NETWORK_ERROR: "A transport failure. Reads are retried automatically; a write timeout is NOT (it may have applied) — check state with a read before retrying.",
    ErrorCode.TASK_NOT_FOUND: "No task matched. Search with `list_tasks`, or pass `task_id` + `taskseries_id` + `list_id` explicitly.",
    ErrorCode.LIST_NOT_FOUND: "No list matched. Call `get_lists` for the available names.",
    ErrorCode.PROJECT_NOT_FOUND: "No `#project` task matched. Call `gtd_project_index` for the active portfolio and use an id from it. If the project genuinely does not exist yet, creating it is a `gtd_project_create` decision, not a retry of this call.",
    ErrorCode.FOCUS_NOT_FOUND: "No Area of Focus matched. Call `gtd_focus_index` (or `gtd_project_index`'s `foci`) for the real names — an area is never created implicitly, so a miss means the destination is wrong rather than missing.",
    ErrorCode.AMBIGUOUS_NAME: "Several candidates matched — the error carries `details.candidates`. Re-call with an id.",
    ErrorCode.INVALID_INPUT: "A parameter value is out of range or malformed. The message names the parameter.",
    ErrorCode.MISSING_PARAMETER: "A required parameter was omitted. The message names it.",
    ErrorCode.INVALID_SCOPE: "`scope` must be one of instant / item / project / plan.",
    ErrorCode.INVALID_EXECUTE: "An execute value must be now / later / quick (plus `off` on a commit, to clear).",
    ErrorCode.INVALID_LIFE: "The life context must be one of the four canonical values (work / personal / family / client).",
    ErrorCode.MISSING_NAME: "An item was submitted without a name. Every created item needs one.",
    ErrorCode.UNKNOWN_ADD_TYPE: "The item type is not in the canonical classifier set.",
    ErrorCode.UNKNOWN_DEP: "A `deps` entry names no item in the draft. Reference an in-draft id or index.",
    ErrorCode.SELF_DEP: "An item depends on itself. Remove the edge.",
    ErrorCode.DUPLICATE_ID: "Two draft items claim the same id (explicitly or by position). Make them unique.",
    ErrorCode.CROSS_PROJECT: "An id is not a child of this project. Only `edits`/`notes`/`completes`/`removes` may name the project itself.",
    ErrorCode.SMART_LIST_TARGET: "A smart list is a saved search and cannot receive items. Target a regular list.",
    ErrorCode.BAD_DATE: "The date phrase did not parse. Use `parse_time` to check it first.",
    ErrorCode.OFF_ENUM: "The value is outside the governed vocabulary; the rejection names the legal set. Choose from that set — the vocabulary is ratified, so inventing a value is never the fix. If none of the legal values fits, the case belongs back with the wrapping skill (gtd) as a grammar question, not a retry.",
    ErrorCode.UNKNOWN_KIND: "The item's kind could not be derived from its tags — it carries no workflow-state tag. Read the item (`gtd_item_context`) and transition it properly (`gtd_item_transition`) rather than forcing a kind at this call site.",
    ErrorCode.DOR_NOT_MET: "The per-kind Definition of Ready is unmet and the rejection names the missing axis. Supply that field. If it is genuinely unknown, the item is not ready to create — capture it instead (`gtd_inbox_capture`) and clarify it later; that ordering is the gtd skill's, and the gate exists to enforce it.",
    ErrorCode.INVALID_NOTE_TYPE: "The note TYPE is not in the journal catalogue. gtd's note-shape catalogue is the authority and this server codifies it — enforced at the write boundary since v5.2.0, so take the TYPE from that reference rather than coining one; a genuinely new type is added there first (codification before validation).",
    ErrorCode.INVALID_BLOCK_ORDER: "The note's blocks are out of the required order. Reorder them to match the grammar the wrapping skill documents; the server checks order only, not content.",
    ErrorCode.TYPE_ILLEGAL: "The verdict is illegal for this item's kind and the rejection carries the closest legal verdict — usually the right answer. The kind was re-derived server-side, so overriding it from the client is not an option; if the kind itself looks wrong, fix the item's tags first.",
    ErrorCode.TASK_NOT_COMPLETED: "The operation needs a completed task; this one is open.",
    ErrorCode.CONVERSATION_READ_ONLY: "The task is completed, so its thread is read-only. Reopen it with `uncomplete_task` to continue.",
    ErrorCode.NO_CONTRIBUTION_NOTE: "The item carries no CONTRIB/PREP note to transition. Check it with `get_task_notes`.",
    ErrorCode.LOCKED_SYSTEM_LIST: "A locked system list (Inbox, Sent) cannot be renamed or deleted.",
    ErrorCode.UNKNOWN_TRANSACTION: "That transaction id is not in this session's log. `get_timeline_info` lists it.",
    ErrorCode.TRANSACTION_ALREADY_UNDONE: "Already undone. `get_timeline_info` shows the current state.",
    ErrorCode.STRICT_TAG_REJECTED: "The tag does not exist in the account and strict-tag mode refuses to mint it — that is the gate working, not a fault. `get_tags` lists the real set; the near-miss is usually a spelling or plural variant of an existing tag. A genuinely new tag is a taxonomy decision (gtd's `tag-taxonomy`) and must be created in RTM out-of-band first.",
    ErrorCode.NOTE_SHAPE_REJECTED: "TWO checks return this code — read `error.details.rejected_by` first. `shape`: the title does not parse as `YYYY-MM-DD [HH:MM] — TYPE — summary` (the separator is an em-dash, and the TYPE token allows no underscore — the commonest two causes). `vocabulary` (since v5.2.0): the title parses but the TYPE is not registered; `how_to_proceed` lists every registered type, and a legacy AI-surface spelling (`Q`, `AR`, `ACTIVITY_REPORT`) is named as legacy rather than unknown. A genuinely new type goes in gtd's note-shape catalogue FIRST — never coined at the call site.",
    ErrorCode.DESTRUCTIVE_UNCONFIRMED: "Pass `confirm_destructive=True` to proceed.",
    ErrorCode.FILING_UNRESOLVED: "The artefact you are journalling does not resolve in the AI Memory vault — read `error.details.rejected_by` first. `artefact_missing`: nothing is at that path; check it with `agent_memory_file_query` (a path broken by a vault reorganisation is the commonest cause, and it is why the fix is to re-resolve rather than retry). `companion_missing`: the file is there but untracked, so re-file it with `agent_memory_file_put`, which writes artefact and companion atomically. If the deliverable is genuinely inline message text with no artefact, `unfiled=True` is the designed escape — it is not a workaround. Note the gate is inert with no vault mounted, so this code means the server LOOKED and did not find it.",
    ErrorCode.COMMIT_REJECTED: "One or more ops failed validation; `rejected[]` names each reason. NOTHING was written.",
    ErrorCode.WRITE_FAILED: "The write reached RTM and failed. `errors[]` carries the per-op detail; earlier ops in the batch may have applied.",
    # Outcome reasons, not failures — these appear ONLY as `not_applied[].reason` on an
    # otherwise-successful write, so "recovery" here means "decide whether you still need
    # something to happen", not "fix an error".
    ErrorCode.NO_CHANGE: "Not an error — the item was already in the state you asked for, so nothing was written. Nothing to do unless you expected a change, in which case re-read the item: your view of it was stale.",
    ErrorCode.NO_DURABLE_WRITE: "Not an error — the operation is a decision or marker with no RTM state change by design. Do not retry; it will never write. If you needed a durable change, pick the verb that makes one.",
    ErrorCode.NOT_ELIGIBLE: "Not an error — the target does not qualify for this operation, so it was skipped. `detail` says why. Retrying will skip it again; act on a qualifying target instead.",
}


# --------------------------------------------------------------------------------------
# Derivations
# --------------------------------------------------------------------------------------

_ALL_CODES = tuple(sorted((c.value for c in ErrorCode), key=len, reverse=True))


def purpose_line(description: str) -> str:
    """The tool's one-line purpose — the description's first block, verbatim.

    Single-sourced on purpose: the selection line a client renders and the line the index
    serves are the SAME characters, so an index entry can never promise something the
    description does not say.
    """
    for para in (description or "").strip().split("\n\n"):
        line = " ".join(para.split())
        if line:
            return line
    return ""


#: Abbreviations whose full stop does not end a sentence. Splitting on ". " without these
#: truncates a purpose mid-clause, which is worse than a long one.
_ABBREVIATIONS = ("e.g.", "i.e.", "cf.", "vs.", "etc.", "Ltd.", "approx.")

#: Hard ceiling for an index purpose, for a description whose first sentence never ends.
_INDEX_PURPOSE_CHARS = 220


def purpose_sentence(description: str) -> str:
    """The SELECTION line — the first sentence of the purpose block.

    The index is the cheap "which tool?" answer, so it must stay cheap: the first *paragraph*
    of all 100 descriptions is ~31 KB (~7.8 k tokens), while the first *sentence* is ~4x less.
    The second sentence is almost always orientation rather than selection — provenance ("a
    faithful native port of …"), history, or a caveat — so it belongs in the contract, which is
    exactly where it stays.

    Derived, never a second copy: the result is always a leading substring of
    `purpose_line`, and a test asserts that, so the index cannot promise something the
    description does not say.
    """
    line = purpose_line(description)
    if not line:
        return ""
    cut = 0
    while True:
        idx = line.find(". ", cut)
        if idx == -1:
            break
        candidate = line[: idx + 1]
        if candidate.endswith(_ABBREVIATIONS) or len(candidate) < 40:
            cut = idx + 2
            continue
        return candidate
    if len(line) <= _INDEX_PURPOSE_CHARS:
        return line
    clipped = line[:_INDEX_PURPOSE_CHARS].rsplit(" ", 1)[0]
    return clipped + " …"


def taxonomy(name: str) -> dict[str, str]:
    """Layer / domain / consumer for a tool, derived from its name plus `BFF_TOOLS`.

    Read/write posture is deliberately absent — `annotations` already carries it and
    restating it here would be the duplication the standard forbids.
    """
    domain = "gtd" if name.startswith("gtd_") else "rtm"
    if name in BFF_TOOLS:
        layer = "bff"
    elif domain == "gtd":
        layer = "domain"
    else:
        layer = "primitive"
    if name in DUAL_CONSUMER:
        consumer = "either"
    elif layer == "bff":
        consumer = "artifact"
    else:
        consumer = "agent"
    return {"domain": domain, "layer": layer, "consumer": consumer}


def posture(annotations: dict[str, Any] | None, *, has_confirm: bool) -> dict[str, Any]:
    """The `annotations` facts rendered for a model that may never be shown annotations."""
    ann = annotations or {}
    read_only = bool(ann.get("readOnlyHint"))
    destructive = bool(ann.get("destructiveHint"))
    out: dict[str, Any] = {
        "read_only": read_only,
        "idempotent": bool(ann.get("idempotentHint")),
        "destructive": destructive,
        "summary": (
            "Read-only — no timeline, no write, safe to call speculatively."
            if read_only
            else (
                "DESTRUCTIVE write — removes or completes state."
                if destructive
                else "Additive write — creates or updates state."
            )
        ),
    }
    if not read_only:
        out["undo"] = (
            "The response carries `metadata.transaction_id`; `undo` reverses one write and "
            "`batch_undo` reverses several in newest-first order."
        )
    if has_confirm:
        out["confirmation"] = "Requires `confirm_destructive=True`; without it nothing is written."
    return out


def parameters(input_schema: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Flatten the advertised `inputSchema` into a per-parameter table."""
    schema = input_schema or {}
    props: dict[str, Any] = schema.get("properties") or {}
    required = set(schema.get("required") or ())
    rows: list[dict[str, Any]] = []
    for pname, spec in props.items():
        spec = spec or {}
        row: dict[str, Any] = {
            "name": pname,
            "type": spec.get("type") or "any",
            "required": pname in required,
            "description": spec.get("description") or "",
        }
        enum = spec.get("enum") or (spec.get("items") or {}).get("enum")
        if enum:
            row["enum"] = list(enum)
        rows.append(row)
    return rows


def error_catalogue(description: str) -> list[dict[str, str]]:
    """Every typed error code the description names, with its recovery.

    Complete by construction: `TestAdvertisedErrorContract` asserts a tool's description
    names every code it can reach, so scanning the description cannot under-report without
    that test failing first.
    """
    desc = description or ""
    found = [code for code in _ALL_CODES if code in desc]
    return [
        {"code": code, "recovery": RECOVERY.get(code, "The error's `message` names the next step.")}
        for code in sorted(found)
    ]


def returns_prose(description: str) -> str:
    """The docstring's own multi-case `Returns` block — rehomed, never rewritten."""
    desc = description or ""
    idx = desc.find("Returns")
    return desc[idx:].strip() if idx != -1 else ""


def combination_rules(name: str, input_schema: dict[str, Any] | None) -> list[str]:
    """The authored rules for this tool, plus the two derivable ones.

    Derived rather than authored where the parameter set already proves it: a tool taking
    both `task_name` and `task_id` carries the identify-by-exactly-one rule, and a tool
    taking `confirm_destructive` carries the confirmation rule. That keeps 30-odd tools
    correct without 30 hand-maintained entries.
    """
    props = set((input_schema or {}).get("properties") or {})
    rules: list[str] = []
    if "task_name" in props and "task_id" in props:
        rules.append(
            "Identify the task by EXACTLY ONE of: `task_name` (fuzzy — searches incomplete "
            "tasks, prefers exact over substring and recent over stale, so it can hit an "
            "unintended task), or all three of `task_id` + `taskseries_id` + `list_id` "
            "(exact). Prefer the ids for anything consequential."
        )
    if "list_name" in props and "list_id" in props:
        rules.append("Identify the list by `list_name` or `list_id` — `get_lists` returns both.")
    rules.extend(COMBINATION_RULES.get(name, ()))
    if "confirm_destructive" in props and not any("confirm_destructive" in r for r in rules):
        rules.append(
            "Destructive ops require `confirm_destructive=True`; without it nothing is written."
        )
    return rules


def build_index(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """The no-argument view: one purpose line per tool, grouped by family.

    This is the cheap "which tool?" answer — the whole point of the tier split. It is a tool
    RESULT, so unlike `_meta` or `annotations` it is always visible to the model.
    """
    families: dict[str, list[dict[str, Any]]] = {"rtm": [], "gtd": []}
    for t in sorted(tools, key=lambda t: str(t.get("name"))):
        name = str(t.get("name"))
        tax = taxonomy(name)
        families[tax["domain"]].append(
            {
                "tool": name,
                "purpose": purpose_sentence(str(t.get("description") or "")),
                "layer": tax["layer"],
                "consumer": tax["consumer"],
                "read_only": bool((t.get("annotations") or {}).get("readOnlyHint")),
            }
        )
    return {
        "server": "rtm",
        "tool_count": len(tools),
        "families": {
            "rtm": {
                "label": "Generic RTM primitives — close to one RTM API method each.",
                "tools": families["rtm"],
            },
            "gtd": {
                "label": (
                    "GTD domain compositions — speak Getting Things Done rather than mapping "
                    "1:1 to an API method. `layer: bff` tools are built for the board artifacts."
                ),
                "tools": families["gtd"],
            },
        },
        "next_step": (
            'Call rtm_tool_help("<tool>") for one tool\'s full contract: combination rules, '
            "worked examples, every return case, and the typed-error catalogue with recovery."
        ),
    }


#: The teaching-receipt contract, served on every governed write's tier-2 contract. Authored
#: here because tier 2 has budget where the description does not: the description carries only
#: the imperative (`receipt.RECEIPT_DOC`, ~190 bytes charged against ~2 KB), and this carries
#: the reasoning behind it. Neither restates the other, which is the § 3 rule.
#:
#: Why a caller should care, stated once: an optional modifier can fail to arrive without
#: anything failing — the hosted client deletes an undeclared argument before this server sees
#: it, and (measured 2026-08-01) a caller can emit the value as literal tool-call markup folded
#: into a sibling string, so the key never exists. Either way the write lands without that
#: property and reports success. The receipt is how that becomes visible after the fact.
RECEIPT_CONTRACT: dict[str, Any] = {
    "applied": (
        "One entry per RTM write that actually happened, each with the `transaction_id` "
        "`undo`/`batch_undo` needs. Since v4.0.0 it contains ONLY real writes — an operation "
        "that wrote nothing is in `not_applied[]`, so `len(applied)` is an honest count."
    ),
    "not_applied": (
        "One entry per operation you requested that produced NO write, as "
        "`{op, id, requested, reason, detail}`. `reason` is a stable code (`no_change` — "
        "already in that state; `no_durable_write` — a decision with no RTM change; "
        "`not_eligible` — the target does not qualify); `detail` is prose, never parse it. "
        "ALWAYS PRESENT, empty when everything landed — so branch on it unconditionally."
    ),
    "guidance": (
        "One plain next step, emitted ONLY where it says something the other fields do not: a "
        "PARTIAL batch (some writes durable, some failed — do not blindly retry, you would "
        "re-apply what succeeded) or a narrower-than-asked result (`not_applied[]` non-empty). "
        "`null` otherwise, including on a full rejection — `rejected[]` already carries every "
        "reason there. Narrowed in v4.1.0 after measurement: when it restated its neighbours it "
        "trained callers to skip it."
    ),
    "advisory": (
        "Set when the call arrived carrying NONE of this tool's optional parameters, naming "
        "them. Not a rejection and never blocking — a minimal call is often legitimate. It "
        "reports the OBSERVATION only; two causes are on record and the server cannot tell "
        "them apart. (1) The value was emitted as literal tool-call markup folded into another "
        "parameter (a stray `</…>` or `<parameter name=…>` tail) — the key never existed, and "
        "the text is written VERBATIM into the record. (2) Some MCP clients silently DROP a "
        "misspelt optional before the server sees it, so the write succeeds without that "
        "property. If you sent an optional and see this, it did not arrive as a parameter — "
        "check your own text for markup first, then re-send with the exact name."
    ),
    "how_to_use": (
        "After any governed write: if `not_applied[]` is non-empty, reconcile it against what "
        "you intended before telling the user it is done; if `advisory` is set and you meant "
        "to pass an optional, re-send it; follow `guidance` when present."
    ),
}


def build_contract(tool: dict[str, Any]) -> dict[str, Any]:
    """The named view: one tool's full contract, projected from its own advertised schema."""
    name = str(tool.get("name"))
    description = str(tool.get("description") or "")
    input_schema = tool.get("input_schema") or {}
    props = set((input_schema or {}).get("properties") or {})
    contract: dict[str, Any] = {
        "tool": name,
        "purpose": purpose_line(description),
        "taxonomy": taxonomy(name),
        "posture": posture(tool.get("annotations"), has_confirm="confirm_destructive" in props),
        "parameters": parameters(input_schema),
        "combination_rules": combination_rules(name, input_schema),
        "examples": list(EXAMPLES.get(name, ())),
        "returns": returns_prose(description),
        "errors": error_catalogue(description),
    }
    # The receipt rides on governed writes only — it answers "did what I asked for land?",
    # which a read has no answer to. Gated on the same posture the wrapper gates on, so the
    # contract can never advertise a receipt the tool does not attach.
    if not contract["posture"]["read_only"] and contract["taxonomy"]["domain"] == "gtd":
        contract["receipt"] = dict(RECEIPT_CONTRACT)
    edges = CHAIN.get(name)
    if edges:
        contract["chain"] = {
            "produced_by": list(edges.get("produced_by", ())),
            "feeds_into": list(edges.get("feeds_into", ())),
        }
    if contract["taxonomy"]["domain"] == "gtd":
        contract["see_also"] = (
            "This tool implements a mechanical contract only. For which GTD workflow it "
            "belongs to and when the method says to use it, see the `gtd` skill — the "
            "server deliberately does not hold that domain judgement."
        )
    return contract
