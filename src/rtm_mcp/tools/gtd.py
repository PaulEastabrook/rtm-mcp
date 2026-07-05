"""GTD domain-composition tools for RTM MCP.

These tools speak a *consuming domain's* language (GTD) rather than mapping 1:1 to an
RTM API method. By convention they carry a `gtd_` prefix (generic RTM primitives stay
bare verbs like `add_task`/`list_tasks`); the prefix marks a GTD-shaped view over RTM
data and keeps a future lift of all `gtd_*` tools into a separate server a clean,
mechanical move.
"""

from datetime import UTC, datetime
from typing import Any

from fastmcp import Context

from ..canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    COMMS_TAGS,
    CONTEXT_TAGS,
    OVERLAY_REFRESH,
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
from ..order_note import from_envelope as resolve_order_note
from ..order_note import make as make_order_note
from ..parsers import parse_tasks_response, priority_to_code
from ..plan_graph import build_graph
from ..project_index import build_actions, build_foci, build_index
from ..project_plan import (
    _PROJECT_TAG,
    REDACTED_TAG,
    build_envelope,
    resolve_focus,
    resolve_project,
)
from ..response_builder import build_response, get_transaction_info, record_and_build_response
from ..strict_tags import enforce_strict_tags, normalize_tag
from ..tool_params import JsonObjArray, JsonObject, JsonStrArray, coerce_json
from ..urls import build_task_url


def register_gtd_tools(mcp: Any, get_client: Any) -> None:
    """Register GTD domain-composition tools."""

    @mcp.tool()
    async def gtd_project_plan(
        ctx: Context,
        project_id: str | None = None,
        project_name: str | None = None,
        list_id: str | None = None,
        include_completed: bool = True,
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

    @mcp.tool()
    async def gtd_project_canvas(
        ctx: Context,
        project_id: str | None = None,
        project_name: str | None = None,
        list_id: str | None = None,
        include_completed: bool = True,
        lean: bool = True,
        note_cap: int = 3,
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

    @mcp.tool()
    async def gtd_project_index(
        ctx: Context,
        include_someday: bool = False,
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
          find-result glyph), plus the urgency signal the "What's hot" band triages on: due,
          priority, blocked.

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
                ("1"|"2"|"3"|""), blocked (bool), redacted (bool, the action's #redacted state)}],
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

    @mcp.tool()
    async def gtd_apply_canvas_commit(
        ctx: Context,
        project_id: str,
        order: JsonStrArray = None,
        edits: JsonObject = None,
        adds: JsonObjArray = None,
        completes: JsonStrArray = None,
        removes: JsonStrArray = None,
        execute: JsonObject = None,
        notes: JsonObject = None,
        confirm_destructive: bool = False,
    ) -> dict[str, Any]:
        """GTD — the single governed write surface for a project-plan-canvas commit. The artifact
        stages edits locally and commits them in ONE call here; governance lives in this tool, not
        the page (so the only writable tool the canvas is given is safe by construction).

        It validates the whole commit up-front and writes NOTHING if anything is rejected, then
        applies the accepted ops durable-first, recording each transaction (undoable via
        batch_undo). It does not execute AI work — `execute` only writes the durable RTM signal.

        Identify the project by project_id (required); every referenced item id must be a child of
        it (cross-project ids are rejected).

        Args:
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
            execute: {id: "now"|"later"|"quick"} — durable progression signal. "now"/"quick"
                write #ai_progress_requested (drained immediately by the on-commit fire); "later"
                writes #ai_progress_deferred (durable, NOT actioned by the fire). The two are
                mutually exclusive — switching an item's state drops the stale sibling so it never
                carries both. #ai_deferred_pending_unblock is still added when the item is blocked.
            notes: {id: {type, text}} — a journaling note per item.
            confirm_destructive: must be True for any completes/removes.

        Tag writes pass the strict-tag existence gate and use a closed canonical classifier→tag
        mapping; created/edited items carry #ai_conversation; a COMMIT note is written to the
        project as an audit trail. On any successful commit the project is also stamped with
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
        # prior commit (e.g. later→now) is removed — an item never carries both.
        for rid, mode in ops["execute"].items():
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

        # COMMIT audit note on the project
        if applied:
            counts = (
                f"adds:{len(ops['adds'])} edits:{len(ops['edits'])} "
                f"execute:{len(ops['execute'])} notes:{len(ops['notes'])} "
                f"completes:{len(ops['completes'])} removes:{len(ops['removes'])}"
            )
            body = (
                f"COMMIT (project-plan-canvas) — {counts}; "
                f"{len(applied)} write(s), {len(errors)} error(s). #ai_conversation"
            )
            await _write(
                "rtm.tasks.notes.add",
                "commit-note",
                note_title="COMMIT",
                note_text=body,
                task_id=proj.get("id"),
                taskseries_id=proj.get("taskseries_id"),
                list_id=proj.get("list_id"),
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

    @mcp.tool()
    async def gtd_create_project(
        ctx: Context,
        frame: JsonObject = None,
        items: JsonObjArray = None,
        notes: JsonObjArray = None,
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

    @mcp.tool()
    async def gtd_chat_post(
        ctx: Context,
        task_id: str,
        text: str,
        role: str = "me",
        scope: str | None = None,
        mode: str | None = None,
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

    @mcp.tool()
    async def gtd_chat_thread(
        ctx: Context,
        task_id: str,
        since: str | None = None,
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

    @mcp.tool()
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

    @mcp.tool()
    async def gtd_set_redaction(
        ctx: Context,
        task_id: str,
        redacted: bool,
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
            write_res = await client.call(
                "rtm.tasks.addTags", require_timeline=True, tags=REDACTED_TAG, **ids
            )
        else:
            write_res = await client.call(
                "rtm.tasks.removeTags", require_timeline=True, tags=REDACTED_TAG, **ids
            )

        return record_and_build_response(
            client,
            write_res,
            data={"task_id": ids["task_id"], "redacted": redacted},
            tool_name="gtd_set_redaction",
        )
