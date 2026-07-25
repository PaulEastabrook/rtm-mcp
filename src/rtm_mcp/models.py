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
from .gtd_writes import GTD_WRITE_REJECT_REASONS


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
    # drift from what gtd_canvas_commit actually emits (test_tool_schemas pins the equality).
    reason: str = Field(json_schema_extra=_enum_extra(COMMIT_REJECT_REASONS))


class CommitResult(BaseModel):
    """gtd_canvas_commit — covers both the success apply and the rejection (nothing
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
    """gtd_engage_commit — success apply + the hard-fail rejection (nothing written)."""

    model_config = ConfigDict(extra="allow")
    applied: list[AppliedOp]
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rejected: list[EngageRejection] | None = None
    count: int
    message: str


# --------------------------------------------------------------------------- #
# Phase 1 writes — the four everyday governed write tools
# --------------------------------------------------------------------------- #


class GtdWriteRejection(BaseModel):
    model_config = ConfigDict(extra="allow")
    reason: str = Field(json_schema_extra=_enum_extra(GTD_WRITE_REJECT_REASONS))
    detail: str = ""


class CreateItemResult(BaseModel):
    """TRUE post-state of the created item — the real id triple RTM returned, never an echo."""

    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    taskseries_id: str = ""
    list_id: str = ""
    name: str = ""
    kind: str = ""
    tags: list[str] = []
    priority: str = ""
    due: str = ""
    deep_link: str = ""
    ready: bool = False
    missing: list[str] = []
    advisory: list[str] = []
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class AddNoteResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    note_title: str = ""
    note_type: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class GtdCaptureResult(BaseModel):
    """gtd_inbox_capture — the TRUE post-state of a raw Inbox_Stuff capture."""

    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    taskseries_id: str = ""
    list_id: str = ""
    name: str = ""
    list_name: str = ""
    tags: list[str] = []
    deep_link: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class TransitionResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    tags: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    signal_stamped: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


# --------------------------------------------------------------------------- #
# Phase 2 writes — completion, dependency, properties, bulk
# --------------------------------------------------------------------------- #


class CompleteActionResult(BaseModel):
    """gtd_item_complete — true post-state plus the fan-out events the caller should fire.

    `fanout_events` are gtd `progression-fanout` EVENT names, not tags: no RTM tag by those names
    exists and a server cannot invoke an agent, so they are returned as data while the sanctioned
    durable mark (`ai_overlay_refresh_needed`) is stamped on the parent project."""

    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    completed: bool = False
    note_type: str = ""
    note_title: str = ""
    cascade_note_title: str = ""
    approval_transition: bool = False
    fanout_events: list[str] = []
    created_items: list[str] = []
    signal_stamped: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class CloseInboxItemResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    completed: bool = False
    note_title: str = ""
    derived_count: int = 0
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class SetPropertiesResult(BaseModel):
    """gtd_item_set_properties — priority/estimate are taskseries-level, so a write may be REDIRECTED
    to the series' nearest-active occurrence; divergent proposals are surfaced, never picked."""

    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    written_to_task_id: str = ""
    properties_set: list[str] = []
    series_collapsed: bool = False
    divergent: list[dict[str, Any]] = []
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class LinkDependencyResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    dependent_id: str = ""
    upstream_id: str = ""
    upstream_type: str = ""
    status: str = ""
    note_title: str = ""
    signal_stamped: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class BatchItemResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    applied: bool = False
    tags: list[str] = []
    signal_stamped: str = ""


class BatchTransitionResult(BaseModel):
    """All-or-nothing (D9): if ANY item fails validation, `applied_count` is 0 and `rejected`
    carries the per-item reasons — nothing was written."""

    model_config = ConfigDict(extra="allow")
    results: list[BatchItemResult] = []
    applied_count: int = 0
    requested_count: int = 0
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


# --------------------------------------------------------------------------- #
# Phase 3 writes — process ops (apply a reviewed verdict set)
# --------------------------------------------------------------------------- #


class ProcessItemResult(BaseModel):
    """One applied item's outcome + its true post-state."""

    model_config = ConfigDict(extra="allow")
    ref: str
    verb: str = ""
    applied: bool = False
    task_id: str = ""
    detail: str = ""


class ProcessOpResult(BaseModel):
    """Shared shape for the three process ops.

    Atomicity contract: the WHOLE set is validated before anything is written — one invalid item
    rejects the call with `applied_count: 0`. If the RTM API then fails mid-apply, the split
    between `results` (applied) and `remaining` (not yet attempted) is returned so the caller can
    resume safely rather than guess.
    """

    model_config = ConfigDict(extra="allow")
    results: list[ProcessItemResult] = []
    applied_count: int = 0
    requested_count: int = 0
    remaining: list[str] = []
    projects_signalled: list[str] = []
    fanout_events: list[str] = []
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


# --------------------------------------------------------------------------- #
# Phase 4a writes — note family, note-edit, dependency-flip
# --------------------------------------------------------------------------- #


class AttachOutputResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    output_note_title: str = ""
    filing_path: str = ""
    register_updated: bool = False
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class AttachContributionResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    note_type: str = ""
    note_title: str = ""
    tag: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class AnnotateClarificationResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    note_title: str = ""
    renamed: bool = False
    new_name: str = ""
    questions_count: int = 0
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class EditNoteResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    note_id: str = ""
    op: str = ""
    changed: bool = False
    detail: str = ""
    note_title: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


# --------------------------------------------------------------------------- #
# Phase 4b writes — the AI-surface subsystem
# --------------------------------------------------------------------------- #


class AiLinkRef(BaseModel):
    entity_id: str
    ai_link_note_id: str = ""
    entity_type: str = ""


class SurfaceCreateResult(BaseModel):
    """True post-state of a created AI-surface item + the AI-LINK back-links written."""

    model_config = ConfigDict(extra="allow")
    item_id: str = ""
    task_id: str = ""
    taskseries_id: str = ""
    list_id: str = ""
    list_name: str = ""
    item_type: str = ""
    item_type_tag: str = ""
    title: str = ""
    tags: list[str] = []
    auto_close_at: str | None = None
    ai_links_created: list[AiLinkRef] = []
    ai_links_skipped: list[str] = []
    status: str = ""  # created | already_existed
    deep_link: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
    message: str


class SurfaceResolveResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    task_id: str = ""
    item_id: str = ""
    resolution: str = ""
    tags_added: list[str] = []
    tags_removed: list[str] = []
    outcome_note_title: str = ""
    completed: bool = False
    links_updated: list[AiLinkRef] = []
    link_status: str = ""
    applied: list[AppliedOp] = []
    errors: list[dict[str, Any]] = []
    rejected: list[GtdWriteRejection] | None = None
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
# Wave 1 — the eight MilkScript-retirement reads (v2.9.0)
# --------------------------------------------------------------------------- #


class SurfaceQueueEntity(BaseModel):
    """One linked entity from a surface item's body frontmatter."""

    model_config = ConfigDict(extra="allow")
    entity_type: str = ""
    entity_url: str = ""
    entity_rtm: dict[str, str] = {}
    relationship: str = ""


class SurfaceEvidence(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    detail: str


class SurfaceUnrecognisedNote(BaseModel):
    note_id: str
    title: str
    created: str


class SurfaceQueueRow(BaseModel):
    task_id: str
    taskseries_id: str
    list_id: str
    surface: str
    name: str
    tags: list[str] = []
    notes_count: int
    created: str
    modified: str
    completed: str
    deep_link: str
    item_id: str | None = None
    item_type: str | None = None
    entities: list[SurfaceQueueEntity] = []
    expected_response_shape: str | None = None
    expected_response_options: list[str] = []
    asked_by: str | None = None
    asked_at: str | None = None
    auto_close_at: str | None = None
    related_artefact: str | None = None
    metadata_parse_error: str | None = None
    auto_close_due: bool
    response_detected: bool
    response_evidence: list[SurfaceEvidence] = []
    unrecognised_notes: list[SurfaceUnrecognisedNote] = []


class SurfaceQueueResult(BaseModel):
    """`questions` / `activity` are present only for the surfaces requested."""

    model_config = ConfigDict(extra="allow")
    surface: str
    current_date: str
    count: int
    metadata_missing_count: int
    questions: list[SurfaceQueueRow] | None = None
    activity: list[SurfaceQueueRow] | None = None


class EngineGap(BaseModel):
    metric: str
    reason: str


class EngineContributions(BaseModel):
    model_config = ConfigDict(extra="allow")
    drafted_in_window: int
    touched_in_window: int
    undated_creation: int
    open_total: int
    cohort_ids: list[str] = []
    by_category: dict[str, int] = {}
    by_state: dict[str, int] = {}
    accepted_count: int
    edited_count: int
    discarded_count: int
    stale_count: int
    acceptance_rate_pct: int
    edit_rate_pct: int
    discard_rate_pct: int
    per_category_acceptance_rate_pct: dict[str, int] = {}


class EngineSurfaceSide(BaseModel):
    model_config = ConfigDict(extra="allow")
    created_in_window: int
    touched_in_window: int
    closed_in_window: int
    auto_closed_in_window: int
    paul_engaged_in_window: int
    open_depth: int
    queue_bloat: bool
    queue_bloat_threshold: int
    avg_latency_to_engagement_hours: float | None = None
    latency_basis: str
    per_item_type: dict[str, dict[str, int]] = {}


class EngineSurface(BaseModel):
    questions: EngineSurfaceSide
    activity: EngineSurfaceSide


class EngineSpeculation(BaseModel):
    open_total: int
    opened_in_window: int
    touched_in_window: int
    oldest_open: str | None = None
    upgrade_rate_reported: bool


class EngineReportResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    window_days: int
    window_start: str
    window_end: str
    window_semantics: str
    current_date: str
    contributions: EngineContributions
    ai_surface: EngineSurface
    speculation: EngineSpeculation
    engine_state: dict[str, int]
    gaps: list[EngineGap] = []


class DependencyGapRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    project_id: str
    name: str
    list_id: str
    parent_id: str
    tags: list[str] = []
    redacted: bool
    deep_link: str
    open_child_count: int | None = None


class DependencyGapsResult(BaseModel):
    eligible: list[DependencyGapRow] = []
    eligible_count: int
    eligible_total: int
    capped: bool
    max_projects: int
    skipped: list[DependencyGapRow] = []
    skipped_count: int
    vault_filter_pending: str


class TagUsage(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    active_count: int


class TagMinimumSet(BaseModel):
    missing_life_context_count: int
    missing_life_context_sample: list[dict[str, str]] = []
    missing_workflow_state_count: int
    missing_workflow_state_sample: list[dict[str, str]] = []
    actions_missing_action_context_count: int
    actions_missing_action_context_sample: list[dict[str, str]] = []


class TagReportResult(BaseModel):
    current_date: str
    total_account_tags: int
    canonical: list[str] = []
    canonical_count: int
    family: list[TagUsage] = []
    family_count: int
    people: list[TagUsage] = []
    retired_in_use: list[TagUsage] = []
    retired_unused: list[TagUsage] = []
    non_canonical_active: list[TagUsage] = []
    non_canonical_unused: list[TagUsage] = []
    non_canonical_count: int
    orphaned_in_use: list[str] = []
    minimum_tag_set: TagMinimumSet
    people_caveat: str
    sample_limit: int


class ReviewCohort(BaseModel):
    model_config = ConfigDict(extra="allow")
    by_life_context: dict[str, int] = {}
    no_life_context: int
    total: int


class ReviewLifeState(BaseModel):
    by_workflow_state: dict[str, int] = {}
    total: int


class ReviewVelocity(BaseModel):
    net_change: int
    direction: str


class ReviewReportResult(BaseModel):
    window_days: int
    current_date: str
    completed: ReviewCohort
    added: ReviewCohort
    current_state: dict[str, ReviewLifeState] = {}
    overdue_count: int
    inbox_depth: int
    velocity: ReviewVelocity


class StaleRow(BaseModel):
    task_id: str
    name: str
    state: str
    kind: str
    life: str
    age_days: int
    updated: str
    due: str
    priority: str
    parent_id: str
    redacted: bool
    deep_link: str


class ItemStaleResult(BaseModel):
    threshold_days: int
    current_date: str
    rows: list[StaleRow] = []
    count: int
    by_state: dict[str, int] = {}
    undated_modification: int


class WorkloadCell(BaseModel):
    count: int
    estimated_count: int
    estimate_minutes: int


class WorkloadLife(BaseModel):
    by_workflow_state: dict[str, WorkloadCell] = {}
    total: int
    estimated_count: int
    estimate_minutes: int
    estimate_hours: float
    estimate_coverage_pct: int


class WorkloadTotals(BaseModel):
    count: int
    estimated_count: int
    estimate_minutes: int
    estimate_hours: float


class WorkloadReportResult(BaseModel):
    current_date: str
    by_life_context: dict[str, WorkloadLife] = {}
    totals: WorkloadTotals
    unclassified_count: int


class FocusIndexRow(BaseModel):
    focus_id: str
    focus: str
    life: str
    project_count: int
    direct_item_count: int
    priority: str
    updated: str
    redacted: bool
    parent_id: str
    deep_link: str


class FocusIndexResult(BaseModel):
    current_date: str
    rows: list[FocusIndexRow] = []
    count: int
    by_life_context: dict[str, int] = {}
    unclassified_count: int


# --------------------------------------------------------------------------- #
# Wave 1b — shape classification + the contribution state machine (v2.10.0)
# --------------------------------------------------------------------------- #


class ShapeKnockOut(BaseModel):
    shape: str
    anti_pattern: str


class ItemClassifyResult(BaseModel):
    name: str
    shape: str
    matched_pattern: str
    also_matched: list[str] = []
    knocked_out: list[ShapeKnockOut] = []


class ContribRejection(BaseModel):
    model_config = ConfigDict(extra="allow")
    reason: str
    detail: str


class ContribTransitionResult(BaseModel):
    """Success and rejection share one shape (the rejection path omits the applied-only fields)."""

    model_config = ConfigDict(extra="allow")
    task_id: str
    state: str
    previous_state: str
    kind: str = ""
    category: str = ""
    contrib_note_id: str = ""
    update_note_id: str = ""
    artefact_path: str = ""
    vault_mirror_pending: str = ""
    rejected: list[ContribRejection] | None = None
    applied: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    message: str


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

# GTD Phase 1 writes
CREATE_ITEM_OUTPUT = _envelope_schema("CreateItemEnvelope", CreateItemResult, Candidates)
ADD_NOTE_OUTPUT = _envelope_schema("GtdAddNoteEnvelope", AddNoteResult, Candidates)
CAPTURE_OUTPUT_SCHEMA = _envelope_schema("GtdCaptureEnvelope", GtdCaptureResult)
TRANSITION_OUTPUT = _envelope_schema("TransitionEnvelope", TransitionResult, Candidates)

# GTD Phase 2 writes
COMPLETE_ACTION_OUTPUT = _envelope_schema(
    "CompleteActionEnvelope", CompleteActionResult, Candidates
)
CLOSE_INBOX_OUTPUT = _envelope_schema("CloseInboxEnvelope", CloseInboxItemResult, Candidates)
SET_PROPERTIES_OUTPUT = _envelope_schema("SetPropertiesEnvelope", SetPropertiesResult, Candidates)
LINK_DEPENDENCY_OUTPUT = _envelope_schema(
    "LinkDependencyEnvelope", LinkDependencyResult, Candidates
)
BATCH_TRANSITION_OUTPUT = _envelope_schema("BatchTransitionEnvelope", BatchTransitionResult)

# GTD Phase 3 writes — process ops
INBOX_ZERO_OUTPUT = _envelope_schema("InboxZeroEnvelope", ProcessOpResult)
CHASE_SWEEP_OUTPUT = _envelope_schema("ChaseSweepEnvelope", ProcessOpResult)
CONSOLIDATE_OUTPUT = _envelope_schema("ConsolidateEnvelope", ProcessOpResult)

# GTD Phase 4a writes — note family, note-edit
ATTACH_OUTPUT_OUTPUT = _envelope_schema("AttachOutputEnvelope", AttachOutputResult, Candidates)
ATTACH_CONTRIB_OUTPUT = _envelope_schema(
    "AttachContribEnvelope", AttachContributionResult, Candidates
)
ANNOTATE_OUTPUT = _envelope_schema("AnnotateEnvelope", AnnotateClarificationResult, Candidates)
EDIT_NOTE_OUTPUT = _envelope_schema("GtdEditNoteEnvelope", EditNoteResult, Candidates)

# GTD Phase 4b writes — AI surface
SURFACE_CREATE_OUTPUT = _envelope_schema("SurfaceCreateEnvelope", SurfaceCreateResult)
SURFACE_RESOLVE_OUTPUT = _envelope_schema(
    "SurfaceResolveEnvelope", SurfaceResolveResult, Candidates
)

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
# gtd_query retired at v3.0.0 (D11) — split into three tools, each with its own envelope. The
# row model is shared because the row SHAPE was never the problem; the parameter set was.
NEXT_ACTIONS_OUTPUT = _envelope_schema("NextActionsEnvelope", QueryResult)
ITEM_TODAY_OUTPUT = _envelope_schema("ItemTodayEnvelope", QueryResult)
FOCUS_PROJECTS_OUTPUT = _envelope_schema("FocusProjectsEnvelope", QueryResult, Candidates)
INBOX_STATE_OUTPUT = _envelope_schema("InboxStateEnvelope", InboxStateResult)
WAITING_FOR_OUTPUT = _envelope_schema("WaitingForEnvelope", WaitingForResult)
GTD_CONTEXT_OUTPUT = _envelope_schema("GtdContextEnvelope", ContextResult, Candidates)

# GTD Wave 1 — the eight MilkScript-retirement reads (v2.9.0)
SURFACE_QUEUE_OUTPUT = _envelope_schema("SurfaceQueueEnvelope", SurfaceQueueResult)
ENGINE_REPORT_OUTPUT = _envelope_schema("EngineReportEnvelope", EngineReportResult)
DEPENDENCY_GAPS_OUTPUT = _envelope_schema("DependencyGapsEnvelope", DependencyGapsResult)
TAG_REPORT_OUTPUT = _envelope_schema("TagReportEnvelope", TagReportResult)
REVIEW_REPORT_OUTPUT = _envelope_schema("ReviewReportEnvelope", ReviewReportResult)
ITEM_STALE_OUTPUT = _envelope_schema("ItemStaleEnvelope", ItemStaleResult)
WORKLOAD_REPORT_OUTPUT = _envelope_schema("WorkloadReportEnvelope", WorkloadReportResult)
FOCUS_INDEX_OUTPUT = _envelope_schema("FocusIndexEnvelope", FocusIndexResult)

# GTD Wave 1b — shape classification + the contribution state machine (v2.10.0)
ITEM_CLASSIFY_OUTPUT = _envelope_schema("ItemClassifyEnvelope", ItemClassifyResult)
CONTRIB_TRANSITION_OUTPUT = _envelope_schema(
    "ContribTransitionEnvelope", ContribTransitionResult, Candidates
)
