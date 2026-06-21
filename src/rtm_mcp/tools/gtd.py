"""GTD domain-composition tools for RTM MCP.

These tools speak a *consuming domain's* language (GTD) rather than mapping 1:1 to an
RTM API method. By convention they carry a `gtd_` prefix (generic RTM primitives stay
bare verbs like `add_task`/`list_tasks`); the prefix marks a GTD-shaped view over RTM
data and keeps a future lift of all `gtd_*` tools into a separate server a clean,
mechanical move.
"""

from typing import Any

from fastmcp import Context

from ..canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    COMMS_TAGS,
    CONTEXT_TAGS,
    classifiers_to_tags,
    collect_commit_tags,
    execute_progress_tags,
    validate_commit,
)
from ..canvas_overlay import apply_graph, lean_seed
from ..canvas_seed import build_seed
from ..client import RTMClient
from ..companion import enrich_files, resolve_vault_root
from ..lookup import resolve_list_id
from ..parsers import parse_tasks_response, priority_to_code
from ..plan_graph import build_graph
from ..project_plan import build_envelope, resolve_project
from ..response_builder import build_response, get_transaction_info
from ..strict_tags import enforce_strict_tags
from ..tool_params import JsonObjArray, JsonObject, JsonStrArray, coerce_json


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
        absent when neither) so the execute pill reflects committed state on reload.

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
        graph = build_graph(envelope["header"], envelope["rows"])
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
            order: dragged open-item order. v1 NO-OP — RTM has no sibling-order field, so order is
                not persisted (it re-derives from the DAG on refresh); ids are still membership-checked.
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
        project as an audit trail.

        Returns (on success): {"applied": [{op, id, transaction_id}, ...], "errors": [...],
            "order_persisted": false, "message": "..."}.
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

        # COMMIT audit note on the project
        if applied:
            proj = by_id[pid]
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

        return build_response(
            data={
                "project_id": pid,
                "applied": applied,
                "errors": errors,
                "order_persisted": False,
                "message": f"Applied {len(applied)} write(s); {len(errors)} error(s).",
            },
            timeline_id=client.timeline_id,
        )
