"""Output-schema models — the machine-readable RESULT contract for every tool.

These Pydantic models exist ONLY to generate each tool's MCP `outputSchema` (attached via
`@mcp.tool(output_schema=...)`), closing the input+output contract loop: a model calling a
tool now knows the result shape (for reliable multi-step chaining), not just how to call it.

They are **NOT used at runtime** — every tool still returns the plain `dict` envelope from
`response_builder`, and FastMCP advertises `output_schema` **without validating the return
against it**, so the error branch (and any richer real-world dict) passes through unharmed.

Contract shared by all tools (CONTRIBUTING § 3):

    {"data": <SUCCESS_PAYLOAD> | <ErrorData>, "metadata": {...}, "analysis"?: {...}}

`data` is ALWAYS advertised as a `success | error` union (`anyOf`), so a caller must branch on
the error discriminator before assuming a success shape. Since **v2.0.0** that discriminator is a
structured object, not prose: `{"error": {"code", "message", "rtm_code", "details"}}`, modelled as
`ErrorData` → `ErrorBody`. `code` is a stable member of the canonical `error_codes.ErrorCode`
registry and is the thing to branch on; `message` is the same actionable prose that used to BE
`data.error` (carried verbatim — only its location moved) and must never be parsed; the recovery
material specific paths attach (`strict_tag_mode` + `how_to_proceed` from the strict-tag gate;
`candidates`; `query`) now rides under `details`. Deeply-nested, evolving, or versioned-external payloads
(project-plan-seed rows, canvas seed rows, RTM `raw` passthroughs) keep `extra="allow"` /
`dict[str, Any]` on purpose — they evolve ahead of this server and are never vocabulary-filtered.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from .canvas_commit import COMMIT_REJECT_REASONS
from .canvas_create import CREATE_REJECT_REASONS
from .engage_commit import ENGAGE_REJECT_REASONS
from .error_codes import ErrorCode


def _enum_extra(reasons: frozenset[ErrorCode]) -> dict[str, Any]:
    """A `json_schema_extra` payload advertising a closed string enum, sourced from a handler's
    canonical reason constant so the advertised vocabulary tracks the handler by construction.

    Members are `ErrorCode` (str-mixin) since v2.0.0 — `.value` is taken so the advertised
    schema carries plain wire strings, not `ErrorCode.X` reprs."""
    return {"enum": sorted(r.value for r in reasons)}


# --------------------------------------------------------------------------- #
# Shared envelope pieces
# --------------------------------------------------------------------------- #


class ErrorBody(BaseModel):
    """The structured error object (v2.0.0). `code` is the machine-branchable
    discriminator; `message` is human-facing prose and MUST NOT be parsed.

    `extra="forbid"`: every optional key lives under `details`, so the top level is a
    closed four-field contract. Detail keys stay open (`dict[str, Any]`) because they
    are per-family and evolving — `candidates`, `how_to_proceed`, `strict_tag_mode`,
    `rejected`, `query`, …"""

    model_config = ConfigDict(extra="forbid")
    code: ErrorCode = Field(description="Stable code from the canonical registry — branch on this.")
    message: str = Field(
        description="Actionable human-facing prose. Never parse it; branch on code."
    )
    rtm_code: int | None = Field(
        default=None, description="Originating RTM API numeric, when the failure came from RTM."
    )
    details: dict[str, Any] | None = Field(
        default=None, description="Optional per-family detail keys. Absent when there are none."
    )


class ErrorData(BaseModel):
    """The `data` payload on any failure: `{"error": {"code": ..., "message": ...}}`.

    BREAKING in v2.0.0 — `error` was a free-text string through v1.35.0; it is now an
    object. The prose survives verbatim as `error.message`; only its location moved.

    `extra="allow"` is retained for the genuine siblings a few paths set alongside
    `error` (notably `status` on `test_connection` / `check_auth`, and `transaction_id`
    on the undo paths) — NOT for error detail keys, which now belong under
    `error.details`."""

    model_config = ConfigDict(extra="allow")
    error: ErrorBody


class Candidate(BaseModel):
    id: str
    name: str
    list_id: str | None = None


class Candidates(BaseModel):
    """The ambiguity branch of the project/focus resolvers — call again with an id."""

    candidates: list[Candidate]


class Metadata(BaseModel):
    fetched_at: str
    transaction_id: str | None = None  # write ops only
    transaction_undoable: bool | None = None  # write ops only
    timeline_id: str | None = None  # write ops only


class MessageResult(BaseModel):
    """A bare acknowledgement — used by deletes and other no-object writes."""

    message: str


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #


class Task(BaseModel):
    """A formatted task (parsers.format_task) — the object every task write returns."""

    name: str
    priority: str  # "high" | "medium" | "low" | "none"
    due: str | None
    start: str | None
    completed: str | None
    tags: list[str]
    url: str | None
    notes_count: int
    estimate: str | None
    parent_task_id: str | None
    subtask_count: int
    modified: str | None
    id: str
    taskseries_id: str
    list_id: str


class TaskListResult(BaseModel):
    tasks: list[Task]
    count: int


class TaskWriteResult(BaseModel):
    task: Task
    message: str


# --------------------------------------------------------------------------- #
# Notes
# --------------------------------------------------------------------------- #


class NoteObject(BaseModel):
    id: str | None
    title: str
    body: str
    created: str | None = None  # add_note / get_task_notes
    modified: str | None = None  # edit_note / get_task_notes


class NoteWriteResult(BaseModel):
    note: NoteObject
    message: str


class TaskNotesResult(BaseModel):
    task_name: str | None
    notes: list[NoteObject]
    count: int


# --------------------------------------------------------------------------- #
# Lists
# --------------------------------------------------------------------------- #


class ListObject(BaseModel):
    id: str | None
    name: str
    smart: bool
    archived: bool
    locked: bool


class ListsResult(BaseModel):
    lists: list[ListObject]
    count: int


class ListWriteResult(BaseModel):
    list: ListObject
    message: str


# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #


class TestConnectionResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: str  # "connected"
    response_time_ms: float
    api_response: dict[str, Any]


class AuthUser(BaseModel):
    id: str | None
    username: str | None
    fullname: str | None


class CheckAuthResult(BaseModel):
    status: str  # "authenticated"
    user: AuthUser
    permissions: str | None


class TagName(BaseModel):
    name: str


class TagsResult(BaseModel):
    tags: list[TagName]
    count: int


class Location(BaseModel):
    id: str | None
    name: str | None
    latitude: float
    longitude: float
    zoom: int | None
    address: str | None


class LocationsResult(BaseModel):
    locations: list[Location]
    count: int


class SettingsResult(BaseModel):
    timezone: str | None
    date_format: str
    time_format: str
    default_list_id: str | None
    language: str | None
    raw: dict[str, Any]  # full RTM settings passthrough — open


class ParseTimeResult(BaseModel):
    input: str
    parsed: str | None  # ISO-8601, chainable into set_task_due_date/start
    precision: str | None  # "date" | "time"


class UndoResult(BaseModel):
    status: str  # "success"
    message: str
    transaction_id: str


class BatchUndoResult(BaseModel):
    undone: list[str]
    skipped: list[str]  # already-undone ids
    failed: dict[str, Any] | None
    timeline_id: str | None


class TransactionEntry(BaseModel):
    transaction_id: str
    method: str
    undoable: bool
    undone: bool
    summary: str


class TimelineInfoResult(BaseModel):
    timeline_id: str | None
    created_at: str | None
    transaction_count: int
    transactions: list[TransactionEntry]


class Contact(BaseModel):
    id: str | None
    fullname: str | None
    username: str | None


class ContactsResult(BaseModel):
    contacts: list[Contact]
    count: int


class Group(BaseModel):
    id: str | None
    name: str | None
    member_count: int


class GroupsResult(BaseModel):
    groups: list[Group]
    count: int


class RateLimitResult(BaseModel):
    tokens_available: float
    bucket_capacity: int
    refill_rate: float
    safety_margin: float
    requests_last_60s: int
    retries_last_60s: int
    http_503_count_session: int
    connection_retries_last_60s: int
    reads_session: int
    writes_session: int


class HierarchyStep(BaseModel):
    name: str
    level: int


class TaskUrlResult(BaseModel):
    model_config = ConfigDict(extra="allow")  # optional `warning`
    url: str
    task_name: str
    list_name: str
    list_id: str
    hierarchy: list[HierarchyStep]


class ListUrlResult(BaseModel):
    url: str
    list_name: str | None
    list_id: str


# --------------------------------------------------------------------------- #
# GTD — project-plan-seed/3 envelope (gtd_project_plan) — the headline citation target
# --------------------------------------------------------------------------- #


class PlanNote(BaseModel):
    model_config = ConfigDict(extra="allow")  # note-object shape evolves with the envelope


class PlanHeaderProject(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    life: str
    listId: str
    permalink: str
    notes: list[dict[str, Any]]
    files: list[str]
    redacted: bool
    is_repeating: bool
    taskseries_id: str


class PlanHeader(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    type: str
    schema_: str = Field(alias="schema")  # "project-plan-seed/3"
    projectId: str
    project: PlanHeaderProject
    rowCount: int


class PlanRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str  # "row"
    id: str
    name: str
    priority: str  # word-form: High | Medium | Low | NoPriority
    completed: int  # 0 | 1
    completedDate: str
    due: str
    tags: list[str]
    permalink: str
    deps: list[str]
    files: list[str]
    noteCount: int
    notes: list[dict[str, Any]]
    estimate: str
    start: str
    url: str
    is_repeating: bool
    taskseries_id: str
    template_child_id: str


class ProjectPlanEnvelope(BaseModel):
    header: PlanHeader
    rows: list[PlanRow]


# --------------------------------------------------------------------------- #
# GTD — canvas seed (gtd_project_canvas)
# --------------------------------------------------------------------------- #


class CanvasFrame(BaseModel):
    model_config = ConfigDict(extra="allow")  # optional notes[]/files[]
    life: str
    focus: str
    name: str
    url: str
    redacted: bool


class CanvasSeedRow(BaseModel):
    """A rendered canvas item — short-key shape from canvas_seed.map_row; keys beyond the common
    core (c/m/p/d/hx/cd/nc/deps/prog/…) are item-kind-dependent, hence extra="allow"."""

    model_config = ConfigDict(extra="allow")
    id: str | None
    k: str  # "action" | "waiting_for" | "calendar"
    t: str  # display text (name)
    redacted: bool


class CanvasSeedResult(BaseModel):
    mode: str  # "existing"
    frame: CanvasFrame
    seed: list[CanvasSeedRow]


# --------------------------------------------------------------------------- #
# GTD — portfolio index (gtd_project_index)
# --------------------------------------------------------------------------- #


class ProjectRow(BaseModel):
    life: str
    focus: str
    focus_id: str
    project: str
    project_id: str
    priority: str  # "1" | "2" | "3" | ""
    open_count: int
    blocked_count: int
    next_tickle: str
    updated: str
    ai_quick: int
    ai_now: int
    ai_later: int
    chat_count: int
    chat_review_count: int
    waiting_count: int
    redacted: bool


class FocusRow(BaseModel):
    focus_id: str
    focus: str
    life: str
    redacted: bool


class ActionRow(BaseModel):
    action_id: str
    name: str
    project_id: str
    project: str
    focus: str
    life: str
    type: str  # "action" | "waiting_for" | "calendar"
    due: str
    priority: str  # "1" | "2" | "3" | ""
    blocked: bool
    estimate: int | None
    contexts: list[str]
    energy: str | None  # "high" | "low" | null
    exec: str | None  # "quick" | "now" | "later" | null
    redacted: bool


class ProjectIndexResult(BaseModel):
    projects: list[ProjectRow]
    foci: list[FocusRow]
    actions: list[ActionRow]


# --------------------------------------------------------------------------- #
# GTD — governed writes (commit / create / stamp)
# --------------------------------------------------------------------------- #


class AppliedOp(BaseModel):
    model_config = ConfigDict(extra="allow")
    op: str
    id: str | None = None
    transaction_id: str | None = None


class CommitRejection(BaseModel):
    model_config = ConfigDict(extra="allow")
    # Enum sourced from the handler's canonical constant so the advertised vocabulary can never
    # drift from what gtd_apply_canvas_commit actually emits (test_tool_schemas pins the equality).
    reason: str = Field(json_schema_extra=_enum_extra(COMMIT_REJECT_REASONS))


class CommitResult(BaseModel):
    """gtd_apply_canvas_commit — covers both the success apply and the rejection (nothing
    written) branches, so a caller reads `rejected` before trusting `applied`."""

    model_config = ConfigDict(extra="allow")
    project_id: str | None = None
    applied: list[AppliedOp]
    errors: list[dict[str, Any]] = []
    rejected: list[CommitRejection] | None = None
    order_persisted: str | bool  # "order-note" | false
    message: str


class CreateRejection(BaseModel):
    model_config = ConfigDict(extra="allow")
    reason: str = Field(json_schema_extra=_enum_extra(CREATE_REJECT_REASONS))


class CreateProjectResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    project_id: str | None = None
    url: str | None = None
    created: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    progressed: dict[str, Any] = {}
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[CreateRejection] | None = None
    message: str


class StampProject(BaseModel):
    model_config = ConfigDict(extra="allow")
    project_id: str
    project_name: str
    is_repeating: bool
    stamped: list[dict[str, Any]]
    dep_lines: list[dict[str, Any]]
    skipped_reason: str | None = None


class StampTokensResult(BaseModel):
    projects: list[StampProject]
    dry_run: bool
    applied: list[AppliedOp]
    errors: list[dict[str, Any]]
    message: str


# --------------------------------------------------------------------------- #
# GTD — conversation surface (chat)
# --------------------------------------------------------------------------- #


class ChatNote(BaseModel):
    id: str | None
    title: str
    created: str | None


class ChatPostResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    note: ChatNote
    task_id: str
    role: str  # "me" | "ai"
    tag_changes: list[str]
    errors: list[dict[str, Any]]


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="allow")
    note_id: str | None
    role: str
    scope: str | None = None
    mode: str | None = None
    text: str
    created: str | None
    files: list[dict[str, Any]]
    links: list[dict[str, Any]]


class ChatThreadResult(BaseModel):
    task_id: str
    turns: list[ChatTurn]
    requested: bool


class InflightItem(BaseModel):
    task_id: str
    name: str
    scope: str  # "item" | "project"
    status: str  # "in_flight" | "awaiting_review" | "open"
    project_id: str
    project_name: str
    last_activity: str


class ChatInflightResult(BaseModel):
    items: list[InflightItem]
    count: int


# --------------------------------------------------------------------------- #
# GTD — redaction + engage
# --------------------------------------------------------------------------- #


class RedactionResult(BaseModel):
    task_id: str
    redacted: bool


class EngageItem(BaseModel):
    id: str
    name: str
    kind: str  # "action" | "waiting_for" | "calendar_entry" | "project"
    has_deadline: bool
    blocked: bool
    postponed: int
    suggested: str
    redacted: bool
    due: str


class EngageSeedResult(BaseModel):
    items: list[EngageItem]
    current_date: str
    count: int


class EngageRejection(BaseModel):
    model_config = ConfigDict(extra="allow")
    reason: str = Field(json_schema_extra=_enum_extra(ENGAGE_REJECT_REASONS))


class EngageCommitResult(BaseModel):
    """gtd_apply_engage_commit — success apply + the hard-fail rejection (nothing written)."""

    model_config = ConfigDict(extra="allow")
    applied: list[AppliedOp]
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rejected: list[EngageRejection] | None = None
    count: int
    message: str


# --------------------------------------------------------------------------- #
# Phase 0 reads — detector candidate tools (gtd_*_candidates / clusters / health)
# --------------------------------------------------------------------------- #


class CandidateRow(BaseModel):
    """A typed detector-candidate row. Common projection fields are named; per-detector extras
    (modified / tag_set / source_class / due / start / date / time / status / taskseries_id /
    list_id) ride under the permissive config so one model serves every candidate detector."""

    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    kind: str  # action | waiting_for | calendar
    priority: str  # "1" | "2" | "3" | ""
    tags: list[str] = []
    parent_id: str | None = None
    deep_link: str


class SkippedItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    reason: str


class ReassessmentResult(BaseModel):
    candidates: list[CandidateRow]
    skipped: list[SkippedItem]
    stale_threshold_days: int
    count: int


class UnblockResult(BaseModel):
    candidates: list[CandidateRow]
    skipped: list[SkippedItem]
    cap: int
    stale_speculative_days: int
    count: int


class LexicalCandidatesResult(BaseModel):
    """decision / deliverable / research / calendar-prep — {candidates, skipped, horizon_days}."""

    candidates: list[CandidateRow]
    skipped: list[SkippedItem]
    horizon_days: int
    count: int


class CaptureResult(BaseModel):
    candidates: list[CandidateRow]
    skipped: list[SkippedItem]
    window_days: int
    count: int


class ClusterSample(BaseModel):
    id: str
    name: str


class TopicClusterRow(BaseModel):
    anchor: str
    anchor_type: str  # person | theme
    item_count: int
    distinct_projects: int
    sample_items: list[ClusterSample]


class TopicClustersResult(BaseModel):
    clusters: list[TopicClusterRow]
    threshold: int
    exclude_personal: bool
    cap: int
    count: int


class HealthIssue(BaseModel):
    category: str
    name: str
    task_id: str
    deep_link: str


class HealthCheckResult(BaseModel):
    issues: list[HealthIssue]
    count: int
    current_date: str


# --------------------------------------------------------------------------- #
# Phase 0 reads — collection / context tools
# --------------------------------------------------------------------------- #


class QueryRow(BaseModel):
    model_config = ConfigDict(extra="allow")  # context / focus / focus_id per perspective
    id: str
    name: str
    kind: str
    priority: str
    due: str
    tags: list[str] = []
    parent_id: str | None = None
    deep_link: str


class QueryResult(BaseModel):
    model_config = ConfigDict(extra="allow")  # context / focus_id echo per perspective
    perspective: str
    rows: list[QueryRow]
    count: int


class InboxStateResult(BaseModel):
    depth: int
    unprocessed_count: int
    awaiting_review_count: int
    approved_unapplied_count: int
    unprocessed: list[QueryRow]
    awaiting_review: list[QueryRow]
    approved_unapplied: list[QueryRow]


class WaitingForRow(QueryRow):
    updated: str
    stale: bool


class WaitingForResult(BaseModel):
    rows: list[WaitingForRow]
    count: int
    stale_count: int
    current_date: str


class ContextTaskView(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    list_id: str
    taskseries_id: str
    gtd_type: str
    kind: str
    priority: str
    due: str
    start: str
    tags: list[str] = []
    parent_id: str | None = None
    notes_count: int
    deep_link: str


class ContextNote(BaseModel):
    id: str
    type: str
    date: str
    summary: str
    body: str


class SiblingRef(BaseModel):
    id: str
    name: str
    gtd_type: str
    completed: bool
    deep_link: str


class AncestorRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    gtd_type: str
    deep_link: str


class ContextResult(BaseModel):
    task: ContextTaskView
    notes: list[ContextNote]
    siblings: list[SiblingRef]
    ancestors: list[AncestorRef]
    depth: str


# --------------------------------------------------------------------------- #
# Envelope schema builder — {data: <Success…> | ErrorData, metadata, analysis?}
# --------------------------------------------------------------------------- #


def _envelope_schema(name: str, *success: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema for a tool's result: the standard envelope whose `data` is a union of the
    tool's success payload(s) and the shared ErrorData. `analysis` is an optional sibling (some
    reads emit insights, e.g. list_tasks / gtd_project_canvas). `create_model` lets pydantic
    assemble the `$defs` and the `anyOf` cleanly."""
    union: Any = success[0]
    for s in success[1:]:
        union = union | s
    union = union | ErrorData
    env = create_model(
        name,
        data=(union, ...),
        metadata=(Metadata, ...),
        analysis=(dict[str, Any] | None, None),
    )
    return env.model_json_schema()


# Tasks
LIST_TASKS_OUTPUT = _envelope_schema("ListTasksEnvelope", TaskListResult)
TASK_WRITE_OUTPUT = _envelope_schema("TaskWriteEnvelope", TaskWriteResult)
DELETE_TASK_OUTPUT = _envelope_schema("DeleteTaskEnvelope", MessageResult)

# Notes
NOTE_WRITE_OUTPUT = _envelope_schema("NoteWriteEnvelope", NoteWriteResult)
DELETE_NOTE_OUTPUT = _envelope_schema("DeleteNoteEnvelope", MessageResult)
TASK_NOTES_OUTPUT = _envelope_schema("TaskNotesEnvelope", TaskNotesResult)

# Lists
GET_LISTS_OUTPUT = _envelope_schema("GetListsEnvelope", ListsResult)
LIST_WRITE_OUTPUT = _envelope_schema("ListWriteEnvelope", ListWriteResult)
LIST_MESSAGE_OUTPUT = _envelope_schema("ListMessageEnvelope", MessageResult)

# Utilities
TEST_CONNECTION_OUTPUT = _envelope_schema("TestConnectionEnvelope", TestConnectionResult)
CHECK_AUTH_OUTPUT = _envelope_schema("CheckAuthEnvelope", CheckAuthResult)
GET_TAGS_OUTPUT = _envelope_schema("GetTagsEnvelope", TagsResult)
GET_LOCATIONS_OUTPUT = _envelope_schema("GetLocationsEnvelope", LocationsResult)
GET_SETTINGS_OUTPUT = _envelope_schema("GetSettingsEnvelope", SettingsResult)
PARSE_TIME_OUTPUT = _envelope_schema("ParseTimeEnvelope", ParseTimeResult)
UNDO_OUTPUT = _envelope_schema("UndoEnvelope", UndoResult)
BATCH_UNDO_OUTPUT = _envelope_schema("BatchUndoEnvelope", BatchUndoResult)
TIMELINE_INFO_OUTPUT = _envelope_schema("TimelineInfoEnvelope", TimelineInfoResult)
CONTACTS_OUTPUT = _envelope_schema("ContactsEnvelope", ContactsResult)
GROUPS_OUTPUT = _envelope_schema("GroupsEnvelope", GroupsResult)
RATE_LIMIT_OUTPUT = _envelope_schema("RateLimitEnvelope", RateLimitResult)
TASK_URL_OUTPUT = _envelope_schema("TaskUrlEnvelope", TaskUrlResult)
LIST_URL_OUTPUT = _envelope_schema("ListUrlEnvelope", ListUrlResult)

# GTD
PROJECT_PLAN_OUTPUT = _envelope_schema("ProjectPlanEnvelopeSchema", ProjectPlanEnvelope, Candidates)
PROJECT_CANVAS_OUTPUT = _envelope_schema("ProjectCanvasEnvelope", CanvasSeedResult, Candidates)
PROJECT_INDEX_OUTPUT = _envelope_schema("ProjectIndexEnvelope", ProjectIndexResult)
CANVAS_COMMIT_OUTPUT = _envelope_schema("CanvasCommitEnvelope", CommitResult)
CREATE_PROJECT_OUTPUT = _envelope_schema("CreateProjectEnvelope", CreateProjectResult, Candidates)
STAMP_TOKENS_OUTPUT = _envelope_schema("StampTokensEnvelope", StampTokensResult)
CHAT_POST_OUTPUT = _envelope_schema("ChatPostEnvelope", ChatPostResult)
CHAT_THREAD_OUTPUT = _envelope_schema("ChatThreadEnvelope", ChatThreadResult)
CHAT_INFLIGHT_OUTPUT = _envelope_schema("ChatInflightEnvelope", ChatInflightResult)
SET_REDACTION_OUTPUT = _envelope_schema("SetRedactionEnvelope", RedactionResult)
ENGAGE_SEED_OUTPUT = _envelope_schema("EngageSeedEnvelope", EngageSeedResult)
ENGAGE_COMMIT_OUTPUT = _envelope_schema("EngageCommitEnvelope", EngageCommitResult)

# GTD Phase 0 reads — detector candidates
REASSESSMENT_OUTPUT = _envelope_schema("ReassessmentEnvelope", ReassessmentResult)
UNBLOCK_OUTPUT = _envelope_schema("UnblockEnvelope", UnblockResult)
DECISION_OUTPUT = _envelope_schema("DecisionEnvelope", LexicalCandidatesResult)
DELIVERABLE_OUTPUT = _envelope_schema("DeliverableEnvelope", LexicalCandidatesResult)
RESEARCH_OUTPUT = _envelope_schema("ResearchEnvelope", LexicalCandidatesResult)
CALENDAR_PREP_OUTPUT = _envelope_schema("CalendarPrepEnvelope", LexicalCandidatesResult)
CAPTURE_OUTPUT = _envelope_schema("CaptureEnvelope", CaptureResult)
TOPIC_CLUSTERS_OUTPUT = _envelope_schema("TopicClustersEnvelope", TopicClustersResult)
HEALTH_CHECK_OUTPUT = _envelope_schema("HealthCheckEnvelope", HealthCheckResult)

# GTD Phase 0 reads — collection / context
GTD_QUERY_OUTPUT = _envelope_schema("GtdQueryEnvelope", QueryResult, Candidates)
INBOX_STATE_OUTPUT = _envelope_schema("InboxStateEnvelope", InboxStateResult)
WAITING_FOR_OUTPUT = _envelope_schema("WaitingForEnvelope", WaitingForResult)
GTD_CONTEXT_OUTPUT = _envelope_schema("GtdContextEnvelope", ContextResult, Candidates)
