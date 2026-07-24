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


# =========================================================================== #
# Phase 3 — process ops (apply a reviewed verdict set)
# =========================================================================== #
# These tools APPLY a set the caller already reviewed and approved; they never fetch-and-decide.
#
# Throughput reality (measured 2026-07-23): RTM's API has NO multi-task write endpoint — a
# comma-separated id list and a filter-based write are both rejected, so every item costs its own
# rate-limited call. The official server's `rtm_batch_*` (max 20) resolve and loop internally; their
# "bypasses the rate limiter" is a separate API-key budget, not a batch. So the mitigations here are
# the bounded input cap below plus honest long-running — not an O(N/20) batch that does not exist.

#: Max items applied per call. A larger reviewed set is applied in order and the tail is returned
#: as `remaining` for a follow-up call (pagination-by-continuation), bounding one call's wall-clock.
PROCESS_BATCH_CAP = 50

INBOX_VERBS = frozenset({"tag", "move", "complete", "leave"})
CHASE_VERDICTS = frozenset({"retickle", "convert_to_action", "complete", "leave"})
CONSOLIDATE_MOVES = frozenset({"reparent", "link_dependency", "complete", "promote"})


def split_batch(items: list[Any]) -> tuple[list[Any], list[Any]]:
    """`(to_apply, remaining)` under the per-call cap."""
    return items[:PROCESS_BATCH_CAP], items[PROCESS_BATCH_CAP:]


def _ref_of(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = str(d.get(k) or "").strip()
        if v:
            return v
    return ""


def validate_inbox_zero(dispositions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every disposition must name a resolvable-shaped ref, a legal verb, and the args that verb
    needs. Validated as a WHOLE SET — one bad item rejects the call (the D9 spirit)."""
    rejections: list[dict[str, Any]] = []
    if not dispositions:
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "provide at least one disposition"))
    for i, d in enumerate(dispositions):
        ref = _ref_of(d, "item_ref", "ref", "id")
        verb = str(d.get("verb") or "").strip()
        args = d.get("args") or {}
        if not ref:
            rejections.append(_reject(ErrorCode.MISSING_PARAMETER, f"[{i}] item_ref is required"))
        if verb not in INBOX_VERBS:
            rejections.append(
                _reject(
                    ErrorCode.INVALID_INPUT,
                    f"[{i}] verb must be one of {sorted(INBOX_VERBS)}",
                    ref=ref,
                    verb=verb,
                )
            )
            continue
        if verb == "tag" and not (args.get("tags") or []):
            rejections.append(
                _reject(ErrorCode.MISSING_PARAMETER, f"[{i}] verb 'tag' needs args.tags", ref=ref)
            )
        if verb == "move" and not str(args.get("list_name") or "").strip():
            rejections.append(
                _reject(
                    ErrorCode.MISSING_PARAMETER, f"[{i}] verb 'move' needs args.list_name", ref=ref
                )
            )
    return rejections


def validate_chase_sweep(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if not verdicts:
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "provide at least one verdict"))
    for i, v in enumerate(verdicts):
        ref = _ref_of(v, "waiting_for_ref", "ref", "id")
        verdict = str(v.get("verdict") or "").strip()
        if not ref:
            rejections.append(
                _reject(ErrorCode.MISSING_PARAMETER, f"[{i}] waiting_for_ref is required")
            )
        if verdict not in CHASE_VERDICTS:
            rejections.append(
                _reject(
                    ErrorCode.INVALID_INPUT,
                    f"[{i}] verdict must be one of {sorted(CHASE_VERDICTS)}",
                    ref=ref,
                    verdict=verdict,
                )
            )
            continue
        if verdict == "retickle" and not str(v.get("new_due") or "").strip():
            rejections.append(
                _reject(
                    ErrorCode.MISSING_PARAMETER,
                    f"[{i}] verdict 'retickle' needs new_due (the new chase date)",
                    ref=ref,
                )
            )
    return rejections


def validate_consolidate(moves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if not moves:
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "provide at least one move"))
    for i, m in enumerate(moves):
        mt = str(m.get("move_type") or "").strip()
        if mt not in CONSOLIDATE_MOVES:
            rejections.append(
                _reject(
                    ErrorCode.INVALID_INPUT,
                    f"[{i}] move_type must be one of {sorted(CONSOLIDATE_MOVES)}",
                    move_type=mt,
                )
            )
            continue
        if mt == "reparent":
            if not _ref_of(m, "task_ref") or not _ref_of(m, "new_parent_ref"):
                rejections.append(
                    _reject(
                        ErrorCode.MISSING_PARAMETER,
                        f"[{i}] 'reparent' needs task_ref and new_parent_ref",
                    )
                )
        elif mt == "link_dependency":
            if not _ref_of(m, "dependent_ref") or not _ref_of(m, "upstream_ref"):
                rejections.append(
                    _reject(
                        ErrorCode.MISSING_PARAMETER,
                        f"[{i}] 'link_dependency' needs dependent_ref and upstream_ref",
                    )
                )
            elif _ref_of(m, "dependent_ref") == _ref_of(m, "upstream_ref"):
                rejections.append(
                    _reject(ErrorCode.SELF_DEP, f"[{i}] a task cannot depend on itself")
                )
            if not str(m.get("why") or "").strip():
                rejections.append(
                    _reject(ErrorCode.MISSING_PARAMETER, f"[{i}] 'link_dependency' needs why")
                )
        elif not _ref_of(m, "task_ref"):
            rejections.append(_reject(ErrorCode.MISSING_PARAMETER, f"[{i}] '{mt}' needs task_ref"))
    return rejections


# =========================================================================== #
# Phase 4a — the note-family, note-edit, and dependency-flip grammar
# =========================================================================== #

# --- OUTPUT + FILING (gtd_attach_output) ----------------------------------- #
# The server emits the NSC / validate-note.py model: ONE OUTPUT note carrying a FILING: LINE in
# its body — NOT the GMI two-note pair. This server's own gtd_chat_thread already parses FILING as
# a line inside an OUTPUT-typed note, so internal consistency forces the single-note shape.

AI_SPECULATIVE = "ai_speculative"
AI_CONTRIB_DRAFTED = "ai_contrib_drafted"
AI_PREP_DRAFTED = "ai_prep_drafted"
OUTPUTS_REGISTER_HEADER = "| Date | Action | Output | Type | Status | Path |"
OUTPUTS_REGISTER_SEP = "|------|--------|--------|------|--------|------|"


def check_filing_path(path: str) -> str | None:
    """Mechanical FILING-path shape (the validator's rule — the server owns shape). Returns an
    error detail, or None. Vault-relative, forward slashes only."""
    p = (path or "").strip()
    if not p:
        return "filing_path is required — the OUTPUT note's machine purpose is the artefact link"
    if p.startswith("/"):
        return "filing_path must be vault-relative (no leading '/')"
    if "\\" in p:
        return "filing_path must use forward slashes, not backslashes"
    return None


def output_note_body(filing_path: str, output_summary: str, *, companion: bool = True) -> str:
    """OUTPUT note body: the narrative then the line-anchored FILING: link the parser reads."""
    marker = " (+ .meta.md)" if companion else ""
    return f"{output_summary.strip()}\n\nFILING: {filing_path.strip()}{marker}"


def outputs_register_row(
    *, date: str, action_name: str, output_title: str, output_type: str, status: str, path: str
) -> str:
    return f"| {date} | {action_name} | {output_title} | {output_type} | {status} | {path} |"


def new_outputs_register(project_name: str, row: str, *, date: str) -> str:
    """A fresh OUTPUTS register note body (used when the project has none yet)."""
    return "\n".join(
        [
            f"OUTPUTS: {project_name}",
            "",
            OUTPUTS_REGISTER_HEADER,
            OUTPUTS_REGISTER_SEP,
            row,
            "",
            f"Last updated: {date}",
        ]
    )


def append_outputs_row(existing_body: str, row: str, *, date: str) -> str:
    """Append a row to an existing OUTPUTS register, refreshing `Last updated:` (append-only rows)."""
    lines = existing_body.split("\n")
    out: list[str] = []
    inserted = False
    for ln in lines:
        if ln.startswith("Last updated:") and not inserted:
            out.append(row)
            out.append("")
            out.append(f"Last updated: {date}")
            inserted = True
            continue
        if ln.startswith("Last updated:"):
            continue
        out.append(ln)
    if not inserted:  # no Last-updated line — append at the end
        out.append(row)
        out.append(f"Last updated: {date}")
    return "\n".join(out).rstrip() + "\n"


def validate_attach_output(*, filing_path: str, output_summary: str) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if not (output_summary or "").strip():
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "output_summary is required"))
    err = check_filing_path(filing_path)
    if err:
        rejections.append(_reject(ErrorCode.INVALID_INPUT, err, field="filing_path"))
    return rejections


# --- CONTRIB family (gtd_attach_contribution) ------------------------------ #

CONTRIB_VARIANTS = frozenset({"contrib", "contrib_update", "prep", "speculative"})
CONTRIB_CATEGORIES = frozenset(
    {"research", "draft", "brief", "decision", "unblock", "capture", "consolidate", "monitor"}
)
#: variant → (note TYPE, the tag it writes).
_CONTRIB_SHAPE: dict[str, tuple[str, str]] = {
    "contrib": ("CONTRIB", AI_CONTRIB_DRAFTED),
    "contrib_update": ("CONTRIB-UPDATE", AI_CONTRIB_DRAFTED),
    "prep": ("PREP", AI_PREP_DRAFTED),
    "speculative": ("SOURCE-DRAFT", AI_SPECULATIVE),
}


def contrib_note_type(variant: str) -> str:
    return _CONTRIB_SHAPE[variant][0]


def contrib_tag(variant: str) -> str:
    return _CONTRIB_SHAPE[variant][1]


def contrib_summary(variant: str, category: str, summary: str) -> str:
    """CONTRIB/CONTRIB-UPDATE carry the category in the title; PREP/SOURCE-DRAFT do not."""
    if variant in ("contrib", "contrib_update"):
        return f"{category} — {summary}".strip(" —")
    return summary.strip()


def validate_attach_contribution(
    *, variant: str, category: str, contrib_body: str
) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    if variant not in CONTRIB_VARIANTS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"variant must be one of {sorted(CONTRIB_VARIANTS)}",
                field="variant",
            )
        )
        return rejections
    if not (contrib_body or "").strip():
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "contrib_body is required"))
    if variant in ("contrib", "contrib_update") and category not in CONTRIB_CATEGORIES:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"category must be one of {sorted(CONTRIB_CATEGORIES)} for a {variant} note",
                field="category",
            )
        )
    return rejections


# --- AI ANALYSIS (gtd_annotate_clarification) ------------------------------ #

AI_ANALYSIS_TYPE = "AI ANALYSIS"  # the one canonical space-bearing TYPE (note-shape-catalogue § 2)


def ai_analysis_body(analysis_body: str, questions: list[str] | None) -> str:
    """The AI ANALYSIS body, with the optional CLARIFYING QUESTIONS block appended (omitted
    entirely when there are no genuine questions — the pipeline rule)."""
    body = analysis_body.strip()
    qs = [q.strip() for q in (questions or []) if q and q.strip()]
    if qs:
        block = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, 1))
        body = f"{body}\n\nCLARIFYING QUESTIONS\n{block}"
    return body


def validate_annotate_clarification(*, analysis_body: str) -> list[dict[str, Any]]:
    if not (analysis_body or "").strip():
        return [_reject(ErrorCode.MISSING_PARAMETER, "analysis_body is required")]
    return []


# --- gtd_edit_note — the bounded op-set (D2) -------------------------------- #
# The ONLY mutate-in-place note verb. `replace_substring` mirrors gtd:replace_in_note_body
# (substring, first occurrence only); `replace_line` / `set_frontmatter_key` / `retitle` are
# net-new bounded ops. There is deliberately NO free-form body overwrite — the bounded set is the
# safety property.

EDIT_NOTE_OPS = frozenset({"replace_substring", "replace_line", "set_frontmatter_key", "retitle"})


def validate_edit_note(edit: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate a single bounded edit op. A retitle additionally re-validates the title grammar."""
    op = str(edit.get("op") or "").strip()
    rejections: list[dict[str, Any]] = []
    if op not in EDIT_NOTE_OPS:
        rejections.append(
            _reject(ErrorCode.INVALID_INPUT, f"op must be one of {sorted(EDIT_NOTE_OPS)}", op=op)
        )
        return rejections
    if op == "replace_substring":
        if not str(edit.get("old") or ""):
            rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "replace_substring needs `old`"))
    elif op == "replace_line":
        if not str(edit.get("match") or ""):
            rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "replace_line needs `match`"))
    elif op == "set_frontmatter_key":
        if not str(edit.get("key") or "").strip():
            rejections.append(
                _reject(ErrorCode.MISSING_PARAMETER, "set_frontmatter_key needs `key`")
            )
    elif op == "retitle":
        new_title = str(edit.get("new_title") or "")
        from .note_shape import check_title

        grammar = check_title(new_title)
        if grammar:
            rejections.append(
                _reject(
                    ErrorCode.INVALID_NOTE_TYPE,
                    f"retitle new_title fails the note-title grammar: {grammar}",
                    new_title=new_title,
                )
            )
    return rejections


def apply_edit_op(title: str, body: str, edit: dict[str, Any]) -> tuple[str, str, str] | None:
    """Apply ONE bounded op to `(title, body)`. Returns `(new_title, new_body, detail)` on a change,
    or None when the op found nothing to change (a no-op — pattern not present)."""
    op = str(edit.get("op"))
    if op == "replace_substring":
        old, new = str(edit.get("old")), str(edit.get("new") or "")
        if old not in body:
            return None
        return title, body.replace(old, new, 1), f"replaced 1 occurrence of {old!r}"
    if op == "replace_line":
        match, new = str(edit.get("match")), str(edit.get("new") or "")
        lines = body.split("\n")
        for i, ln in enumerate(lines):
            if match in ln:
                lines[i] = new
                return title, "\n".join(lines), f"replaced line matching {match!r}"
        return None
    if op == "set_frontmatter_key":
        key, value = str(edit.get("key")).strip(), str(edit.get("value") or "")
        lines = body.split("\n")
        newline = f"{key}: {value}"
        for i, ln in enumerate(lines):
            if ln.strip().startswith(f"{key}:"):
                lines[i] = newline
                return title, "\n".join(lines), f"set {key}"
        # key absent — append it (bounded add of one k/v line, not a free-form overwrite)
        lines.append(newline)
        return title, "\n".join(lines), f"added {key}"
    if op == "retitle":
        return str(edit.get("new_title")), body, "retitled"
    return None


# --- DEPENDS-ON resolve/flip (gtd_link_dependency mode) --------------------- #

LINK_MODES = frozenset({"create", "resolve", "obsolete"})


def is_active_depends_on(body: str) -> bool:
    return "DEPENDS-ON" in body and "Status: active" in body


def flip_depends_on(body: str, *, status: str, date: str) -> str:
    """Flip `Status: active` → resolved|obsolete and append `Resolved at: <date>` (the engine's
    exact line — space, not hyphen; there is no `Resolved-by:` line)."""
    out = body.replace("Status: active", f"Status: {status}", 1)
    if "Resolved at:" not in out:
        out = out.rstrip() + f"\nResolved at: {date}"
    return out


# =========================================================================== #
# Phase 4b — the AI-surface subsystem
# =========================================================================== #
# Ported from the six binding sources. Load-bearing corrections vs the brief:
#  * TWO vocabularies: the `item_type` INPUT is question|alert|notification|surface|
#    activity_report; the TAG is q_question|q_alert|q_notification|q_surface|q_activity.
#    ai-surface-creator.md:168 says derive `q_<item_type>` — that yields `q_activity_report`
#    for the fifth type, which is NOT canonical and which gtd's `q_[a-z0-9_]+` wildcard would
#    pass SILENTLY, producing an item invisible to every scan filter. Explicit table, never
#    derivation.
#  * TWO disjoint lifecycle machines (tag-taxonomy.md:136-147), not one flat set.
#  * auto_close_at is a YAML line in the BODY note (not a tag, not a due date), per-type TTL.
#  * The AI-LINK note lives on the LINKED ENTITY ONLY (journaling-lifecycle.md:655).
#  * The AI-surface OUTCOME note is TITLE-ONLY — the catalogue's OUTCOME is the meeting shape.
#  * Priority is RTM's FIELD, not a tag (`!1` is SmartAdd syntax).

AI_QUESTIONS_LIST = "AI_Questions"
AI_ACTIVITY_LIST = "AI_Activity"

#: The item_type INPUT vocabulary (ai-surface-creator.md:39) — what a caller passes.
SURFACE_ITEM_TYPES = frozenset({"question", "alert", "notification", "surface", "activity_report"})

#: item_type → the canonical tag. EXPLICIT, never `q_` + item_type (see the header note).
SURFACE_TYPE_TAG: dict[str, str] = {
    "question": "q_question",
    "alert": "q_alert",
    "notification": "q_notification",
    "surface": "q_surface",
    "activity_report": "q_activity",  # NOT q_activity_report
}

#: item_type → target list (ai-surface.md:39-53 decision tree; creator § 3c table).
SURFACE_ROUTING: dict[str, str] = {
    "question": AI_QUESTIONS_LIST,
    "alert": AI_QUESTIONS_LIST,
    "notification": AI_ACTIVITY_LIST,
    "surface": AI_ACTIVITY_LIST,
    "activity_report": AI_ACTIVITY_LIST,
}

#: item_type → title-line type letter (creator § 3d).
SURFACE_TYPE_LETTER: dict[str, str] = {
    "question": "Q",
    "alert": "A",
    "notification": "N",
    "surface": "S",
    "activity_report": "AR",
}

#: Auto-close TTL in days. None = never (questions/alerts). Per-type, NOT one constant.
SURFACE_TTL_DAYS: dict[str, int | None] = {
    "question": None,
    "alert": None,
    "notification": 7,
    "surface": 14,
    "activity_report": 7,
}

#: Provenance tag by list (permanent, set at creation).
CLAUDE_QUESTION = "claude_question"
AI_ACTIVITY_TAG = "ai_activity"

#: Initial lifecycle state by list.
Q_PENDING = "q_pending"
Q_OPEN = "q_open"
Q_ANSWERED = "q_answered"
Q_PROCESSED = "q_processed"
Q_ACKNOWLEDGED = "q_acknowledged"
AUTO_CLOSED = "auto_closed"  # deliberately NOT q_-prefixed

#: The two disjoint lifecycle machines. A resolution illegal for the item's list is rejected.
QUESTIONS_RESOLUTIONS = frozenset({"answered", "processed"})
ACTIVITY_RESOLUTIONS = frozenset({"acknowledged", "auto_closed"})
SURFACE_RESOLUTIONS = QUESTIONS_RESOLUTIONS | ACTIVITY_RESOLUTIONS

#: resolution → (tags to add, tags to remove).
_RESOLUTION_TAGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "answered": ((Q_ANSWERED,), ()),
    "processed": ((Q_PROCESSED,), (Q_PENDING, Q_ANSWERED)),
    "acknowledged": ((Q_ACKNOWLEDGED,), ()),
    "auto_closed": ((AUTO_CLOSED,), ()),
}

#: AI-LINK `Status:` enum (journaling-lifecycle.md:677 — the grammar owner). Note `auto-closed`
#: is HYPHENATED here while the tag is `auto_closed`.
AI_LINK_STATUSES = frozenset(
    {"open", "answered", "processed", "acknowledged", "auto-closed", "closed"}
)
#: resolution → the AI-LINK Status value written on each linked entity.
_RESOLUTION_LINK_STATUS: dict[str, str] = {
    "answered": "answered",
    "processed": "closed",
    "acknowledged": "closed",
    "auto_closed": "auto-closed",
}

#: The nine entity types (creator § 2). `meta` needs no url/triple; `meta` + `scheduled_task`
#: are AI-LINK no-ops.
SURFACE_ENTITY_TYPES = frozenset(
    {
        "action",
        "project",
        "calendar_entry",
        "waiting_for",
        "goal",
        "focus_area",
        "speculative",
        "scheduled_task",
        "meta",
    }
)
AI_LINK_SKIP_ENTITY_TYPES = frozenset({"meta", "scheduled_task"})
AI_LINK_CAP = 20  # creator § 4f

#: Response shapes (creator § 2). `none` is mandatory for AI_Activity types and illegal for
#: AI_Questions types (creator § 3a rule 4).
RESPONSE_SHAPES = frozenset(
    {"free-text", "yes-no", "pick-one", "confirm-list", "structured", "none"}
)
_SHAPES_NEEDING_OPTIONS = frozenset({"pick-one", "confirm-list"})

#: "How to engage" per type (specs/proactive-contribution.md:1017-1024 — NOT ai-surface.md).
HOW_TO_ENGAGE: dict[str, str] = {
    "question": "Add a note to this task with your answer / direction. I'll pick it up at the "
    "next scan.",
    "alert": "Add a note to this task with your answer / direction. I'll pick it up at the "
    "next scan.",
    "notification": "Mark complete when read.",
    "surface": "Review when convenient. Act on linked entities or close when satisfied.",
    "activity_report": "Read at leisure; auto-closes in {ttl} days. Drill into linked entities "
    "for detail.",
}


def surface_list_for(item_type: str) -> str:
    return SURFACE_ROUTING[item_type]


def surface_tags(
    item_type: str, entity_types: list[str], *, extra: list[str] | None = None
) -> list[str]:
    """The full create-time tag set (creator § 3f), sorted.

    Item-type tag + one q_<entity-type> facet per DISTINCT linked entity type + the provenance
    tag for the list + ai_conversation + the initial lifecycle state. NO life-context and NO
    workflow-state tag — no source applies one, and adding one would leak the surface item into
    Paul's GTD smart lists.
    """
    target = surface_list_for(item_type)
    tags: set[str] = {
        SURFACE_TYPE_TAG[item_type],
        AI_CONVERSATION,
        CLAUDE_QUESTION if target == AI_QUESTIONS_LIST else AI_ACTIVITY_TAG,
        Q_PENDING if target == AI_QUESTIONS_LIST else Q_OPEN,
    }
    for et in entity_types:
        if et:
            tags.add(f"q_{et}")
    tags |= {t.strip() for t in (extra or []) if t and t.strip()}
    return sorted(tags)


def surface_title(item_type: str, title_summary: str, entity_short_ref: str, *, date: str) -> str:
    """`YYYY-MM-DD — <TYPE> — <summary> (<entity-short-ref>)` (creator § 3d)."""
    letter = SURFACE_TYPE_LETTER[item_type]
    suffix = f" ({entity_short_ref})" if entity_short_ref else ""
    return f"{date} — {letter} — {title_summary.strip()}{suffix}"


def entity_short_ref(entity: dict[str, Any]) -> str:
    """The compact primary-entity reference in the title (creator § 3d)."""
    et = str(entity.get("entity_type") or "")
    tid = str((entity.get("entity_rtm") or {}).get("task_id") or entity.get("task_id") or "")
    prefix = {
        "action": "act",
        "project": "prj",
        "calendar_entry": "cal",
        "waiting_for": "wf",
        "speculative": "spec",
    }.get(et)
    if et == "meta":
        return "meta"
    if et == "scheduled_task":
        return f"sched:{entity.get('name') or entity.get('relationship') or ''}".rstrip(":")
    if prefix and tid:
        return f"{prefix}:rtm:{tid}"
    return f"{et}:rtm:{tid}" if tid else et


def slugify(text: str, *, cap: int = 40) -> str:
    import re as _re

    s = _re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:cap].rstrip("-")


def surface_item_id(title_summary: str, *, date: str) -> str:
    """`<YYYY-MM-DD>-<short-slug>` — the day-bucket idempotency key (creator § 3b)."""
    return f"{date}-{slugify(title_summary)}"


def _shift_days(iso_date: str, days: int) -> str:
    """YYYY-MM-DD + N days (pure, no clock)."""
    from datetime import date as _date
    from datetime import timedelta as _td

    try:
        y, m, d = (int(x) for x in iso_date[:10].split("-"))
        return (_date(y, m, d) + _td(days=days)).isoformat()
    except Exception:
        return iso_date[:10]


def auto_close_at(item_type: str, *, today: str) -> str | None:
    """The `auto_close_at:` value — a DATE in the body YAML, or None for questions/alerts."""
    ttl = SURFACE_TTL_DAYS[item_type]
    return None if ttl is None else _shift_days(today, ttl)


def surface_body(
    *,
    item_id: str,
    item_type: str,
    entities: list[dict[str, Any]],
    content: str,
    why_this_is_here: str,
    expected_response_shape: str,
    expected_response_options: list[str] | None,
    priority: int,
    asked_by: str,
    asked_at: str,
    context_summary: str,
    related_artefact: str | None,
    auto_close: str | None,
    paired: dict[str, str] | None = None,
) -> str:
    """The structured body note (creator § 3e): YAML frontmatter + four H2 sections.

    This frontmatter is what makes an item RESOLVABLE — the scan reads auto_close_at (to
    auto-close), item_id (to match AI-LINKs), entities (to fan out), asked_by (to dispatch) and
    asked_at (the Paul-note baseline). The published publish_ai_activity path omits it entirely,
    which is why items created that way can never auto-close (see the module header).
    """
    lines = [
        "---",
        f"item_id: {item_id}",
        f"item_type: {item_type}",
        f"list: {surface_list_for(item_type)}",
        "entities:",
    ]
    for e in entities:
        rtm = e.get("entity_rtm") or {}
        lines.append(f"  - entity_type: {e.get('entity_type', '')}")
        lines.append(f"    entity_url: {e.get('entity_url', '')}")
        lines.append("    entity_rtm:")
        for k in ("task_id", "taskseries_id", "list_id"):
            lines.append(f'      {k}: "{rtm.get(k, "")}"')
        lines.append(f"    relationship: {e.get('relationship', '')}")
    lines.append(f"expected_response_shape: {expected_response_shape}")
    if expected_response_options:
        lines.append("expected_response_options:")
        lines += [f'  - "{o}"' for o in expected_response_options]
    lines.append(f"priority: P{priority}")
    lines.append(f"asked_by: {asked_by}")
    lines.append(f"asked_at: {asked_at}")
    lines.append("context_summary: |")
    lines.append(f"  {context_summary}")
    lines.append(f"related_artefact: {related_artefact or 'null'}")
    lines.append(f"auto_close_at: {auto_close or 'null'}")
    lines.append("---")
    lines.append("")
    # The paired cross-reference lines (communication-channels § 3.4/3.5 convention).
    for label, tid in sorted((paired or {}).items()):
        lines.append(f"Paired {label} task: {tid}")
    if paired:
        lines.append("")
    heading = {
        "question": "Question",
        "alert": "Alert",
        "notification": "Notification",
        "surface": "Surface",
        "activity_report": "Activity Report",
    }[item_type]
    ttl = SURFACE_TTL_DAYS[item_type]
    engage = HOW_TO_ENGAGE[item_type].replace("{ttl}", str(ttl or ""))
    lines += [
        f"## {heading}",
        "",
        content.strip(),
        "",
        "## Why this is here",
        "",
        why_this_is_here.strip(),
        "",
        "## Linked entities",
        "",
    ]
    lines.append("| Entity | Type | Relationship |")
    lines.append("|---|---|---|")
    for e in entities:
        lines.append(
            f"| {e.get('entity_url', '') or e.get('entity_type', '')} "
            f"| {e.get('entity_type', '')} | {e.get('relationship', '')} |"
        )
    lines += ["", "## How to engage", "", engage, ""]
    return "\n".join(lines)


def ai_link_note(
    *,
    item_summary: str,
    surface_url: str,
    surface_ids: dict[str, str],
    item_id: str,
    item_type: str,
    list_name: str,
    asked_by: str,
    asked_at: str,
    why: str,
    status: str = "open",
) -> str:
    """The AI-LINK note BODY (journaling-lifecycle.md:663-680 — the grammar owner).

    Lives on the LINKED ENTITY, never on the surface item. `Status:` opens as `open` — the
    creator agent writes `q_pending`/`q_open` here, which are not legal Status values.
    """
    ttl = SURFACE_TTL_DAYS[item_type]
    engage = HOW_TO_ENGAGE[item_type].replace("{ttl}", str(ttl or ""))
    return "\n".join(
        [
            f"Item: {item_summary}",
            f"Surface item URL: {surface_url}",
            "Surface item RTM IDs:",
            f'  task_id: "{surface_ids.get("task_id", "")}"',
            f'  taskseries_id: "{surface_ids.get("taskseries_id", "")}"',
            f'  list_id: "{surface_ids.get("list_id", "")}"',
            f"Item ID: {item_id}",
            f"Item type: {item_type}",
            f"List: {list_name}",
            f"Asked by: {asked_by}",
            f"Asked at: {asked_at}",
            f"Status: {status}",
            f"Why: {why}",
            f"How to engage: {engage}",
        ]
    )


def ai_link_targets(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entities that actually get an AI-LINK note: `meta` and `scheduled_task` are no-ops
    (creator §§ 3i/3i-note), capped at AI_LINK_CAP (creator § 4f)."""
    out = [e for e in entities if str(e.get("entity_type")) not in AI_LINK_SKIP_ENTITY_TYPES]
    return out[:AI_LINK_CAP]


def resolution_tags(resolution: str) -> tuple[list[str], list[str]]:
    add, remove = _RESOLUTION_TAGS[resolution]
    return list(add), list(remove)


def resolution_link_status(resolution: str) -> str:
    return _RESOLUTION_LINK_STATUS[resolution]


def surface_outcome_summary(resolution: str, detail: str = "", *, days: int | None = None) -> str:
    """The OUTCOME note title summary. TITLE-ONLY — the AI surface has no structured OUTCOME
    body (the catalogue's OUTCOME grammar is the MEETING shape; emitting it here would be wrong)."""
    if resolution == "processed":
        return f"Response received and acted on: {detail}".rstrip(": ")
    if resolution == "auto_closed":
        return f"Auto-closed after {days if days is not None else 'N'} days unread"
    if resolution == "acknowledged":
        return f"Acknowledged: {detail}" if detail.strip() else "Acknowledged: marked acknowledged"
    return f"Response recorded: {detail}".rstrip(": ")


def validate_surface_create(
    *,
    item_type: str,
    title_summary: str,
    content: str,
    entities: list[dict[str, Any]],
    expected_response_shape: str,
    expected_response_options: list[str] | None,
    priority: int,
    asked_by: str,
    list_ok: bool,
) -> list[dict[str, Any]]:
    """The creator's § 3a gate, ported. Fail-closed: any breach writes nothing."""
    rejections: list[dict[str, Any]] = []
    if item_type not in SURFACE_ITEM_TYPES:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"item_type must be one of {sorted(SURFACE_ITEM_TYPES)} (the INPUT vocabulary — "
                "the tag is derived server-side)",
                field="item_type",
            )
        )
        return rejections  # everything below is type-relative
    if not (title_summary or "").strip():
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "title_summary is required"))
    if not (content or "").strip():
        rejections.append(_reject(ErrorCode.MISSING_PARAMETER, "content is required"))
    if not (asked_by or "").strip():
        rejections.append(
            _reject(ErrorCode.MISSING_PARAMETER, "asked_by is required (response routing)")
        )
    if not entities:
        rejections.append(
            _reject(
                ErrorCode.MISSING_PARAMETER,
                "entities must be non-empty — every item links at least one GTD entity, or "
                "carries entity_type 'meta'",
            )
        )
    for i, e in enumerate(entities):
        et = str(e.get("entity_type") or "")
        if et not in SURFACE_ENTITY_TYPES:
            rejections.append(
                _reject(
                    ErrorCode.INVALID_INPUT,
                    f"entities[{i}].entity_type must be one of {sorted(SURFACE_ENTITY_TYPES)}",
                    entity_type=et,
                )
            )
            continue
        if et != "meta":
            rtm = e.get("entity_rtm") or {}
            if not e.get("entity_url") or not all(
                rtm.get(k) for k in ("task_id", "taskseries_id", "list_id")
            ):
                rejections.append(
                    _reject(
                        ErrorCode.MISSING_PARAMETER,
                        f"entities[{i}] ({et}) needs entity_url AND the full entity_rtm triple",
                    )
                )
    # Rule 4 — the response-shape/list coupling.
    target = SURFACE_ROUTING[item_type]
    if target == AI_ACTIVITY_LIST and expected_response_shape != "none":
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"expected_response_shape must be 'none' for a {item_type} (AI_Activity items "
                "require no response)",
                field="expected_response_shape",
            )
        )
    if target == AI_QUESTIONS_LIST:
        if expected_response_shape not in (RESPONSE_SHAPES - {"none"}):
            rejections.append(
                _reject(
                    ErrorCode.INVALID_INPUT,
                    f"expected_response_shape must be one of "
                    f"{sorted(RESPONSE_SHAPES - {'none'})} for a {item_type}",
                    field="expected_response_shape",
                )
            )
        elif expected_response_shape in _SHAPES_NEEDING_OPTIONS and not (
            expected_response_options or []
        ):
            rejections.append(
                _reject(
                    ErrorCode.MISSING_PARAMETER,
                    f"expected_response_shape '{expected_response_shape}' needs "
                    "expected_response_options",
                )
            )
    if priority not in (1, 2, 3):
        rejections.append(
            _reject(ErrorCode.INVALID_INPUT, "priority must be 1, 2 or 3", field="priority")
        )
    if not list_ok:
        rejections.append(
            _reject(ErrorCode.SMART_LIST_TARGET, f"the {target} list is missing or not writable")
        )
    return rejections


def validate_surface_resolve(*, resolution: str, item_tags: list[str]) -> list[dict[str, Any]]:
    """Resolution legality against the TWO disjoint lifecycle machines (tag-taxonomy.md:136-147).

    A resolution valid for one list is ILLEGAL for the other — `q_acknowledged` can never follow
    `q_pending`, and `q_processed` can never follow `q_open`.
    """
    rejections: list[dict[str, Any]] = []
    if resolution not in SURFACE_RESOLUTIONS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"resolution must be one of {sorted(SURFACE_RESOLUTIONS)}",
                field="resolution",
            )
        )
        return rejections
    on_questions = CLAUDE_QUESTION in item_tags
    on_activity = AI_ACTIVITY_TAG in item_tags
    if on_questions and resolution in ACTIVITY_RESOLUTIONS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"'{resolution}' is an AI_Activity resolution — an AI_Questions item resolves "
                f"via {sorted(QUESTIONS_RESOLUTIONS)}",
                resolution=resolution,
            )
        )
    if on_activity and resolution in QUESTIONS_RESOLUTIONS:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                f"'{resolution}' is an AI_Questions resolution — an AI_Activity item resolves "
                f"via {sorted(ACTIVITY_RESOLUTIONS)}",
                resolution=resolution,
            )
        )
    if not on_questions and not on_activity:
        rejections.append(
            _reject(
                ErrorCode.INVALID_INPUT,
                "the target is not an AI-surface item (no claude_question / ai_activity "
                "provenance tag)",
            )
        )
    return rejections


def collect_surface_tags(
    item_type: str, entity_types: list[str], extra: list[str] | None = None
) -> set[str]:
    """Every tag a create writes — the strict-tag existence-gate input."""
    return set(surface_tags(item_type, entity_types, extra=extra))
