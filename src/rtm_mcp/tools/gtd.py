"""GTD domain-composition tools for RTM MCP.

These tools speak a *consuming domain's* language (GTD) rather than mapping 1:1 to an
RTM API method. By convention they carry a `gtd_` prefix (generic RTM primitives stay
bare verbs like `add_task`/`list_tasks`); the prefix marks a GTD-shaped view over RTM
data and keeps a future lift of all `gtd_*` tools into a separate server a clean,
mechanical move.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastmcp import Context
from pydantic import BeforeValidator, Field, WithJsonSchema

from ..canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    COMMS_TAGS,
    CONTEXT_TAGS,
    EXECUTE_CLEAR_TAGS,
    OVERLAY_REFRESH,
    VALID_EXECUTE_COMMIT,
    VALID_SCOPES,
    classifiers_to_tags,
    collect_commit_tags,
    execute_progress_tags,
    validate_commit,
)
from ..canvas_create import (
    collect_create_tags,
    item_id,
    project_tags,
    validate_create,
)
from ..canvas_overlay import apply_graph, lean_seed
from ..canvas_seed import build_seed
from ..client import RTMClient
from ..companion import enrich_files, resolve_vault_root
from ..detectors import (
    ACTION_QUERY,
    CALENDAR_PREP_QUERY,
    CAPTURE_INCOMPLETE_QUERIES,
    HEALTH_CHECK_QUERY,
    REASSESSMENT_QUERIES,
    TOPIC_CLUSTER_QUERY,
    UNBLOCK_QUERIES,
    build_calendar_prep_candidates,
    build_capture_candidates,
    build_decision_candidates,
    build_deliverable_candidates,
    build_health_check,
    build_reassessment_candidates,
    build_research_candidates,
    build_topic_clusters,
    build_unblock_candidates,
    capture_completed_queries,
)
from ..engage_commit import (
    CALENDAR_ENTRY_TAG,
    SOMEDAY_TAG,
    STEER_VERBS,
    VERDICT_FAMILY,
    base_verdict,
    collect_engage_tags,
    date_phrase_for,
    make_steer_note,
    sanitize_steer,
    steer_note_text,
    verdict_arg,
)
from ..engage_commit import validate as validate_engage
from ..engage_seed import _blocked_map as engage_blocked_map
from ..engage_seed import _kind as engage_kind
from ..engage_seed import build_engage_seed
from ..error_codes import ErrorCode
from ..gtd_chat import (
    AI_CHAT,
    AI_CHAT_REQUESTED,
    VALID_MODES,
    VALID_ROLES,
    append_mode_footer,
    build_inflight,
    build_thread,
    format_chat_title,
    local_stamp,
    project_descendants,
)
from ..gtd_reads import (
    VALID_DEPTHS,
    VALID_PERSPECTIVES,
    build_context,
    build_inbox_state,
    build_query_focus_projects,
    build_query_next_actions,
    build_query_todays_field,
    build_waiting_for_queue,
    classify_gtd_type,
    resolve_task_ref,
)
from ..gtd_writes import (
    ACTION_CONTEXTS,
    AI_REVIEW,
    CALENDAR_TAG,
    COMMS_MODES,
    ENERGY_LEVELS,
    INBOX_CLOSE_SUMMARY,
    INBOX_LIST,
    ITEM_KINDS,
    JOURNAL_NOTE_TYPES,
    LIFE_CONTEXTS,
    MOSCOW_BANDS,
    MOSCOW_TO_PRIORITY,
    PROCESSED_LIST,
    UPSTREAM_TYPES,
    collapse_write,
    collect_item_tags,
    collect_transition_tags,
    completion_events,
    depends_on_note,
    divergent_band_proposals,
    format_note_title,
    inbox_close_body,
    item_tags,
    output_approval_transition,
    state_body,
    validate_add_note,
    validate_capture,
    validate_complete,
    validate_create_item,
    validate_link_dependency,
    validate_set_properties,
    validate_transition,
)
from ..lookup import resolve_list_id, resolve_system_list_id
from ..models import (
    ADD_NOTE_OUTPUT,
    BATCH_TRANSITION_OUTPUT,
    CALENDAR_PREP_OUTPUT,
    CANVAS_COMMIT_OUTPUT,
    CAPTURE_OUTPUT,
    CAPTURE_OUTPUT_SCHEMA,
    CHAT_INFLIGHT_OUTPUT,
    CHAT_POST_OUTPUT,
    CHAT_THREAD_OUTPUT,
    CLOSE_INBOX_OUTPUT,
    COMPLETE_ACTION_OUTPUT,
    CREATE_ITEM_OUTPUT,
    CREATE_PROJECT_OUTPUT,
    DECISION_OUTPUT,
    DELIVERABLE_OUTPUT,
    ENGAGE_COMMIT_OUTPUT,
    ENGAGE_SEED_OUTPUT,
    GTD_CONTEXT_OUTPUT,
    GTD_QUERY_OUTPUT,
    HEALTH_CHECK_OUTPUT,
    INBOX_STATE_OUTPUT,
    LINK_DEPENDENCY_OUTPUT,
    PROJECT_CANVAS_OUTPUT,
    PROJECT_INDEX_OUTPUT,
    PROJECT_PLAN_OUTPUT,
    REASSESSMENT_OUTPUT,
    RESEARCH_OUTPUT,
    SET_PROPERTIES_OUTPUT,
    SET_REDACTION_OUTPUT,
    STAMP_TOKENS_OUTPUT,
    TOPIC_CLUSTERS_OUTPUT,
    TRANSITION_OUTPUT,
    UNBLOCK_OUTPUT,
    WAITING_FOR_OUTPUT,
)
from ..order_note import from_envelope as resolve_order_note
from ..order_note import make as make_order_note
from ..parsers import extract_note_body, parse_tasks_response, priority_to_code
from ..plan_graph import build_graph
from ..project_index import build_actions, build_foci, build_index
from ..project_plan import (
    _PROJECT_TAG,
    _TEST_TAG,
    REDACTED_TAG,
    _norm_date,
    _permalink,
    build_envelope,
    resolve_focus,
    resolve_project,
)
from ..response_builder import (
    ADDITIVE_WRITE_ANNOTATIONS,
    DESTRUCTIVE_WRITE_ANNOTATIONS,
    READ_ONLY_ANNOTATIONS,
    build_error,
    build_response,
    get_transaction_info,
)
from ..strict_tags import as_rejection, enforce_strict_tags, normalize_tag
from ..tmpl_child import make_tmpl_child_note, new_slug, plan_backfill
from ..tool_params import (
    coerce_json,
    coerced_obj_array_schema,
    coerced_object_schema,
    coerced_str_array_schema,
    optional_string,
)
from ..urls import build_task_url


def _utc_today() -> str:
    """Today's calendar date (YYYY-MM-DD) in UTC — the safe fallback when the account timezone is
    unknown or invalid (mirrors the raw-UTC fallback in project_plan._norm_date)."""
    return datetime.now(UTC).date().isoformat()


def _account_today(tz: str | None) -> str:
    """Today's calendar date in the account timezone (the clock the pure detector builders need),
    falling back to UTC when the tz is unknown/invalid (never raises)."""
    try:
        return datetime.now(ZoneInfo(tz)).date().isoformat() if tz else _utc_today()
    except Exception:
        return _utc_today()


# Advisory input-constraint metadata (surface 4) — every enum is sourced from the canonical
# constant it validates against (VALID_SCOPES / VALID_ROLES / VALID_MODES / VALID_EXECUTE_COMMIT /
# VERDICT_FAMILY), so the advertised set can never drift from the handler. Typed dict[str, Any]
# (pyright requires it for json_schema_extra / WithJsonSchema).
_SCOPE_ENUM: dict[str, Any] = {"enum": sorted(VALID_SCOPES)}
_ROLE_ENUM: dict[str, Any] = {"enum": sorted(VALID_ROLES)}
_MODE_ENUM: dict[str, Any] = {"enum": sorted(VALID_MODES)}
# execute is a {id: value} map — type the VALUE space with the closed set (now/later/quick/off).
_EXECUTE_EXTRA: dict[str, Any] = {
    "additionalProperties": {"type": "string", "enum": sorted(VALID_EXECUTE_COMMIT)}
}
# engage items[] — type the element object, surfacing the closed verdict enum.
_ENGAGE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "verdict": {"type": "string", "enum": sorted(VERDICT_FAMILY)},
        "date_phrase": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["id", "verdict"],
}
# Phase 0 read tools — advisory enums, sourced from the canonical frozensets in gtd_reads.
_PERSPECTIVE_ENUM: dict[str, Any] = {"enum": sorted(VALID_PERSPECTIVES)}
_DEPTH_ENUM: dict[str, Any] = {"enum": sorted(VALID_DEPTHS)}
# Phase 1 write tools — the SEVEN Tier-1 structural vocabularies (D1 shared-kernel promotion),
# each sourced from its canonical frozenset in gtd_writes so the advertised set cannot drift.
_LIFE_ENUM: dict[str, Any] = {"enum": sorted(LIFE_CONTEXTS)}
_KIND_ENUM: dict[str, Any] = {"enum": sorted(ITEM_KINDS)}
_ACTION_CONTEXT_ENUM: dict[str, Any] = {"enum": sorted(ACTION_CONTEXTS)}
_ENERGY_ENUM: dict[str, Any] = {"enum": sorted(ENERGY_LEVELS)}
_COMMS_ENUM: dict[str, Any] = {"enum": sorted(COMMS_MODES)}
_MOSCOW_ENUM: dict[str, Any] = {"enum": sorted(MOSCOW_BANDS)}
_NOTE_TYPE_ENUM: dict[str, Any] = {"enum": sorted(JOURNAL_NOTE_TYPES)}
_UPSTREAM_TYPE_ENUM: dict[str, Any] = {"enum": sorted(UPSTREAM_TYPES)}
_BATCH_ITEM_SCHEMA: dict[str, Any] = {"type": "string", "description": "A task id."}


def register_gtd_tools(mcp: Any, get_client: Any) -> None:
    """Register GTD domain-composition tools."""

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=PROJECT_PLAN_OUTPUT)
    async def gtd_project_plan(
        ctx: Context,
        project_id: Annotated[
            str | None, optional_string("The project (parent) task id. Preferred when known.")
        ] = None,
        project_name: Annotated[
            str | None,
            optional_string(
                "Project name; resolved to an incomplete #project task (ambiguous → candidates)."
            ),
        ] = None,
        list_id: Annotated[
            str | None,
            optional_string("Optional — scope the fetch to one list (smaller/faster)."),
        ] = None,
        include_completed: Annotated[
            bool, Field(description="Include completed children as history rows (default True).")
        ] = True,
    ) -> dict[str, Any]:
        """GTD — return a whole project plan (the project + all its descendant items + every
            note, with full bodies) as the `project-plan-seed` envelope consumed by the GTD canvas.

            Read-only. Collapses the canvas read path from ~1+N calls to ONE signed
            rtm.tasks.getList (plus a session-cached rtm.settings.getList for the account timezone):
            it fetches the tasks once, reconstructs the project→children tree via parent_task_id, and
            emits the comprehensive envelope — the RTM token never leaves the server. Dates are
            localised to the account timezone (RTM returns UTC). The tool issues no write and creates
            no timeline.

            Identify the project by EXACTLY ONE of:
                project_id: the project (parent) task id. Preferred when known.
                project_name: resolved server-side to an incomplete, `project`-tagged, non-`test`
                    task. If the name matches more than one, a candidate list is returned (the tool
                    does not guess).

            Args:
                list_id: optional — scope the fetch to one list (smaller/faster). When omitted, the
                    whole account is read so the project can be found anywhere.
                include_completed: include completed children (default True — the canvas needs the
                    history rows). Set False for only-active items.

            Returns (on success): {"header": {...}, "rows": [...]} — the `project-plan-seed/3`
                envelope (project metadata + own notes in the header; one row per descendant with
                priority, dates, tags, permalink, deps, filed-artefact paths, and full note bodies).
            Returns (on ambiguity): {"candidates": [{id, name, list_id}, ...]} — call again with a
                project_id from the list.
            Returns (on miss / bad input): {"error": {"code": "project_not_found" | "missing_parameter",
        "message": "<actionable prose>", "rtm_code": null}} — branch on `code`, never the prose.
        """
        client: RTMClient = await get_client()

        if bool(project_id) == bool(project_name):
            return build_response(
                data=build_error(
                    ErrorCode.MISSING_PARAMETER,
                    "Provide exactly one of project_id or project_name.",
                )
            )

        filter_str = (
            "status:incomplete OR status:completed" if include_completed else "status:incomplete"
        )
        params: dict[str, Any] = {"filter": filter_str}
        if list_id:
            params["list_id"] = list_id

        result = await client.call("rtm.tasks.getList", **params)
        parsed = parse_tasks_response(result)

        if project_name:
            resolved = resolve_project(parsed, project_name)
            if "project" not in resolved:
                return build_response(data=resolved)  # error or candidates
            pid = resolved["project"]["id"]
        else:
            pid = str(project_id)
            if pid not in {t["id"] for t in parsed}:
                return build_response(
                    data=build_error(
                        ErrorCode.PROJECT_NOT_FOUND,
                        f"Project {pid} not found in the fetched tasks. Check the id, or "
                        "pass list_id and/or include_completed=true if it lives in a specific list "
                        "or is completed.",
                    )
                )

        # Localise dates to the account timezone (cached settings read) so BST/DST dues don't
        # render a day early — RTM returns UTC. None on failure → safe raw-UTC fallback.
        tz = await client.get_timezone()
        return build_response(data=build_envelope(parsed, pid, timezone=tz))

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=PROJECT_CANVAS_OUTPUT)
    async def gtd_project_canvas(
        ctx: Context,
        project_id: Annotated[
            str | None, optional_string("The project (parent) task id. Preferred when known.")
        ] = None,
        project_name: Annotated[
            str | None,
            optional_string(
                "Project name; resolved to an incomplete #project task (ambiguous → candidates)."
            ),
        ] = None,
        list_id: Annotated[
            str | None,
            optional_string("Optional — scope the fetch to one list (smaller/faster)."),
        ] = None,
        include_completed: Annotated[
            bool,
            Field(description="Include completed children as inert history rows (default True)."),
        ] = True,
        lean: Annotated[
            bool,
            Field(
                description="Emit the inline-widget profile — drop note bodies, cap notes per item (default True)."
            ),
        ] = True,
        note_cap: Annotated[
            int, Field(description="Max notes kept per item when lean (default 3).")
        ] = 3,
    ) -> dict[str, Any]:
        """GTD — return a project plan as the canvas-ready seed the project-plan-canvas artifact
            renders directly. The read-sibling of gtd_project_plan: same single read, but with the
            deterministic plan-graph overlay already applied, so the page never re-implements GTD
            ordering/blocking.

            Read-only. One signed rtm.tasks.getList (plus a session-cached rtm.settings.getList for
            the account timezone); no write, no timeline. Dates are localised to the account timezone
            (RTM returns UTC, so BST/DST dues would otherwise render a day early). It reconstructs the
            project→children tree, builds the `{mode, frame, seed}` seed (priority/context/comms,
            completion→history, note gists, files), then merges the plan-graph overlay: `quick` (from
            the #quick_win tag), sibling `deps`, and a dependency-respecting timeline order (the array
            order of `seed`). `blocked` is NOT a field — the template derives it from `deps[]`. Each row
            also carries `prog` ("now" from #ai_progress_requested / "later" from #ai_progress_deferred;
            absent when neither) so the execute pill reflects committed state on reload, and `redacted`
            (bool, from the item's #redacted tag) so the board can lock the row. `frame.redacted` is the
            project's own #redacted state (an open-but-redacted project renders its locked screen without
            a second lookup). Set/clear #redacted via gtd_set_redaction.

            File objects (per-action `files[]` and project-level `frame.files`) carry `{n, ext, kind,
            path}`; each also gains a `meta` block (the companion `.md`/`.yaml` frontmatter — title,
            type, status, dates, authors, tags, …) when the read-only AI Memory vault is configured
            (RTM_VAULT_ROOT / AI_MEMORY_DIR, or the host default) and a companion exists. Absent vault
            or companion → no `meta`, no error.

            Identify the project by EXACTLY ONE of:
                project_id: the project (parent) task id. Preferred when known.
                project_name: resolved server-side to an incomplete, `project`-tagged, non-`test`
                    task. Ambiguous names return a candidate list (the tool does not guess).

            Args:
                list_id: optional — scope the fetch to one list (smaller/faster).
                include_completed: include completed children as inert history rows (default True).
                lean: emit the inline-widget profile — drop note bodies, cap notes per item, set an
                    honest `nc` (default True; byte-compatible with build_canvas --emit html-lean).
                note_cap: max notes kept per item when lean (default 3).

            Returns (on success): {"mode": "existing", "frame": {...}, "seed": [...]} — the canvas seed.
            Returns (on ambiguity): {"candidates": [{id, name, list_id}, ...]}.
            Returns (on miss / bad input): {"error": {"code": "project_not_found" | "missing_parameter",
        "message": "<actionable prose>", "rtm_code": null}} — branch on `code`, never the prose.
        """
        client: RTMClient = await get_client()

        if bool(project_id) == bool(project_name):
            return build_response(
                data=build_error(
                    ErrorCode.MISSING_PARAMETER,
                    "Provide exactly one of project_id or project_name.",
                )
            )

        filter_str = (
            "status:incomplete OR status:completed" if include_completed else "status:incomplete"
        )
        params: dict[str, Any] = {"filter": filter_str}
        if list_id:
            params["list_id"] = list_id

        result = await client.call("rtm.tasks.getList", **params)
        parsed = parse_tasks_response(result)

        if project_name:
            resolved = resolve_project(parsed, project_name)
            if "project" not in resolved:
                return build_response(data=resolved)  # error or candidates
            pid = resolved["project"]["id"]
        else:
            pid = str(project_id)
            if pid not in {t["id"] for t in parsed}:
                return build_response(
                    data=build_error(
                        ErrorCode.PROJECT_NOT_FOUND,
                        f"Project {pid} not found in the fetched tasks. Check the id, or "
                        "pass list_id and/or include_completed=true if it lives in a specific list "
                        "or is completed.",
                    )
                )

        # Localise dates to the account timezone (cached settings read) so BST/DST dues don't
        # render a day early — RTM returns UTC. None on failure → safe raw-UTC fallback.
        tz = await client.get_timezone()
        envelope = build_envelope(parsed, pid, timezone=tz)
        seed = build_seed(envelope["header"], envelope["rows"], outputs_index=None)
        # DC-4: honour the latest valid ORDER note (the durable manual-order intent on the
        # project task) as the plan-graph manual-order bias — same clamping semantics as gtd's
        # enriched engine (cosmetic tiering only, never topology; unlisted ids fall to their
        # cohort end; departed ids are pruned). An invalid note fails closed (resolution falls
        # back to the next-latest valid; none → no bias), so the seed always renders.
        manual = resolve_order_note(envelope)
        graph = build_graph(envelope["header"], envelope["rows"], manual_order=manual["order"])
        seed = apply_graph(seed, graph)
        if lean:
            seed = lean_seed(seed, note_cap)
        # Enrich file objects with companion metadata from the read-only AI Memory vault, when
        # available. Last step: apply_graph/lean_seed don't touch files[], and a missing vault is a
        # graceful no-op (n/ext/kind/path unchanged; `meta` added only where a companion exists).
        enrich_files(seed, resolve_vault_root(client.config.vault_root))

        analysis = None
        cycles = graph.get("cycles") or []
        if cycles:
            analysis = {
                "insights": [
                    f"{len(cycles)} dependency cycle(s) detected (advisory — the order is a "
                    "best-effort fallback; resolve in RTM when convenient)."
                ]
            }

        return build_response(data=seed, analysis=analysis)

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=PROJECT_INDEX_OUTPUT)
    async def gtd_project_index(
        ctx: Context,
        include_someday: Annotated[
            bool,
            Field(
                description="Include #someday projects AND foci (default False; #hold always excluded)."
            ),
        ] = False,
    ) -> dict[str, Any]:
        """GTD — return the active-project portfolio for the cockpit navigator: per-project rows
        (open / blocked counts + next tickle, grouped by life → focus), the complete focus list, and
        a flat action index for fast search / jump-to. The data source for the project-plan-canvas
        navigator (the Phase C cockpit picker); a read-sibling of gtd_project_plan /
        gtd_project_canvas.

        Read-only. One signed rtm.tasks.getList (status:incomplete) plus a session-cached
        rtm.settings.getList for the account timezone; no write, no timeline. All three collections
        come from that single read — projects, #focus areas, and action rows are all in the result.
        Counts are vault-free — derived from the THIN plan-graph over each project's rows (the same
        blocked judgement gtd_project_canvas applies), so cross-project / completed upstreams don't
        count as blockers. Dates are localised to the account timezone (RTM returns UTC).

        Selection:
        - projects: incomplete tasks tagged #project, NOT #test; #hold always excluded, #someday
          excluded unless include_someday=True. A project with no Area-of-Focus parent is kept with
          focus="(unfiled)", focus_id="" — never dropped. Each row also carries the AI-progressible
          tallies the navigator's 4th sort lens ranks on: ai_quick / ai_now / ai_later (counts of
          quick-win / progress-now / progress-later items, the same classification gtd_project_canvas
          applies), the conversation counts chat_count / chat_review_count (incomplete items
          tagged #ai_chat / #ai_output_review_needed — the navigator chip + Conversations sort lens),
          and the engage-filter count waiting_count (incomplete #waiting_for items — the Focus pill's
          waiting-for segment).
        - foci: incomplete tasks tagged #focus (the same #test/#hold/#someday gate) — the complete
          focus list, INCLUDING focus areas with zero active projects (which the per-project rows
          can never surface on their own).
        - actions: every incomplete child under an active project (actions, waiting-fors, and
          calendar entries — all jumpable), NOT #test. Each carries its project/focus/life context,
          the item type (action/waiting_for/calendar — the canvas r.k classification, for the
          find-result glyph), the urgency signal the "What's hot" band triages on (due, priority,
          blocked), and the engage-lens funnel fields (estimate in minutes, contexts, energy, exec —
          the same execute classification behind the project ai_* tallies). Redaction is
          server-derived and CASCADES onto actions (own #redacted OR a redacted project / focus); a
          shielded action carries no engage data (estimate/energy/exec null, contexts []).

        Args:
            include_someday: include #someday projects AND foci in the portfolio (default False;
                #hold stays excluded regardless).

        Returns (on success): an object {projects, foci, actions} where
            projects: [{life, focus, focus_id, project, project_id, priority ("1"|"2"|"3"|""),
                open_count (incomplete children), blocked_count (children blocked by an open
                DEPENDS-ON upstream), next_tickle (earliest open due date, incl. overdue, or ""),
                updated (project modified date), ai_quick / ai_now / ai_later (incomplete
                quick-win / progress-now / progress-later counts, mirroring gtd_project_canvas),
                chat_count / chat_review_count (incomplete #ai_chat / #ai_output_review_needed
                items), waiting_count (incomplete #waiting_for items — the Focus pill's waiting-for
                segment), redacted (bool, the project's #redacted viewing-curtain state)}], sorted by
                life → focus → project;
            foci: [{focus_id, focus, life, redacted (bool, the area's #redacted state — the
                navigator collapses a redacted focus to one "Redacted Area of Focus" row)}], sorted
                by life → focus;
            actions: [{action_id, name, project_id, project, focus, life, type
                ("action"|"waiting_for"|"calendar"), due (YYYY-MM-DD localised, or ""), priority
                ("1"|"2"|"3"|""), blocked (bool), estimate (int minutes or null), contexts (list of
                action-context tags, may be []), energy ("high"|"low"|null), exec
                ("quick"|"now"|"later"|null — the execute classification behind the project ai_*
                tallies), redacted (bool — the action's own #redacted OR a cascade from a redacted
                project / focus; a shielded row's estimate/energy/exec are null and contexts [])}],
                sorted by life → focus → project → name.
        Returns (on empty portfolio): {"projects": [], "foci": [], "actions": []}.
        """
        client: RTMClient = await get_client()
        result = await client.call("rtm.tasks.getList", filter="status:incomplete")
        parsed = parse_tasks_response(result)
        # Localise dates to the account timezone (cached settings read) — RTM returns UTC, so a BST
        # due/modified would otherwise render a day early. None on failure → safe raw-UTC fallback.
        tz = await client.get_timezone()
        return build_response(
            data={
                "projects": build_index(parsed, include_someday=include_someday, timezone=tz),
                "foci": build_foci(parsed, include_someday=include_someday),
                "actions": build_actions(parsed, include_someday=include_someday, timezone=tz),
            }
        )

    @mcp.tool(annotations=DESTRUCTIVE_WRITE_ANNOTATIONS, output_schema=CANVAS_COMMIT_OUTPUT)
    async def gtd_apply_canvas_commit(
        ctx: Context,
        project_id: Annotated[
            str,
            Field(
                description="The project (parent) task id; every referenced child id must belong to it."
            ),
        ],
        order: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema(
                    "Dragged open-item order (ids); persisted as a durable ORDER note on the project."
                )
            ),
        ] = None,
        edits: Annotated[
            dict[str, Any] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_object_schema(
                    "{id: {priority?, context?, comms?, chase?/calendar_date?/due?, text?}} — per-item field edits."
                )
            ),
        ] = None,
        adds: Annotated[
            list[dict[str, Any]] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_obj_array_schema(
                    "[{type: action|waiting_for|calendar, text, classifiers:{context?,comms?,priority?,quick?}, "
                    "chase?/calendar_date?/due?}] — items created on Processed, parented to the project."
                )
            ),
        ] = None,
        completes: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema(
                    "Ids to complete — DESTRUCTIVE, requires confirm_destructive=True."
                )
            ),
        ] = None,
        removes: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema(
                    "Ids to remove (RTM soft-delete) — DESTRUCTIVE, requires confirm_destructive=True."
                )
            ),
        ] = None,
        execute: Annotated[
            dict[str, Any] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_object_schema(
                    "{id: 'now'|'later'|'quick'|'off'} — durable progression signal (child-only). "
                    "'off' clears the directive.",
                    extra=_EXECUTE_EXTRA,
                )
            ),
        ] = None,
        notes: Annotated[
            dict[str, Any] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_object_schema("{id: {type, text}} — a journaling note per item.")
            ),
        ] = None,
        confirm_destructive: Annotated[
            bool,
            Field(
                description="Must be True for any completes/removes; else the batch is rejected."
            ),
        ] = False,
        scope: Annotated[
            str,
            Field(
                description="Audit-note placement label: instant | item | project | plan (default plan). Label only.",
                json_schema_extra=_SCOPE_ENUM,
            ),
        ] = "plan",
    ) -> dict[str, Any]:
        """GTD — the single governed write surface for a project-plan-canvas commit. The artifact
        stages edits locally and commits them in ONE call here; governance lives in this tool, not
        the page (so the only writable tool the canvas is given is safe by construction).

        It validates the whole commit up-front and writes NOTHING if anything is rejected, then
        applies the accepted ops durable-first, recording each transaction (undoable via
        batch_undo). It does not execute AI work — `execute` only writes the durable RTM signal.

        Identify the project by project_id (required); every referenced item id must be a child of
        it (cross-project ids are rejected). EXCEPTION — the project-entity verbs: project_id itself
        is an accepted target for rename (edits[project_id].text), add-project-note
        (notes[project_id]), complete (completes) and delete (removes); the carve-out is
        project_id-only (arbitrary non-children are still rejected) and covers edits/notes/completes/
        removes only (execute/order stay child-only). Completing/deleting the project writes the
        durable RTM state only — it does NOT fire the gtd-side finalise engine (that is a board-side
        scheduled task).

        Args:
            scope: the commit's audit-note placement label — "instant" | "item" | "project" |
                "plan" (default "plan"). It is a label ONLY: it does not change validation, the
                strict-tag gate, durable-first apply, or batch_undo. "instant"/"item" place the one
                audit note on the referenced item; "project" on the project entity; "plan" writes the
                project-level COMMIT note (the pre-scope behaviour). An unknown value is rejected with
                nothing written.
            order: dragged open-item order (ids membership-checked). Persisted as an ORDER note
                on the project task (order-note/1: strict-JSON body with count + sha256
                self-checks, source "board-commit") — RTM has no sibling-order field, so the note
                IS the durable record of order intent; every consumer (this server's thin
                plan-graph, gtd's enriched overlay refresh) derives the manual-order bias from the
                latest valid ORDER note. Append-only: superseded notes are retained.
            edits: {id: {priority?, context?, comms?, chase?/calendar_date?/due?, text?}}.
            adds: [{type: action|waiting_for|calendar, text, classifiers:{context?, comms?,
                priority?, quick?}, chase?/calendar_date?/due?}] — created on `Processed`, parented
                to the project.
            completes / removes: lists of ids — DESTRUCTIVE, require confirm_destructive=True
                (removes are RTM soft-deletes).
            execute: {id: "now"|"later"|"quick"|"off"} — durable progression signal. "now"/"quick"
                write #ai_progress_requested (drained immediately by the on-commit fire); "later"
                writes #ai_progress_deferred (durable, NOT actioned by the fire). The two are
                mutually exclusive — switching an item's state drops the stale sibling so it never
                carries both. #ai_deferred_pending_unblock is still added when the item is blocked.
                "off" is the inverse — it REMOVES the progression directive (any of
                #ai_progress_requested / #ai_progress_deferred / #ai_deferred_pending_unblock),
                returning the item to no directive; idempotent (a clean no-op when none present)
                and fires no engine. execute is child-only (no project_id).
            notes: {id: {type, text}} — a journaling note per item.
            confirm_destructive: must be True for any completes/removes.

        Tag writes pass the strict-tag existence gate and use a closed canonical classifier→tag
        mapping; created/edited items carry #ai_conversation; one audit note is written per successful
        commit, placed per `scope` (item for instant/item, project for project, the project-level
        COMMIT note for plan). On any successful commit the project is also stamped with
        #ai_overlay_refresh_needed (the gtd-side finalise engine drains it to recompute + persist the
        enriched plan-graph overlay); this tag must exist in the RTM account under strict-tag mode.

        Returns (on success): {"applied": [{op, id, transaction_id}, ...], "errors": [...],
            "order_persisted": "order-note" | false, "message": "..."} — "order-note" iff a
            non-empty `order` was durably written as the ORDER note (the board gates its
            "order saved" chip on exactly this value); false when the commit carried no order
            (or the note write failed — see errors).
        Returns (on rejection — nothing written): {"applied": [], "rejected": [...], "message": ...}.

        Errors: {"error": {"code": ..., "message": "<actionable prose>",
            "rtm_code": ...}} — branch on `code`, NEVER parse the message.
            Possible: invalid_scope, list_not_found, project_not_found, strict_tag_rejected.
            A strict_tag_rejected carries rejected_tags / how_to_proceed
            under `error.details`.
            Per-item rejections are the FLAT `rejected[]` entries
            ({reason, detail}), not this nested envelope error.
        """
        client: RTMClient = await get_client()

        if scope not in VALID_SCOPES:
            return build_response(
                data={
                    "applied": [],
                    "rejected": [
                        {
                            "reason": ErrorCode.INVALID_SCOPE.value,
                            "scope": scope,
                            "detail": f"scope {scope!r} not in {sorted(VALID_SCOPES)}",
                        }
                    ],
                    "order_persisted": False,
                    "message": "Commit rejected; nothing was written.",
                }
            )

        # Belt-and-braces: a client may pass a complex op as a JSON string. The typed parameter
        # schemas + BeforeValidator already coerce this for pydantic-validated calls; this also
        # covers any caller that bypasses validation (e.g. direct/test invocation).
        order = coerce_json(order)
        edits = coerce_json(edits)
        adds = coerce_json(adds)
        completes = coerce_json(completes)
        removes = coerce_json(removes)
        execute = coerce_json(execute)
        notes = coerce_json(notes)

        result = await client.call(
            "rtm.tasks.getList", filter="status:incomplete OR status:completed"
        )
        parsed = parse_tasks_response(result)
        by_id = {t["id"]: t for t in parsed}
        pid = str(project_id)
        if pid not in by_id:
            return build_response(
                data=build_error(
                    ErrorCode.PROJECT_NOT_FOUND,
                    f"Project {pid} not found. Check the id (pass the project's task id).",
                )
            )

        envelope = build_envelope(parsed, pid)
        plan_ids = {r["id"] for r in envelope["rows"]}
        graph = build_graph(envelope["header"], envelope["rows"])
        blocked_by_id = {
            rid: bool(j.get("blocked")) for rid, j in graph.get("judgement", {}).items()
        }

        ops: dict[str, Any] = {
            "order": order or [],
            "edits": edits or {},
            "adds": adds or [],
            "completes": completes or [],
            "removes": removes or [],
            "execute": execute or {},
            "notes": notes or {},
        }

        # Repeating templated project (Wave B token stamping): a child added to a project whose own
        # taskseries recurs must carry a TMPL-CHILD token so its identity (and any dep authored
        # against it) survives the re-keying each occurrence performs. Seed the used-slug set from
        # the rows already carrying a token so a fresh slug is unique within the plan. A one-off
        # project reads is_repeating False → no stamping → byte-unchanged.
        is_repeating_project = bool(by_id[pid].get("is_repeating"))
        used_slugs = {
            r["template_child_id"] for r in envelope["rows"] if r.get("template_child_id")
        }

        # ── Phase 1: validate (no writes) ─────────────────────────────────
        processed = await resolve_list_id(client, "Processed")
        processed_ok = "error" not in processed and not (processed.get("list") or {}).get("smart")
        processed_list_id = processed.get("list_id") if "error" not in processed else None

        validation = validate_commit(
            ops,
            plan_ids,
            pid,
            processed_list_ok=processed_ok,
            confirm_destructive=confirm_destructive,
        )
        rejections = list(validation["rejections"])

        gate = await enforce_strict_tags(
            client, sorted(collect_commit_tags(ops)), tool="gtd_apply_canvas_commit"
        )
        if gate:
            rejections.append(as_rejection(gate))

        if rejections:
            return build_response(
                data={
                    "project_id": pid,
                    "applied": [],
                    "rejected": rejections,
                    "order_persisted": False,
                    "message": "Commit rejected; nothing was written.",
                }
            )

        # ── Phase 2: apply (durable-first), recording transactions ────────
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        created_item_triples: list[dict[str, Any]] = []  # for instant/item audit-note placement

        async def _write(
            method: str, label: str, _id: str | None = None, **kwargs: Any
        ) -> dict[str, Any] | None:
            try:
                res = await client.call(method, require_timeline=True, **kwargs)
                tx_id, undoable = get_transaction_info(res)
                if tx_id:
                    client.record_transaction(tx_id, method, undoable, label)
                applied.append({"op": label, "id": _id, "transaction_id": tx_id})
                return res
            except Exception as exc:  # batch resilience: record the failure and continue
                errors.append({"op": label, "id": _id, "error": str(exc)})
                return None

        def _ids(rid: str) -> dict[str, Any]:
            t = by_id.get(rid, {})
            return {
                "task_id": t.get("id"),
                "taskseries_id": t.get("taskseries_id"),
                "list_id": t.get("list_id"),
            }

        def _date_of(d: dict[str, Any]) -> str | None:
            return d.get("calendar_date") or d.get("chase") or d.get("due")

        # adds: create on Processed → tags → priority → due → reparent (last, may move lists)
        for add in ops["adds"]:
            text = add.get("text") or ""
            res = await _write(
                "rtm.tasks.add", f"add:{text[:40]}", name=text, parse="0", list_id=processed_list_id
            )
            if res is None:
                continue
            created = parse_tasks_response(res)
            new = created[0] if created else {}
            new_id = new.get("id")
            if not new_id:
                errors.append({"op": "add", "id": None, "error": "created task id not returned"})
                continue
            nid = {
                "task_id": new_id,
                "taskseries_id": new.get("taskseries_id"),
                "list_id": new.get("list_id"),
            }
            created_item_triples.append(nid)
            tags = classifiers_to_tags(add.get("type"), add.get("classifiers"))
            await _write("rtm.tasks.setTags", "add:tags", new_id, tags=",".join(tags), **nid)
            pr = (add.get("classifiers") or {}).get("priority")
            if pr:
                await _write(
                    "rtm.tasks.setPriority",
                    "add:priority",
                    new_id,
                    priority=priority_to_code(pr),
                    **nid,
                )
            dt = _date_of(add)
            if dt:
                await _write("rtm.tasks.setDueDate", "add:due", new_id, due=dt, parse="1", **nid)
            await _write("rtm.tasks.setParentTask", "add:parent", new_id, parent_task_id=pid, **nid)
            # Stamp a TMPL-CHILD token when the project recurs (Wave B). Fresh, unique-within-plan
            # slug; RTM copies the note onto each new occurrence so the identity is durable.
            if is_repeating_project:
                slug = new_slug()
                while slug in used_slugs:
                    slug = new_slug()
                used_slugs.add(slug)
                tc_title, tc_text = make_tmpl_child_note(
                    slug, local_stamp(await client.get_timezone())[:10]
                )
                await _write(
                    "rtm.tasks.notes.add",
                    "add:tmpl-child",
                    new_id,
                    note_title=tc_title,
                    note_text=tc_text,
                    **nid,
                )

        # edits
        for rid, raw in ops["edits"].items():
            e = raw or {}
            ids = _ids(rid)
            if e.get("text"):
                await _write("rtm.tasks.setName", "edit:name", rid, name=e["text"], **ids)
            if e.get("priority"):
                await _write(
                    "rtm.tasks.setPriority",
                    "edit:priority",
                    rid,
                    priority=priority_to_code(e["priority"]),
                    **ids,
                )
            dt = _date_of(e)
            if dt:
                await _write("rtm.tasks.setDueDate", "edit:due", rid, due=dt, parse="1", **ids)
            existing = set(by_id.get(rid, {}).get("tags") or [])
            new_tags = set(existing)
            if e.get("context") in CONTEXT_TAGS:
                new_tags -= CONTEXT_TAGS
                new_tags.add(e["context"])
            if e.get("comms") in COMMS_TAGS:
                new_tags -= COMMS_TAGS
                new_tags.add(e["comms"])
            new_tags.add(AI_CONVERSATION)
            if new_tags != existing:
                await _write(
                    "rtm.tasks.setTags", "edit:tags", rid, tags=",".join(sorted(new_tags)), **ids
                )

        # execute → durable progression signal (no AI work here). now/quick request immediate
        # progress (#ai_progress_requested); later is the durable deferred sibling
        # (#ai_progress_deferred). The two are mutually exclusive, so a stale sibling left by a
        # prior commit (e.g. later→now) is removed — an item never carries both. "off" is the
        # instant-control clear: it REMOVES the progression directive (the inverse of the set-paths)
        # and fires no engine. Idempotent — nothing present → no write; removal is never strict-gated.
        for rid, mode in ops["execute"].items():
            if mode == "off":
                present = [
                    t for t in EXECUTE_CLEAR_TAGS if t in (by_id.get(rid, {}).get("tags") or [])
                ]
                if present:
                    await _write(
                        "rtm.tasks.removeTags",
                        "execute:off",
                        rid,
                        tags=",".join(present),
                        **_ids(rid),
                    )
                continue
            progress_tag, stale_sibling = execute_progress_tags(mode)
            tags = [progress_tag, AI_CONVERSATION]
            if blocked_by_id.get(rid):
                tags.append(AI_DEFERRED)
            await _write(
                "rtm.tasks.addTags", f"execute:{mode}", rid, tags=",".join(tags), **_ids(rid)
            )
            if stale_sibling in (by_id.get(rid, {}).get("tags") or []):
                await _write(
                    "rtm.tasks.removeTags",
                    f"execute:{mode}:drop-stale",
                    rid,
                    tags=stale_sibling,
                    **_ids(rid),
                )

        # notes
        for rid, n in ops["notes"].items():
            await _write(
                "rtm.tasks.notes.add",
                "note",
                rid,
                note_title=(n or {}).get("type") or "",
                note_text=(n or {}).get("text") or "",
                **_ids(rid),
            )

        # destructive (only reachable because confirm_destructive passed validation)
        for rid in ops["completes"]:
            await _write("rtm.tasks.complete", "complete", rid, **_ids(rid))
        for rid in ops["removes"]:
            await _write("rtm.tasks.delete", "remove (soft-delete)", rid, **_ids(rid))

        proj = by_id[pid]

        # DC-4: persist the dragged order as an ORDER note on the project task — the single
        # durable record of order intent (RTM = system of record; the plan-graph manual-order
        # bias is pure derivation from the latest valid note, on both membrane sides). Written
        # BEFORE the overlay-refresh stamp below, so a finalise fired off the mark can never
        # read a commit whose ORDER note hasn't landed. Append-only (superseded notes retained);
        # the transaction is recorded like every other write, so batch_undo reverts it with the
        # rest of the commit. The title is the note body's first line on read (RTM has no
        # note-title field), which order_note.parse strips before its strict-JSON parse.
        order_persisted: str | bool = False
        if ops["order"]:
            tz = await client.get_timezone()
            title, order_body = make_order_note(
                ops["order"],
                "board-commit",
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                local_stamp(tz),
            )
            order_res = await _write(
                "rtm.tasks.notes.add",
                "order-note",
                note_title=title,
                note_text=order_body,
                task_id=proj.get("id"),
                taskseries_id=proj.get("taskseries_id"),
                list_id=proj.get("list_id"),
            )
            if order_res is not None:
                order_persisted = "order-note"

        # Audit note (one per successful commit), placed per scope. plan → project-level COMMIT note
        # (the pre-scope behaviour); project → the project entity, distinctly titled so it never
        # reads as a plan-wide COMMIT; instant/item → the referenced item (its own id, else a
        # freshly-created add). The overlay-refresh mark below always stays on the project regardless
        # of scope — it is a project-level signal for the finalise engine, not an audit trail.
        if applied:
            counts = (
                f"adds:{len(ops['adds'])} edits:{len(ops['edits'])} "
                f"execute:{len(ops['execute'])} notes:{len(ops['notes'])} "
                f"completes:{len(ops['completes'])} removes:{len(ops['removes'])}"
            )
            proj_triple = {
                "task_id": proj.get("id"),
                "taskseries_id": proj.get("taskseries_id"),
                "list_id": proj.get("list_id"),
            }
            if scope in ("plan", "project"):
                note_target = proj_triple
            else:  # instant / item — the single referenced/created item, else the project as fallback
                referenced = [
                    rid
                    for rid in (
                        list(ops["edits"].keys())
                        + ops["completes"]
                        + ops["removes"]
                        + list(ops["execute"].keys())
                        + list(ops["notes"].keys())
                        + ops["order"]
                    )
                    if rid != pid and rid in by_id
                ]
                if referenced:
                    note_target = _ids(referenced[0])
                elif created_item_triples:
                    note_target = created_item_triples[0]
                else:
                    note_target = proj_triple
            note_title = "COMMIT" if scope == "plan" else f"COMMIT ({scope})"
            body = (
                f"COMMIT (project-plan-canvas, {scope}) — {counts}; "
                f"{len(applied)} write(s), {len(errors)} error(s). #ai_conversation"
            )
            await _write(
                "rtm.tasks.notes.add",
                "commit-note",
                note_title=note_title,
                note_text=body,
                **note_target,
            )
            # Piece 0b: stamp the overlay-refresh mark on the project so the gtd-side
            # gtd-project-finalise engine recomputes + persists the enriched plan-graph overlay
            # after ANY commit (not only execute-triggered ones). Best-effort + idempotent: addTags
            # dedupes, and _write records the op in `applied` / `errors` like every other write.
            await _write(
                "rtm.tasks.addTags",
                "overlay-refresh-mark",
                proj.get("id"),
                tags=OVERLAY_REFRESH,
                task_id=proj.get("id"),
                taskseries_id=proj.get("taskseries_id"),
                list_id=proj.get("list_id"),
            )

        return build_response(
            data={
                "project_id": pid,
                "applied": applied,
                "errors": errors,
                "order_persisted": order_persisted,
                "message": f"Applied {len(applied)} write(s); {len(errors)} error(s).",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=CREATE_PROJECT_OUTPUT)
    async def gtd_create_project(
        ctx: Context,
        frame: Annotated[
            dict[str, Any] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_object_schema(
                    "{life (work|personal|leanworking), focus (area name/id), name (required), outcome}."
                )
            ),
        ] = None,
        items: Annotated[
            list[dict[str, Any]] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_obj_array_schema(
                    "[{id, type, text, classifiers, chase?/calendar_date?/due?, start?, estimate?, "
                    "deps:[in-draft ids], done?, execute?, notes}] — the child items in dependency order."
                )
            ),
        ] = None,
        notes: Annotated[
            list[dict[str, Any]] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_obj_array_schema(
                    "[{title?/type?, text/body}] — project-level notes (e.g. the authored INCEPTION)."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — the single governed write surface for creating a NEW project from a canvas draft.
        The create-sibling of gtd_apply_canvas_commit: where commit edits an existing project, this
        builds a brand-new one — the project task, its child items (parented, in dependency order),
        tags, priorities/dates/estimates, DEPENDS-ON notes, progression signals, create-then-complete
        for already-done draft items, and the #ai_project_needs_finalise mark that triggers the
        gtd-side discipline tail.

        It validates the whole draft up-front and writes NOTHING if anything is rejected, then
        creates durable-first, recording each transaction (undoable via batch_undo). It does the
        STRUCTURAL RTM write only — the vault folder / context.md / progression fan-out are gtd-side,
        driven by the finalise mark. It does not execute AI work; `execute` only writes the durable
        RTM signal. Children are created directly under their parent (rtm.tasks.add with
        parent_task_id), inheriting the parent's list — no neutral staging list is involved.

        Identify the destination Area of Focus by frame.focus — a name (resolved to the parent of
        existing #project tasks; an ambiguous name returns a candidate list) or an area task id. The
        project is never created loose: an unknown focus is rejected.

        Args:
            frame: {life, focus, name, outcome}. `life` is one of work|personal|leanworking; `name`
                is the project title (required); `focus` selects the parent area; `outcome` is
                recorded in the INCEPTION note.
            items: [{id, type: action|waiting_for|calendar, text, classifiers:{context?, comms?,
                priority?, quick?}, chase?/calendar_date?/due?, start?, estimate?, deps:[in-draft
                ids], done?, execute?: now|later|quick, notes:[{title?/type?, text}]}]. `id` is the
                in-draft id deps reference (defaults to the array index); the dependency graph refines
                the creation/display order.
            notes: project-level notes [{title?/type?, text/body}] (e.g. the authored INCEPTION).

        Tag writes pass the strict-tag existence gate and use the closed canonical classifier→tag
        mapping; the project and every item carry #ai_conversation; an INCEPTION note is written to
        the project as an audit trail. NOTE: #ai_project_needs_finalise must exist in the RTM account
        (strict-tag mode) or every create is rejected — provision it once.

        Returns (on success): {"project_id", "url", "created": [...], "completed": [...],
            "progressed": {id: mode}, "applied": [...], "errors": [...], "message": "..."}.
        Returns (on ambiguity): {"candidates": [{id, name, list_id}, ...]} — re-call with frame.focus
            set to one id.
        Returns (on rejection — nothing written): {"created": [], "rejected": [...], "message": ...}.

        Errors: {"error": {"code": ..., "message": "<actionable prose>",
            "rtm_code": ...}} — branch on `code`, NEVER parse the message.
            Possible: strict_tag_rejected.
            A strict_tag_rejected carries rejected_tags / how_to_proceed
            under `error.details`.
            Per-item rejections are the FLAT `rejected[]` entries
            ({reason, detail}), not this nested envelope error.
        """
        client: RTMClient = await get_client()

        # Belt-and-braces: complex params may arrive as JSON strings (the Cowork serialisation). The
        # typed schemas + BeforeValidator already coerce this for pydantic-validated calls; this also
        # covers any caller that bypasses validation (e.g. direct/test invocation).
        frame_d: dict[str, Any] = coerce_json(frame) or {}
        items_l: list[dict[str, Any]] = coerce_json(items) or []
        notes_l: list[dict[str, Any]] = coerce_json(notes) or []

        def _date_of(d: dict[str, Any]) -> str | None:
            return d.get("calendar_date") or d.get("chase") or d.get("due")

        # ── Resolve the destination area (read-only) ──────────────────────
        result = await client.call("rtm.tasks.getList", filter="status:incomplete")
        parsed = parse_tasks_response(result)
        resolved = resolve_focus(parsed, str(frame_d.get("focus") or ""))
        if "focus" not in resolved:
            return build_response(data=resolved)  # error or candidates — nothing written
        area = resolved["focus"]
        area_id = area["id"]

        # ── Phase 1: validate (no writes) ─────────────────────────────────
        rejections = list(validate_create(frame_d, items_l)["rejections"])
        gate = await enforce_strict_tags(
            client, sorted(collect_create_tags(frame_d, items_l)), tool="gtd_create_project"
        )
        if gate:
            rejections.append(as_rejection(gate))
        if rejections:
            return build_response(
                data={
                    "created": [],
                    "rejected": rejections,
                    "message": "Create rejected; nothing was written.",
                }
            )

        # ── Order: thin deterministic graph over the in-draft deps ────────
        norm = [(item_id(it, i), it) for i, it in enumerate(items_l)]
        by_iid = {iid: it for iid, it in norm}
        graph_rows = [
            {
                "id": iid,
                "name": it.get("text") or "",
                "completed": 1 if it.get("done") else 0,
                "due": _date_of(it) or "",
                "start": it.get("start") or "",
                "estimate": it.get("estimate") or "",
                "tags": classifiers_to_tags(it.get("type"), it.get("classifiers")),
                "deps": [str(d) for d in (it.get("deps") or [])],
            }
            for iid, it in norm
        ]
        graph = build_graph({"project": {"id": "create"}}, graph_rows)
        blocked_by_iid = {
            rid: bool(j.get("blocked")) for rid, j in graph.get("judgement", {}).items()
        }
        order = [iid for iid in graph.get("order", []) if iid in by_iid]
        for iid, _ in norm:  # defensive: include any id the order omitted
            if iid not in order:
                order.append(iid)

        # ── Phase 2: apply (durable-first), recording transactions ────────
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        async def _write(
            method: str, label: str, _id: str | None = None, **kwargs: Any
        ) -> dict[str, Any] | None:
            try:
                res = await client.call(method, require_timeline=True, **kwargs)
                tx_id, undoable = get_transaction_info(res)
                if tx_id:
                    client.record_transaction(tx_id, method, undoable, label)
                applied.append({"op": label, "id": _id, "transaction_id": tx_id})
                return res
            except Exception as exc:  # batch resilience: record the failure and continue
                errors.append({"op": label, "id": _id, "error": str(exc)})
                return None

        idmap: dict[str, dict[str, Any]] = {}  # in-draft id → created task ids
        created: list[str] = []
        completed: list[str] = []
        progressed: dict[str, str] = {}

        # A. Project task — created under the area (inherits the area's list), then tagged.
        proj_res = await _write(
            "rtm.tasks.add",
            f"create-project:{(frame_d.get('name') or '')[:40]}",
            name=frame_d.get("name") or "",
            parse="0",
            parent_task_id=area_id,
        )
        proj = (parse_tasks_response(proj_res) or [{}])[0] if proj_res else {}
        new_project_id = proj.get("id")
        if not new_project_id:
            return build_response(
                data={
                    "created": [],
                    "errors": errors
                    or [{"op": "create-project", "error": "project id not returned"}],
                    "message": "Project task could not be created; nothing else was written.",
                },
                timeline_id=client.timeline_id,
            )
        proj_ids = {
            "task_id": new_project_id,
            "taskseries_id": proj.get("taskseries_id"),
            "list_id": proj.get("list_id"),
        }
        await _write(
            "rtm.tasks.setTags",
            "project:tags",
            new_project_id,
            tags=",".join(project_tags(frame_d.get("life"))),
            **proj_ids,
        )

        # B. Children — created under the project (dependency order), then tags/priority/dates/est.
        for iid in order:
            it = by_iid[iid]
            res = await _write(
                "rtm.tasks.add",
                f"add:{(it.get('text') or '')[:40]}",
                iid,
                name=it.get("text") or "",
                parse="0",
                parent_task_id=new_project_id,
            )
            if res is None:
                continue
            new = (parse_tasks_response(res) or [{}])[0]
            cid = new.get("id")
            if not cid:
                errors.append({"op": "add", "id": iid, "error": "created task id not returned"})
                continue
            nid = {
                "task_id": cid,
                "taskseries_id": new.get("taskseries_id"),
                "list_id": new.get("list_id"),
            }
            idmap[iid] = nid
            created.append(cid)
            await _write(
                "rtm.tasks.setTags",
                "add:tags",
                cid,
                tags=",".join(classifiers_to_tags(it.get("type"), it.get("classifiers"))),
                **nid,
            )
            pr = (it.get("classifiers") or {}).get("priority")
            if pr:
                await _write(
                    "rtm.tasks.setPriority",
                    "add:priority",
                    cid,
                    priority=priority_to_code(pr),
                    **nid,
                )
            dt = _date_of(it)
            if dt:
                await _write("rtm.tasks.setDueDate", "add:due", cid, due=dt, parse="1", **nid)
            if it.get("start"):
                await _write(
                    "rtm.tasks.setStartDate", "add:start", cid, start=it["start"], parse="1", **nid
                )
            if it.get("estimate"):
                await _write(
                    "rtm.tasks.setEstimate", "add:estimate", cid, estimate=it["estimate"], **nid
                )

        # C. DEPENDS-ON notes — second pass (all ids now known). Mapped from in-draft producer ids to
        #    the created RTM ids, in the exact body project_plan._extract_deps_and_files round-trips.
        for iid in order:
            it = by_iid[iid]
            if iid not in idmap:
                continue
            for dep in it.get("deps") or []:
                producer = idmap.get(str(dep))
                if not producer:
                    continue
                body = (
                    "DEPENDS-ON\nUpstream RTM IDs:\n"
                    f'  task_id: "{producer["task_id"]}"\n'
                    f'  list_id: "{producer.get("list_id") or ""}"\n'
                    "Status: active\n"
                )
                await _write(
                    "rtm.tasks.notes.add",
                    "dep-note",
                    iid,
                    note_title="DEPENDS-ON",
                    note_text=body,
                    **idmap[iid],
                )

        # D. Execute → durable progression signal (mirrors commit; fresh items carry no stale
        #    sibling to drop). Blocked items (open upstream) get #ai_deferred_pending_unblock.
        for iid in order:
            mode = by_iid[iid].get("execute")
            if not mode or iid not in idmap:
                continue
            progress_tag, _stale = execute_progress_tags(mode)
            tags = [progress_tag, AI_CONVERSATION]
            if blocked_by_iid.get(iid):
                tags.append(AI_DEFERRED)
            res = await _write(
                "rtm.tasks.addTags", f"execute:{mode}", iid, tags=",".join(tags), **idmap[iid]
            )
            if res is not None:  # only report progression that actually landed
                progressed[iid] = mode

        # E. Per-item notes.
        for iid in order:
            if iid not in idmap:
                continue
            for n in by_iid[iid].get("notes") or []:
                await _write(
                    "rtm.tasks.notes.add",
                    "note",
                    iid,
                    note_title=(n or {}).get("title") or (n or {}).get("type") or "",
                    note_text=(n or {}).get("text") or (n or {}).get("body") or "",
                    **idmap[iid],
                )

        # F. Already-done draft items → create-then-complete.
        for iid in order:
            if by_iid[iid].get("done") and iid in idmap:
                res = await _write("rtm.tasks.complete", "complete", iid, **idmap[iid])
                if res is not None:  # only report completions that actually landed
                    completed.append(idmap[iid]["task_id"])

        # G. Project-level notes from the payload.
        for n in notes_l:
            await _write(
                "rtm.tasks.notes.add",
                "project-note",
                new_project_id,
                note_title=(n or {}).get("title") or (n or {}).get("type") or "",
                note_text=(n or {}).get("text") or (n or {}).get("body") or "",
                **proj_ids,
            )

        # H. INCEPTION audit note on the project (the create analog of the COMMIT note).
        dep_count = sum(len(by_iid[i].get("deps") or []) for i in idmap)
        outcome = (frame_d.get("outcome") or "").strip()
        body = (
            f"INCEPTION (project-plan-canvas, created) — children:{len(created)} deps:{dep_count} "
            f"execute:{len(progressed)} completed:{len(completed)}; "
            f"{len(applied)} write(s), {len(errors)} error(s)."
            + (f"\nOutcome: {outcome}" if outcome else "")
            + " #ai_conversation"
        )
        await _write(
            "rtm.tasks.notes.add",
            "inception-note",
            new_project_id,
            note_title="INCEPTION",
            note_text=body,
            **proj_ids,
        )

        url = (
            build_task_url(proj_ids["list_id"], [area_id, new_project_id])
            if proj_ids.get("list_id")
            else ""
        )
        return build_response(
            data={
                "project_id": new_project_id,
                "url": url,
                "created": created,
                "completed": completed,
                "progressed": progressed,
                "applied": applied,
                "errors": errors,
                "message": (
                    f"Created project '{frame_d.get('name') or ''}' with {len(created)} item(s); "
                    f"{len(errors)} error(s)."
                ),
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=STAMP_TOKENS_OUTPUT)
    async def gtd_stamp_tokens(
        ctx: Context,
        project_id: Annotated[
            str | None,
            optional_string(
                "Repeating project's task id; omit to sweep every active repeating templated project."
            ),
        ] = None,
        dry_run: Annotated[
            bool, Field(description="Compute and return the plan WITHOUT writing anything.")
        ] = False,
    ) -> dict[str, Any]:
        """GTD — stamp durable template-child tokens on a repeating templated project's children so
            its dependencies survive recurrence (repeating-templated-project Wave B). A bounded,
            idempotent governed op: the gtd-side finalise engine can fire it per project, or Paul can
            run it once over the whole portfolio to switch the resolver on for the live recurring
            projects.

            A repeating templated project re-keys every occurrence's children with fresh task_ids, so a
            DEPENDS-ON dep or ORDER pin authored against a prior occurrence's raw id goes stale. The fix
            (already resolved read-side, v1.24.0): each child carries a TMPL-CHILD note holding an
            8-hex token (tmpl-child/1), and deps are authored in token-space. RTM copies a child's notes
            verbatim onto each new occurrence, so a token stamped ONCE propagates forward automatically —
            this is the one-time back-fill that writes the tokens the resolver then maps.

            Constrained write. One rtm.tasks.getList (status:incomplete) + a session-cached settings
            read for the token-note date; for each unstamped open child it writes a TMPL-CHILD note, and
            re-authors each active DEPENDS-ON note with the additive `Template-child-id:` line (the raw
            task_id stays as the fallback). Records each write's transaction (undoable via batch_undo).

            IDEMPOTENT — a child already carrying a token is skipped (never re-slugged; RTM has already
            propagated that identity), and a DEPENDS-ON already carrying the line is left alone, so a
            second run is a no-op. ONE-OFF projects are never stamped (no is_repeating → skipped_reason
            "not_repeating"). No tag is written (the TMPL-CHILD body is pure tmpl-child/1 JSON), so there
            is no strict-tag interaction and no activation hazard.

            Args:
                project_id: the repeating project's task id. Omit to sweep EVERY active repeating
                    templated project in the portfolio (incomplete #project, not #test, is_repeating).
                dry_run: compute and return the plan (what would be stamped) WITHOUT writing anything.

            Returns: {"projects": [{project_id, project_name, is_repeating, stamped: [{child_id, slug}],
                dep_lines: [{child_id, note_id, upstream_slug}], skipped_reason ("not_repeating"|null)}],
                "dry_run", "applied": [...], "errors": [...], "message": "..."}.
            Returns (on a bad explicit project_id): {"error": {"code": "project_not_found",
        "message": "<actionable prose>", "rtm_code": null}} — branch on `code`, never the prose.
        """
        client: RTMClient = await get_client()
        result = await client.call("rtm.tasks.getList", filter="status:incomplete")
        parsed = parse_tasks_response(result)
        by_id = {t["id"]: t for t in parsed}

        if project_id is not None:
            pid = str(project_id)
            proj = by_id.get(pid)
            if proj is None:
                return build_response(
                    data=build_error(
                        ErrorCode.PROJECT_NOT_FOUND,
                        f"Project {pid} not found among active tasks. Pass the task id of "
                        "an incomplete #project (from gtd_project_index).",
                    )
                )
            targets = [proj]
        else:
            targets = [
                t
                for t in parsed
                if _PROJECT_TAG in (t.get("tags") or [])
                and _TEST_TAG not in (t.get("tags") or [])
                and not t.get("completed")
                and t.get("is_repeating")
            ]

        stamp_date = local_stamp(await client.get_timezone())[:10]

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        async def _write(
            method: str, label: str, _id: str | None = None, **kwargs: Any
        ) -> dict[str, Any] | None:
            try:
                res = await client.call(method, require_timeline=True, **kwargs)
                tx_id, undoable = get_transaction_info(res)
                if tx_id:
                    client.record_transaction(tx_id, method, undoable, label)
                applied.append({"op": label, "id": _id, "transaction_id": tx_id})
                return res
            except Exception as exc:  # batch resilience: record the failure and continue
                errors.append({"op": label, "id": _id, "error": str(exc)})
                return None

        projects_out: list[dict[str, Any]] = []
        for proj in targets:
            pid = proj["id"]
            entry: dict[str, Any] = {
                "project_id": pid,
                "project_name": proj.get("name") or "",
                "is_repeating": bool(proj.get("is_repeating")),
                "stamped": [],
                "dep_lines": [],
                "skipped_reason": None,
            }
            if not proj.get("is_repeating"):
                entry["skipped_reason"] = "not_repeating"  # one-off projects are never stamped
                projects_out.append(entry)
                continue

            children = [
                t
                for t in parsed
                if str(t.get("parent_task_id") or "") == pid
                and not t.get("deleted")
                and not t.get("completed")
            ]
            view = [
                {
                    "id": c["id"],
                    "name": c.get("name") or "",
                    "notes": [
                        {"id": n.get("id"), "body": extract_note_body(n)}
                        for n in (c.get("notes") or [])
                    ],
                }
                for c in children
            ]
            plan = plan_backfill(view)
            entry["stamped"] = [
                {"child_id": cid, "slug": slug} for cid, slug in plan["assign"].items()
            ]
            entry["dep_lines"] = [
                {
                    "child_id": d["child_id"],
                    "note_id": d["note_id"],
                    "upstream_slug": d["upstream_slug"],
                }
                for d in plan["dep_edits"]
            ]

            if dry_run or (not plan["assign"] and not plan["dep_edits"]):
                projects_out.append(entry)  # nothing to write (preview, or idempotent no-op)
                continue

            for cid, slug in plan["assign"].items():
                t = by_id[cid]
                tc_title, tc_text = make_tmpl_child_note(slug, stamp_date)
                await _write(
                    "rtm.tasks.notes.add",
                    "tmpl-child-note",
                    cid,
                    note_title=tc_title,
                    note_text=tc_text,
                    task_id=t["id"],
                    taskseries_id=t.get("taskseries_id"),
                    list_id=t.get("list_id"),
                )
            for d in plan["dep_edits"]:
                await _write(
                    "rtm.tasks.notes.edit",
                    "dep-token-line",
                    d["child_id"],
                    note_id=d["note_id"],
                    note_title=d["note_title"],
                    note_text=d["note_text"],
                )
            # Audit note on the project (the #ai_conversation marker rides the body, keeping the
            # TMPL-CHILD note bodies pure tmpl-child/1 JSON). Only written when something changed.
            audit = (
                f"TMPL-STAMP (repeating-templated-project) — stamped:{len(plan['assign'])} "
                f"dep-lines:{len(plan['dep_edits'])}. #ai_conversation"
            )
            await _write(
                "rtm.tasks.notes.add",
                "stamp-note",
                pid,
                note_title="TMPL-STAMP",
                note_text=audit,
                task_id=proj["id"],
                taskseries_id=proj.get("taskseries_id"),
                list_id=proj.get("list_id"),
            )
            projects_out.append(entry)

        verb = "Would stamp" if dry_run else "Stamped"
        return build_response(
            data={
                "projects": projects_out,
                "dry_run": dry_run,
                "applied": applied,
                "errors": errors,
                "message": (
                    f"{verb} tokens across {len(projects_out)} project(s); "
                    f"{len(applied)} write(s), {len(errors)} error(s)."
                ),
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=CHAT_POST_OUTPUT)
    async def gtd_chat_post(
        ctx: Context,
        task_id: Annotated[
            str,
            Field(
                description="Target task id (a project or item, from gtd_project_index/list_tasks)."
            ),
        ],
        text: Annotated[str, Field(description="The message body (plain; markdown allowed).")],
        role: Annotated[
            str,
            Field(
                description="'me' (Paul's turn, default) or 'ai' (the worker's reply).",
                json_schema_extra=_ROLE_ENUM,
            ),
        ] = "me",
        scope: Annotated[
            str | None,
            optional_string(
                "Optional short display label for the title; defaults to the task name."
            ),
        ] = None,
        mode: Annotated[
            str | None,
            optional_string(
                "Posture for a 'me' turn — 'discuss' | 'act' (ignored for 'ai' turns).",
                **_MODE_ENUM,
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — post one turn of the in-board AI conversation surface (the CHAT note class) to a
            task and manage the worker's drain signal in ONE signed call. The board's governed write
            path for the project-plan-canvas chat: Paul types an instruction (role "me"); a headless
            worker session replies (role "ai"). They converse through RTM notes — the system of record —
            never a live session.

            The turn is one note on the target task, titled `YYYY-MM-DD HH:MM — CHAT — <role> — <scope>`
            (localised to the account timezone), body = the message text. It is governed: a "me" turn
            also stamps #ai_chat_requested (the worker's durable work-list signal) + #ai_chat (has-a-
            thread marker); an "ai" turn removes #ai_chat_requested (the turn is answered) and leaves
            #ai_chat. Pass only the task_id you have — taskseries_id + list_id are resolved internally
            from one rtm.tasks.getList. Records each write's transaction (undoable via batch_undo).

            Args:
                task_id: the target task id (a project or an item — from gtd_project_index / list_tasks).
                text: the message body (plain; markdown allowed).
                role: "me" (Paul's turn, default) or "ai" (the worker's reply).
                scope: optional short display label for the title; defaults to the task name.
                mode: optional posture for a "me" turn — "discuss" | "act" — recorded as a body footer
                    so the worker knows the requested posture (ignored for "ai" turns).

            The #ai_chat_requested / #ai_chat tag writes pass the strict-tag existence gate — both must
            exist in the RTM account (provision once, account-side); a missing tag yields the guided
            error with NOTHING written. Tag removal ("ai" turn) is never gated.

            Returns (on success): {"note": {id, title, created}, "task_id", "role", "tag_changes": [...],
                "errors": [...]} with the note's transaction_id for undo.
            Returns (on bad input / strict-tag rejection — nothing written): {"error": {"code":
        "invalid_input" | "task_not_found" | "conversation_read_only" | "strict_tag_rejected"
        | "write_failed",
        "message": "<actionable prose>", "rtm_code": null, "details": {...}}}. The strict-tag
        gate's recovery material (rejected_tags / how_to_proceed / strict_tag_mode) is under
        `details`. Branch on `code`, never the prose.
        """
        client: RTMClient = await get_client()

        if role not in VALID_ROLES:
            return build_response(
                data=build_error(
                    ErrorCode.INVALID_INPUT,
                    f"role must be one of {sorted(VALID_ROLES)}; got {role!r}.",
                )
            )
        if mode is not None and mode not in VALID_MODES:
            return build_response(
                data=build_error(
                    ErrorCode.INVALID_INPUT,
                    f"mode must be one of {sorted(VALID_MODES)} or omitted; got {mode!r}.",
                )
            )
        eff_mode = mode if role == "me" else None

        # Resolve the task by id from one read (active items — chat POSTS live on incomplete work:
        # the worker only drains #ai_chat_requested on incomplete items, so a me-turn on a completed
        # task would never get a reply). gtd_chat_thread reads completed too, but posting doesn't.
        result = await client.call("rtm.tasks.getList", filter="status:incomplete")
        parsed = parse_tasks_response(result)
        task = next((t for t in parsed if t["id"] == str(task_id)), None)
        if task is None:
            # Distinguish "completed (read-only)" from "genuinely missing" with a second read — a
            # clearer error than the generic not-found. Read-only; nothing is written on either miss.
            done = parse_tasks_response(
                await client.call("rtm.tasks.getList", filter="status:completed")
            )
            if any(t["id"] == str(task_id) for t in done):
                return build_response(
                    data=build_error(
                        ErrorCode.CONVERSATION_READ_ONLY,
                        f"Task {task_id} is completed — its conversation is read-only "
                        "(view it with gtd_chat_thread). Reopen the task to continue the thread.",
                    )
                )
            return build_response(
                data=build_error(
                    ErrorCode.TASK_NOT_FOUND,
                    f"Task {task_id} not found among active tasks. Pass the task id of an "
                    "incomplete project or item (from gtd_project_index or list_tasks).",
                )
            )
        ids = {
            "task_id": task["id"],
            "taskseries_id": task["taskseries_id"],
            "list_id": task["list_id"],
        }
        scope_label = scope or task.get("name") or ""

        # Strict-tag existence gate — only the "me" turn ADDS tags; reject before any write.
        if role == "me":
            gate = await enforce_strict_tags(
                client, [AI_CHAT_REQUESTED, AI_CHAT], tool="gtd_chat_post"
            )
            if gate:
                return build_response(data=gate)

        tz = await client.get_timezone()
        title = format_chat_title(local_stamp(tz), role, scope_label)
        body = append_mode_footer(text, eff_mode)

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        async def _write(method: str, label: str, **kwargs: Any) -> dict[str, Any] | None:
            try:
                res = await client.call(method, require_timeline=True, **kwargs)
                tx_id, undoable = get_transaction_info(res)
                if tx_id:
                    client.record_transaction(tx_id, method, undoable, label)
                applied.append({"op": label, "transaction_id": tx_id})
                return res
            except Exception as exc:  # batch resilience: record the failure and continue
                errors.append({"op": label, "error": str(exc)})
                return None

        note_res = await _write(
            "rtm.tasks.notes.add", "chat-note", note_title=title, note_text=body, **ids
        )
        if note_res is None:
            # The signal management is predicated on the turn existing: a drain
            # signal with no CHAT note would summon the worker to an empty
            # thread (and an `ai` removal would mark an unanswered turn as
            # answered). Surface the failure instead of half-applying.
            return build_response(
                data={
                    **build_error(
                        ErrorCode.WRITE_FAILED,
                        "Chat note write failed — no signal tags were changed. "
                        "See errors for the underlying failure; retry the post.",
                    ),
                    "task_id": ids["task_id"],
                    "role": role,
                    "errors": errors,
                }
            )
        note = note_res.get("note", {})

        if role == "me":
            await _write(
                "rtm.tasks.addTags", "chat-requested", tags=f"{AI_CHAT_REQUESTED},{AI_CHAT}", **ids
            )
            tag_changes = [f"+{AI_CHAT_REQUESTED}", f"+{AI_CHAT}"]
        else:
            await _write("rtm.tasks.removeTags", "chat-answered", tags=AI_CHAT_REQUESTED, **ids)
            tag_changes = [f"-{AI_CHAT_REQUESTED}"]

        note_tx, note_undoable = get_transaction_info(note_res or {})
        return build_response(
            data={
                "note": {
                    "id": note.get("id"),
                    "title": note.get("title") or title,
                    "created": note.get("created"),
                },
                "task_id": ids["task_id"],
                "role": role,
                "tag_changes": tag_changes,
                "errors": errors,
            },
            transaction_id=note_tx,
            transaction_undoable=note_undoable if note_tx else None,
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=CHAT_THREAD_OUTPUT)
    async def gtd_chat_thread(
        ctx: Context,
        task_id: Annotated[
            str, Field(description="Target task id (a project or item, incomplete or completed).")
        ],
        since: Annotated[
            str | None,
            optional_string(
                "Optional ISO-8601 timestamp — return only turns created strictly after it."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — return just the CHAT turns for a task: the cheap poll path for the in-board AI
            conversation surface (vs re-reading the whole canvas). The read-sibling of gtd_chat_post.

            Read-only. One signed rtm.tasks.getList (spanning incomplete AND completed tasks); no write,
            no timeline, no settings read. Resolves the task by id, parses its CHAT notes (non-CHAT notes
            excluded) into turns oldest-first, and reports whether the worker's drain signal is raised.
            Completed items are included so a prior conversation stays viewable after the task is done
            (CHAT notes persist); `requested` is naturally False for a completed task (no pending worker),
            so the board renders the history read-only without a "thinking…" state.

            Each turn carries server-derived attachments (always present, [] when none):
            - files: [{path, label, note_id}] — artefacts filed by the worker, parsed from OUTPUT
              notes' "FILING: <vault-relative path> (+ .meta.md)" lines (single-line and
              labelled-continuation forms) and time-correlated to the ai turn that reported them (an
              OUTPUT note attaches to the earliest ai turn created at-or-after it; an OUTPUT note after
              the last ai turn attaches to nothing). For an ITEM target the scan covers the task's own
              notes only. For a #project target it additionally covers the project's DESCENDANT tasks
              (children + grandchildren, completed included — a project's artefacts are filed against
              its child actions), and each descendant-filed entry carries two extra provenance fields:
              `item_id`/`item_name` (the descendant that filed it). The gate is the #project tag, not
              subtask presence. `path` is the vault-relative path VERBATIM — it compares equal to a
              FILED: trailer echo in the turn text, so a client should prefer files[] and suppress its
              own FILED: parse when the key is present. `label` is the OUTPUT note's title summary;
              `note_id` the OUTPUT note (provenance). Only ai turns carry files.
            - links: [{url, label}] — "LINK: <url> — <label>" trailer lines parsed from the turn's own
              text (em/en-dash or spaced-hyphen separator; no separator → label ""). The trailer lines
              remain IN `text` (clients strip them when rendering).

            Args:
                task_id: the target task id (a project or an item, incomplete or completed).
                since: optional ISO-8601 timestamp — return only turns created strictly after it
                    (incremental poll; attachment correlation still runs over the full thread).

            Returns (on success): {"task_id", "turns": [{note_id, role, scope, mode?, text, created,
                files: [{path, label, note_id}], links: [{url, label}]}...], "requested": bool} — turns
                oldest-first; `requested` is whether #ai_chat_requested is set (lets the board show a
                "thinking…" state without a second call). `created` is RTM's value (UTC); the localised
                display stamp lives in the note title.
            Returns (on miss): {"error": {"code": "task_not_found", "message":
        "<actionable prose>", "rtm_code": null}} — branch on `code`, never the prose.
        """
        client: RTMClient = await get_client()
        result = await client.call(
            "rtm.tasks.getList", filter="status:incomplete OR status:completed"
        )
        parsed = parse_tasks_response(result)
        task = next((t for t in parsed if t["id"] == str(task_id)), None)
        if task is None:
            return build_response(
                data=build_error(
                    ErrorCode.TASK_NOT_FOUND,
                    f"Task {task_id} not found. Pass the task id of a project or item "
                    "(incomplete or completed) — from gtd_project_index or list_tasks.",
                )
            )

        tags = {normalize_tag(t) for t in (task.get("tags") or [])}
        # Project scope (stage 2b): a project's artefacts are filed against its child actions, so
        # the FILING scan covers the descendant tree — same one-call read, the broad getList above
        # already carries the children. The gate is the #project tag, not subtask presence.
        descendants = project_descendants(parsed, task["id"]) if _PROJECT_TAG in tags else None
        turns = build_thread(task.get("notes") or [], since=since, descendants=descendants)
        requested = AI_CHAT_REQUESTED in tags
        return build_response(data={"task_id": task["id"], "turns": turns, "requested": requested})

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=CHAT_INFLIGHT_OUTPUT)
    async def gtd_chat_inflight(ctx: Context) -> dict[str, Any]:
        """GTD — the conversation cockpit's cross-project live band: every incomplete item with an
        open CHAT thread (#ai_chat), across all lists/projects, in one read. The per-project canvas
        only sees its own project; this is the "all my agents working right now" view.

        Read-only. One signed rtm.tasks.getList (status:incomplete); no write, no timeline, no
        settings read (call surface exactly ["rtm.tasks.getList"]). The broad incomplete read — not a
        tag-filtered one — is deliberate: each item's enclosing project must be resolved by walking
        ancestors, and the ancestor project tasks don't themselves carry #ai_chat, so they must be in
        the result set. Vault-free; reads #ai_chat / #ai_chat_requested / #ai_output_review_needed
        (all account-provisioned) — writes nothing, introduces no tag.

        Selection: incomplete, #ai_chat, NOT #test. Each item's status derives from its tags
        (#ai_chat_requested → in_flight; else #ai_output_review_needed → awaiting_review; else open);
        scope is "project" when the task is itself a #project, else "item"; project_id/project_name
        are the nearest #project ancestor (the task itself when it is a project).

        Returns (on success): {"items": [{task_id, name, scope ("item"|"project"), status
            ("in_flight"|"awaiting_review"|"open"), project_id, project_name, last_activity
            (most-recent CHAT note created, UTC, or "")}], "count": <int>}, sorted by status →
            most-recent activity → name. Empty portfolio → {"items": [], "count": 0}.
        """
        client: RTMClient = await get_client()
        result = await client.call("rtm.tasks.getList", filter="status:incomplete")
        return build_response(data=build_inflight(parse_tasks_response(result)))

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=SET_REDACTION_OUTPUT)
    async def gtd_set_redaction(
        ctx: Context,
        task_id: Annotated[
            str,
            Field(description="Target task id (a #project or an item, incomplete or completed)."),
        ],
        redacted: Annotated[
            bool, Field(description="True to add #redacted (draw the curtain); False to remove it.")
        ],
    ) -> dict[str, Any]:
        """GTD — mark or unmark a task's #redacted viewing curtain: the single governed write surface
            the project-plan-canvas is given for redaction (the sandboxed board may not call the bare
            add_task_tags / remove_task_tags primitives). Redaction renders the project/item as a locked
            placeholder — a curtain for casual over-the-shoulder privacy, not a server-side vault.

            Constrained write. Resolves the task's full triple by id from ONE rtm.tasks.getList (spanning
            incomplete AND completed — redaction is a viewing-state change that applies to done items too),
            then applies exactly one tag write and records its transaction (undoable via undo/batch_undo).
            Nothing is written on a miss or a strict-tag rejection.

            Identify the task by task_id (required) — the board always has it from gtd_project_index /
            gtd_project_canvas, so no fuzzy name resolution is used.

            Args:
                task_id: the target task id (a #project or an item).
                redacted: True to add #redacted (draw the curtain); False to remove it (lift the curtain).

            The add path passes the strict-tag existence gate — #redacted must exist in the RTM account
            (it is provisioned); a missing tag yields the guided error with NOTHING written. Removal is
            never gated (it reduces entropy).

            Returns (on success): {"task_id", "redacted"} with the transaction_id for undo.
            Returns (on miss / strict-tag rejection — nothing written): {"error": {"code":
        "task_not_found" | "strict_tag_rejected", "message": "<actionable prose>",
        "rtm_code": null, "details": {...}}} — the strict-tag gate's recovery material rides
        under `details`. Branch on `code`, never the prose.
        """
        client: RTMClient = await get_client()

        # Resolve the task's triple from one read — span incomplete OR completed so redaction works on
        # done items too. No timeline; nothing is written on a miss.
        result = await client.call(
            "rtm.tasks.getList", filter="status:incomplete OR status:completed"
        )
        parsed = parse_tasks_response(result)
        task = next((t for t in parsed if t["id"] == str(task_id)), None)
        if task is None:
            return build_response(
                data=build_error(
                    ErrorCode.TASK_NOT_FOUND,
                    f"Task {task_id} not found. Pass the task id of a project or item "
                    "(from gtd_project_index or gtd_project_canvas).",
                )
            )
        ids = {
            "task_id": task["id"],
            "taskseries_id": task["taskseries_id"],
            "list_id": task["list_id"],
        }

        if redacted:
            gate = await enforce_strict_tags(client, [REDACTED_TAG], tool="gtd_set_redaction")
            if gate:
                return build_response(data=gate)  # nothing written
            tag_method = "rtm.tasks.addTags"
        else:
            tag_method = "rtm.tasks.removeTags"
        write_res = await client.call(tag_method, require_timeline=True, tags=REDACTED_TAG, **ids)

        # Record the tag-write transaction first (chronological — before the audit note below).
        tag_tx, tag_undoable = get_transaction_info(write_res)
        if tag_tx:
            client.record_transaction(tag_tx, tag_method, tag_undoable, "gtd_set_redaction")

        # One-line audit note recording the toggle. It carries NO #ai_conversation marker — this is a
        # user viewing-state change, not an AI write. Best-effort (a note failure never undoes the tag
        # write) and records its own transaction, so batch_undo reverts it alongside the tag change.
        audit = "REDACTION — curtain drawn" if redacted else "REDACTION — curtain lifted"
        try:
            note_res = await client.call(
                "rtm.tasks.notes.add",
                require_timeline=True,
                note_title="REDACTION",
                note_text=audit,
                **ids,
            )
            note_tx, note_undoable = get_transaction_info(note_res)
            if note_tx:
                client.record_transaction(
                    note_tx, "rtm.tasks.notes.add", note_undoable, "gtd_set_redaction:audit"
                )
        except Exception:  # audit note is best-effort; the tag write is the durable state
            pass

        return build_response(
            data={"task_id": ids["task_id"], "redacted": redacted},
            transaction_id=tag_tx,
            transaction_undoable=tag_undoable if tag_tx else None,
            timeline_id=client.timeline_id if tag_tx else None,
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=ENGAGE_SEED_OUTPUT)
    async def gtd_engage_seed(ctx: Context) -> dict[str, Any]:
        """GTD — return the overdue + soft-parked set for the engage renegotiation sweep: every dated
        item at/after its date, each with server-derived flags. The read ground truth both engage
        surfaces (the chat funnel and the live board, incl. its advisory askClaude) reason over; the
        read-sibling of gtd_apply_engage_commit. Model: gtd_project_index (same read-only discipline,
        same flag-emission style).

        Read-only. ONE signed rtm.tasks.getList (status:incomplete) plus a session-cached
        rtm.settings.getList for the account timezone; no write, no timeline. Flags are vault-free —
        `blocked` is the THIN plan-graph judgement (an open DEPENDS-ON upstream within the item's own
        project, the SAME judgement gtd_project_index emits), never the AI-Memory overlay.
        `has_deadline` is the RTM has_due_time primitive (a due carrying a specific TIME is genuinely
        day/time-specific — the GTD hard landscape; a date-only due is a soft parked-date). Dates are
        localised to the account timezone (RTM returns UTC).

        Selection (the overdue set): incomplete items with a due date on-or-before today (overdue OR
        due today), NOT #test, NOT #someday (a #someday item is deliberately parked, not overdue). All
        kinds carrying a date are included — action, waiting-for, calendar entry, and a #project task
        with its own due.

        Redaction is CURTAIN-NOT-VAULT (CLAUDE.md § Redaction surface): each row carries a `redacted`
        flag (own #redacted OR a cascade from a redacted #project/#focus ancestor) but the server
        NEVER nulls or withholds any field on it — a shielded row flows its full name/flags exactly
        like an unshielded one. Enforcement (the locked placeholder, funnel exclusion, the askClaude
        PII shield) is 100% client-side.

        Returns: {items: [{id, name, kind ("action"|"waiting_for"|"calendar_entry"|"project"),
            has_deadline (bool — RTM has_due_time), blocked (bool — thin plan-graph), postponed (int —
            RTM postpone count, the bump-fatigue signal), suggested (the deterministic pre-triage
            verdict — keep for a deadline, resurface for a blocked item, nudge for a waiting-for,
            next_actions for a soft action), redacted (bool — the viewing-curtain flag), due
            (YYYY-MM-DD localised)}], current_date (YYYY-MM-DD, account tz), count}, items sorted by
            due → name.
        """
        client: RTMClient = await get_client()
        result = await client.call("rtm.tasks.getList", filter="status:incomplete")
        parsed = parse_tasks_response(result)
        tz = await client.get_timezone()
        try:
            today = datetime.now(ZoneInfo(tz)).date().isoformat() if tz else _utc_today()
        except Exception:  # unknown/invalid tz → UTC calendar date (never raises)
            today = _utc_today()
        return build_response(data=build_engage_seed(parsed, today=today, timezone=tz))

    # Per-verdict tag additions written on the ITEM (grammar § 4). Date-writing verdicts additionally
    # carry #ai_conversation (added in the apply loop); do_now/keep write no tag; drop deletes.
    _ENGAGE_ITEM_TAGS = {
        "someday": [SOMEDAY_TAG, AI_CONVERSATION],
        "to_calendar": [CALENDAR_ENTRY_TAG, AI_CONVERSATION],
        "draft": [AI_PROGRESS, AI_CONVERSATION],
    }

    @mcp.tool(annotations=DESTRUCTIVE_WRITE_ANNOTATIONS, output_schema=ENGAGE_COMMIT_OUTPUT)
    async def gtd_apply_engage_commit(
        ctx: Context,
        items: Annotated[
            list[dict[str, Any]] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_obj_array_schema(
                    "[{id, verdict, date_phrase?, note?}] — the renegotiation verdicts to apply "
                    "(re-validated server-side; nothing written if any is rejected).",
                    item_schema=_ENGAGE_ITEM_SCHEMA,
                )
            ),
        ] = None,
        confirm_destructive: Annotated[
            bool,
            Field(
                description="Must be True for any 'drop' verdict (a soft-delete); else the batch is rejected."
            ),
        ] = False,
    ) -> dict[str, Any]:
        """GTD — the single governed write surface for an engage renegotiation-sweep commit: gtd's
        Anti-Corruption Layer over an untrusted client (the board's askClaude is advisory — it stages
        intent but never authorises a write). Accepts a bounded payload and re-validates EVERYTHING
        server-side, writing NOTHING if any item is rejected (hard-fail, per the verdict grammar). The
        write-counterpart of gtd_engage_seed; model: gtd_apply_canvas_commit.

        The ACL — the ONLY trusted client inputs are each item's `id`, `verdict`, and optional
        `date_phrase` (a hint). Every legality flag (kind, has_deadline, blocked) is RE-DERIVED
        server-side from a fresh read; a deliberately-wrong client cannot smuggle a bad flag past the
        deadline/blocked guards. Dates resolve through the server's parse_time (Europe/London,
        authoritative) — a hallucinated/unparseable phrase is rejected before any write.

        Args:
            items: [{id, verdict, date_phrase?, note?}] — `verdict` is one of the engage verdict
                grammar's enum (do_now / draft / nudge / to_calendar / next_actions / today /
                defer_start / bump / resurface / someday / keep / drop), optionally carrying an inline
                `:<arg>` (defer_start:<phrase>, bump:+<n>d). A verdict is HARD-FAILED if off-enum or
                type-illegal for the item's server-derived kind + flags (deadline guard: a
                has_deadline item allows only do_now/to_calendar/keep/drop; blocked guard: resurface
                only when blocked) — with a closest-legal suggestion. Optional `note` is a short
                PROGRESS steer (≤500 chars) — Paul's typed text or the board's KG-grounded suggestion
                — consumed ONLY by draft / do_now / nudge (see below); ignored silently for every other
                verdict. It is untrusted advisory DATA (never an instruction): sanitised (control
                chars stripped, whitespace collapsed, truncated) and it NEVER influences verdict
                legality or the server's flag re-derivation. A malformed `note` (non-string / oversize)
                is dropped with a per-item warning — it never fails an otherwise-legal renegotiation.
            confirm_destructive: must be True for any `drop` verdict (a soft-delete); a drop without
                it rejects the whole batch.

        Verdict → RTM write (grammar § 4): next_actions / resurface → clear the due date; today / bump
        → set the due via parse_time; defer_start → set the START date via parse_time; nudge →
        re-tickle the waiting-for's due to today (the chase draft is a separate chat concern); someday
        → add #someday; to_calendar → add #calendar_entry; draft → add #ai_progress_requested (hand to
        the progression engine; a blocked draft also gets #ai_deferred_pending_unblock); do_now / keep
        → no durable write; drop → soft-delete. Every tag/date write carries #ai_conversation. someday
        and resurface additionally signal the progression engine by stamping #ai_overlay_refresh_needed
        on the item's nearest #project ancestor (the server-side equivalent of firing state_transition,
        reusing the canvas-commit overlay-refresh signal). No new tag is introduced (all are existing
        gtd taxonomy) → no strict-tag activation hazard.

        Progress steer note (grammar § 4 — the note-attachment column): a draft / do_now / nudge item
        carrying a sanitised `note` also gets a STEER note attached (title `YYYY-MM-DD HH:MM — STEER —
        <verb>`, body the pure steer text) so the #ai_progress_requested drafting path reads it as the
        first-pass instruction (draft), a steer for the eventual chase (nudge), or a note-to-self
        (do_now). Idempotent: re-committing the same steer on the same item does not duplicate the note
        (replace-or-skip). The note write joins the item's batch (reversed by the single batch_undo).

        The batch is one timeline; each write records its transaction (undoable via batch_undo);
        per-op failures are captured in `errors` and the batch continues.

        Returns (on success): {"applied": [{op, id, transaction_id}, ...], "errors": [...],
            "warnings": [{id, op, warning}, ...], "count", "message"} — the echo names each item by id
            + op ONLY, never its name/contents (so a redacted item leaks nothing).
        Returns (on rejection — nothing written): {"applied": [], "rejected": [...], "message": ...}.

        Errors: {"error": {"code": ..., "message": "<actionable prose>",
            "rtm_code": ...}} — branch on `code`, NEVER parse the message.
            Possible: bad_date, destructive_unconfirmed, strict_tag_rejected, task_not_found.
            A strict_tag_rejected carries rejected_tags / how_to_proceed
            under `error.details`.
            Per-item rejections are the FLAT `rejected[]` entries
            ({reason, detail}), not this nested envelope error.
        """
        client: RTMClient = await get_client()
        items = coerce_json(items) or []
        if not items:
            return build_response(
                data={"applied": [], "rejected": [], "count": 0, "message": "No items supplied."}
            )

        result = await client.call(
            "rtm.tasks.getList", filter="status:incomplete OR status:completed"
        )
        parsed = parse_tasks_response(result)
        by_id = {t["id"]: t for t in parsed}
        tz = await client.get_timezone()

        # ── Phase 1: validate (no writes). Re-derive every flag server-side (the ACL). ──
        blocked_map = engage_blocked_map(parsed, tz)
        rejections: list[dict[str, Any]] = []
        val_items: list[dict[str, Any]] = []
        for it in items:
            rid = str(it.get("id") or "")
            verdict = it.get("verdict") or ""
            t = by_id.get(rid)
            if t is None:
                rejections.append(
                    {"id": rid, "verdict": verdict, "reason": ErrorCode.TASK_NOT_FOUND.value}
                )
                continue
            tags = t.get("tags") or []
            val_items.append(
                {
                    "id": rid,
                    "verdict": verdict,
                    "kind": engage_kind(tags),
                    "has_deadline": bool(t.get("has_due_time")),
                    "blocked": bool(blocked_map.get(rid)),
                    "date_phrase": it.get("date_phrase"),
                    "note": it.get("note"),  # untrusted PROGRESS steer; sanitised at apply time
                }
            )

        report = validate_engage(val_items)
        for r in report["errors"]:
            rejections.append(
                {
                    "id": r["id"],
                    "verdict": r["verdict"],
                    "reason": r["reason"],
                    "suggestion": r["suggestion"],
                }
            )

        # Destructive gate: any drop needs confirm_destructive.
        if not confirm_destructive:
            for v in val_items:
                if base_verdict(v["verdict"]) == "drop":
                    rejections.append(
                        {
                            "id": v["id"],
                            "verdict": v["verdict"],
                            "reason": ErrorCode.DESTRUCTIVE_UNCONFIRMED.value,
                        }
                    )

        # Strict-tag existence gate over the tags the batch would write (all existing gtd tags).
        gate = await enforce_strict_tags(
            client, sorted(collect_engage_tags(val_items)), tool="gtd_apply_engage_commit"
        )
        if gate:
            rejections.append(as_rejection(gate))

        if rejections:
            return build_response(
                data={
                    "applied": [],
                    "rejected": rejections,
                    "count": len(items),
                    "message": "Engage commit rejected; nothing was written.",
                }
            )

        # Date resolution through parse_time (authoritative) — reached only when every verdict is
        # legal. A bad/hallucinated phrase rejects the whole batch (the ACL), still writing nothing.
        resolved_dates: dict[str, str] = {}
        for v in val_items:
            verb = base_verdict(v["verdict"])
            phrase = date_phrase_for(verb, verdict_arg(v["verdict"]), v.get("date_phrase"))
            if verb == "nudge":  # re-tickle the waiting-for's due to today
                phrase = "today"
            if phrase is None:
                continue
            parse_params: dict[str, Any] = {"text": phrase}
            if tz:
                parse_params["timezone"] = tz
            try:
                pres = await client.call("rtm.time.parse", **parse_params)
                iso = ((pres.get("time") or {}) if isinstance(pres, dict) else {}).get("$t")
            except Exception:
                iso = None
            if not iso:
                rejections.append(
                    {
                        "id": v["id"],
                        "verdict": v["verdict"],
                        "reason": ErrorCode.BAD_DATE.value,
                        "phrase": phrase,
                    }
                )
            else:
                resolved_dates[v["id"]] = iso

        if rejections:
            return build_response(
                data={
                    "applied": [],
                    "rejected": rejections,
                    "count": len(items),
                    "message": "Engage commit rejected; nothing was written.",
                }
            )

        # ── Phase 2: apply (durable-first), recording transactions ──
        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        refresh_projects: set[str] = set()

        async def _write(
            method: str, label: str, _id: str | None = None, **kwargs: Any
        ) -> dict[str, Any] | None:
            try:
                res = await client.call(method, require_timeline=True, **kwargs)
                tx_id, undoable = get_transaction_info(res)
                if tx_id:
                    client.record_transaction(tx_id, method, undoable, label)
                applied.append({"op": label, "id": _id, "transaction_id": tx_id})
                return res
            except Exception as exc:  # batch resilience
                errors.append({"op": label, "id": _id, "error": str(exc)})
                return None

        def _ids(rid: str) -> dict[str, Any]:
            t = by_id.get(rid, {})
            return {
                "task_id": t.get("id"),
                "taskseries_id": t.get("taskseries_id"),
                "list_id": t.get("list_id"),
            }

        def _nearest_project(rid: str) -> str | None:
            cur = rid
            seen: set[str] = set()
            for _ in range(10):
                if not cur or cur in seen:
                    break
                seen.add(cur)
                t = by_id.get(cur)
                if not t:
                    break
                if _PROJECT_TAG in (t.get("tags") or []):
                    return cur
                cur = str(t.get("parent_task_id") or "")
            return None

        async def _attach_steer(rid: str, verb: str, raw_note: Any, ids: dict[str, Any]) -> None:
            """Attach the sanitised PROGRESS steer as a STEER note (draft/do_now/nudge only). A
            malformed note is dropped with a per-item warning; the verdict write stands. Idempotent:
            an identical STEER note already on the item is left as-is (replace-or-skip)."""
            if verb not in STEER_VERBS:
                return
            clean, warning = sanitize_steer(raw_note)
            if warning:
                warnings.append({"id": rid, "op": f"engage:{verb}", "warning": warning})
            if not clean:
                return
            for n in by_id.get(rid, {}).get("notes") or []:
                if steer_note_text(extract_note_body(n)) == clean:
                    applied.append(
                        {
                            "op": f"engage:{verb}:steer-note (skipped, duplicate)",
                            "id": rid,
                            "transaction_id": None,
                        }
                    )
                    return
            title, text = make_steer_note(local_stamp(tz), verb, clean)
            await _write(
                "rtm.tasks.notes.add",
                f"engage:{verb}:steer-note",
                rid,
                note_title=title,
                note_text=text,
                **ids,
            )

        for v in val_items:
            rid = v["id"]
            verb = base_verdict(v["verdict"])
            ids = _ids(rid)

            if verb in ("keep", "do_now"):
                applied.append({"op": f"engage:{verb}", "id": rid, "transaction_id": None})
                await _attach_steer(rid, verb, v.get("note"), ids)  # do_now → note-to-self
                continue
            if verb == "drop":
                await _write("rtm.tasks.delete", "engage:drop (soft-delete)", rid, **ids)
                continue

            # Date writes (grammar § 4).
            if verb in ("next_actions", "resurface"):
                await _write(
                    "rtm.tasks.setDueDate",
                    f"engage:{verb}:clear-due",
                    rid,
                    due="",
                    parse="0",
                    **ids,
                )
            elif verb in ("today", "bump", "nudge"):
                await _write(
                    "rtm.tasks.setDueDate",
                    f"engage:{verb}",
                    rid,
                    due=resolved_dates.get(rid, ""),
                    parse="0",
                    **ids,
                )
            elif verb == "defer_start":
                await _write(
                    "rtm.tasks.setStartDate",
                    "engage:defer_start",
                    rid,
                    start=resolved_dates.get(rid, ""),
                    parse="0",
                    **ids,
                )

            # Tag writes. Verbs with a durable tag payload carry it (+#ai_conversation); the pure date
            # verbs still stamp #ai_conversation so every write is marked.
            add_tags = list(_ENGAGE_ITEM_TAGS.get(verb, [AI_CONVERSATION]))
            if verb == "draft" and blocked_map.get(rid):
                add_tags.append(AI_DEFERRED)
            await _write(
                "rtm.tasks.addTags", f"engage:{verb}:tags", rid, tags=",".join(add_tags), **ids
            )

            # PROGRESS steer note (draft/nudge among the fall-through verbs; do_now handled above).
            await _attach_steer(rid, verb, v.get("note"), ids)

            # Progression signal (someday/resurface) — stamp the overlay-refresh mark on the item's
            # nearest #project ancestor so the gtd-side finalise engine recomputes the plan-graph
            # overlay (the server-side equivalent of firing state_transition). Deduped per project.
            if verb in ("someday", "resurface"):
                proj_id = _nearest_project(rid)
                if proj_id:
                    refresh_projects.add(proj_id)

        for proj_id in sorted(refresh_projects):
            p = by_id.get(proj_id)
            if not p:
                continue
            await _write(
                "rtm.tasks.addTags",
                "engage:overlay-refresh-mark",
                proj_id,
                tags=OVERLAY_REFRESH,
                task_id=p.get("id"),
                taskseries_id=p.get("taskseries_id"),
                list_id=p.get("list_id"),
            )

        return build_response(
            data={
                "applied": applied,
                "errors": errors,
                "warnings": warnings,
                "count": len(val_items),
                "message": f"Applied {len(applied)} write(s); {len(errors)} error(s).",
            },
            timeline_id=client.timeline_id,
        )

    # ======================================================================= #
    # Phase 0 reads — typed GTD detectors (ports of the *-candidates.ms scripts)
    # ======================================================================= #

    async def _getlist(client: RTMClient, filter_str: str) -> list[dict[str, Any]]:
        """One read-only rtm.tasks.getList(filter=...) → parsed task rows (keeps the read-only
        call surface at exactly ["rtm.tasks.getList"])."""
        return parse_tasks_response(await client.call("rtm.tasks.getList", filter=filter_str))

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=REASSESSMENT_OUTPUT)
    async def gtd_reassessment_candidates(
        ctx: Context,
        stale_threshold_days: Annotated[
            int,
            Field(
                description="Minimum days since the task's last RTM modification before it is "
                "eligible (default 1 — let a just-produced artefact settle)."
            ),
        ] = 1,
    ) -> dict[str, Any]:
        """GTD — open AI contributions (`#ai_contrib_drafted` / `#ai_prep_drafted`) that may be
        due for reassessment. A faithful native port of `reassessment-candidates.ms`.

        Read-only: two signed `rtm.tasks.getList` reads (the two contribution tags, OR'd and
        deduped) plus a session-cached settings read for the timezone; no write, no timeline.
        The cheap RTM-side filter only — the calling agent applies the per-artefact
        frontmatter check (phase / freshness / cadence) that RTM can't see.

        Args:
            stale_threshold_days: skip items modified within this many days (default 1).

        Returns (on success): {"candidates": [{id, name, modified, tag_set, kind, priority,
            tags, deep_link, ...}], "skipped": [{name, reason}], "stale_threshold_days", "count"}
            — candidates sorted oldest-modified first. Then read each candidate's artefact.
        This tool cannot fail (no resolution): it always returns a success payload.
        """
        client: RTMClient = await get_client()
        contrib = await _getlist(client, REASSESSMENT_QUERIES[0])
        prep = await _getlist(client, REASSESSMENT_QUERIES[1])
        tz = await client.get_timezone()
        return build_response(
            data=build_reassessment_candidates(
                contrib,
                prep,
                stale_threshold_days=stale_threshold_days,
                today=_account_today(tz),
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=UNBLOCK_OUTPUT)
    async def gtd_unblock_candidates(
        ctx: Context,
        max_candidates: Annotated[
            int, Field(description="Cap on returned candidates (default 50; 0 = no cap).")
        ] = 50,
        include_speculative_stale: Annotated[
            bool,
            Field(
                description="Include stale `#ai_speculative` items as a source class (default True)."
            ),
        ] = True,
        stale_speculative_days: Annotated[
            int,
            Field(
                description="Age (days) after which a speculative item counts as stale (default 14)."
            ),
        ] = 14,
    ) -> dict[str, Any]:
        """GTD — actions that may now be unblockable, across five source classes (deferred,
        overdue waiting-fors, active BLOCKER / DEPENDS-ON notes, stale speculative). A faithful
        native port of `unblock-candidates.ms`.

        Read-only: one signed `rtm.tasks.getList` per source class (all on the same method) plus
        a cached timezone read; no write, no timeline. `#test` / `#do_not_auto_progress` /
        `#someday` are disqualified; the merged set is deduped (class order = precedence) and
        capped last.

        Args:
            max_candidates: cap on the merged result (0 = no cap).
            include_speculative_stale: include the stale-speculative class.
            stale_speculative_days: staleness threshold for that class.

        Returns (on success): {"candidates": [{id, name, source_class, taskseries_id, list_id,
            kind, tags, deep_link, ...}], "skipped": [{id, name, reason, source}], "cap",
            "stale_speculative_days", "count"}. This tool cannot fail — always a success payload.
        """
        client: RTMClient = await get_client()
        class_results: dict[str, list[dict[str, Any]]] = {}
        for source_class, filt in UNBLOCK_QUERIES:
            if source_class == "speculative_stale" and not include_speculative_stale:
                continue
            class_results[source_class] = await _getlist(client, filt)
        tz = await client.get_timezone()
        return build_response(
            data=build_unblock_candidates(
                class_results,
                max_candidates=max_candidates,
                include_speculative_stale=include_speculative_stale,
                stale_speculative_days=stale_speculative_days,
                today=_account_today(tz),
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=DECISION_OUTPUT)
    async def gtd_decision_candidates(
        ctx: Context,
        horizon_days: Annotated[
            int,
            Field(description="Days-forward date window (default 0 = no horizon; scan all)."),
        ] = 0,
        exclude_drafted: Annotated[
            bool, Field(description="Exclude items already `#ai_contrib_drafted` (default True).")
        ] = True,
    ) -> dict[str, Any]:
        """GTD — incomplete actions whose name reads as a decision to be made. A faithful native
        port of `decision-candidates.ms` (lexical decision-pattern match, anti-pattern exclusion).

        Read-only: one signed `rtm.tasks.getList` plus a cached timezone read; no write, no
        timeline. Personal items are skipped unless `#ai_decide_optin`; a lexical or
        out-of-horizon miss is silent (not listed in `skipped`).

        Args:
            horizon_days: 0 (default) scans all; a positive value date-bounds via start-or-due.
            exclude_drafted: skip already-drafted items.

        Returns (on success): {"candidates": [{id, name, date, kind, priority, tags, deep_link}],
            "skipped": [{name, reason}], "horizon_days", "count"} — sorted by effective date.
        Cannot fail — always a success payload.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, ACTION_QUERY)
        tz = await client.get_timezone()
        return build_response(
            data=build_decision_candidates(
                tasks,
                horizon_days=horizon_days,
                exclude_drafted=exclude_drafted,
                today=_account_today(tz),
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=DELIVERABLE_OUTPUT)
    async def gtd_deliverable_candidates(
        ctx: Context,
        horizon_days: Annotated[
            int, Field(description="Days-forward date window (default 0 = no horizon; scan all).")
        ] = 0,
        exclude_drafted: Annotated[
            bool, Field(description="Exclude items already `#ai_contrib_drafted` (default True).")
        ] = True,
    ) -> dict[str, Any]:
        """GTD — incomplete actions whose name reads as a deliverable to produce (draft / email /
        document / spec / report). A faithful native port of `deliverable-candidates.ms`.

        Read-only: one signed `rtm.tasks.getList` plus a cached timezone read; no write, no
        timeline. Personal items skipped unless `#ai_draft_optin`; lexical/out-of-horizon
        misses are silent.

        Args:
            horizon_days: 0 (default) scans all; a positive value date-bounds via start-or-due.
            exclude_drafted: skip already-drafted items.

        Returns (on success): {"candidates": [{id, name, date, kind, priority, tags, deep_link}],
            "skipped": [{name, reason}], "horizon_days", "count"}. Cannot fail.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, ACTION_QUERY)
        tz = await client.get_timezone()
        return build_response(
            data=build_deliverable_candidates(
                tasks,
                horizon_days=horizon_days,
                exclude_drafted=exclude_drafted,
                today=_account_today(tz),
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=RESEARCH_OUTPUT)
    async def gtd_research_candidates(
        ctx: Context,
        horizon_days: Annotated[
            int,
            Field(description="Days-forward date window (default 2; pass 0 for no horizon)."),
        ] = 2,
        exclude_drafted: Annotated[
            bool, Field(description="Exclude items already `#ai_contrib_drafted` (default True).")
        ] = True,
    ) -> dict[str, Any]:
        """GTD — incomplete actions whose name reads as research / investigation to run. A faithful
        native port of `research-candidates.ms`.

        Read-only: one signed `rtm.tasks.getList` plus a cached timezone read; no write, no
        timeline. Personal items skipped unless `#ai_research_optin`. NOTE the default horizon
        is 2 days (the .ms default) — the date filter is ACTIVE by default; pass horizon_days=0
        to scan all.

        Args:
            horizon_days: default 2 (date-bounded); 0 disables the horizon.
            exclude_drafted: skip already-drafted items.

        Returns (on success): {"candidates": [{id, name, date, kind, priority, tags, deep_link}],
            "skipped": [{name, reason}], "horizon_days", "count"}. Cannot fail.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, ACTION_QUERY)
        tz = await client.get_timezone()
        return build_response(
            data=build_research_candidates(
                tasks,
                horizon_days=horizon_days,
                exclude_drafted=exclude_drafted,
                today=_account_today(tz),
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=CALENDAR_PREP_OUTPUT)
    async def gtd_calendar_prep_candidates(
        ctx: Context,
        horizon_days: Annotated[
            int,
            Field(
                description="Days-forward window over start-or-due (default 2; 0 is treated as 2)."
            ),
        ] = 2,
        exclude_drafted: Annotated[
            bool, Field(description="Exclude items already `#ai_prep_drafted` (default True).")
        ] = True,
    ) -> dict[str, Any]:
        """GTD — upcoming `#calendar_entry` items (a start-or-due date inside the horizon) needing
        prep. A faithful native port of `calendar-prep-candidates.ms`.

        Read-only: one signed `rtm.tasks.getList` plus a cached timezone read; no write, no
        timeline. No personal-context filter (the calling agent owns that); skips
        `#do_not_auto_progress` and (by default) already-prepped items. Emits a wall-clock time.
        NOTE: horizon_days is `value or 2`, so 0 is treated as 2 (0 cannot disable the horizon).

        Args:
            horizon_days: days-forward window (default 2; 0 → 2).
            exclude_drafted: skip already-prepped items.

        Returns (on success): {"candidates": [{id, name, date, time, start, due, kind, tags,
            deep_link}], "skipped": [{name, reason}], "horizon_days", "count"}. Cannot fail.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, CALENDAR_PREP_QUERY)
        tz = await client.get_timezone()
        return build_response(
            data=build_calendar_prep_candidates(
                tasks,
                horizon_days=horizon_days,
                exclude_drafted=exclude_drafted,
                today=_account_today(tz),
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=CAPTURE_OUTPUT)
    async def gtd_capture_candidates(
        ctx: Context,
        window_days: Annotated[
            int, Field(description="Look-back window in days (default 7; 0 = full scan).")
        ] = 7,
        include_completed: Annotated[
            bool,
            Field(
                description="Also include contributions completed within the window (default True)."
            ),
        ] = True,
    ) -> dict[str, Any]:
        """GTD — recent AI contributions whose artefact bodies may hold promotion candidates. A
        faithful native port of `capture-candidates.ms`.

        Read-only: two-to-four signed `rtm.tasks.getList` reads (incomplete + optionally
        completed-within-window) plus a cached timezone read; no write, no timeline. Personal
        items skipped unless `#ai_research_optin`; sorted newest-modified first.

        Args:
            window_days: look-back window (0 = no window).
            include_completed: add the completed-within-window queries.

        Returns (on success): {"candidates": [{id, name, modified, status, tag_set, kind, tags,
            deep_link}], "skipped": [{name, reason}], "window_days", "count"}. Cannot fail.
        """
        client: RTMClient = await get_client()
        incomplete = [await _getlist(client, q) for q in CAPTURE_INCOMPLETE_QUERIES]
        completed: list[list[dict[str, Any]]] = []
        if include_completed:
            completed = [await _getlist(client, q) for q in capture_completed_queries(window_days)]
        tz = await client.get_timezone()
        return build_response(
            data=build_capture_candidates(
                incomplete,
                completed,
                window_days=window_days,
                today=_account_today(tz),
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=TOPIC_CLUSTERS_OUTPUT)
    async def gtd_topic_clusters(
        ctx: Context,
        threshold: Annotated[
            int, Field(description="Minimum items sharing a tag to form a cluster (default 5).")
        ] = 5,
        max_clusters: Annotated[
            int, Field(description="Cap on returned clusters (default 20; 0 = no cap).")
        ] = 20,
        exclude_personal: Annotated[
            bool, Field(description="Exclude `#personal` items from clustering (default True).")
        ] = True,
    ) -> dict[str, Any]:
        """GTD — cross-project topic/person clusters: a non-trivial tag carried by many workflow
        items spanning ≥2 projects (a candidate emergent project or theme). A faithful native
        port of `topic-cluster-detector.ms`.

        Read-only: one signed `rtm.tasks.getList` plus a cached timezone read; no write, no
        timeline. Trivial workflow/system tags (and `q_*` / `ai_*optin`) never anchor a cluster.

        Args:
            threshold: minimum item count per cluster.
            max_clusters: cap on returned clusters (0 = no cap).
            exclude_personal: drop personal-context items.

        Returns (on success): {"clusters": [{anchor, anchor_type, item_count, distinct_projects,
            sample_items:[{id, name}]}], "threshold", "exclude_personal", "cap", "count"}. Cannot fail.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, TOPIC_CLUSTER_QUERY)
        tz = await client.get_timezone()
        return build_response(
            data=build_topic_clusters(
                tasks,
                threshold=threshold,
                max_clusters=max_clusters,
                exclude_personal=exclude_personal,
                timezone=tz,
            )
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=HEALTH_CHECK_OUTPUT)
    async def gtd_health_check(ctx: Context) -> dict[str, Any]:
        """GTD — systemic health audit: stuck projects (no next action), items missing a life or
        workflow-state tag, stale waiting-fors, and actions carrying due dates. A faithful native
        port of `health-check.ms`.

        Read-only: ONE broad signed `rtm.tasks.getList(status:incomplete)` plus a cached
        timezone read; no write, no timeline. (The .ms ran a per-project child sub-query — this
        derives the parent→children map client-side from the one read, avoiding that N+1, for
        the same result.)

        Returns (on success): {"issues": [{category, name, task_id, deep_link}], "count",
            "current_date"} where category ∈ {stuck_project, missing_life_context,
            missing_workflow_state, stale_waiting_for, action_with_due_date}. Cannot fail.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, HEALTH_CHECK_QUERY)
        tz = await client.get_timezone()
        return build_response(data=build_health_check(tasks, today=_account_today(tz), timezone=tz))

    # ======================================================================= #
    # Phase 0 reads — collection / context tools
    # ======================================================================= #

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=GTD_QUERY_OUTPUT)
    async def gtd_query(
        ctx: Context,
        perspective: Annotated[
            str,
            Field(
                description="Which view: 'next_actions_by_context' | 'todays_field' | "
                "'focus_projects'.",
                json_schema_extra=_PERSPECTIVE_ENUM,
            ),
        ] = "todays_field",
        context: Annotated[
            str | None,
            optional_string(
                "For next_actions_by_context: filter to one action-context tag (e.g. "
                "'location_home', 'using_device', 'conversation_email'). Omit for all contexts."
            ),
        ] = None,
        focus: Annotated[
            str | None,
            optional_string(
                "For focus_projects: an Area-of-Focus id or name to scope to. Omit for all foci."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — a GTD-shaped collection view in one read: next actions grouped by context, today's
        field (due-today + overdue + untagged capture), or a focus area's projects.

        Read-only: one signed `rtm.tasks.getList` plus a cached timezone read; no write, no
        timeline. `focus_projects` with a `focus` name resolves it server-side (ambiguous name →
        candidates; a miss → an error).

        Args:
            perspective: the view to return (advisory enum).
            context: next_actions_by_context only — scope to one action-context tag.
            focus: focus_projects only — an area id or name to scope to.

        Returns (on success): {"perspective", "rows": [{id, name, kind, priority, due, tags,
            deep_link, ...}], "count"} (rows carry `context` / `focus` per perspective).
        Returns (on ambiguity, focus name): {"candidates": [{id, name, list_id}]} — call again
            with focus set to an id.
        Returns (on bad input / focus miss): {"error": {"code": "invalid_input" (unknown
            perspective) | "focus_not_found" | "missing_parameter", "message": ...}} — branch on
            `error.code`, never the prose.
        """
        if perspective not in VALID_PERSPECTIVES:
            return build_response(
                data=build_error(
                    ErrorCode.INVALID_INPUT,
                    f"Unknown perspective '{perspective}'. Use one of {sorted(VALID_PERSPECTIVES)}.",
                    perspective=perspective,
                )
            )
        client: RTMClient = await get_client()
        tz = await client.get_timezone()
        if perspective == "next_actions_by_context":
            tasks = await _getlist(client, "tag:action AND status:incomplete AND NOT tag:test")
            return build_response(
                data=build_query_next_actions(tasks, context=context, timezone=tz)
            )
        if perspective == "todays_field":
            # status:incomplete is REQUIRED here — the list-catalogue TODAY filter is a smart-list
            # definition whose incomplete-scoping the UI implies; via the API its absence matches
            # years of completed/recurring dated occurrences (measured: 39k+ rows live).
            tasks = await _getlist(
                client,
                "status:incomplete AND NOT tag:test AND "
                "((dueBefore:today OR due:today) OR (isTagged:false AND isSubtask:false))",
            )
            return build_response(data=build_query_todays_field(tasks, timezone=tz))
        # focus_projects
        parsed = await _getlist(client, "status:incomplete")
        focus_id: str | None = None
        if focus:
            resolved = resolve_focus(parsed, focus)
            if "focus" not in resolved:
                return build_response(data=resolved)  # error or candidates
            focus_id = str(resolved["focus"]["id"])
        return build_response(
            data=build_query_focus_projects(parsed, focus_id=focus_id, timezone=tz)
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=INBOX_STATE_OUTPUT)
    async def gtd_inbox_state(ctx: Context) -> dict[str, Any]:
        """GTD — the three inbox-health signals for Inbox_Stuff in one read: depth, unprocessed
        (no pipeline tag), awaiting-review (`#ai_review`), and approved-but-unapplied
        (`#ai_approved`).

        Read-only: ONE signed `rtm.tasks.getList(list:Inbox_Stuff)` plus a cached timezone read
        (the three signals are subsets of the one read); no write, no timeline.

        Returns (on success): {"depth", "unprocessed_count", "awaiting_review_count",
            "approved_unapplied_count", "unprocessed": [...], "awaiting_review": [...],
            "approved_unapplied": [...]} — each list carries typed rows. Cannot fail.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, "list:Inbox_Stuff AND status:incomplete AND NOT tag:test")
        tz = await client.get_timezone()
        return build_response(data=build_inbox_state(tasks, timezone=tz))

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=WAITING_FOR_OUTPUT)
    async def gtd_waiting_for_queue(ctx: Context) -> dict[str, Any]:
        """GTD — the waiting-for chase queue: incomplete `#waiting_for` items with their due tickle
        (chase prompt), last-updated age, and a `stale` flag (updated >14 days ago).

        Read-only: ONE signed `rtm.tasks.getList` plus a cached timezone read; no write, no
        timeline. Sorted stale-first, then by earliest due tickle.

        Returns (on success): {"rows": [{id, name, due, updated, stale, kind, tags, deep_link}],
            "count", "stale_count", "current_date"}. Cannot fail.
        """
        client: RTMClient = await get_client()
        tasks = await _getlist(client, "tag:waiting_for AND status:incomplete AND NOT tag:test")
        tz = await client.get_timezone()
        return build_response(
            data=build_waiting_for_queue(tasks, today=_account_today(tz), timezone=tz)
        )

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=GTD_CONTEXT_OUTPUT)
    async def gtd_context(
        ctx: Context,
        task_ref: Annotated[
            str,
            Field(description="The task to bundle context for — a task id (preferred) or a name."),
        ],
        depth: Annotated[
            str,
            Field(
                description="Bundle breadth: 'shallow' (task + own notes) | 'medium' (+ parent + "
                "immediate siblings) | 'deep' (+ full note bodies, all siblings, full ancestry).",
                json_schema_extra=_DEPTH_ENUM,
            ),
        ] = "medium",
    ) -> dict[str, Any]:
        """GTD — the note-reading-protocol context bundle for one task: the gtd-interpreted task,
        its notes ordered STATE-first, its siblings, and the parent chain to the Area of Focus —
        in one read, so a session can orient without re-reading the whole project.

        Read-only: ONE signed `rtm.tasks.getList` (incomplete OR completed) plus a cached
        timezone read; no write, no timeline. `task_ref` is resolved server-side by id or name.

        Args:
            task_ref: a task id (preferred) or a name (fuzzy; ambiguous → candidates).
            depth: how far the bundle reaches (advisory enum; default 'medium').

        Returns (on success): {"task": {...}, "notes": [{type, date, summary, body}],
            "siblings": [...], "ancestors": [...], "depth"} — notes STATE-first.
        Returns (on ambiguity): {"candidates": [{id, name, list_id}]} — call again with an id.
        Returns (on bad input / miss): {"error": {"code": "task_not_found" | "missing_parameter"
            | "invalid_input", "message": ...}} — branch on `error.code`, never the prose.
        """
        if not task_ref or not task_ref.strip():
            return build_response(
                data=build_error(
                    ErrorCode.MISSING_PARAMETER, "Provide task_ref — a task id or name."
                )
            )
        if depth not in VALID_DEPTHS:
            return build_response(
                data=build_error(
                    ErrorCode.INVALID_INPUT,
                    f"Unknown depth '{depth}'. Use one of {sorted(VALID_DEPTHS)}.",
                    depth=depth,
                )
            )
        client: RTMClient = await get_client()
        parsed = await _getlist(client, "status:incomplete OR status:completed")
        resolved = resolve_task_ref(parsed, task_ref)
        if "task" not in resolved:
            if "candidates" in resolved:
                return build_response(data=resolved)
            return build_response(
                data=build_error(
                    ErrorCode.TASK_NOT_FOUND,
                    f"No task matching '{task_ref}'. Pass a task id, or check the name with "
                    "list_tasks.",
                    query=task_ref,
                )
            )
        tz = await client.get_timezone()
        return build_response(
            data=build_context(parsed, resolved["task"], depth=depth, timezone=tz)
        )

    # ======================================================================= #
    # Phase 1 writes — the four everyday governed write tools
    # ======================================================================= #

    def _writer(applied: list[dict[str, Any]], errors: list[dict[str, Any]], client: RTMClient):
        """Build the batch-resilient write closure (the canvas-commit `_write` contract)."""

        async def _write(
            method: str, label: str, _id: str | None = None, **kwargs: Any
        ) -> dict[str, Any] | None:
            try:
                res = await client.call(method, require_timeline=True, **kwargs)
                tx_id, undoable = get_transaction_info(res)
                if tx_id:
                    client.record_transaction(tx_id, method, undoable, label)
                applied.append({"op": label, "id": _id, "transaction_id": tx_id})
                return res
            except Exception as exc:  # batch resilience: record and continue
                errors.append({"op": label, "id": _id, "error": str(exc)})
                return None

        return _write

    def _nearest_project(task: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """The item's nearest `#project` ancestor (the plan-graph overlay is per project), falling
        back to the item itself when it is loose."""
        cur = task
        for _ in range(10):
            if _PROJECT_TAG in (cur.get("tags") or []):
                return cur
            nxt = by_id.get(str(cur.get("parent_task_id") or ""))
            if not nxt:
                return task
            cur = nxt
        return task

    async def _resolve_ref(client: RTMClient, task_ref: str, filter_str: str) -> dict[str, Any]:
        """One read + id-or-name resolution → {"task":…, "parsed":…} | {"candidates":…} | {"error":…}."""
        parsed = await _getlist(client, filter_str)
        res = resolve_task_ref(parsed, task_ref)
        if "task" in res:
            return {"task": res["task"], "parsed": parsed}
        if "candidates" in res:
            return res
        return build_error(
            ErrorCode.TASK_NOT_FOUND,
            f"No task matching '{task_ref}'. Pass a task id, or find it with gtd_query / list_tasks.",
            query=task_ref,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=CREATE_ITEM_OUTPUT)
    async def gtd_create_item(
        ctx: Context,
        parent_ref: Annotated[
            str, Field(description="The parent project/task — a task id (preferred) or a name.")
        ],
        kind: Annotated[
            str,
            Field(
                description="What to create: 'action' | 'waiting_for' | 'calendar_entry'. "
                "(A project is created with gtd_create_project.)",
                json_schema_extra=_KIND_ENUM,
            ),
        ],
        name: Annotated[
            str, Field(description="The item's name (written verbatim; never SmartAdd-parsed).")
        ],
        life_context: Annotated[
            str,
            Field(description="Life context — exactly one per task.", json_schema_extra=_LIFE_ENUM),
        ],
        priority: Annotated[
            str,
            Field(
                description="MoSCoW band (RTM's priority field): must | should | could.",
                json_schema_extra=_MOSCOW_ENUM,
            ),
        ],
        action_context: Annotated[
            str | None,
            optional_string(
                "Action context for an action/calendar entry. Defaults to 'using_device'.",
                **_ACTION_CONTEXT_ENUM,
            ),
        ] = None,
        energy: Annotated[
            str | None,
            optional_string("Energy rating — required for an action.", **_ENERGY_ENUM),
        ] = None,
        comms: Annotated[
            str | None,
            optional_string(
                "Mode of communication, when the item is a conversation.", **_COMMS_ENUM
            ),
        ] = None,
        estimate: Annotated[
            str | None,
            optional_string("Time estimate (e.g. '30 minutes') — required for an action."),
        ] = None,
        due: Annotated[
            str | None,
            optional_string(
                "Due date phrase — resolved server-side via rtm.time.parse. Required for a "
                "waiting_for (the chase tickle) and a calendar_entry."
            ),
        ] = None,
        context_note: Annotated[
            str | None, optional_string("Optional CONTEXT note body written on the new item.")
        ] = None,
        extra_tags: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema(
                    "Genuinely-open extra tags. Existence-gated by strict-tag mode; the server "
                    "never mints a tag, and structural tags are materialised from the typed "
                    "facets above — do not pass them here."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — create ONE clarified item (action / waiting-for / calendar entry) under a parent,
        atomically: the server materialises the structural tags from typed facets, sets the
        MoSCoW band, resolves the due phrase, writes an optional CONTEXT note, and stamps the
        overlay-refresh signal — replacing a 5-6 call generic dance.

        Governed write. Validate-then-apply: enum membership, list writability, the
        Definition-of-Ready for the kind, and the strict-tag existence gate all run BEFORE any
        mutation — a rejected create writes NOTHING. Every write is transaction-recorded, so the
        whole item is revertible with batch_undo. Stamps `#ai_conversation` on the item and
        `#ai_overlay_refresh_needed` on its nearest `#project` ancestor so the gtd engine
        refreshes the plan-graph overlay on its next scan (the server stamps the durable signal;
        it never invokes a gtd agent).

        DoR is HARD-GATED (Paul's decision 2026-07-23; note gtd's own catalogue treats DoR as
        report-and-resolve). Required per kind — action: life_context + estimate + energy +
        priority; waiting_for: life_context + priority + due; calendar_entry: life_context +
        priority + due. `action_context` is satisfied by the documented 'using_device' default.
        The `relational` axis is REPORTED in `advisory`, not gated (DEPENDS-ON authoring is a
        later phase).

        Args:
            parent_ref: the parent project/task (id preferred; a name resolves, ambiguous →
                candidates).
            kind: action | waiting_for | calendar_entry. A calendar entry is materialised as
                `action` + `calendar_entry` (calendar_entry is a Special Tag, not a workflow state).
            name: the item name, written verbatim (parse is disabled so a '#token' cannot mint a tag).
            life_context / priority: required structural facets.
            action_context / energy / comms / estimate / due / context_note / extra_tags: see each.

        Returns (on success): the TRUE post-state — {"task_id", "taskseries_id", "list_id",
            "name", "kind", "tags", "priority", "due", "deep_link", "ready", "missing",
            "advisory", "applied", "errors", "message"} — the real id triple RTM returned,
            never an echo of the request.
        Returns (on ambiguity): {"candidates": [{id, name, list_id}]} — call again with an id.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail, …}], …} where
            reason ∈ "invalid_input" | "invalid_life" | "missing_name" | "dor_not_met" |
            "smart_list_target" | "strict_tag_rejected" | "bad_date" | "list_not_found".
        Returns (on miss): {"error": {"code": "task_not_found", "message": …}} — branch on
            `error.code`, never the prose.
        """
        client: RTMClient = await get_client()
        extra = coerce_json(extra_tags) or []

        ref = await _resolve_ref(client, parent_ref, "status:incomplete")
        if "task" not in ref:
            return build_response(data=ref)
        parent = ref["task"]
        by_id = {str(t.get("id")): t for t in ref["parsed"]}

        processed = await resolve_system_list_id(client, PROCESSED_LIST)
        processed_ok = "error" not in processed and not (processed.get("list") or {}).get("smart")

        val = validate_create_item(
            kind=kind,
            name=name,
            life_context=life_context,
            action_context=action_context,
            energy=energy,
            comms=comms,
            priority=priority,
            estimate=estimate,
            due=due,
            processed_ok=processed_ok,
        )
        rejections = list(val["rejections"])

        # Dates resolve through rtm.time.parse BEFORE any write — a hallucinated phrase is a
        # bad_date rejection, never a written date.
        tz = await client.get_timezone()
        due_iso = ""
        if due and not rejections:
            params: dict[str, Any] = {"text": due}
            if tz:
                params["timezone"] = tz
            try:
                pres = await client.call("rtm.time.parse", **params)
                due_iso = ((pres.get("time") or {}) if isinstance(pres, dict) else {}).get(
                    "$t"
                ) or ""
            except Exception:
                due_iso = ""
            if not due_iso:
                rejections.append(
                    {"reason": ErrorCode.BAD_DATE.value, "detail": f"could not resolve due '{due}'"}
                )

        tags = item_tags(
            kind,
            life_context,
            action_context=action_context,
            energy=energy,
            comms=comms,
            extra_tags=extra,
        )
        if not rejections:
            gate = await enforce_strict_tags(
                client,
                sorted(
                    collect_item_tags(
                        kind,
                        life_context,
                        action_context=action_context,
                        energy=energy,
                        comms=comms,
                        extra_tags=extra,
                    )
                    | {OVERLAY_REFRESH}
                ),
                tool="gtd_create_item",
            )
            if gate:
                rejections.append(as_rejection(gate))

        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "ready": not val["missing"],
                    "missing": val["missing"],
                    "advisory": val["advisory"],
                    "message": "Create rejected; nothing was written.",
                }
            )

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)

        res = await _write(
            "rtm.tasks.add",
            f"create:{name[:40]}",
            None,
            name=name,
            parse="0",
            parent_task_id=parent.get("id"),
        )
        new = (parse_tasks_response(res) if res else [{}]) or [{}]
        created = new[0]
        cid = created.get("id")
        if not cid:
            return build_response(
                data={
                    "applied": applied,
                    "errors": errors or [{"op": "create", "error": "no id returned"}],
                    "ready": False,
                    "missing": val["missing"],
                    "advisory": val["advisory"],
                    "message": "Create failed; no task id returned.",
                },
                timeline_id=client.timeline_id,
            )
        nid = {
            "task_id": cid,
            "taskseries_id": created.get("taskseries_id"),
            "list_id": created.get("list_id"),
        }

        await _write("rtm.tasks.setTags", "create:tags", cid, tags=",".join(tags), **nid)
        await _write(
            "rtm.tasks.setPriority",
            "create:priority",
            cid,
            priority=MOSCOW_TO_PRIORITY[priority],
            **nid,
        )
        if estimate:
            await _write("rtm.tasks.setEstimate", "create:estimate", cid, estimate=estimate, **nid)
        if due_iso:
            await _write("rtm.tasks.setDueDate", "create:due", cid, due=due_iso, parse="0", **nid)
        if context_note:
            today = _account_today(tz)
            await _write(
                "rtm.tasks.notes.add",
                "create:context-note",
                cid,
                note_title=format_note_title("CONTEXT", name[:60], date=today),
                note_text=context_note,
                **nid,
            )

        # Durable orchestration signal — stamped, never fired (the server cannot run a gtd agent).
        proj = _nearest_project(parent, by_id)
        await _write(
            "rtm.tasks.addTags",
            "create:overlay-refresh",
            str(proj.get("id")),
            tags=OVERLAY_REFRESH,
            task_id=proj.get("id"),
            taskseries_id=proj.get("taskseries_id"),
            list_id=proj.get("list_id"),
        )

        return build_response(
            data={
                "task_id": cid,
                "taskseries_id": str(nid["taskseries_id"] or ""),
                "list_id": str(nid["list_id"] or ""),
                "name": name,
                "kind": kind,
                "tags": tags,
                "priority": MOSCOW_TO_PRIORITY[priority],
                "due": _norm_date(due_iso, tz) if due_iso else "",
                "deep_link": build_task_url(
                    str(nid["list_id"] or ""), [str(parent.get("id")), str(cid)]
                ),
                "ready": True,
                "missing": [],
                "advisory": val["advisory"],
                "applied": applied,
                "errors": errors,
                "message": f"Created {kind} '{name}' with {len(applied)} write(s).",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=ADD_NOTE_OUTPUT)
    async def gtd_add_note(
        ctx: Context,
        task_ref: Annotated[
            str, Field(description="The task to journal against — a task id (preferred) or a name.")
        ],
        note_type: Annotated[
            str,
            Field(
                description="The journalling note TYPE. Side-effect types (DEPENDS-ON, OUTPUT, "
                "CHAT, ORDER) have their own tools and are not accepted here.",
                json_schema_extra=_NOTE_TYPE_ENUM,
            ),
        ],
        summary: Annotated[str, Field(description="The title's brief summary (after the TYPE).")],
        body: Annotated[str, Field(description="The note body (the narrative).")] = "",
        timestamp: Annotated[
            bool,
            Field(description="Include HH:MM in the title (default False — date only)."),
        ] = False,
    ) -> dict[str, Any]:
        """GTD — write a conforming journal note on a task: the server builds the
        `YYYY-MM-DD [HH:MM] — TYPE — summary` title and validates the body's block order, so a
        malformed note can't reach RTM.

        Governed write. Validate-then-apply — an unknown TYPE, an empty summary or an
        out-of-order body block rejects with NOTHING written. The write is
        transaction-recorded (revert with undo / batch_undo).

        Note shape enforced: the em-dash title grammar (never en-dash), and the fixed body block
        order narrative → `--- Sources ---` → `--- AI Context ---`. A STATE note additionally
        gets its `Snapshot as of: <date>` marker prepended; STATE is LATEST-WINS — the prior
        STATE note is never deleted or retitled (older snapshots remain as history).

        Args:
            task_ref: the task (id preferred; a name resolves, ambiguous → candidates).
            note_type / summary / body / timestamp: see each.

        Returns (on success): {"task_id", "note_title", "note_type", "applied", "errors",
            "message"} — the title the server actually wrote.
        Returns (on ambiguity): {"candidates": [{id, name, list_id}]} — call again with an id.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail}], …} where
            reason ∈ "invalid_note_type" | "invalid_block_order" | "missing_parameter".
        Returns (on miss): {"error": {"code": "task_not_found", "message": …}} — branch on
            `error.code`, never the prose.
        """
        client: RTMClient = await get_client()
        rejections = validate_add_note(note_type=note_type, summary=summary, body=body)
        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "message": "Note rejected; nothing was written.",
                }
            )
        ref = await _resolve_ref(client, task_ref, "status:incomplete OR status:completed")
        if "task" not in ref:
            return build_response(data=ref)
        task = ref["task"]

        tz = await client.get_timezone()
        today = _account_today(tz)
        time_part = None
        if timestamp:
            try:
                time_part = datetime.now(ZoneInfo(tz)).strftime("%H:%M") if tz else None
            except Exception:
                time_part = None
        title = format_note_title(note_type, summary, date=today, time=time_part)
        text = state_body(body, date=today) if note_type == "STATE" else body

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        await _write(
            "rtm.tasks.notes.add",
            f"note:{note_type}",
            str(task.get("id")),
            note_title=title,
            note_text=text,
            task_id=task.get("id"),
            taskseries_id=task.get("taskseries_id"),
            list_id=task.get("list_id"),
        )
        return build_response(
            data={
                "task_id": str(task.get("id")),
                "note_title": title,
                "note_type": note_type,
                "applied": applied,
                "errors": errors,
                "message": f"Wrote a {note_type} note.",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=CAPTURE_OUTPUT_SCHEMA)
    async def gtd_capture(
        ctx: Context,
        text: Annotated[str, Field(description="The raw capture text, written verbatim.")],
        source_type: Annotated[
            str | None,
            optional_string(
                "What the capture came from (default 'conversational capture') — becomes the "
                "SOURCE note's summary."
            ),
        ] = None,
        source_body: Annotated[
            str | None,
            optional_string(
                "SOURCE note body — the verbatim trigger/provenance. Defaults to `text`."
            ),
        ] = None,
        pre_analysis: Annotated[
            str | None,
            optional_string(
                "Programmatic-submission variant: a pre-filled analysis body. Adds an AI ANALYSIS "
                "note and the `ai_review` pipeline tag so the item enters the review queue."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — capture raw stuff onto Inbox_Stuff atomically: the task (verbatim, never
        SmartAdd-parsed) + its SOURCE provenance note + the pipeline tag, in one call.

        Governed write. Capture-first: the item is staged RAW — the server applies
        `#ai_conversation` (plus `ai_review` only for the pre-analysis variant) and
        deliberately NO life-context or workflow-state tags. Classifying a capture is the
        Inbox_Stuff Executor's job at clarify time, so this tool cannot do it: there is no
        tag parameter to pass. Every write is transaction-recorded (revert with batch_undo).

        Args:
            text: the raw capture, written verbatim (parse disabled).
            source_type / source_body / pre_analysis: see each.

        Returns (on success): the TRUE post-state — {"task_id", "taskseries_id", "list_id",
            "name", "list_name", "tags", "deep_link", "applied", "errors", "message"}.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail}], …} where
            reason ∈ "missing_parameter" | "strict_tag_rejected" | "list_not_found" |
            "smart_list_target". Note a list-resolution failure is folded into `rejected[]` as
            "list_not_found" rather than surfacing as a nested {"error": {"code", "message"}}
            envelope — this tool has no name-resolution miss path, so branch on
            `rejected[].reason`.
        """
        client: RTMClient = await get_client()
        rejections = validate_capture(text=text)

        inbox = await resolve_system_list_id(client, INBOX_LIST)
        if "error" in inbox:
            rejections.append(
                {"reason": ErrorCode.LIST_NOT_FOUND.value, "detail": f"{INBOX_LIST} not found"}
            )
        elif (inbox.get("list") or {}).get("smart"):
            rejections.append(
                {
                    "reason": ErrorCode.SMART_LIST_TARGET.value,
                    "detail": f"{INBOX_LIST} is a smart list",
                }
            )

        tags = [AI_CONVERSATION] + ([AI_REVIEW] if pre_analysis else [])
        if not rejections:
            gate = await enforce_strict_tags(client, sorted(tags), tool="gtd_capture")
            if gate:
                rejections.append(as_rejection(gate))
        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "message": "Capture rejected; nothing was written.",
                }
            )

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        tz = await client.get_timezone()
        today = _account_today(tz)

        res = await _write(
            "rtm.tasks.add",
            f"capture:{text[:40]}",
            None,
            name=text,
            parse="0",
            list_id=inbox["list_id"],
        )
        new = (parse_tasks_response(res) if res else [{}]) or [{}]
        created = new[0]
        cid = created.get("id")
        if not cid:
            return build_response(
                data={
                    "applied": applied,
                    "errors": errors or [{"op": "capture", "error": "no id returned"}],
                    "message": "Capture failed; no task id returned.",
                },
                timeline_id=client.timeline_id,
            )
        nid = {
            "task_id": cid,
            "taskseries_id": created.get("taskseries_id"),
            "list_id": created.get("list_id"),
        }
        await _write(
            "rtm.tasks.notes.add",
            "capture:source",
            cid,
            note_title=format_note_title(
                "SOURCE", source_type or "conversational capture", date=today
            ),
            note_text=source_body or text,
            **nid,
        )
        if pre_analysis:
            await _write(
                "rtm.tasks.notes.add",
                "capture:analysis",
                cid,
                note_title=format_note_title("AI ANALYSIS", "proposed disposition", date=today),
                note_text=pre_analysis,
                **nid,
            )
        await _write("rtm.tasks.setTags", "capture:tags", cid, tags=",".join(tags), **nid)

        return build_response(
            data={
                "task_id": cid,
                "taskseries_id": str(nid["taskseries_id"] or ""),
                "list_id": str(nid["list_id"] or ""),
                "name": text,
                "list_name": INBOX_LIST,
                "tags": tags,
                "deep_link": build_task_url(str(nid["list_id"] or ""), [str(cid)]),
                "applied": applied,
                "errors": errors,
                "message": f"Captured to {INBOX_LIST} with {len(applied)} write(s).",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=TRANSITION_OUTPUT)
    async def gtd_transition_state(
        ctx: Context,
        task_ref: Annotated[
            str, Field(description="The task to transition — a task id (preferred) or a name.")
        ],
        add_tags: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema(
                    "Tags to add. Existence-gated by strict-tag mode — the server never mints a tag."
                )
            ),
        ] = None,
        remove_tags: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema("Tags to remove. Never gated — removal reduces entropy.")
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — apply a validated tag transition AND stamp the durable orchestration signal in the
        same governed call, so the caller no longer carries the remembered-fire responsibility.

        Governed write. Validate-then-apply — the transition is checked against the structural
        "exactly one per task" invariants (workflow state, life context, action context, energy)
        computed over the RESULTING tag set, and additions pass the strict-tag existence gate.
        A rejected transition writes NOTHING. Each write is transaction-recorded (batch_undo).

        The signal: `#ai_overlay_refresh_needed` is stamped on the item's nearest `#project`
        ancestor on EVERY successful transition (the simple, safe form — mildly over-eager
        rather than depending on a progress-ability tag set that is not fully canonical
        account-side). The server stamps the durable signal; the gtd engine drains it on its
        next scan. The server never invokes a gtd agent.

        Args:
            task_ref: the task (id preferred; a name resolves, ambiguous → candidates).
            add_tags / remove_tags: at least one must be non-empty.

        Returns (on success): the TRUE post-state — {"task_id", "tags" (resulting), "added",
            "removed", "signal_stamped", "applied", "errors", "message"}.
        Returns (on ambiguity): {"candidates": [{id, name, list_id}]} — call again with an id.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail}], …} where
            reason ∈ "invalid_input" | "missing_parameter" | "strict_tag_rejected".
        Returns (on miss): {"error": {"code": "task_not_found", "message": …}} — branch on
            `error.code`, never the prose.
        """
        client: RTMClient = await get_client()
        add = [t for t in (coerce_json(add_tags) or []) if str(t).strip()]
        remove = [t for t in (coerce_json(remove_tags) or []) if str(t).strip()]

        ref = await _resolve_ref(client, task_ref, "status:incomplete OR status:completed")
        if "task" not in ref:
            return build_response(data=ref)
        task = ref["task"]
        by_id = {str(t.get("id")): t for t in ref["parsed"]}
        existing = list(task.get("tags") or [])

        rejections = validate_transition(add_tags=add, remove_tags=remove, existing=existing)
        if not rejections and add:
            gate = await enforce_strict_tags(
                client, sorted(collect_transition_tags(add)), tool="gtd_transition_state"
            )
            if gate:
                rejections.append(as_rejection(gate))
        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "task_id": str(task.get("id")),
                    "tags": existing,
                    "message": "Transition rejected; nothing was written.",
                }
            )

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        ids = {
            "task_id": task.get("id"),
            "taskseries_id": task.get("taskseries_id"),
            "list_id": task.get("list_id"),
        }
        if remove:
            await _write(
                "rtm.tasks.removeTags",
                "transition:remove",
                str(task.get("id")),
                tags=",".join(remove),
                **ids,
            )
        add_with_marker = sorted(set(add) | {AI_CONVERSATION})
        await _write(
            "rtm.tasks.addTags",
            "transition:add",
            str(task.get("id")),
            tags=",".join(add_with_marker),
            **ids,
        )

        proj = _nearest_project(task, by_id)
        await _write(
            "rtm.tasks.addTags",
            "transition:overlay-refresh",
            str(proj.get("id")),
            tags=OVERLAY_REFRESH,
            task_id=proj.get("id"),
            taskseries_id=proj.get("taskseries_id"),
            list_id=proj.get("list_id"),
        )

        resulting = sorted((set(existing) - set(remove)) | set(add_with_marker))
        return build_response(
            data={
                "task_id": str(task.get("id")),
                "tags": resulting,
                "added": add_with_marker,
                "removed": sorted(remove),
                "signal_stamped": OVERLAY_REFRESH,
                "applied": applied,
                "errors": errors,
                "message": f"Transition applied with {len(applied)} write(s).",
            },
            timeline_id=client.timeline_id,
        )

    # ======================================================================= #
    # Phase 2 writes — completion, dependency, properties, bulk
    # ======================================================================= #

    @mcp.tool(annotations=DESTRUCTIVE_WRITE_ANNOTATIONS, output_schema=COMPLETE_ACTION_OUTPUT)
    async def gtd_complete_action(
        ctx: Context,
        task_ref: Annotated[
            str, Field(description="The action to complete — a task id (preferred) or a name.")
        ],
        completion: Annotated[
            str | None,
            optional_string(
                "COMPLETION note body — the result, what was produced/learned, what it means for "
                "next steps, loose ends. Required unless the item is a #calendar_entry."
            ),
        ] = None,
        outcome: Annotated[
            str | None,
            optional_string(
                "OUTCOME note body — REQUIRED for a #calendar_entry (decisions made, actions "
                "assigned, waiting-fors created, topics deferred). Replaces the COMPLETION note."
            ),
        ] = None,
        cascade: Annotated[
            str | None,
            optional_string(
                "CASCADE note body for the parent project — the completion in PROJECT terms. "
                "Omit to skip (the most commonly skipped step; supply it where a parent exists)."
            ),
        ] = None,
        decided: Annotated[
            bool,
            Field(
                description="True when this action was decision-shaped AND produced a DECISION "
                "note — adds the `decided` fan-out event."
            ),
        ] = False,
    ) -> dict[str, Any]:
        """GTD — complete an action densely and correctly: the COMPLETION note (or an OUTCOME note
        for a calendar entry) is written FIRST, the AI-output review tag resolves to approved,
        the task is completed, a CASCADE note lands on the parent project, and the durable
        overlay-refresh signal is stamped — in one governed call.

        DESTRUCTIVE: this completes a pre-existing task. Every write is transaction-recorded,
        so the whole completion is reversible with `batch_undo`. Validate-then-apply — a
        rejected completion writes NOTHING. The tool executes a completion you have already
        decided on; it never decides to complete.

        Ordering invariant honoured: the note is written BEFORE the task is marked complete
        (journalling-lifecycle — "the note should be the last thing written to the action").

        Fan-out: `fanout_events` are returned as DATA, not stamped. They are gtd
        `progression-fanout` event names (`completed` / `waiting_for_resolved` /
        `calendar_entry_completed` / `decided`) — no RTM tag by those names exists and a server
        cannot invoke an agent, so the caller fires them while the server stamps the sanctioned
        durable mark `#ai_overlay_refresh_needed` on the parent project. Guards apply:
        `waiting_for_resolved` only for a waiting-for, `calendar_entry_completed` only when the
        calendar entry has no OUTCOME note this cycle, and a `#test` item fans out nothing.

        Args:
            task_ref: the action (id preferred; a name resolves, ambiguous → candidates).
            completion / outcome / cascade / decided: see each.

        Returns (on success): {"task_id", "completed", "note_type", "note_title",
            "cascade_note_title", "approval_transition", "fanout_events", "signal_stamped",
            "applied", "errors", "message"}.
        Returns (on ambiguity): {"candidates": [{id, name, list_id}]} — call again with an id.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail}], …} where
            reason ∈ "missing_parameter" | "strict_tag_rejected".
        Returns (on miss): {"error": {"code": "task_not_found", "message": …}} — branch on
            `error.code`, never the prose.
        """
        client: RTMClient = await get_client()
        ref = await _resolve_ref(client, task_ref, "status:incomplete")
        if "task" not in ref:
            return build_response(data=ref)
        task = ref["task"]
        by_id = {str(t.get("id")): t for t in ref["parsed"]}
        tags = list(task.get("tags") or [])

        rejections = validate_complete(
            kind_tags=tags, completion=completion or "", outcome=outcome or ""
        )
        add_tags, remove_tags = output_approval_transition(tags)
        if not rejections and add_tags:
            gate = await enforce_strict_tags(
                client, sorted(set(add_tags) | {OVERLAY_REFRESH}), tool="gtd_complete_action"
            )
            if gate:
                rejections.append(as_rejection(gate))
        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "task_id": str(task.get("id")),
                    "completed": False,
                    "message": "Completion rejected; nothing was written.",
                }
            )

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        tz = await client.get_timezone()
        today = _account_today(tz)
        ids = {
            "task_id": task.get("id"),
            "taskseries_id": task.get("taskseries_id"),
            "list_id": task.get("list_id"),
        }

        # 6a — the note comes FIRST, before the completion.
        is_calendar = CALENDAR_TAG in tags
        note_type = "OUTCOME" if is_calendar else "COMPLETION"
        note_title = format_note_title(note_type, (task.get("name") or "")[:60], date=today)
        await _write(
            "rtm.tasks.notes.add",
            f"complete:{note_type.lower()}-note",
            str(task.get("id")),
            note_title=note_title,
            note_text=(outcome if is_calendar else completion) or "",
            **ids,
        )

        # 6b — completion is implicit approval of AI output (first transition only).
        if add_tags:
            await _write(
                "rtm.tasks.addTags",
                "complete:approve",
                str(task.get("id")),
                tags=",".join(add_tags),
                **ids,
            )
            await _write(
                "rtm.tasks.removeTags",
                "complete:clear-review",
                str(task.get("id")),
                tags=",".join(remove_tags),
                **ids,
            )

        # 6c — mark complete.
        done = await _write("rtm.tasks.complete", "complete:task", str(task.get("id")), **ids)

        # 6d — CASCADE note on the parent project, in project terms.
        proj = _nearest_project(task, by_id)
        cascade_title = ""
        if cascade and str(proj.get("id")) != str(task.get("id")):
            cascade_title = format_note_title("CASCADE", (task.get("name") or "")[:60], date=today)
            await _write(
                "rtm.tasks.notes.add",
                "complete:cascade",
                str(proj.get("id")),
                note_title=cascade_title,
                note_text=cascade,
                task_id=proj.get("id"),
                taskseries_id=proj.get("taskseries_id"),
                list_id=proj.get("list_id"),
            )

        # The durable mark the gtd engine drains (the server never invokes an agent).
        await _write(
            "rtm.tasks.addTags",
            "complete:overlay-refresh",
            str(proj.get("id")),
            tags=OVERLAY_REFRESH,
            task_id=proj.get("id"),
            taskseries_id=proj.get("taskseries_id"),
            list_id=proj.get("list_id"),
        )

        events = completion_events(
            tags, has_outcome_note=is_calendar and bool(outcome), decided=decided
        )
        return build_response(
            data={
                "task_id": str(task.get("id")),
                "completed": done is not None,
                "note_type": note_type,
                "note_title": note_title,
                "cascade_note_title": cascade_title,
                "approval_transition": bool(add_tags),
                "fanout_events": events,
                "signal_stamped": OVERLAY_REFRESH,
                "applied": applied,
                "errors": errors,
                "message": f"Completed '{task.get('name')}' with {len(applied)} write(s).",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=DESTRUCTIVE_WRITE_ANNOTATIONS, output_schema=CLOSE_INBOX_OUTPUT)
    async def gtd_close_inbox_item(
        ctx: Context,
        inbox_item_ref: Annotated[
            str, Field(description="The Inbox_Stuff item to close — a task id (preferred) or name.")
        ],
        derived_refs: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema(
                    "Task ids of the items derived from this capture. Each is resolved and listed "
                    "in the COMPLETION note; an unresolvable id rejects the close (never orphan "
                    "the source)."
                )
            ),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — close the clarify loop on an Inbox_Stuff item: write the COMPLETION note listing
        every derived item with its deep link, then complete the source.

        DESTRUCTIVE: completes a pre-existing task (transaction-recorded, reversible via
        `batch_undo`). The item is COMPLETED, never deleted — it stays on Inbox_Stuff as the
        audit record of what was captured and what it became.

        Safety: if any `derived_refs` id cannot be resolved the close is REJECTED and nothing
        is written — the pipeline rule is never to close a source whose derived writes did not
        land. The note title is the fixed canonical string
        `YYYY-MM-DD — COMPLETION — Processed into GTD system`.

        Args:
            inbox_item_ref: the source item (id preferred; a name resolves).
            derived_refs: ids of the derived items to list in the note.

        Returns (on success): {"task_id", "completed", "note_title", "derived_count",
            "applied", "errors", "message"}.
        Returns (on ambiguity): {"candidates": [...]} — call again with an id.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail}], …} where
            reason ∈ "task_not_found" | "missing_parameter".
        Returns (on miss): {"error": {"code": "task_not_found", "message": …}}.
        """
        client: RTMClient = await get_client()
        refs = [str(r).strip() for r in (coerce_json(derived_refs) or []) if str(r).strip()]
        ref = await _resolve_ref(client, inbox_item_ref, "status:incomplete")
        if "task" not in ref:
            return build_response(data=ref)
        task = ref["task"]
        by_id = {str(t.get("id")): t for t in ref["parsed"]}

        derived: list[dict[str, str]] = []
        rejections: list[dict[str, Any]] = []
        for rid in refs:
            d = by_id.get(rid)
            if not d:
                rejections.append(
                    {
                        "reason": ErrorCode.TASK_NOT_FOUND.value,
                        "detail": f"derived item {rid} not found — refusing to close the source",
                        "id": rid,
                    }
                )
                continue
            derived.append(
                {
                    "type": classify_gtd_type(d.get("tags") or []),
                    "name": d.get("name") or "",
                    "url": _permalink(rid, by_id, d.get("list_id")),
                }
            )
        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "task_id": str(task.get("id")),
                    "completed": False,
                    "message": "Close rejected; nothing was written.",
                }
            )

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        tz = await client.get_timezone()
        title = format_note_title("COMPLETION", INBOX_CLOSE_SUMMARY, date=_account_today(tz))
        ids = {
            "task_id": task.get("id"),
            "taskseries_id": task.get("taskseries_id"),
            "list_id": task.get("list_id"),
        }
        await _write(
            "rtm.tasks.notes.add",
            "close-inbox:note",
            str(task.get("id")),
            note_title=title,
            note_text=inbox_close_body(
                derived,
                source_name=task.get("name") or "",
                source_url=_permalink(str(task.get("id")), by_id, task.get("list_id")),
            ),
            **ids,
        )
        done = await _write(
            "rtm.tasks.complete", "close-inbox:complete", str(task.get("id")), **ids
        )
        return build_response(
            data={
                "task_id": str(task.get("id")),
                "completed": done is not None,
                "note_title": title,
                "derived_count": len(derived),
                "applied": applied,
                "errors": errors,
                "message": f"Closed the inbox item; {len(derived)} derived item(s) recorded.",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=SET_PROPERTIES_OUTPUT)
    async def gtd_set_properties(
        ctx: Context,
        task_ref: Annotated[
            str, Field(description="The task to edit — a task id (preferred) or a name.")
        ],
        name: Annotated[str | None, optional_string("New name (written verbatim).")] = None,
        priority: Annotated[
            str | None,
            optional_string("MoSCoW band — must | should | could.", **_MOSCOW_ENUM),
        ] = None,
        estimate: Annotated[
            str | None, optional_string("Time estimate, e.g. '30 minutes'.")
        ] = None,
        due: Annotated[
            str | None, optional_string("Due date phrase — resolved via rtm.time.parse. '' clears.")
        ] = None,
        start: Annotated[
            str | None, optional_string("Start date phrase — resolved via rtm.time.parse.")
        ] = None,
        energy: Annotated[
            str | None, optional_string("Energy rating — swaps the pair.", **_ENERGY_ENUM)
        ] = None,
        recurrence: Annotated[
            str | None, optional_string("RTM repeat rule, e.g. 'every week'. '' clears.")
        ] = None,
    ) -> dict[str, Any]:
        """GTD — set several scalar properties on one task in a single governed call, with the
        recurring-series guard applied.

        Governed write, validate-then-apply — a rejected edit writes NOTHING. Dates resolve
        through `rtm.time.parse` BEFORE any write, so a hallucinated phrase is a `bad_date`
        rejection rather than a written date. Each write is transaction-recorded (`batch_undo`).

        SERIES GUARD (the subtle one): RTM stores **priority and estimate on the taskseries**,
        so a write to one occurrence silently re-writes every open sibling. This tool therefore
        collapses such a write to ONE write per series, **redirected to the series'
        nearest-active occurrence** (soonest-due open, tie-broken by smallest id) — which may
        not be the occurrence you named; the response reports `written_to_task_id` and
        `series_collapsed`. A one-off task passes through unchanged. Divergent band proposals
        are surfaced in `divergent`, never silently resolved.

        Args:
            task_ref: the task (id preferred; a name resolves, ambiguous → candidates).
            name / priority / estimate / due / start / energy / recurrence: at least one required.

        Returns (on success): {"task_id", "written_to_task_id", "properties_set",
            "series_collapsed", "divergent", "applied", "errors", "message"}.
        Returns (on ambiguity): {"candidates": [...]} — call again with an id.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail}], …} where
            reason ∈ "invalid_input" | "missing_parameter" | "bad_date" | "strict_tag_rejected".
        Returns (on miss): {"error": {"code": "task_not_found", "message": …}}.
        """
        client: RTMClient = await get_client()
        has_any = any(
            v is not None for v in (name, priority, estimate, due, start, energy, recurrence)
        )
        rejections = validate_set_properties(priority=priority, energy=energy, has_any=has_any)
        ref = await _resolve_ref(client, task_ref, "status:incomplete")
        if "task" not in ref:
            return build_response(data=ref)
        task = ref["task"]
        parsed = ref["parsed"]

        tz = await client.get_timezone()
        dates: dict[str, str] = {}
        for label, phrase in (("due", due), ("start", start)):
            if phrase is None:
                continue
            if not phrase.strip():
                dates[label] = ""  # explicit clear
                continue
            params: dict[str, Any] = {"text": phrase}
            if tz:
                params["timezone"] = tz
            try:
                pres = await client.call("rtm.time.parse", **params)
                iso = ((pres.get("time") or {}) if isinstance(pres, dict) else {}).get("$t") or ""
            except Exception:
                iso = ""
            if not iso:
                rejections.append(
                    {
                        "reason": ErrorCode.BAD_DATE.value,
                        "detail": f"could not resolve {label} '{phrase}'",
                    }
                )
            else:
                dates[label] = iso

        if energy and not rejections:
            gate = await enforce_strict_tags(client, [energy], tool="gtd_set_properties")
            if gate:
                rejections.append(as_rejection(gate))
        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "task_id": str(task.get("id")),
                    "message": "Property edit rejected; nothing was written.",
                }
            )

        # Series guard: redirect the series-level writes (priority / estimate) to nearest-active.
        tid = str(task.get("id"))
        target = task
        series_collapsed = False
        divergent: list[dict[str, Any]] = []
        if priority is not None or estimate is not None:
            siblings = [
                r
                for r in parsed
                if str(r.get("taskseries_id") or "") == str(task.get("taskseries_id") or "")
            ]
            collapsed = collapse_write({tid: priority or "band"}, siblings)
            written_id = next(iter(collapsed), tid)
            if written_id != tid:
                series_collapsed = True
                target = next((r for r in siblings if str(r.get("id")) == written_id), task)
            divergent = divergent_band_proposals({tid: priority or "band"}, siblings)

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        ids = {
            "task_id": task.get("id"),
            "taskseries_id": task.get("taskseries_id"),
            "list_id": task.get("list_id"),
        }
        series_ids = {
            "task_id": target.get("id"),
            "taskseries_id": target.get("taskseries_id"),
            "list_id": target.get("list_id"),
        }
        done: list[str] = []
        if name is not None:
            await _write("rtm.tasks.setName", "props:name", tid, name=name, **ids)
            done.append("name")
        if priority is not None:
            await _write(
                "rtm.tasks.setPriority",
                "props:priority",
                str(target.get("id")),
                priority=MOSCOW_TO_PRIORITY[priority],
                **series_ids,
            )
            done.append("priority")
        if estimate is not None:
            await _write(
                "rtm.tasks.setEstimate",
                "props:estimate",
                str(target.get("id")),
                estimate=estimate,
                **series_ids,
            )
            done.append("estimate")
        if "due" in dates:
            await _write(
                "rtm.tasks.setDueDate", "props:due", tid, due=dates["due"], parse="0", **ids
            )
            done.append("due")
        if "start" in dates:
            await _write(
                "rtm.tasks.setStartDate", "props:start", tid, start=dates["start"], parse="0", **ids
            )
            done.append("start")
        if energy:
            drop = sorted(ENERGY_LEVELS - {energy})
            await _write(
                "rtm.tasks.removeTags", "props:energy-clear", tid, tags=",".join(drop), **ids
            )
            await _write("rtm.tasks.addTags", "props:energy", tid, tags=energy, **ids)
            done.append("energy")
        if recurrence is not None:
            await _write(
                "rtm.tasks.setRecurrence", "props:recurrence", tid, repeat=recurrence, **ids
            )
            done.append("recurrence")

        return build_response(
            data={
                "task_id": tid,
                "written_to_task_id": str(target.get("id")),
                "properties_set": done,
                "series_collapsed": series_collapsed,
                "divergent": divergent,
                "applied": applied,
                "errors": errors,
                "message": f"Set {len(done)} propert(ies) with {len(applied)} write(s).",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=ADDITIVE_WRITE_ANNOTATIONS, output_schema=LINK_DEPENDENCY_OUTPUT)
    async def gtd_link_dependency(
        ctx: Context,
        dependent_ref: Annotated[
            str,
            Field(
                description="The BLOCKED task — the note lands here ('X depends on Y' lives on X)."
            ),
        ],
        upstream_ref: Annotated[
            str, Field(description="The task being waited on (the prerequisite).")
        ],
        why: Annotated[
            str,
            Field(
                description="One or two sentences: what is the prereq nature of this dependency?"
            ),
        ],
        upstream_type: Annotated[
            str,
            Field(description="What the upstream is.", json_schema_extra=_UPSTREAM_TYPE_ENUM),
        ] = "action",
    ) -> dict[str, Any]:
        """GTD — record a dependency as a conforming DEPENDS-ON note on the DEPENDENT task, and
        stamp the overlay-refresh signal so the plan-graph re-layers.

        Governed write, validate-then-apply — a rejected link writes NOTHING. The note carries
        every field the gtd validator hard-requires (`Depends on:`, the full upstream id triple,
        `Status:`) plus the documented `Upstream URL:` / `Upstream type:` / `Why:` /
        `Captured at:` / `Captured by:` lines. `Status:` opens as `active`.

        Placement: on the dependent, never the upstream — and no back-link is written on the
        upstream (that is the convention, not an omission).

        NOT done here (the membrane): the `context.md` `dependencies:` frontmatter mirror is a
        VAULT filesystem write. This server is vault-free — agent-memory owns the vault, gtd
        wraps RTM — so the mirror is gtd-side drain work, triggered by the
        `#ai_overlay_refresh_needed` mark this tool stamps. RTM is the system of record; the
        frontmatter is a derivative queryable view.

        Args:
            dependent_ref / upstream_ref: task ids (preferred) or names.
            why: the human reason for the dependency.
            upstream_type: action | waiting_for | calendar_entry | project | external.

        Returns (on success): {"dependent_id", "upstream_id", "upstream_type", "status",
            "note_title", "signal_stamped", "applied", "errors", "message"}.
        Returns (on ambiguity): {"candidates": [...]} — call again with an id.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail}], …} where
            reason ∈ "invalid_input" | "missing_parameter" | "self_dep" | "strict_tag_rejected".
        Returns (on miss): {"error": {"code": "task_not_found", "message": …}}.
        """
        client: RTMClient = await get_client()
        ref = await _resolve_ref(client, dependent_ref, "status:incomplete")
        if "task" not in ref:
            return build_response(data=ref)
        dependent = ref["task"]
        parsed = ref["parsed"]
        by_id = {str(t.get("id")): t for t in parsed}

        up = resolve_task_ref(parsed, upstream_ref)
        if "task" not in up:
            if "candidates" in up:
                return build_response(data=up)
            return build_response(
                data=build_error(
                    ErrorCode.TASK_NOT_FOUND,
                    f"No upstream task matching '{upstream_ref}'.",
                    query=upstream_ref,
                )
            )
        upstream = up["task"]

        rejections = validate_link_dependency(
            upstream_type=upstream_type,
            why=why,
            same_task=str(dependent.get("id")) == str(upstream.get("id")),
        )
        if not rejections:
            gate = await enforce_strict_tags(client, [OVERLAY_REFRESH], tool="gtd_link_dependency")
            if gate:
                rejections.append(as_rejection(gate))
        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "applied": [],
                    "errors": [],
                    "dependent_id": str(dependent.get("id")),
                    "message": "Dependency rejected; nothing was written.",
                }
            )

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        tz = await client.get_timezone()
        today = _account_today(tz)
        uid = str(upstream.get("id"))
        title = format_note_title(
            "DEPENDS-ON", f"depends on {(upstream.get('name') or '')[:50]}", date=today
        )
        body = depends_on_note(
            upstream_name=upstream.get("name") or "",
            upstream_ids={
                "task_id": uid,
                "taskseries_id": str(upstream.get("taskseries_id") or ""),
                "list_id": str(upstream.get("list_id") or ""),
            },
            upstream_type=upstream_type,
            why=why,
            upstream_url=_permalink(uid, by_id, upstream.get("list_id")),
            captured_at=today,
        )
        await _write(
            "rtm.tasks.notes.add",
            "dep:note",
            str(dependent.get("id")),
            note_title=title,
            note_text=body,
            task_id=dependent.get("id"),
            taskseries_id=dependent.get("taskseries_id"),
            list_id=dependent.get("list_id"),
        )
        proj = _nearest_project(dependent, by_id)
        await _write(
            "rtm.tasks.addTags",
            "dep:overlay-refresh",
            str(proj.get("id")),
            tags=OVERLAY_REFRESH,
            task_id=proj.get("id"),
            taskseries_id=proj.get("taskseries_id"),
            list_id=proj.get("list_id"),
        )
        return build_response(
            data={
                "dependent_id": str(dependent.get("id")),
                "upstream_id": uid,
                "upstream_type": upstream_type,
                "status": "active",
                "note_title": title,
                "signal_stamped": OVERLAY_REFRESH,
                "applied": applied,
                "errors": errors,
                "message": "Dependency recorded.",
            },
            timeline_id=client.timeline_id,
        )

    @mcp.tool(annotations=DESTRUCTIVE_WRITE_ANNOTATIONS, output_schema=BATCH_TRANSITION_OUTPUT)
    async def gtd_batch_transition(
        ctx: Context,
        items: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(
                coerced_str_array_schema("Task ids to transition. Every item is validated first.")
            ),
        ] = None,
        add_tags: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(coerced_str_array_schema("Tags to add to every item.")),
        ] = None,
        remove_tags: Annotated[
            list[str] | None,
            BeforeValidator(coerce_json),
            WithJsonSchema(coerced_str_array_schema("Tags to remove from every item.")),
        ] = None,
    ) -> dict[str, Any]:
        """GTD — transition MANY items in one governed call, stamping the orchestration signal for
        EVERY item. This closes the silent fan-out gap the generic bulk tag path leaves: with
        `rtm_batch_tag` the caller must remember a separate signal fire per item, and item 15
        of 20 is where that discipline fails invisibly.

        ALL-OR-NOTHING (D9): every item is validated — resolvable, and the RESULTING tag set
        respecting the "exactly one per task" invariants — before anything is written. If ANY
        item fails, `applied_count` is 0 and nothing was written. Each write is
        transaction-recorded, so the whole batch reverses with one `batch_undo`.

        DESTRUCTIVE-annotated because a transition can park or defer pre-existing work
        (`#someday`, `#hold`), which changes what surfaces in every view.

        Args:
            items: the task ids to transition.
            add_tags / remove_tags: applied uniformly; at least one must be non-empty.

        Returns (on success): {"results": [{id, applied, tags, signal_stamped}],
            "applied_count", "requested_count", "applied", "errors", "message"}.
        Returns (on rejection — nothing written): {"rejected": [{reason, detail, id}], …,
            "applied_count": 0} where reason ∈ "invalid_input" | "missing_parameter" |
            "task_not_found" | "strict_tag_rejected". Per-item failures are reported in that
            flat `rejected[]` vector — this tool resolves ids itself, so it never returns the
            nested {"error": {"code", "message"}} envelope form.
        """
        client: RTMClient = await get_client()
        ids = [str(i).strip() for i in (coerce_json(items) or []) if str(i).strip()]
        add = [t for t in (coerce_json(add_tags) or []) if str(t).strip()]
        remove = [t for t in (coerce_json(remove_tags) or []) if str(t).strip()]

        rejections: list[dict[str, Any]] = []
        if not ids:
            rejections.append(
                {"reason": ErrorCode.MISSING_PARAMETER.value, "detail": "provide at least one item"}
            )
        parsed = await _getlist(client, "status:incomplete")
        by_id = {str(t.get("id")): t for t in parsed}

        targets: list[dict[str, Any]] = []
        for tid in ids:
            t = by_id.get(tid)
            if not t:
                rejections.append(
                    {
                        "reason": ErrorCode.TASK_NOT_FOUND.value,
                        "detail": f"{tid} not found",
                        "id": tid,
                    }
                )
                continue
            per_item = validate_transition(
                add_tags=add, remove_tags=remove, existing=list(t.get("tags") or [])
            )
            for r in per_item:
                rejections.append({**r, "id": tid})
            targets.append(t)

        if not rejections and add:
            gate = await enforce_strict_tags(
                client, sorted(collect_transition_tags(add)), tool="gtd_batch_transition"
            )
            if gate:
                rejections.append(as_rejection(gate))

        if rejections:
            return build_response(
                data={
                    "rejected": rejections,
                    "results": [],
                    "applied_count": 0,
                    "requested_count": len(ids),
                    "applied": [],
                    "errors": [],
                    "message": "Batch rejected; nothing was written (all-or-nothing).",
                }
            )

        applied: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        _write = _writer(applied, errors, client)
        add_with_marker = sorted(set(add) | {AI_CONVERSATION})
        results: list[dict[str, Any]] = []
        stamped: set[str] = set()
        for t in targets:
            tid = str(t.get("id"))
            tids = {
                "task_id": t.get("id"),
                "taskseries_id": t.get("taskseries_id"),
                "list_id": t.get("list_id"),
            }
            if remove:
                await _write(
                    "rtm.tasks.removeTags", "batch:remove", tid, tags=",".join(remove), **tids
                )
            await _write(
                "rtm.tasks.addTags", "batch:add", tid, tags=",".join(add_with_marker), **tids
            )
            # The per-item signal — the thing the generic bulk path silently drops.
            proj = _nearest_project(t, by_id)
            pid = str(proj.get("id"))
            if pid not in stamped:
                await _write(
                    "rtm.tasks.addTags",
                    "batch:overlay-refresh",
                    pid,
                    tags=OVERLAY_REFRESH,
                    task_id=proj.get("id"),
                    taskseries_id=proj.get("taskseries_id"),
                    list_id=proj.get("list_id"),
                )
                stamped.add(pid)
            results.append(
                {
                    "id": tid,
                    "applied": True,
                    "tags": sorted((set(t.get("tags") or []) - set(remove)) | set(add_with_marker)),
                    "signal_stamped": OVERLAY_REFRESH,
                }
            )
        return build_response(
            data={
                "results": results,
                "applied_count": len(results),
                "requested_count": len(ids),
                "applied": applied,
                "errors": errors,
                "message": f"Transitioned {len(results)} item(s); signal stamped on {len(stamped)} project(s).",
            },
            timeline_id=client.timeline_id,
        )
