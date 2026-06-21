"""Pure helpers for the gtd_apply_canvas_commit write tool.

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

# Workflow-state tag per add `type` (canvas grammar → RTM workflow tag).
TYPE_TAG = {"action": "action", "waiting_for": "waiting_for", "calendar": "calendar_entry"}
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
AI_CONVERSATION = "ai_conversation"
# execute now/quick — immediate progress, drained by the on-commit fire
AI_PROGRESS = "ai_progress_requested"
# execute later — durable, deferred (the mutually-exclusive sibling of AI_PROGRESS)
AI_PROGRESS_DEFERRED = "ai_progress_deferred"
# blocked, pending unblock (engine-set; a distinct concept, NOT user-deferred)
AI_DEFERRED = "ai_deferred_pending_unblock"
QUICK_WIN = "quick_win"

VALID_TYPES = frozenset(TYPE_TAG)
VALID_EXECUTE = frozenset({"now", "later", "quick"})


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


def classifiers_to_tags(item_type: str | None, classifiers: dict[str, Any] | None) -> list[str]:
    """Closed map: an add's type + classifiers → its canonical tag list (deduped, order-stable).

    Priority is NOT a tag (set via set_task_priority) and is excluded. Unknown type / non-canonical
    context/comms are dropped here (validate_commit rejects an unknown type separately); a truthy
    `quick` classifier adds `quick_win`. `ai_conversation` is always included (every created item
    carries the journaling tag)."""
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
    plus `ai_progress_deferred` when any execute value is `later`); and `ai_conversation` whenever
    any task-touching op is present."""
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
    if execute:
        tags.update({AI_PROGRESS, AI_DEFERRED, AI_CONVERSATION})
        # `later` writes the new deferred sibling; gate it only when actually present so a
        # now/quick-only commit stays backward-compatible (doesn't require the new tag to exist).
        if any(v == "later" for v in execute.values()):
            tags.add(AI_PROGRESS_DEFERRED)
    if ops.get("notes"):
        tags.add(AI_CONVERSATION)
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
    An empty list means the commit may proceed."""
    rejections: list[dict[str, Any]] = []
    plan_ids = set(plan_ids)

    def _check_ids(id_iter: Any, op_label: str) -> None:
        for rid in id_iter:
            if rid not in plan_ids:
                rejections.append(
                    {
                        "reason": "cross_project",
                        "op": op_label,
                        "id": rid,
                        "detail": f"id {rid} is not a child of project {project_id}",
                    }
                )

    _check_ids((ops.get("edits") or {}).keys(), "edits")
    _check_ids(ops.get("completes") or [], "completes")
    _check_ids(ops.get("removes") or [], "removes")
    _check_ids((ops.get("execute") or {}).keys(), "execute")
    _check_ids((ops.get("notes") or {}).keys(), "notes")
    _check_ids(ops.get("order") or [], "order")

    completes = ops.get("completes") or []
    removes = ops.get("removes") or []
    if (completes or removes) and not confirm_destructive:
        rejections.append(
            {
                "reason": "destructive_unconfirmed",
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
                    "reason": "unknown_add_type",
                    "index": i,
                    "type": t,
                    "detail": f"add type {t!r} not in {sorted(VALID_TYPES)}",
                }
            )

    for rid, val in (ops.get("execute") or {}).items():
        if val not in VALID_EXECUTE:
            rejections.append(
                {
                    "reason": "invalid_execute",
                    "id": rid,
                    "value": val,
                    "detail": f"execute {val!r} not in {sorted(VALID_EXECUTE)}",
                }
            )

    # The creation target only matters when there are items to create.
    if (ops.get("adds")) and not processed_list_ok:
        rejections.append(
            {
                "reason": "smart_list_target",
                "detail": "target list 'Processed' is missing or is a smart list",
            }
        )

    return {"rejections": rejections}
