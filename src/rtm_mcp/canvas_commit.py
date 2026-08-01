"""Pure helpers for the gtd_canvas_commit write tool.

Pure (no IO). Holds the **closed canonical classifier→tag mapping** and the **pure validators**
the commit tool runs up-front, so the grammar parse and every rejection path are unit-testable
without a client.

Design note (see CONTRIBUTING.md § 6): the server holds no canonical taxonomy. The mapping here
emits only a fixed set of canonical tags by construction; the *existence* of each is enforced
separately by the strict-tag gate (`strict_tags.enforce_strict_tags`). Together — closed mapping
+ existence gate — they give the brief's "reject a non-canonical tag" without importing the gtd
plugin's taxonomy.
"""

from typing import Any

from .error_codes import ErrorCode

# Workflow-state tag per add `type` (canvas grammar → RTM workflow tag).
#
# `calendar_entry` is an ACCEPTED SYNONYM of `calendar`, not a fourth type (v6.2.0). The canvas
# grammar says `calendar`; `gtd_item_create` says `calendar_entry` — the same domain concept under
# two spellings across sibling create surfaces, which cost a live 17-item plan its entire create
# (the whole draft was rejected as `unknown_add_type`). The fix is ADDITIVE widening rather than
# picking a winner: renaming either spelling would break the artifact board, and a *rendered* board
# is a frozen copy of its template — a live caller no repo grep can see (CONTRIBUTING § 2.8). Both
# spellings map to the same `calendar_entry` tag, so nothing downstream can tell them apart.
# `calendar` stays the CANONICAL spelling advertised to callers.
TYPE_TAG = {
    "action": "action",
    "waiting_for": "waiting_for",
    "calendar": "calendar_entry",
    "calendar_entry": "calendar_entry",  # synonym of `calendar` — see above
}
#: The canonical spellings advertised in the schema — the synonym above is accepted but not offered.
CANONICAL_TYPES = ("action", "waiting_for", "calendar")
CONTEXT_TAGS = frozenset({"using_device", "location_office", "location_home", "location_errand"})
COMMS_TAGS = frozenset(
    {
        "conversation_messenger",
        "conversation_email",
        "conversation_phone_call",
        "conversation_video_call",
        "conversation_f2f",
    }
)
#: The energy-designation tag pair. Lives here beside its `CONTEXT_TAGS` / `COMMS_TAGS` siblings
#: because this module is the canonical home of the classifier→tag vocabularies (`gtd_writes`
#: already imports the other two from here and re-exports this one as `ENERGY_LEVELS`).
ENERGY_TAGS = frozenset({"high_energy", "low_energy"})
AI_CONVERSATION = "ai_conversation"
# execute now/quick — immediate progress, drained by the on-commit fire
AI_PROGRESS = "ai_progress_requested"
# execute later — durable, deferred (the mutually-exclusive sibling of AI_PROGRESS)
AI_PROGRESS_DEFERRED = "ai_progress_deferred"
# blocked, pending unblock (engine-set; a distinct concept, NOT user-deferred)
AI_DEFERRED = "ai_deferred_pending_unblock"
# overlay-refresh mark — stamped on the project by gtd_canvas_commit after ANY successful
# commit; drained (overlay recomputed + persisted, then removed) by the gtd-side gtd-project-finalise
# engine. A NEW tag: under strict-tag mode it must be provisioned in RTM before this server version is
# activated, else the up-front existence gate rejects every commit. The commit-path twin of
# canvas_create.FINALISE_MARK. (A2.1 Piece 0b.)
OVERLAY_REFRESH = "ai_overlay_refresh_needed"
QUICK_WIN = "quick_win"

VALID_TYPES = frozenset(TYPE_TAG)

# ─── The closed key vocabularies, and why they are declared rather than implied ──────────────
#
# `classifiers_to_tags` reads a fixed set of keys and ignores everything else. That is correct as
# a mapping and was a data-loss bug as a *surface*: `energy` and `estimate` were passed by callers
# for months, never read, never rejected, never reported — 17 live items landed without the two
# designations the Definition of Ready calls REQUIRED for an action, with no signal at all
# (`definition-of-ready-catalogue.md` § Posture).
#
# So the recognised keys are now NAMED, and `unknown_keys` reports anything outside them into the
# receipt's `not_applied[]`. The rule this encodes is more important than the two facets that
# prompted it: **an unrecognised key is REPORTED, never dropped** — which is what makes the next
# divergence between these sibling surfaces self-announcing instead of silent.
#: Recognised `classifiers{}` keys on an add / create item. Anything else is reported.
CLASSIFIER_KEYS = frozenset({"context", "comms", "priority", "quick", "energy"})
#: Recognised top-level keys on a `gtd_canvas_commit` `adds[]` entry.
ADD_KEYS = frozenset(
    {"type", "text", "classifiers", "chase", "calendar_date", "due", "start", "estimate"}
)
# Set-modes: the progression directives create AND commit both accept. `execute_progress_tags`
# maps each of these to the tag it writes.
VALID_EXECUTE = frozenset({"now", "later", "quick"})
# The commit tool additionally accepts "off" — the instant-control clear that REMOVES the
# progression directive (the inverse of now/later/quick), so the board's execute pill can return to
# an off state. Create keeps the set-only VALID_EXECUTE: a brand-new item has no directive to clear,
# and `execute_progress_tags` has no "off" branch (it would wrongly ADD a progress tag).
VALID_EXECUTE_COMMIT = VALID_EXECUTE | frozenset({"off"})
# The progression-directive tags an "off" clear removes — the precise inverse of what the
# now/later/quick set-paths write (now/quick → AI_PROGRESS; later → AI_PROGRESS_DEFERRED; a blocked
# item additionally carries AI_DEFERRED). Built from the same constants so it cannot drift from the
# set-paths.
EXECUTE_CLEAR_TAGS = (AI_PROGRESS, AI_PROGRESS_DEFERRED, AI_DEFERRED)
# Commit scope (audit-note placement axis; see the commit-granularity designed change). `plan` is
# the default and preserves the pre-scope behaviour exactly. `instant`/`item` place the audit note
# on the referenced item; `project` on the project entity; `plan` keeps the project-level COMMIT
# note. Scope is a LABEL only — it does not change validation, gating, apply order, or batch_undo.
VALID_SCOPES = frozenset({"instant", "item", "project", "plan"})

# The complete `rejected[].reason` vocabulary gtd_canvas_commit can emit — the canonical
# source the output-schema model cites (so the advertised enum can never drift from the handler,
# exactly as the input enums are pinned to VALID_SCOPES / VALID_EXECUTE_COMMIT). Five are produced
# by `validate_commit` below; `invalid_scope` and `non_canonical_tag` are produced in the tool
# wrapper (the up-front scope check and the strict-tag existence gate respectively).
COMMIT_REJECT_REASONS = frozenset(
    {
        ErrorCode.CROSS_PROJECT,  # validate_commit: a referenced id is not a child of project_id
        ErrorCode.DESTRUCTIVE_UNCONFIRMED,  # validate_commit: completes/removes unconfirmed
        ErrorCode.MISSING_NAME,  # validate_commit: an add whose `text` is absent/whitespace-only
        ErrorCode.UNKNOWN_ADD_TYPE,  # validate_commit: an add type outside VALID_TYPES
        ErrorCode.INVALID_EXECUTE,  # validate_commit: execute outside VALID_EXECUTE_COMMIT
        ErrorCode.SMART_LIST_TARGET,  # validate_commit: target 'Processed' missing or smart
        ErrorCode.INVALID_SCOPE,  # tool: scope outside VALID_SCOPES
        ErrorCode.STRICT_TAG_REJECTED,  # tool: strict-tag existence gate rejected a tag
    }
)


def execute_progress_tags(mode: str) -> tuple[str, str]:
    """An execute mode → (progress_tag_to_write, stale_sibling_to_drop).

    `later` is the durable deferred signal (`ai_progress_deferred`); `now`/`quick` request
    immediate progress (`ai_progress_requested`). The two progression siblings are mutually
    exclusive — an item must never carry both — so the returned stale sibling is removed when a
    prior commit left it. (Blocked handling adds `ai_deferred_pending_unblock` separately; it is a
    distinct concept and is not one of these siblings.)"""
    if mode == "later":
        return AI_PROGRESS_DEFERRED, AI_PROGRESS
    return AI_PROGRESS, AI_PROGRESS_DEFERRED


def unknown_keys(mapping: dict[str, Any] | None, known: frozenset[str]) -> list[str]:
    """The keys of `mapping` this surface does not understand, sorted. Empty when all are known.

    Pure and shape-agnostic so both canvas surfaces and both levels (item and `classifiers{}`) use
    the one implementation — three sibling create surfaces disagreeing is the defect this whole
    change exists to stop, and two copies of the check would be the same mistake one layer down."""
    if not isinstance(mapping, dict):
        return []
    return sorted(k for k in mapping if k not in known)


def blank_text_rejection(text: Any, *, index: int, key: str = "text") -> dict[str, Any] | None:
    """A `missing_name` rejection for an item whose name is absent or whitespace-only, else None.

    **This is the up-front half of a durable-first write, and it exists because the write is NOT
    atomic.** A plan keyed on `name` instead of `text` (the sibling surfaces disagree — see
    `CLASSIFIER_KEYS` above) yields items with empty names. Without this check the project task and
    its notes are already durable by the time RTM refuses each child with *"Task name provided is
    invalid"* — a half-built project, which the surface's own documentation promised could not
    happen. Validating here restores that promise for this failure class.

    The detail names the `text`/`name` confusion explicitly rather than saying merely "required":
    the caller reaching this rejection has almost certainly used the sibling surface's key, and the
    schema alone did not stop them."""
    if isinstance(text, str) and text.strip():
        return None
    return {
        "reason": ErrorCode.MISSING_NAME.value,
        "index": index,
        "detail": (
            f"item {key!r} is required and must not be whitespace-only. Note that this surface "
            f"keys the name on {key!r} — `gtd_item_create` uses `name`, and a draft carrying "
            "`name` here creates items with empty names that RTM rejects one by one."
        ),
    }


def classifiers_to_tags(item_type: str | None, classifiers: dict[str, Any] | None) -> list[str]:
    """Closed map: an add's type + classifiers → its canonical tag list (deduped, order-stable).

    Priority is NOT a tag (set via set_task_priority) and is excluded. Unknown type / non-canonical
    context/comms/energy are dropped here (validate_commit rejects an unknown type separately, and
    `unknown_keys` reports an unrecognised KEY); a truthy `quick` classifier adds `quick_win`.
    `ai_conversation` is always included (every created item carries the journaling tag).

    `energy` (v6.2.0) maps exactly as context and comms do — it is a tag, so it belongs here rather
    than as a sibling key, and routing it through this one function means the strict-tag existence
    gate picks it up for free (both `collect_commit_tags` and `collect_create_tags` call this)."""
    classifiers = classifiers or {}
    out: list[str] = []
    type_tag = TYPE_TAG.get(item_type or "")
    if type_tag:
        out.append(type_tag)
    ctx = classifiers.get("context")
    if ctx in CONTEXT_TAGS:
        out.append(ctx)
    comms = classifiers.get("comms")
    if comms in COMMS_TAGS:
        out.append(comms)
    energy = classifiers.get("energy")
    if energy in ENERGY_TAGS:
        out.append(energy)
    if classifiers.get("quick"):
        out.append(QUICK_WIN)
    out.append(AI_CONVERSATION)
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def collect_commit_tags(ops: dict[str, Any]) -> set[str]:
    """Every canonical tag the commit *could* write, for the single up-front existence-gate pass.

    Bounded by the closed mapping: add classifier tags; edit context/comms tags; the execute tags
    (`ai_progress_requested` + `ai_deferred_pending_unblock`, since `blocked` is decided at apply,
    plus `ai_progress_deferred` when any execute value is `later`) for the set-modes only — an `off`
    execute only REMOVES tags (never gated); and `ai_conversation` whenever any task-touching op is
    present."""
    tags: set[str] = set()
    for add in ops.get("adds") or []:
        tags.update(classifiers_to_tags(add.get("type"), add.get("classifiers")))
    for _id, e in (ops.get("edits") or {}).items():
        ctx = (e or {}).get("context")
        if ctx in CONTEXT_TAGS:
            tags.add(ctx)
        comms = (e or {}).get("comms")
        if comms in COMMS_TAGS:
            tags.add(comms)
        tags.add(AI_CONVERSATION)
    execute = ops.get("execute") or {}
    # Only the set-modes (now/later/quick) write tags and enter the existence gate; "off" only
    # REMOVES tags (never gated — removal reduces entropy), so an off-only commit requires none of
    # these to exist.
    set_modes = [v for v in execute.values() if v != "off"]
    if set_modes:
        tags.update({AI_PROGRESS, AI_DEFERRED, AI_CONVERSATION})
        # `later` writes the new deferred sibling; gate it only when actually present so a
        # now/quick-only commit stays backward-compatible (doesn't require the new tag to exist).
        if any(v == "later" for v in set_modes):
            tags.add(AI_PROGRESS_DEFERRED)
    if ops.get("notes"):
        tags.add(AI_CONVERSATION)
    # Every non-empty commit stamps the overlay-refresh mark on the project (Piece 0b) — so the gate
    # must include it whenever any actionable op is present (adds / edits / execute / notes /
    # completes / removes / order — since DC-4 an order-only commit writes the ORDER note, then
    # stamps the mark), not only the tag-writing ops above.
    if any(
        ops.get(k) for k in ("adds", "edits", "execute", "notes", "completes", "removes", "order")
    ):
        tags.add(OVERLAY_REFRESH)
    return tags


def validate_commit(
    ops: dict[str, Any],
    plan_ids: set[str],
    project_id: str,
    *,
    processed_list_ok: bool,
    confirm_destructive: bool,
) -> dict[str, Any]:
    """Pure rejection collector — run BEFORE any write. Returns {"rejections": [...]}.

    Rejection reasons: `cross_project` (a referenced id is not a child of project_id),
    `destructive_unconfirmed` (completes/removes without confirm_destructive),
    `unknown_add_type`, `invalid_execute`, `smart_list_target` (target 'Processed' missing/smart).
    An empty list means the commit may proceed.

    Project-entity carve-out: the project is not a child of itself, but the board may target it for
    the entity verbs — rename (`edits`), add-project-note (`notes`), complete (`completes`), delete
    (`removes`). Those four maps accept `project_id` in addition to its children; `execute`/`order`
    stay child-only (a project is not progressed, nor ordered among its siblings). A note ON the
    project is a legitimate project-level journal entry, so `notes[project_id]` is permitted."""
    rejections: list[dict[str, Any]] = []
    plan_ids = set(plan_ids)

    def _check_ids(id_iter: Any, op_label: str, *, allow_project: bool = False) -> None:
        for rid in id_iter:
            if allow_project and rid == project_id:
                continue  # project-entity verb (rename/complete/delete) — permitted target
            if rid not in plan_ids:
                rejections.append(
                    {
                        "reason": ErrorCode.CROSS_PROJECT.value,
                        "op": op_label,
                        "id": rid,
                        "detail": f"id {rid} is not a child of project {project_id}",
                    }
                )

    _check_ids((ops.get("edits") or {}).keys(), "edits", allow_project=True)
    _check_ids(ops.get("completes") or [], "completes", allow_project=True)
    _check_ids(ops.get("removes") or [], "removes", allow_project=True)
    _check_ids((ops.get("notes") or {}).keys(), "notes", allow_project=True)
    _check_ids((ops.get("execute") or {}).keys(), "execute")
    _check_ids(ops.get("order") or [], "order")

    completes = ops.get("completes") or []
    removes = ops.get("removes") or []
    if (completes or removes) and not confirm_destructive:
        rejections.append(
            {
                "reason": ErrorCode.DESTRUCTIVE_UNCONFIRMED.value,
                "detail": "completes/removes require confirm_destructive=true",
                "completes": list(completes),
                "removes": list(removes),
            }
        )

    for i, add in enumerate(ops.get("adds") or []):
        t = (add or {}).get("type")
        if t not in VALID_TYPES:
            rejections.append(
                {
                    "reason": ErrorCode.UNKNOWN_ADD_TYPE.value,
                    "index": i,
                    "type": t,
                    "detail": f"add type {t!r} not in {sorted(CANONICAL_TYPES)}",
                }
            )
        blank = blank_text_rejection((add or {}).get("text"), index=i)
        if blank:
            rejections.append(blank)

    for rid, val in (ops.get("execute") or {}).items():
        if val not in VALID_EXECUTE_COMMIT:
            rejections.append(
                {
                    "reason": ErrorCode.INVALID_EXECUTE.value,
                    "id": rid,
                    "value": val,
                    "detail": f"execute {val!r} not in {sorted(VALID_EXECUTE_COMMIT)}",
                }
            )

    # The creation target only matters when there are items to create.
    if (ops.get("adds")) and not processed_list_ok:
        rejections.append(
            {
                "reason": ErrorCode.SMART_LIST_TARGET.value,
                "detail": "target list 'Processed' is missing or is a smart list",
            }
        )

    return {"rejections": rejections}
