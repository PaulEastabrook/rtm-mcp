"""Pure helpers for the gtd_create_project write tool.

Pure (no IO). The create sibling of `canvas_commit`: it owns the create-specific tags (the
`#project` workflow tag, the life-context tags, and the `#ai_project_needs_finalise` mark) and the
up-front validators a new-project create runs before any write, so every rejection path is
unit-testable without a client. The shared classifier→tag taxonomy (item type, context/comms,
progression) is imported from `canvas_commit` — create owns no duplicate taxonomy.

Design note (see CONTRIBUTING.md § 6): the server holds no canonical taxonomy. The mapping here
emits only a fixed set of canonical tags by construction; the *existence* of each is enforced
separately by the strict-tag gate (`strict_tags.enforce_strict_tags`).
"""

from typing import Any

from .canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    AI_PROGRESS_DEFERRED,
    VALID_EXECUTE,
    VALID_TYPES,
    classifiers_to_tags,
)

# The new project's own workflow tag, the canonical life-context tags, and the finalise mark.
PROJECT_TAG = "project"
LIFE_TAGS = frozenset({"work", "personal", "leanworking"})
# Durable mark stamped on every created project — the signal the gtd-side finalise/discipline engine
# drains (vault folder, context.md, progression fan-out). A NEW tag: under strict-tag mode it must be
# provisioned in RTM, else every create is rejected up-front by the existence gate.
FINALISE_MARK = "ai_project_needs_finalise"


def item_id(item: dict[str, Any], index: int) -> str:
    """The in-draft id for an item: its explicit `id`, else its positional index (stringified).

    Used for dependency resolution and DEPENDS-ON note mapping — it MUST match between
    `validate_create` (which checks deps) and the apply loop (which maps in-draft ids to new RTM
    ids), so both call this single helper."""
    raw = (item or {}).get("id")
    return str(raw) if raw not in (None, "") else str(index)


def project_tags(life: str | None) -> list[str]:
    """The new project task's tag set: life-context (if given) + `#project` + `#ai_conversation` +
    the finalise mark. Order-stable, deduped."""
    out: list[str] = []
    if life:
        out.append(life)
    out.extend([PROJECT_TAG, AI_CONVERSATION, FINALISE_MARK])
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def collect_create_tags(frame: dict[str, Any], items: list[dict[str, Any]]) -> set[str]:
    """Every canonical tag a create *could* write, for the single up-front existence-gate pass.

    Bounded by the closed mapping: the project's own tags (life + `#project` + `#ai_conversation`
    + the finalise mark); each item's classifier tags; and the execute tags (`ai_progress_requested`
    + `ai_deferred_pending_unblock`, since `blocked` is decided at apply, plus `ai_progress_deferred`
    when any item's execute is `later`)."""
    tags: set[str] = set(project_tags((frame or {}).get("life")))
    for item in items or []:
        tags.update(classifiers_to_tags(item.get("type"), item.get("classifiers")))
    execute_vals = [it.get("execute") for it in (items or []) if it.get("execute")]
    if execute_vals:
        tags.update({AI_PROGRESS, AI_DEFERRED, AI_CONVERSATION})
        # `later` writes the deferred sibling; gate it only when present so a now/quick-only create
        # stays backward-compatible (doesn't require the new tag to exist).
        if any(v == "later" for v in execute_vals):
            tags.add(AI_PROGRESS_DEFERRED)
    return tags


def validate_create(frame: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure rejection collector — run BEFORE any write. Returns {"rejections": [...]}.

    Rejection reasons: `missing_name` (no project title), `invalid_life` (life not one of the
    canonical life contexts), `unknown_add_type` (an item type outside the canvas grammar),
    `invalid_execute` (an item execute value outside now/later/quick), `unknown_dep` (a dep
    referencing an id absent from the payload's own items), `duplicate_id` (two items resolving to
    the same in-draft id — the apply loop keys by id, so a collision would silently drop an item),
    `self_dep` (an item depending on itself). An empty list means create may proceed.

    Note: there is no creation-list rejection — children are created directly under their parent via
    `rtm.tasks.add(parent_task_id=...)`, inheriting the parent's list, so no neutral staging list is
    needed (and a smart-list target is impossible: tasks never live in a smart list)."""
    rejections: list[dict[str, Any]] = []
    frame = frame or {}
    items = items or []

    if not (frame.get("name") or "").strip():
        rejections.append(
            {"reason": "missing_name", "detail": "frame.name is required (the project title)."}
        )

    life = frame.get("life")
    if life is not None and life not in LIFE_TAGS:
        rejections.append(
            {
                "reason": "invalid_life",
                "value": life,
                "detail": f"life {life!r} not in {sorted(LIFE_TAGS)}",
            }
        )

    # Duplicate in-draft ids are rejected up-front: the apply loop keys items by
    # resolved id, so a collision (two explicit "a"s, or an explicit "1" colliding
    # with another item's positional index) would silently drop an item and remap
    # its dependants to the wrong producer.
    resolved_ids = [item_id(it, i) for i, it in enumerate(items)]
    seen_ids: set[str] = set()
    for i, rid in enumerate(resolved_ids):
        if rid in seen_ids:
            rejections.append(
                {
                    "reason": "duplicate_id",
                    "index": i,
                    "id": rid,
                    "detail": f"in-draft id {rid!r} resolves to more than one item "
                    "(explicit ids must be unique and must not collide with "
                    "another item's positional index)",
                }
            )
        seen_ids.add(rid)

    item_ids = set(resolved_ids)
    for i, item in enumerate(items):
        t = (item or {}).get("type")
        if t not in VALID_TYPES:
            rejections.append(
                {
                    "reason": "unknown_add_type",
                    "index": i,
                    "type": t,
                    "detail": f"item type {t!r} not in {sorted(VALID_TYPES)}",
                }
            )
        ex = (item or {}).get("execute")
        if ex is not None and ex not in VALID_EXECUTE:
            rejections.append(
                {
                    "reason": "invalid_execute",
                    "index": i,
                    "value": ex,
                    "detail": f"execute {ex!r} not in {sorted(VALID_EXECUTE)}",
                }
            )
        for dep in (item or {}).get("deps") or []:
            if str(dep) not in item_ids:
                rejections.append(
                    {
                        "reason": "unknown_dep",
                        "index": i,
                        "dep": dep,
                        "detail": f"dep {dep!r} does not reference any item id in this create",
                    }
                )
            elif str(dep) == item_id(item, i):
                # A self-dep is dropped by the graph but would still persist a
                # junk self-referencing DEPENDS-ON note in RTM.
                rejections.append(
                    {
                        "reason": "self_dep",
                        "index": i,
                        "dep": dep,
                        "detail": f"item {item_id(item, i)!r} depends on itself",
                    }
                )

    return {"rejections": rejections}
