"""Canonical rtm-mcp error-code registry — the single source of truth for every
machine-branchable failure this server can report.

ADDITIVE-ONLY. Once a code ships it is never renamed or removed; a new failure gets a
new member. (The v2.0.0 envelope *shape* change was a one-time restructure — it is not
licence to mutate the registry. See CONTRIBUTING § 5.)

**Why codes.** Before v2.0.0 `data.error` was free-text prose, so a wrapper, scheduled
engine, or eval grader recovering from a failure had to pattern-match English. A prose
edit silently broke recovery. Now every failure carries a stable `code`; the prose
survives verbatim as `message`, for humans only.

**Scope — two error shapes, one changed.** This registry governs the *envelope* error
(`data.error`, the `success | error` union discriminator) and the per-item
`rejected[].reason` vocabularies of the commit engines. It does NOT govern the per-op
`data.errors[]` list that batch tools attach to a *successful* envelope
(`{"op": ..., "id": ..., "error": str(exc)}`) — that is a different contract, reporting
partial failure inside a batch that otherwise applied. Unifying it is a separate change.

**One vocabulary, three scoped views.** `gtd_apply_canvas_commit` / `gtd_create_project` /
`gtd_apply_engage_commit` each advertise a closed `rejected[].reason` enum. Those enums
are frozensets of members *of this registry*, declared next to their handlers
(`canvas_commit.COMMIT_REJECT_REASONS`, `canvas_create.CREATE_REJECT_REASONS`,
`engage_commit.ENGAGE_REJECT_REASONS`) so per-tool scoping stays honest while the spelling
of any given reason is defined exactly once — here.

**v2.0.0 reconciliations.** Unifying the three previously-independent reject vocabularies
exposed genuine drift, all resolved in favour of one spelling:

    off-enum                    → off_enum                  (hyphen → underscore)
    unknown-kind                → unknown_kind              (hyphen → underscore)
    type-illegal                → type_illegal              (hyphen → underscore)
    confirm_destructive_required→ destructive_unconfirmed   (one concept, two names)
    non_canonical_tag           → strict_tag_rejected       (names the gate, not the tag)
    not_found (engage)          → task_not_found            (it is a task id miss)

The first three are **grammar-bound**: they mirror gtd's `validate-engage-verdict.py`
under the ratified `engage-verdict-grammar.md`. Their renaming is a LOCKSTEP change —
the gtd validator, its tests, and the grammar document move with this release. Do not
edit them here alone.

This module is a leaf: it imports nothing from the package, so any module may source
codes from it without an import cycle.
"""

from enum import Enum


class ErrorCode(str, Enum):
    """Every machine-branchable failure. Grouped by family; values are the wire strings.

    `str` mixin so a member serialises as its plain value in JSON and compares equal to
    it (`ErrorCode.TASK_NOT_FOUND == "task_not_found"`), keeping consumers that branch on
    the raw string working without importing this enum.
    """

    # ----------------------------------------------------------------- transport
    # Raised from the RTM API itself; each maps from an RTM numeric (RTM_CODE_MAP),
    # which is preserved on the envelope as `error.rtm_code`.
    AUTH_FAILED = "auth_failed"  # RTM 98/99/114 — bad, revoked, or under-scoped token
    INVALID_SIGNATURE = "invalid_signature"  # RTM 100/111 — signing bug or bad secret
    INVALID_API_KEY = "invalid_api_key"  # RTM 101
    SERVICE_UNAVAILABLE = "service_unavailable"  # RTM 102 — transient, retry
    SERVICE_NOT_FOUND = "service_not_found"  # RTM 105
    METHOD_NOT_FOUND = "method_not_found"  # RTM 112
    INVALID_FORMAT = "invalid_format"  # RTM 113
    PRO_REQUIRED = "pro_required"  # RTM 4040 — subtask features need RTM Pro
    INVALID_PARENT = "invalid_parent"  # RTM 4050
    NESTING_TOO_DEEP = "nesting_too_deep"  # RTM 4060 — max 3 levels
    REPEATING_TASK_CONFLICT = "repeating_task_conflict"  # RTM 4070
    DUE_BEFORE_START = "due_before_start"  # RTM 4080
    SELF_PARENTING = "self_parenting"  # RTM 4090
    RATE_LIMITED = "rate_limited"  # local token bucket or RTM throttle
    NETWORK_ERROR = "network_error"  # timeout, DNS, TCP reset, non-JSON 200

    # ---------------------------------------------------------------- resolution
    # A name or id did not resolve to exactly one entity.
    TASK_NOT_FOUND = "task_not_found"  # RTM 341 + every name/id task resolver
    LIST_NOT_FOUND = "list_not_found"  # RTM 340 + list-name resolver
    PROJECT_NOT_FOUND = "project_not_found"  # gtd project id/name miss
    FOCUS_NOT_FOUND = "focus_not_found"  # gtd Area-of-Focus miss (never create loose)
    AMBIGUOUS_NAME = "ambiguous_name"  # >1 match; response carries details.candidates

    # ---------------------------------------------------------------- validation
    # The caller's input was malformed or outside a closed vocabulary. Caller-fixable.
    INVALID_INPUT = "invalid_input"  # catch-all for a bad scalar/enum argument
    MISSING_PARAMETER = "missing_parameter"  # a required (or one-of-N) argument absent
    INVALID_SCOPE = "invalid_scope"  # commit scope outside VALID_SCOPES
    INVALID_EXECUTE = "invalid_execute"  # execute value outside its valid set
    INVALID_LIFE = "invalid_life"  # life tag outside LIFE_TAGS
    MISSING_NAME = "missing_name"  # create: no project title
    UNKNOWN_ADD_TYPE = "unknown_add_type"  # an add's type outside VALID_TYPES
    UNKNOWN_DEP = "unknown_dep"  # a dep referencing an id absent from the payload
    SELF_DEP = "self_dep"  # an item depending on itself
    DUPLICATE_ID = "duplicate_id"  # two draft items resolve to the same in-draft id
    CROSS_PROJECT = "cross_project"  # a referenced id is not a child of project_id
    SMART_LIST_TARGET = "smart_list_target"  # target list missing or smart
    BAD_DATE = "bad_date"  # a date phrase rtm.time.parse could not resolve
    OFF_ENUM = "off_enum"  # LOCKSTEP: engage verdict outside the enum
    UNKNOWN_KIND = "unknown_kind"  # LOCKSTEP: engage item kind unrecognised
    DOR_NOT_MET = "dor_not_met"  # Phase 1: a create missing a Definition-of-Ready axis
    INVALID_NOTE_TYPE = "invalid_note_type"  # note_type outside the journalling vocabulary
    INVALID_BLOCK_ORDER = "invalid_block_order"  # note body blocks out of the fixed order
    TYPE_ILLEGAL = "type_illegal"  # LOCKSTEP: verdict illegal for this item's kind

    # --------------------------------------------------------------------- state
    # Input was well-formed, but the target's current state forbids the operation.
    TASK_NOT_COMPLETED = "task_not_completed"  # uncomplete_task on an open task
    CONVERSATION_READ_ONLY = "conversation_read_only"  # chat post to a completed task
    LOCKED_SYSTEM_LIST = "locked_system_list"  # delete/rename of Inbox, Sent, …
    UNKNOWN_TRANSACTION = "unknown_transaction"  # undo id not in this session's log
    TRANSACTION_ALREADY_UNDONE = "transaction_already_undone"

    # ---------------------------------------------------------------- governance
    # A deterministic safety gate refused the write. Not a bug — the gate working.
    STRICT_TAG_REJECTED = "strict_tag_rejected"  # tag absent from the account
    NOTE_SHAPE_REJECTED = "note_shape_rejected"  # note title fails the mechanical grammar
    DESTRUCTIVE_UNCONFIRMED = "destructive_unconfirmed"  # confirm_destructive not set

    # -------------------------------------------------------------------- commit
    COMMIT_REJECTED = "commit_rejected"  # envelope code; details.rejected[] is granular

    # --------------------------------------------------------------------- write
    WRITE_FAILED = "write_failed"  # a write reached RTM but returned no usable result


# RTM API numeric → semantic code. The numeric survives on the envelope as
# `error.rtm_code`, so the transport fact is never lost — it just stops being the
# thing callers branch on. Mirrors exceptions.ERROR_CODE_MAP key-for-key.
RTM_CODE_MAP: dict[int, ErrorCode] = {
    98: ErrorCode.AUTH_FAILED,
    99: ErrorCode.AUTH_FAILED,
    100: ErrorCode.INVALID_SIGNATURE,
    101: ErrorCode.INVALID_API_KEY,
    102: ErrorCode.SERVICE_UNAVAILABLE,
    105: ErrorCode.SERVICE_NOT_FOUND,
    111: ErrorCode.INVALID_SIGNATURE,
    112: ErrorCode.METHOD_NOT_FOUND,
    113: ErrorCode.INVALID_FORMAT,
    114: ErrorCode.AUTH_FAILED,
    340: ErrorCode.LIST_NOT_FOUND,
    341: ErrorCode.TASK_NOT_FOUND,
    4040: ErrorCode.PRO_REQUIRED,
    4050: ErrorCode.INVALID_PARENT,
    4060: ErrorCode.NESTING_TOO_DEEP,
    4070: ErrorCode.REPEATING_TASK_CONFLICT,
    4080: ErrorCode.DUE_BEFORE_START,
    4090: ErrorCode.SELF_PARENTING,
}


def code_for_rtm(rtm_code: int | None) -> ErrorCode:
    """Map an RTM numeric to its semantic code, defaulting to INVALID_INPUT.

    An unmapped numeric is far more often a caller-side validation failure than a
    transport fault, so INVALID_INPUT is the honest default — and the unmapped numeric
    still rides along on `error.rtm_code` for diagnosis.
    """
    if rtm_code is None:
        return ErrorCode.INVALID_INPUT
    return RTM_CODE_MAP.get(rtm_code, ErrorCode.INVALID_INPUT)
