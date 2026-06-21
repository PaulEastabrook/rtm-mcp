"""Project-plan envelope builder — the `project-plan-seed/3` contract.

Pure (no IO) reconstruction of a whole GTD project plan from a flat, parsed
`rtm.tasks.getList` result (as produced by `parsers.parse_tasks_response`). The
emitted envelope is byte-compatible with the GTD plugin's reference port
`rtm_fetch.py` (`reconstruct`/`to_ndjson`) — the integration contract consumed by
the canvas mapper `build-canvas-seed.py`. Backs the `gtd_project_plan` MCP tool.

Server adaptations vs the reference (output stays identical):
- note bodies are read via `parsers.extract_note_body` (server notes carry the
  body in the `$t` XML text node, not a `body` key);
- `name`/`estimate`/`url` are coerced to `""` (server parsing yields `None` for
  empties, the envelope expects empty strings);
- permalinks reuse `urls.build_task_url` with an id-based ancestor chain that
  includes an ancestor even when its own row isn't in the fetched set.
"""

import re
from typing import Any

from .config import RTM_WEB_BASE_URL
from .parsers import _convert_rtm_date, extract_note_body
from .urls import build_task_url

SCHEMA = "project-plan-seed/3"

# RTM numeric priority → the word form the canvas mapper expects.
_PRIORITY_WORD = {"1": "High", "2": "Medium", "3": "Low", "N": "NoPriority", "": "NoPriority"}
# A project's life-context is its first tag in this set.
_LIFE_TAGS = ("work", "personal", "leanworking")
# Tag marking a GTD project (for name resolution) and the test-exclusion tag.
_PROJECT_TAG = "project"
_TEST_TAG = "test"
# files[]: a note path is a filed artefact only under an output|reference folder.
_PATHRE = re.compile(r"([A-Za-z0-9_.\-/ ]+\.(?:md|docx|xlsx|pptx|pdf|csv))")
_DIGITS = re.compile(r"\d+")
_FILES_PER_ROW = 8


def _norm_date(iso: str | None, timezone: str | None = None) -> str:
    """RTM ISO timestamp → YYYY-MM-DD in the user's timezone (empty stays empty).

    RTM returns timestamps in UTC: a London-BST date-only due of 22 Jun arrives on the wire as
    ``2026-06-21T23:00:00Z``. Truncating the UTC string directly (``[:10]``) would roll every BST
    midnight date back a day, so we convert to the account timezone FIRST, then take the calendar
    date. With no timezone (the settings fetch failed, or a pure call passes none) we fall back to
    the raw truncation — identical for UTC-midnight values, and it never raises."""
    if not iso:
        return ""
    if timezone and "T" in iso:
        iso = _convert_rtm_date(iso, timezone)
    return iso[:10] if "T" in iso or len(iso) >= 10 else iso


def _first_line(body: str | None, cap: int = 160) -> str:
    line = (body or "").split("\n", 1)[0].strip()
    return line[:cap]


def _note_objs(notes: list[dict[str, Any]], timezone: str | None = None) -> list[dict[str, str]]:
    """Map raw RTM notes → envelope note objects with full bodies + a one-line summary."""
    out = []
    for n in notes:
        body = extract_note_body(n)
        out.append(
            {
                "date": _norm_date(n.get("created"), timezone),
                "summary": _first_line(body),
                "body": body,
            }
        )
    return out


def _extract_deps_and_files(notes: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """From full note bodies: active DEPENDS-ON upstream task_ids + filed-artefact paths."""
    deps: list[str] = []
    files: list[str] = []
    seen: set[str] = set()
    for n in notes:
        body = extract_note_body(n) or ""
        if "DEPENDS-ON" in body:
            si = body.find("Status:")
            status = body[si + 7 : si + 40] if si >= 0 else ""
            if "resolved" not in status and "obsolete" not in status:
                ti = body.find("task_id:")
                if ti >= 0:
                    m = _DIGITS.search(body[ti + 8 : ti + 44])
                    if m:
                        deps.append(m.group(0))
        for line in body.split("\n"):
            pm = _PATHRE.search(line)
            if not pm:
                continue
            path = pm.group(1).strip()
            for marker, cut in (("Agent Memory/", 13), ("AI Memory/", 10)):
                idx = path.find(marker)
                if idx >= 0:
                    path = path[idx + cut :]
                    break
            path = path.strip().lstrip("-/ ").strip()
            base = path.rsplit("/", 1)[-1]
            low = path.lower()
            filed = "output/" in low or "reference/" in low
            transient = "local-agent-mode-sessions" in path or "Library/Application" in path
            if (
                filed
                and not transient
                and not base.startswith("_")
                and base not in seen
                and len(files) < _FILES_PER_ROW
            ):
                seen.add(base)
                files.append(path)
    return deps, files


def _ancestor_chain(task_id: str, by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Root-first list of task_ids from the task up to its top-level ancestor, following
    parent_task_id. An ancestor id is included even when its own row isn't in `by_id`
    (the id is still known from the child's parent_task_id), so a partial task set still
    yields the full path. 10-iter guard against cycles/corruption."""
    chain: list[str] = []
    seen: set[str] = set()
    cur = str(task_id)
    for _ in range(10):
        if not cur or cur in seen:
            break
        seen.add(cur)
        chain.append(cur)
        row = by_id.get(cur)
        cur = str((row or {}).get("parent_task_id") or "")
    chain.reverse()
    return chain


def _permalink(task_id: str, by_id: dict[str, dict[str, Any]], list_id: str | None) -> str:
    """RTM web deep link in the canonical #list/{list_id}/{ancestor-chain} form. Falls back
    to #all/<id> only when the list is unknown (which RTM can't always resolve)."""
    if not list_id:
        return f"{RTM_WEB_BASE_URL}#all/{task_id}"
    return build_task_url(list_id, _ancestor_chain(str(task_id), by_id))


def resolve_project(parsed: list[dict[str, Any]], project_name: str) -> dict[str, Any]:
    """Resolve a project by name among incomplete, `project`-tagged, non-`test` tasks.

    Exact (case-insensitive) match wins over substring. Returns:
        {"project": <task>}                              — unambiguous match
        {"candidates": [{id, name, list_id}, ...]}       — >1 match (caller must disambiguate)
        {"error": "..."}                                 — no match
    """
    name_lower = project_name.strip().lower()
    projects = [
        t
        for t in parsed
        if _PROJECT_TAG in (t.get("tags") or [])
        and _TEST_TAG not in (t.get("tags") or [])
        and not t.get("completed")
    ]
    exact = [t for t in projects if (t.get("name") or "").lower() == name_lower]
    matches = exact or [t for t in projects if name_lower in (t.get("name") or "").lower()]

    if not matches:
        return {
            "error": f"No incomplete project named '{project_name}' found. "
            "Pass project_id, or check the name with list_tasks(filter='tag:project')."
        }
    if len(matches) > 1:
        return {
            "candidates": [
                {"id": t["id"], "name": t.get("name") or "", "list_id": t.get("list_id") or ""}
                for t in matches
            ]
        }
    return {"project": matches[0]}


def build_envelope(
    parsed: list[dict[str, Any]], project_id: str, timezone: str | None = None
) -> dict[str, Any]:
    """Flat parsed tasks → the {header, rows} `project-plan-seed/3` envelope for project_id.

    timezone: the account's IANA zone (e.g. 'Europe/London'). When supplied, every date field
        (due/start/completedDate + note dates) is localised to it before truncation — RTM returns
        UTC, so a BST midnight date would otherwise render a day early. None → raw-UTC truncation
        (the pre-fix behaviour; safe fallback when the tz settings read fails)."""
    project_id = str(project_id)
    by_id = {r["id"]: r for r in parsed}
    proj = by_id.get(project_id)
    children = [
        r
        for r in parsed
        if str(r.get("parent_task_id") or "") == project_id and not r.get("deleted")
    ]

    life = ""
    if proj:
        for tg in proj.get("tags", []):
            if tg in _LIFE_TAGS:
                life = tg
                break

    proj_list_id = proj.get("list_id") if proj else ""
    proj_notes_raw = proj.get("notes", []) if proj else []
    # Project-level support material: filed-artefact paths from the PROJECT's own notes
    # (not a child action's) — the analog of row files[]. deps are unused at project level.
    _proj_deps, proj_files = _extract_deps_and_files(proj_notes_raw)
    header = {
        "type": "header",
        "schema": SCHEMA,
        "projectId": project_id,
        "project": {
            "id": project_id,
            "name": (proj.get("name") or "") if proj else "",
            "life": life,
            "listId": proj_list_id or "",
            "permalink": _permalink(project_id, by_id, proj_list_id),
            "notes": _note_objs(proj_notes_raw, timezone),
            "files": proj_files,
        },
        "rowCount": len(children),
    }

    rows = []
    for c in children:
        notes_full = c.get("notes", [])
        deps, files = _extract_deps_and_files(notes_full)
        rows.append(
            {
                "type": "row",
                "id": c["id"],
                "name": c.get("name") or "",
                "priority": _PRIORITY_WORD.get(str(c.get("priority", "N")), "NoPriority"),
                "completed": 1 if c.get("completed") else 0,
                "completedDate": _norm_date(c.get("completed"), timezone),
                "due": _norm_date(c.get("due"), timezone),
                "tags": c.get("tags", []),
                "permalink": _permalink(c["id"], by_id, c.get("list_id") or proj_list_id),
                "deps": deps,
                "files": files,
                "noteCount": len(notes_full),
                "notes": _note_objs(notes_full, timezone),
                "estimate": c.get("estimate") or "",
                "start": _norm_date(c.get("start"), timezone),
                "url": c.get("url") or "",
            }
        )

    return {"header": header, "rows": rows}
