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
from ..lookup import resolve_list_id
from ..models import (
    CANVAS_COMMIT_OUTPUT,
    CHAT_INFLIGHT_OUTPUT,
    CHAT_POST_OUTPUT,
    CHAT_THREAD_OUTPUT,
    CREATE_PROJECT_OUTPUT,
    ENGAGE_COMMIT_OUTPUT,
    ENGAGE_SEED_OUTPUT,
    PROJECT_CANVAS_OUTPUT,
    PROJECT_INDEX_OUTPUT,
    PROJECT_PLAN_OUTPUT,
    SET_REDACTION_OUTPUT,
    STAMP_TOKENS_OUTPUT,
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
    build_envelope,
    resolve_focus,
    resolve_project,
)
from ..response_builder import (
    ADDITIVE_WRITE_ANNOTATIONS,
    DESTRUCTIVE_WRITE_ANNOTATIONS,
    READ_ONLY_ANNOTATIONS,
    build_response,
    get_transaction_info,
)
from ..strict_tags import enforce_strict_tags, normalize_tag
from ..tmpl_child import make_tmpl_child_note, new_slug, plan_backfill
from ..tool_params import (
    coerce_json,
    coerced_obj_array_schema,
    coerced_object_schema,
    coerced_str_array_schema,
)
from ..urls import build_task_url


def _utc_today() -> str:
    """Today's calendar date (YYYY-MM-DD) in UTC — the safe fallback when the account timezone is
    unknown or invalid (mirrors the raw-UTC fallback in project_plan._norm_date)."""
    return datetime.now(UTC).date().isoformat()


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


def register_gtd_tools(mcp: Any, get_client: Any) -> None:
    """Register GTD domain-composition tools."""

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=PROJECT_PLAN_OUTPUT)
    async def gtd_project_plan(
        ctx: Context,
        project_id: Annotated[
            str | None, Field(description="The project (parent) task id. Preferred when known.")
        ] = None,
        project_name: Annotated[
            str | None,
            Field(
                description="Project name; resolved to an incomplete #project task (ambiguous → candidates)."
            ),
        ] = None,
        list_id: Annotated[
            str | None,
            Field(description="Optional — scope the fetch to one list (smaller/faster)."),
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
        Returns (on miss / bad input): {"error": "..."}.
        """
        client: RTMClient = await get_client()

        if bool(project_id) == bool(project_name):
            return build_response(
                data={"error": "Provide exactly one of project_id or project_name."}
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
                    data={
                        "error": f"Project {pid} not found in the fetched tasks. Check the id, or "
                        "pass list_id and/or include_completed=true if it lives in a specific list "
                        "or is completed."
                    }
                )

        # Localise dates to the account timezone (cached settings read) so BST/DST dues don't
        # render a day early — RTM returns UTC. None on failure → safe raw-UTC fallback.
        tz = await client.get_timezone()
        return build_response(data=build_envelope(parsed, pid, timezone=tz))

    @mcp.tool(annotations=READ_ONLY_ANNOTATIONS, output_schema=PROJECT_CANVAS_OUTPUT)
    async def gtd_project_canvas(
        ctx: Context,
        project_id: Annotated[
            str | None, Field(description="The project (parent) task id. Preferred when known.")
        ] = None,
        project_name: Annotated[
            str | None,
            Field(
                description="Project name; resolved to an incomplete #project task (ambiguous → candidates)."
            ),
        ] = None,
        list_id: Annotated[
            str | None,
            Field(description="Optional — scope the fetch to one list (smaller/faster)."),
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
        Returns (on miss / bad input): {"error": "..."}.
        """
        client: RTMClient = await get_client()

        if bool(project_id) == bool(project_name):
            return build_response(
                data={"error": "Provide exactly one of project_id or project_name."}
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
                    data={
                        "error": f"Project {pid} not found in the fetched tasks. Check the id, or "
                        "pass list_id and/or include_completed=true if it lives in a specific list "
                        "or is completed."
                    }
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
        """
        client: RTMClient = await get_client()

        if scope not in VALID_SCOPES:
            return build_response(
                data={
                    "applied": [],
                    "rejected": [
                        {
                            "reason": "invalid_scope",
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
                data={
                    "error": f"Project {pid} not found. Check the id (pass the project's task id)."
                }
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
            rejections.append({**gate, "reason": "non_canonical_tag"})

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
            rejections.append({**gate, "reason": "non_canonical_tag"})
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
            Field(
                description="Repeating project's task id; omit to sweep every active repeating templated project."
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
        Returns (on a bad explicit project_id): {"error": "..."}.
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
                    data={
                        "error": f"Project {pid} not found among active tasks. Pass the task id of "
                        "an incomplete #project (from gtd_project_index)."
                    }
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
            Field(
                description="Optional short display label for the title; defaults to the task name."
            ),
        ] = None,
        mode: Annotated[
            str | None,
            Field(
                description="Posture for a 'me' turn — 'discuss' | 'act' (ignored for 'ai' turns).",
                json_schema_extra=_MODE_ENUM,
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
        Returns (on bad input / strict-tag rejection — nothing written): {"error": "...", ...}.
        """
        client: RTMClient = await get_client()

        if role not in VALID_ROLES:
            return build_response(
                data={"error": f"role must be one of {sorted(VALID_ROLES)}; got {role!r}."}
            )
        if mode is not None and mode not in VALID_MODES:
            return build_response(
                data={
                    "error": f"mode must be one of {sorted(VALID_MODES)} or omitted; got {mode!r}."
                }
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
                    data={
                        "error": f"Task {task_id} is completed — its conversation is read-only "
                        "(view it with gtd_chat_thread). Reopen the task to continue the thread."
                    }
                )
            return build_response(
                data={
                    "error": f"Task {task_id} not found among active tasks. Pass the task id of an "
                    "incomplete project or item (from gtd_project_index or list_tasks)."
                }
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
                    "error": "Chat note write failed — no signal tags were changed. "
                    "See errors for the underlying failure; retry the post.",
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
            Field(
                description="Optional ISO-8601 timestamp — return only turns created strictly after it."
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
        Returns (on miss / bad input): {"error": "..."}.
        """
        client: RTMClient = await get_client()
        result = await client.call(
            "rtm.tasks.getList", filter="status:incomplete OR status:completed"
        )
        parsed = parse_tasks_response(result)
        task = next((t for t in parsed if t["id"] == str(task_id)), None)
        if task is None:
            return build_response(
                data={
                    "error": f"Task {task_id} not found. Pass the task id of a project or item "
                    "(incomplete or completed) — from gtd_project_index or list_tasks."
                }
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
        Returns (on miss / strict-tag rejection — nothing written): {"error": "...", ...}.
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
                data={
                    "error": f"Task {task_id} not found. Pass the task id of a project or item "
                    "(from gtd_project_index or gtd_project_canvas)."
                }
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
                rejections.append({"id": rid, "verdict": verdict, "reason": "not_found"})
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
                            "reason": "confirm_destructive_required",
                        }
                    )

        # Strict-tag existence gate over the tags the batch would write (all existing gtd tags).
        gate = await enforce_strict_tags(
            client, sorted(collect_engage_tags(val_items)), tool="gtd_apply_engage_commit"
        )
        if gate:
            rejections.append({**gate, "reason": "non_canonical_tag"})

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
                    {"id": v["id"], "verdict": v["verdict"], "reason": "bad_date", "phrase": phrase}
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
