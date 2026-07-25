"""Pure (no-IO) builder for `gtd_tag_report` — tag-taxonomy hygiene.

Replaces `tag-audit.ms`, consumed by the live `tag-audit-weekly` scheduled task (Sundays 09:30),
described there as *"the sole control that catches tags created in the RTM native clients"* since
the strict-tag write gate went live. This is the read half of that gate: the gate stops the
server minting tags, this finds what got in another way.

**The taxonomy is codified here, not read from the plugin.** The server is standalone and cannot
read `references/tag-taxonomy.md` at runtime, so the vocabulary is a Python constant — exactly as
`engage_commit.py` codifies the engage verdict grammar and `surface_queue.py` the note-type
catalogue. Codification before validation: the markdown remains the authority and a change there
is a lockstep change here.

**Built to the taxonomy, not to the script.** `tag-audit.ms` carried a hand-copied 24-tag list
that had drifted badly — it was missing every `q_*` lifecycle tag, every `ai_*` engine signal,
`client`, `focus`, `hold`, `quick_win`, `single_action`, the energy pair, `redacted`, and all four
plugin families. Against 87 live account tags it would report the overwhelming majority as
"outside taxonomy", which is noise, not a finding.

**One broad read replaces an N+1.** The `.ms` issued `rtm.getTasks("tag:" + name …)` once PER
non-canonical tag — up to 87 signed calls at ~0.9 RPS. Usage is instead tallied client-side from
the single `status:incomplete AND NOT tag:test` read that the minimum-tag-set signals need
anyway. Same answer, two calls total. (The same divergence `detectors.build_health_check` already
makes against `health-check.ms`.)

**Three-way classification, because binary would lie.** A tag is `canonical` (an exact member),
`family` (matched a registered wildcard family — `ai_*_optin`, `q_<entity-type>`, `agile_wow_*`,
`architect_*`, `eval_*`, `communication_*`), or `non_canonical`. People tags are the honest
caveat: `tag-taxonomy.md` § People says they *"accumulate organically"* and names only `alex` /
`luke`, so a person tag is indistinguishable from a typo by any rule — they land in
`non_canonical` and the report says so rather than pretending otherwise.
"""

from __future__ import annotations

from typing import Any

from .gtd_writes import SURFACE_ENTITY_TYPES

#: Life context (`tag-taxonomy.md` § Life Context) — FOUR members. `client` is canonical and was
#: absent from the script's list; note the older `_LIFE_TAGS` tuples in `project_plan.py` /
#: `gtd_reads.py` also carry only three (a pre-existing inconsistency, flagged not changed here —
#: altering them would change shipped tool output and this change is additive).
LIFE_CONTEXT_TAGS = frozenset({"work", "leanworking", "client", "personal"})
WORKFLOW_STATE_TAGS = frozenset({"action", "project", "focus", "waiting_for", "someday"})
STRUCTURAL_QUALIFIER_TAGS = frozenset({"single_action", "quick_win"})
HORIZON_TAGS = frozenset({"purpose_principles", "vision", "goal"})
ACTION_CONTEXT_TAGS = frozenset(
    {"location_home", "location_office", "location_errand", "using_device"}
)
ENERGY_TAGS = frozenset({"high_energy", "low_energy"})
COMMS_TAGS = frozenset(
    {
        "conversation_messenger",
        "conversation_email",
        "conversation_phone_call",
        "conversation_video_call",
        "conversation_f2f",
    }
)
SPECIAL_TAGS = frozenset({"calendar_entry", "redacted"})
AI_COLLABORATION_TAGS = frozenset(
    {
        "ai_conversation",
        "ai_output_review_needed",
        "ai_output_approved",
        "ai_contrib_drafted",
        "ai_prep_drafted",
        "ai_deferred_pending_unblock",
        "ai_pending_creation_fanout",
        "ai_speculative",
        "ai_progress_requested",
        "ai_progress_deferred",
        "ai_chat_requested",
        "ai_chat",
        "ai_project_needs_finalise",
        "ai_overlay_refresh_needed",
    }
)
AI_SURFACE_TAGS = frozenset(
    {
        "claude_question",
        "ai_activity",
        "q_question",
        "q_alert",
        "q_notification",
        "q_surface",
        "q_activity",
        "q_pending",
        "q_answered",
        "q_processed",
        "q_open",
        "q_acknowledged",
        "auto_closed",
    }
)
#: The `q_<entity-type>` facet family, derived from the canonical entity-type set rather than
#: re-listed — one vocabulary, one place.
Q_ENTITY_TAGS = frozenset(f"q_{et}" for et in SURFACE_ENTITY_TYPES)
INBOX_PIPELINE_TAGS = frozenset({"note", "ai_review", "ai_approved"})
TYPE_ROUTING_TAGS = frozenset({"improvement_candidate"})
#: `#hold` is used by `project_index` as a portfolio-exclusion tag and is live in the account,
#: but is NOT listed in `tag-taxonomy.md`. Treated as canonical here and reported as a
#: codification gap so the omission surfaces rather than reading as an unknown tag.
OTHER_TAGS = frozenset({"chore", "gtd", "test", "hold"})

#: Explicitly retired — `tag-taxonomy.md` marks `next_action` retired in favour of `action` and
#: says the validator rejects it. Reported in its own bucket: still-in-use is a live finding.
RETIRED_TAGS = frozenset({"next_action"})

CANONICAL_TAGS = (
    LIFE_CONTEXT_TAGS
    | WORKFLOW_STATE_TAGS
    | STRUCTURAL_QUALIFIER_TAGS
    | HORIZON_TAGS
    | ACTION_CONTEXT_TAGS
    | ENERGY_TAGS
    | COMMS_TAGS
    | SPECIAL_TAGS
    | AI_COLLABORATION_TAGS
    | AI_SURFACE_TAGS
    | Q_ENTITY_TAGS
    | INBOX_PIPELINE_TAGS
    | TYPE_ROUTING_TAGS
    | OTHER_TAGS
)

#: Registered plugin / wildcard families, `family name → (prefix, suffix)`. A suffix of `""`
#: means prefix-only. Ownership is one plugin per family (`tag-taxonomy.md` § Plugin-Specific Tag
#: Families); the server checks membership shape only — cross-plugin emission is gtd's check.
TAG_FAMILIES: dict[str, tuple[str, str]] = {
    "ai_optin": ("ai_", "_optin"),
    "agile_wow": ("agile_wow_", ""),
    "architect": ("architect_", ""),
    "eval": ("eval_", ""),
    "communication": ("communication_", ""),
}

#: Documented people tags. Listed so they classify cleanly; the family is open by design.
KNOWN_PEOPLE_TAGS = frozenset({"alex", "luke"})

PEOPLE_CAVEAT = (
    "People tags accumulate organically (tag-taxonomy.md § People Tags names only 'alex' and "
    "'luke'), so a person tag is indistinguishable from a typo by any deterministic rule. Any "
    "person tag beyond the two documented ones appears under non_canonical — review before "
    "deleting."
)


def classify_tag(name: str) -> tuple[str, str]:
    """`(classification, detail)` for one tag name.

    classification ∈ `canonical` | `family` | `retired` | `people` | `non_canonical`.
    """
    tag = (name or "").strip().lower()
    if not tag:
        return "non_canonical", ""
    if tag in RETIRED_TAGS:
        return "retired", "retired in favour of the canonical replacement"
    if tag in CANONICAL_TAGS:
        return "canonical", ""
    for family, (prefix, suffix) in TAG_FAMILIES.items():
        if (
            tag.startswith(prefix)
            and (not suffix or tag.endswith(suffix))
            and len(tag) > len(prefix) + len(suffix)
        ):
            return "family", family
    if tag in KNOWN_PEOPLE_TAGS:
        return "people", "documented person tag"
    return "non_canonical", ""


def _tally_usage(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tasks:
        for tag in t.get("tags") or []:
            key = str(tag).strip().lower()
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _sample(rows: list[dict[str, Any]], limit: int) -> list[dict[str, str]]:
    return [{"task_id": str(r.get("id") or ""), "name": r.get("name") or ""} for r in rows[:limit]]


def build_tag_report(
    account_tags: list[str],
    tasks: list[dict[str, Any]],
    *,
    today: str,
    sample_limit: int = 10,
) -> dict[str, Any]:
    """The tag audit.

    ``account_tags`` is every tag name RTM knows (`rtm.tags.getList`) — including tags used only
    on completed tasks, which is why the account list is read rather than derived from the task
    tally. ``tasks`` is one `status:incomplete AND NOT tag:test` read, used both for active-usage
    counts and for the minimum-tag-set signals.
    """
    usage = _tally_usage(tasks)
    names = sorted({str(t).strip().lower() for t in account_tags if str(t).strip()})

    canonical: list[str] = []
    families: list[dict[str, Any]] = []
    people: list[dict[str, Any]] = []
    retired: list[dict[str, Any]] = []
    non_canonical: list[dict[str, Any]] = []

    for name in names:
        kind, detail = classify_tag(name)
        active = usage.get(name, 0)
        if kind == "canonical":
            canonical.append(name)
        elif kind == "family":
            families.append({"name": name, "family": detail, "active_count": active})
        elif kind == "people":
            people.append({"name": name, "active_count": active})
        elif kind == "retired":
            retired.append({"name": name, "active_count": active, "detail": detail})
        else:
            non_canonical.append({"name": name, "active_count": active})

    # Tags used on live tasks that RTM's own tag list does not carry. Should be empty; a
    # non-empty list means the two RTM surfaces disagree and is worth surfacing, not swallowing.
    orphaned = sorted(set(usage) - set(names))

    missing_life = [
        t
        for t in tasks
        if not (LIFE_CONTEXT_TAGS & {str(x).lower() for x in (t.get("tags") or [])})
    ]
    missing_state = [
        t
        for t in tasks
        if not (WORKFLOW_STATE_TAGS & {str(x).lower() for x in (t.get("tags") or [])})
    ]
    actions_missing_context = [
        t
        for t in tasks
        if "action" in {str(x).lower() for x in (t.get("tags") or [])}
        and not (ACTION_CONTEXT_TAGS & {str(x).lower() for x in (t.get("tags") or [])})
    ]

    return {
        "current_date": today,
        "total_account_tags": len(names),
        "canonical": canonical,
        "canonical_count": len(canonical),
        "family": families,
        "family_count": len(families),
        "people": people,
        "retired_in_use": [r for r in retired if r["active_count"] > 0],
        "retired_unused": [r for r in retired if r["active_count"] == 0],
        "non_canonical_active": [r for r in non_canonical if r["active_count"] > 0],
        "non_canonical_unused": [r for r in non_canonical if r["active_count"] == 0],
        "non_canonical_count": len(non_canonical),
        "orphaned_in_use": orphaned,
        "minimum_tag_set": {
            "missing_life_context_count": len(missing_life),
            "missing_life_context_sample": _sample(missing_life, sample_limit),
            "missing_workflow_state_count": len(missing_state),
            "missing_workflow_state_sample": _sample(missing_state, sample_limit),
            "actions_missing_action_context_count": len(actions_missing_context),
            "actions_missing_action_context_sample": _sample(actions_missing_context, sample_limit),
        },
        "people_caveat": PEOPLE_CAVEAT,
        "sample_limit": sample_limit,
    }


__all__ = [
    "ACTION_CONTEXT_TAGS",
    "AI_COLLABORATION_TAGS",
    "AI_SURFACE_TAGS",
    "CANONICAL_TAGS",
    "COMMS_TAGS",
    "ENERGY_TAGS",
    "HORIZON_TAGS",
    "INBOX_PIPELINE_TAGS",
    "KNOWN_PEOPLE_TAGS",
    "LIFE_CONTEXT_TAGS",
    "OTHER_TAGS",
    "PEOPLE_CAVEAT",
    "Q_ENTITY_TAGS",
    "RETIRED_TAGS",
    "SPECIAL_TAGS",
    "STRUCTURAL_QUALIFIER_TAGS",
    "TAG_FAMILIES",
    "TYPE_ROUTING_TAGS",
    "WORKFLOW_STATE_TAGS",
    "build_tag_report",
    "classify_tag",
]
