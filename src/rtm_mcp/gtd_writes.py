"""Pure (no-IO) grammar for the Phase 1 everyday GTD write tools.

Holds the **Tier-1 shared-kernel promotion** (designed change D1): the seven structural GTD
vocabularies are now *server-owned* canonical constants, advertised as advisory
`json_schema_extra` enums on the four Phase-1 write tools and asserted equal in
`tests/test_tool_schemas.py` so they cannot drift.

Ownership boundary (unchanged): the server owns the seven structural enums, note SHAPE +
block order, list writability and the "exactly one per task" structural invariants. The **tag
taxonomy stays gtd** — `extra_tags` are existence-gated by strict-tag mode and never minted here.

Scope discipline: these constants are used by the NEW tools only. The generic `add_task` /
`add_note` stay permissive (the escape hatch) — retrofitting these enums onto them would start
rejecting values they accept today, which would be breaking.
"""

from __future__ import annotations

from typing import Any

from .canvas_commit import AI_CONVERSATION, COMMS_TAGS, CONTEXT_TAGS, OVERLAY_REFRESH
from .error_codes import ErrorCode

# --------------------------------------------------------------------------- #
# Tier-1 canonical vocabularies (D1) — sourced from gtd's tag-taxonomy.md § headings
# --------------------------------------------------------------------------- #

#: 1. Life context — exactly one per task. `client` IS canonical (a Work-domain refinement,
#: codified 2026-06-07); note gtd's DoR catalogue names only work/leanworking/personal on its
#: life-context axis — we accept all four, the taxonomy being the authority for tag validity.
LIFE_CONTEXTS = frozenset({"work", "leanworking", "client", "personal"})

#: 2a. The full GTD workflow-state set — exactly one per task (used by transition validation).
WORKFLOW_STATES = frozenset({"action", "project", "focus", "waiting_for", "someday"})

#: 2b. The item kinds `gtd_create_item` can create. `project` is deliberately absent — it has its
#: own governed tool (`gtd_create_project`) with a richer DoR (Area-of-Focus parent, INCEPTION
#: note, vault folder). NOTE: `calendar_entry` is NOT a workflow state — it is a Special Tag, so a
#: calendar entry materialises `action` + `calendar_entry` (see `item_tags`).
ITEM_KINDS = frozenset({"action", "waiting_for", "calendar_entry"})

#: 3. Action context — exactly one per action/calendar entry (reused, not restated).
ACTION_CONTEXTS = CONTEXT_TAGS

#: 4. Energy — at most one of the pair; unset means *unrated*.
ENERGY_LEVELS = frozenset({"high_energy", "low_energy"})

#: 5. Mode of communication (reused, not restated).
COMMS_MODES = COMMS_TAGS

#: 6. MoSCoW band — carried by RTM's priority FIELD, never a tag ("one field, no parallel tag
#: overlay"). `!-` means "no band set yet" (triage debt), never "Won't have" — so a band is
#: required at create time rather than defaulted.
MOSCOW_BANDS = frozenset({"must", "should", "could"})
MOSCOW_TO_PRIORITY: dict[str, str] = {"must": "1", "should": "2", "could": "3"}

#: 7. Note types this phase writes — the free-prose journalling subset of the 25-type catalogue.
#: The machine-parsed / side-effect-bearing types (DEPENDS-ON, OUTPUT, CHAT, ORDER, AI-LINK,
#: TMPL-CHILD, CONTRIB…) each own a grammar and get their own tool in a later phase.
JOURNAL_NOTE_TYPES = frozenset(
    {"INCEPTION", "CONTEXT", "DECISION", "PROGRESS", "CASCADE", "STATE", "SESSION", "BLOCKER"}
)

# --------------------------------------------------------------------------- #
# Structural constants
# --------------------------------------------------------------------------- #

CALENDAR_TAG = "calendar_entry"
DEFAULT_ACTION_CONTEXT = "using_device"  # the taxonomy's documented default
PROCESSED_LIST = "Processed"  # clarified items — the single system of record
INBOX_LIST = "Inbox_Stuff"  # the sole capture entry point
AI_REVIEW = "ai_review"  # inbox pipeline state: analysed, awaiting Paul

#: Note body block order (note-shape-catalogue § 6): narrative → Sources → AI Context.
SOURCES_DELIM = "--- Sources ---"
AI_CONTEXT_DELIM = "--- AI Context ---"

#: STATE notes carry this as the first body line after the title.
STATE_MARKER = "Snapshot as of:"

GTD_WRITE_REJECT_REASONS = frozenset(
    {
        ErrorCode.INVALID_INPUT,
        ErrorCode.INVALID_LIFE,
        ErrorCode.MISSING_NAME,
        ErrorCode.MISSING_PARAMETER,
        ErrorCode.DOR_NOT_MET,
        ErrorCode.INVALID_NOTE_TYPE,
        ErrorCode.INVALID_BLOCK_ORDER,
        ErrorCode.SMART_LIST_TARGET,
        ErrorCode.STRICT_TAG_REJECTED,
        ErrorCode.TASK_NOT_FOUND,
        ErrorCode.LIST_NOT_FOUND,
        ErrorCode.BAD_DATE,
        ErrorCode.SELF_DEP,
        ErrorCode.DESTRUCTIVE_UNCONFIRMED,
    }
)

# --------------------------------------------------------------------------- #
# Definition of Ready — hard-gated (Paul's decision, 2026-07-23)
# --------------------------------------------------------------------------- #

#: Required axes per kind (definition-of-ready-catalogue § 2). `action_context` is satisfied by
#: the documented `using_device` default, so it never rejects. The `relational` axis (a DEPENDS-ON
#: edge or an explicit "parallel — no edge") is REPORTED but NOT gated: its satisfaction mechanism
#: is the DEPENDS-ON note tool, explicitly out of Phase-1 scope.
REQUIRED_AXES: dict[str, tuple[str, ...]] = {
    "action": ("life_context", "estimate", "energy", "priority"),
    "waiting_for": ("life_context", "priority", "due"),
    "calendar_entry": ("life_context", "priority", "due"),
}

#: Advisory-only axes surfaced in the response but never gated.
ADVISORY_AXES: dict[str, tuple[str, ...]] = {
    "action": ("relational",),
    "waiting_for": (),
    "calendar_entry": (),
}


def check_dor(kind: str, supplied: dict[str, Any]) -> list[str]:
    """Axes required for ``kind`` that the caller did not supply. Empty list == ready."""
    return [ax for ax in REQUIRED_AXES.get(kind, ()) if not supplied.get(ax)]


# --------------------------------------------------------------------------- #
# Tag materialisation — the server builds the structural tags from typed facets
# --------------------------------------------------------------------------- #


def item_tags(
    kind: str,
    life_context: str,
    *,
    action_context: str | None = None,
    energy: str | None = None,
    comms: str | None = None,
    extra_tags: list[str] | None = None,
) -> list[str]:
    """The structural tag set for a created item, sorted.

    A calendar entry carries BOTH `action` (its workflow state) and `calendar_entry` (the Special
    Tag) — `calendar_entry` is not itself a workflow state. Action context applies to actions and
    calendar entries only (defaulted when absent); a waiting-for carries neither context nor energy.
    """
    tags: set[str] = {life_context, AI_CONVERSATION}
    if kind == "calendar_entry":
        tags |= {"action", CALENDAR_TAG}
    else:
        tags.add(kind)
    if kind in ("action", "calendar_entry"):
        tags.add(action_context or DEFAULT_ACTION_CONTEXT)
    if energy:
        tags.add(energy)
    if comms:
        tags.add(comms)
    tags |= {t.strip() for t in (extra_tags or []) if t and t.strip()}
    return sorted(tags)


def collect_item_tags(
    kind: str,
    life_context: str,
    *,
    action_context: str | None = None,
    energy: str | None = None,
    comms: str | None = None,
    extra_tags: list[str] | None = None,
) -> set[str]:
    """Every tag a create would write — the up-front strict-tag existence-gate input."""
    return set(
        item_tags(
            kind,
            life_context,
            action_context=action_context,
            energy=energy,
            comms=comms,
            extra_tags=extra_tags,
        )
    )


# --------------------------------------------------------------------------- #
# Note grammar — title construction + block-order validation
# --------------------------------------------------------------------------- #


def format_note_title(note_type: str, summary: str, *, date: str, time: str | None = None) -> str:
    """`YYYY-MM-DD [HH:MM] — TYPE — summary` — the em-dash form, always written (never en-dash)."""
    stamp = f"{date} {time}" if time else date
    return f"{stamp} — {note_type} — {summary.strip()}"


def check_block_order(body: str | None) -> str | None:
    """Validate the fixed body block order. Returns an error detail, or None when well-formed.

    Ordering is fixed: narrative → `--- Sources ---` → `--- AI Context ---`. A hard-fail per the
    note-shape catalogue § 8 error policy (wrong block order is machine-breaking, not style drift).
    """
    text = body or ""
    src = text.find(SOURCES_DELIM)
    ctx = text.find(AI_CONTEXT_DELIM)
    if src >= 0 and ctx >= 0 and ctx < src:
        return f"'{AI_CONTEXT_DELIM}' appears before '{SOURCES_DELIM}'"
    return None


def state_body(body: str, *, date: str) -> str:
    """A STATE note's body must open with the snapshot marker. Idempotent — an already-marked
    body is returned unchanged. STATE is latest-wins: the prior STATE note is NEVER deleted or
    retitled (journaling-lifecycle: older snapshots remain as history)."""
    if body.lstrip().startswith(STATE_MARKER):
        return body
    return f"{STATE_MARKER} {date}\n{body}"


# --------------------------------------------------------------------------- #
# Validators — each returns a list of flat `{reason, ...}` rejections
# --------------------------------------------------------------------------- #


def _reject(reason: ErrorCode, detail: str, **extra: Any) -> dict[str, Any]:
    return {"reason": reason.value, "detail": detail, **extra}


def validate_create_item(
    *,
    kind: str,
    name: str,
    life_context: str,
    action_context: str | None,
    energy: str | None,
    comms: str | None,
    priority: str,
    estimate: str | None,
    due: str | None,
    processed_ok: bool,
) -> dict[str, Any]:
    """Validate a create. Returns `{"rejections": [...], "missing": [...], "advisory": [...]}`."""
    rejections: list[dict[str, Any]] = []
    if kind not in ITEM_KINDS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT, f"kind must be one of {sorted(ITEM_KINDS)}", field="kind"
            )
        )
    if not (name or "").strip():
        rejections.append(_reject(ErrorCode.MISSING_NAME, "name is required"))
    if life_context not in LIFE_CONTEXTS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_LIFE,
                f"life_context must be one of {sorted(LIFE_CONTEXTS)}",
                field="life_context",
            )
        )
    if action_context and action_context not in ACTION_CONTEXTS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"action_context must be one of {sorted(ACTION_CONTEXTS)}",
                field="action_context",
            )
        )
    if energy and energy not in ENERGY_LEVELS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"energy must be one of {sorted(ENERGY_LEVELS)}",
                field="energy",
            )
        )
    if comms and comms not in COMMS_MODES:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"comms must be one of {sorted(COMMS_MODES)}",
                field="comms",
            )
        )
    if priority not in MOSCOW_BANDS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"priority must be one of {sorted(MOSCOW_BANDS)} (the MoSCoW band)",
                field="priority",
            )
        )
    if not processed_ok:
        rejections.append(
            _reject(ErrorCode.SMART_LIST_TARGET, f"the {PROCESSED_LIST} list is missing or smart")
        )

    missing = (
        check_dor(
            kind,
            {
                "life_context": life_context,
                "estimate": estimate,
                "energy": energy,
                "priority": priority,
                "due": due,
            },
        )
        if kind in REQUIRED_AXES
        else []
    )
    if missing:
        rejections.append(
            _reject(
                ErrorCode.DOR_NOT_MET,
                f"{kind} is not ready — missing required axes: {', '.join(missing)}",
                missing=missing,
            )
        )
    return {
        "rejections": rejections,
        "missing": missing,
        "advisory": list(ADVISORY_AXES.get(kind, ())),
    }


def validate_add_note(*, note_type: str, summary: str, body: str | None) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if note_type not in JOURNAL_NOTE_TYPES:
        rejections.append(
            _reject(
                ErrorCode.INVALID_NOTE_TYPE,
                f"note_type must be one of {sorted(JOURNAL_NOTE_TYPES)} — the journalling types "
                "this tool writes. Side-effect note types (DEPENDS-ON, OUTPUT, CHAT, ORDER) have "
                "their own tools.",
                note_type=note_type,
            )
        )
    if not (summary or "").strip():
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "summary is required"))
    order_err = check_block_order(body)
    if order_err:
        rejections.append(_reject(ErrorCode.INVALID_BLOCK_ORDER, order_err))
    return rejections


def validate_capture(*, text: str) -> list[dict[str, Any]]:
    if not (text or "").strip():
        return [_reject(ErrorCode.MISSING_PARAMETER, "text is required")]
    return []


def validate_transition(
    *, add_tags: list[str], remove_tags: list[str], existing: list[str]
) -> list[dict[str, Any]]:
    """Validate a tag transition against the 'exactly one per task' structural invariants.

    The server owns these mechanical cardinality rules; canonicality of the tag itself stays with
    gtd (the strict-tag existence gate covers additions)."""
    rejections: list[dict[str, Any]] = []
    add = {t.strip() for t in add_tags if t and t.strip()}
    remove = {t.strip() for t in remove_tags if t and t.strip()}
    if not add and not remove:
        rejections.append(
            _reject(ErrorCode.MISSING_PARAMETER, "provide at least one of add_tags / remove_tags")
        )
    overlap = add & remove
    if overlap:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"tags appear in both add_tags and remove_tags: {sorted(overlap)}",
                tags=sorted(overlap),
            )
        )
    resulting = (set(existing) - remove) | add
    for label, vocab in (
        ("workflow state", WORKFLOW_STATES),
        ("life context", LIFE_CONTEXTS),
        ("action context", ACTION_CONTEXTS),
        ("energy", ENERGY_LEVELS),
    ):
        present = sorted(resulting & vocab)
        if len(present) > 1:
            rejections.append(
                _reject(
                    ErrorCode.INVALID_INPUT,
                    f"the transition would leave {len(present)} {label} tags ({', '.join(present)}) "
                    "— at most one is allowed",
                    tags=present,
                )
            )
    return rejections


def collect_transition_tags(add_tags: list[str]) -> set[str]:
    """Additions only — the strict-tag gate input. Removals reduce entropy and are never gated."""
    return {t.strip() for t in add_tags if t and t.strip()} | {AI_CONVERSATION, OVERLAY_REFRESH}


# =========================================================================== #
# Phase 2 — completion, dependency, properties, bulk
# =========================================================================== #

#: The AI-output review→approved transition pair (completion is implicit approval).
AI_OUTPUT_REVIEW_NEEDED = "ai_output_review_needed"
AI_OUTPUT_APPROVED = "ai_output_approved"

#: Fixed COMPLETION title for closing an Inbox_Stuff item (inbox-stuff-pipeline § COMPLETION).
INBOX_CLOSE_SUMMARY = "Processed into GTD system"

#: Fan-out EVENTS. These are `event:` arguments to gtd's progression-fanout agent — NOT RTM tags.
#: No tag by these names exists in the taxonomy, and a server cannot invoke an agent, so the tools
#: RETURN them for the caller to fire and stamp the sanctioned durable mark instead.
FANOUT_EVENTS = frozenset(
    {"completed", "decided", "waiting_for_resolved", "calendar_entry_completed"}
)

#: DEPENDS-ON note vocabularies. `Status:` is active|resolved|obsolete — note-shape-catalogue § 5
#: says "superseded", but journaling-lifecycle and five runtime call sites all write "resolved";
#: the catalogue is the stale one. `Upstream type:` takes the wider journaling-lifecycle union.
DEPENDS_ON_STATUSES = frozenset({"active", "resolved", "obsolete"})
UPSTREAM_TYPES = frozenset({"action", "waiting_for", "calendar_entry", "project", "external"})


def completion_events(tags: list[str], *, has_outcome_note: bool, decided: bool) -> list[str]:
    """The fan-out events a completion WOULD fire, per completion-workflow's conditional guards.

    Returned as data (never stamped): `waiting_for_resolved` only for a waiting-for;
    `calendar_entry_completed` only when a calendar entry has NO outcome note filed this cycle;
    `decided` only when the action is decision-shaped AND produced a DECISION note. `#test` items
    are excluded from fan-out entirely."""
    if "test" in tags:
        return []
    events = ["completed"]
    if "waiting_for" in tags:
        events.append("waiting_for_resolved")
    if "calendar_entry" in tags and not has_outcome_note:
        events.append("calendar_entry_completed")
    if decided:
        events.append("decided")
    return events


def output_approval_transition(tags: list[str]) -> tuple[list[str], list[str]]:
    """`(add, remove)` for the review→approved transition. Completion is implicit approval, but
    only on the FIRST transition — an already-approved item needs no tag change."""
    if AI_OUTPUT_REVIEW_NEEDED in tags and AI_OUTPUT_APPROVED not in tags:
        return [AI_OUTPUT_APPROVED], [AI_OUTPUT_REVIEW_NEEDED]
    return [], []


def depends_on_note(
    *,
    upstream_name: str,
    upstream_ids: dict[str, str],
    upstream_type: str,
    why: str,
    upstream_url: str = "",
    status: str = "active",
    captured_at: str,
    captured_by: str = "rtm-mcp gtd_link_dependency",
) -> str:
    """The DEPENDS-ON note BODY. The validator hard-requires `Depends on:` + the full id triple +
    `Status:`; the remaining lines are documented-required and always emitted. Placed on the
    DEPENDENT (the convention is "X depends on Y" lives on X)."""
    return "\n".join(
        [
            f"Depends on: {upstream_name}",
            f"Upstream URL: {upstream_url}",
            "Upstream RTM IDs:",
            f'  task_id: "{upstream_ids.get("task_id", "")}"',
            f'  taskseries_id: "{upstream_ids.get("taskseries_id", "")}"',
            f'  list_id: "{upstream_ids.get("list_id", "")}"',
            f"Upstream type: {upstream_type}",
            f"Why: {why}",
            f"Status: {status}",
            f"Captured at: {captured_at}",
            f"Captured by: {captured_by}",
        ]
    )


def validate_link_dependency(*, upstream_type: str, why: str, same_task: bool) -> list[dict]:
    rejections: list[dict[str, Any]] = []
    if upstream_type not in UPSTREAM_TYPES:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"upstream_type must be one of {sorted(UPSTREAM_TYPES)}",
                field="upstream_type",
            )
        )
    if not (why or "").strip():
        rejections.append(
            _reject(ErrorCode.MISSING_PARAMETER, "why is required — record the prereq nature")
        )
    if same_task:
        rejections.append(_reject(ErrorCode.SELF_DEP, "a task cannot depend on itself"))
    return rejections


def validate_set_properties(
    *, priority: str | None, energy: str | None, has_any: bool
) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if not has_any:
        rejections.append(
            _reject(ErrorCode.MISSING_PARAMETER, "provide at least one property to set")
        )
    if priority and priority not in MOSCOW_BANDS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"priority must be one of {sorted(MOSCOW_BANDS)} (the MoSCoW band)",
                field="priority",
            )
        )
    if energy and energy not in ENERGY_LEVELS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"energy must be one of {sorted(ENERGY_LEVELS)}",
                field="energy",
            )
        )
    return rejections


def validate_complete(*, kind_tags: list[str], completion: str, outcome: str) -> list[dict]:
    """A calendar entry takes an OUTCOME note in place of the generic COMPLETION note; everything
    else takes a COMPLETION. Exactly one body must be supplied for the applicable note."""
    rejections: list[dict[str, Any]] = []
    is_calendar = CALENDAR_TAG in kind_tags
    if is_calendar and not (outcome or "").strip():
        rejections.append(
            _reject(
                ErrorCode.MISSING_PARAMETER,
                "a #calendar_entry completion takes an OUTCOME note — provide `outcome`",
            )
        )
    if not is_calendar and not (completion or "").strip():
        rejections.append(
            _reject(ErrorCode.MISSING_PARAMETER, "provide `completion` — the COMPLETION note body")
        )
    return rejections


def inbox_close_body(derived: list[dict[str, str]], *, source_name: str, source_url: str) -> str:
    """The Inbox_Stuff COMPLETION body: every derived item with type/name/url, then the SOURCE
    back-pointer carrying the ORIGINAL name (the Processor may have renamed the item)."""
    lines = ["DERIVED ITEMS CREATED:"]
    for i, d in enumerate(derived, 1):
        lines.append(
            f'{i}. [{d.get("type", "item")}] "{d.get("name", "")}" — RTM URL: {d.get("url", "")}'
        )
    if not derived:
        lines.append("(none — closed without derived items)")
    lines.append("")
    lines.append(f'SOURCE: Inbox_Stuff item "{source_name}" — RTM URL: {source_url}')
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# series_guard — priority AND estimate are taskseries-level facts in RTM
# --------------------------------------------------------------------------- #
# Faithful port of gtd's scripts/series_guard.py. A write to ONE occurrence re-writes EVERY open
# sibling occurrence, so a governed write must collapse to one write per series on the
# nearest-active occurrence, and must never silently pick when proposals diverge.

_BAND_ALIASES = {
    "high": "must",
    "1": "must",
    "must": "must",
    "medium": "should",
    "2": "should",
    "should": "should",
    "low": "could",
    "3": "could",
    "could": "could",
}


def _norm_band(band: str) -> str:
    return _BAND_ALIASES.get(str(band).strip().lower(), str(band).strip().lower())


def _open_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("id") is not None and not r.get("completed")]


def _due_key(row: dict[str, Any]) -> tuple[int, str, Any]:
    """Dated occurrences (soonest first) sort BEFORE undated; ids numeric when castable."""
    due = row.get("due") or ""
    rid = str(row.get("id") or "")
    try:
        id_key: Any = (0, int(rid))
    except ValueError:
        id_key = (1, rid)
    return (0, due, id_key) if due else (1, "", id_key)


def group_open_series(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in _open_rows(rows):
        sid = str(r.get("taskseries_id") or "")
        if sid:
            out.setdefault(sid, []).append(r)
    return out


def collapsible_series(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """A series is collapsible with >=2 open occurrences OR any open occurrence is_repeating.
    One-off tasks pass through as a no-op — the overwhelming common case."""
    return {
        sid: srows
        for sid, srows in group_open_series(rows).items()
        if len(srows) >= 2 or any(r.get("is_repeating") for r in srows)
    }


def nearest_active(series_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The occurrence to write: soonest-due open occurrence, tie-broken by smallest id."""
    return sorted(series_rows, key=_due_key)[0]


def collapse_write(proposed: dict[str, str], rows: list[dict[str, Any]]) -> dict[str, str]:
    """Redirect each proposed write on a collapsible series to that series' nearest-active
    occurrence and dedupe to ONE write per series. The nearest-active's own proposed band wins."""
    coll = collapsible_series(rows)
    id_to_series = {str(r["id"]): sid for sid, srows in coll.items() for r in srows}
    out: dict[str, str] = {}
    for tid, band in proposed.items():
        sid = id_to_series.get(str(tid))
        if sid is None:
            out[str(tid)] = band  # singleton / one-off — identity
            continue
        target = str(nearest_active(coll[sid])["id"])
        if str(tid) == target:
            out[target] = band  # the nearest-active's own proposal wins
        else:
            out.setdefault(target, band)
    return out


def divergent_band_proposals(
    proposed: dict[str, str], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Series whose occurrences were proposed DIFFERENT bands — surfaced, never silently picked."""
    coll = collapsible_series(rows)
    conflicts: list[dict[str, Any]] = []
    for sid, srows in coll.items():
        ids = {str(r["id"]) for r in srows}
        props = {t: b for t, b in proposed.items() if str(t) in ids}
        if len({_norm_band(b) for b in props.values()}) > 1:
            target = str(nearest_active(srows)["id"])
            conflicts.append(
                {
                    "taskseries_id": sid,
                    "proposals": props,
                    "nearest_active_id": target,
                    "chosen_band": props.get(target, next(iter(props.values()))),
                }
            )
    return sorted(conflicts, key=lambda c: c["taskseries_id"])
