"""Deterministic mapper: project-plan-seed envelope → canvas seed.

Pure (no IO). Byte-compatible port of the gtd plugin's
`skills/gtd/scripts/build-canvas-seed.py` (`build_seed` + helpers). It turns the
`project-plan-seed/3` envelope produced by `project_plan.build_envelope` into the `{frame, seed}`
shape the ui-patterns project-plan-canvas template consumes. The CLI / `parse_envelope` /
`parse_mcp_output` shims from the reference are intentionally dropped — the server already holds
the envelope in memory.

Boundary preserved from the reference: this maps the RTM-native surface (frame, rows, priority,
context/comms, completion→history, per-note first-line summaries + parsed note type, self-links,
note-scraped files, sibling deps). The `quick` / `blocked` / timeline-`order` judgement is NOT
applied here — that is `plan_graph` + `canvas_overlay.apply_graph` (the "LLM only for judgement"
boundary the reference draws). With `outputs_index=None` (v1, no vault) files[] resolves via the
note-scrape fallback, exactly as the reference does without a file-store index.
"""

import re
from typing import Any

_PRIORITY = {"High": "1", "Medium": "2", "Low": "3", "NoPriority": "", "": ""}
_CONTEXT_TAGS = ("using_device", "location_office", "location_home", "location_errand")
_COMMS_TAGS = (
    "conversation_messenger",
    "conversation_email",
    "conversation_phone_call",
    "conversation_video_call",
    "conversation_f2f",
)  # canonical tag is video_call (tag-taxonomy)
_DEFAULT_CONTEXT = "using_device"

# files[]: a raw envelope path is a genuine filed artefact only if it sits under a
# life-context / general / memory root AND inside an output|reference folder. This rejects
# transient Cowork-session scratch paths the script may have swept up.
_FILED_ROOTS = ("personal/", "work/", "leanworking/", "general/", "memory/")
_EXT_MAP = {
    "docx": "docx",
    "doc": "docx",
    "xlsx": "xls",
    "xls": "xls",
    "pptx": "ppt",
    "ppt": "ppt",
    "pdf": "pdf",
    "md": "md",
    "csv": "md",
    "txt": "md",
}

_TYPE_DASH = re.compile(r"—\s*([A-Z][A-Z0-9 _\-]+?)\s*—")  # "— CONTEXT —" / "— AI ANALYSIS —"
_TYPE_COLON = re.compile(r"^\d{4}-\d{2}-\d{2}\s+([A-Z][A-Z0-9_\-]+):")  # "2026-04-06 OUTPUT:"


def parse_file(path: str | None) -> dict[str, str] | None:
    """Raw envelope path -> {n, ext, kind, path} if it is a filed artefact, else None."""
    path = (path or "").strip().lstrip("-/ ").strip()
    if not path:
        return None
    low = path.lower()
    if not (
        any(path.startswith(r) for r in _FILED_ROOTS) and ("/output" in low or "/reference" in low)
    ):
        return None
    base = path.rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if "/reference" in low:
        kind = "reference"
    elif "/output/drafts" in low or "/drafts/" in low:
        kind = "output · draft"
    else:
        kind = "output"
    return {"n": base, "ext": _EXT_MAP.get(ext, "md"), "kind": kind, "path": path}


def map_priority(value: str | None) -> str:
    return _PRIORITY.get((value or "").strip(), "")


def map_kind(tags: list[str]) -> str:
    if "waiting_for" in tags:
        return "waiting_for"
    if "calendar_entry" in tags:
        return "calendar"
    return "action"


def map_context(tags: list[str]) -> str:
    for t in _CONTEXT_TAGS:
        if t in tags:
            return t
    return _DEFAULT_CONTEXT


def map_comms(tags: list[str]) -> str:
    for t in _COMMS_TAGS:
        if t in tags:
            return t
    return ""


def parse_note(note: dict[str, Any]) -> dict[str, Any]:
    """{date, summary, body?} -> {t: <TYPE>, d: <date>, s: <gist>, b?: <full body>}. Type parsed
    from the journaling first-line; gist is the (one-line) summary minus the date/type prefix; `b`
    is the FULL note body, carried whenever it adds detail beyond the one-line gist so the canvas
    can expand a note to its complete content inline (no RTM round-trip). `b` is omitted for
    single-line notes (body == gist) to keep the seed lean — absence means "the gist IS the note"."""
    summary = (note.get("summary") or "").strip()
    body = note.get("body") or ""
    date = note.get("date") or ""
    typ = "NOTE"
    gist = summary
    m = _TYPE_DASH.search(summary)
    if m:
        typ = m.group(1)
        # gist = text after the second em-dash, if present
        parts = summary.split("—")
        if len(parts) >= 3:
            gist = "—".join(parts[2:]).strip()
    else:
        m2 = _TYPE_COLON.search(summary)
        if m2:
            typ = m2.group(1)
            gist = summary.split(":", 1)[1].strip()
    out: dict[str, Any] = {"t": typ, "d": date, "s": gist or summary}
    if body.strip() and body.strip() != (gist or summary).strip():
        out["b"] = body  # full body — multi-line or longer-than-summary; drives the expand
    return out


def map_row(row: dict[str, Any]) -> dict[str, Any]:
    tags = row.get("tags") or []
    completed = bool(row.get("completed"))
    item: dict[str, Any] = {
        "e": 1,
        "id": row.get("id"),
        "k": map_kind(tags),
        "t": row.get("name") or "",
        "u": row.get("permalink") or "",
        "notes": [parse_note(n) for n in (row.get("notes") or [])],
        # files[]: parse raw envelope paths; keep only genuine filed artefacts.
        # (Superseded by the file-store outputs index when build_seed is given one — see below.)
        "files": [f for f in (parse_file(p) for p in (row.get("files") or [])) if f],
    }
    # the raw note-derived file pointers carry the action↔artefact LINKAGE; build_seed resolves them
    # against the authoritative file-store outputs index when one is supplied.
    item["_files_raw"] = [str(p) for p in (row.get("files") or [])]
    # nc = the TRUE total note count. The envelope caps the emitted notes[] (NOTES_PER_ROW), so a
    # heavily-journalled item would otherwise hide the rest SILENTLY. Carry the true total when it
    # exceeds what was emitted, so the consumer can render an honest "+N more — open in RTM" line.
    # Absence of nc means "what you see is all there is" (Invariant: no silent truncation).
    note_count = row.get("noteCount")
    if isinstance(note_count, int) and note_count > len(item["notes"]):
        item["nc"] = note_count
    # deps[]: raw upstream task_ids from active DEPENDS-ON notes; build_seed filters to siblings.
    if row.get("deps"):
        item["_deps_raw"] = [str(d) for d in row["deps"]]
    if item["k"] == "action":
        item["c"] = map_context(tags)
        item["m"] = map_comms(tags)
        item["p"] = map_priority(row.get("priority"))
    elif item["k"] in ("waiting_for", "calendar"):
        # carry the date through: waiting-for chase / calendar date (template reads r.d)
        due = row.get("due") or ""
        if due:
            item["d"] = due
    if completed:
        item["hx"] = 1
        item["cd"] = row.get("completedDate") or ""
    # NOTE: `quick` (2-minute rule) is NOT set here — it is a judgement call the consumer applies
    # after this deterministic seed (the "LLM only for judgement" boundary). `deps[]` is carried
    # from active DEPENDS-ON notes; the consumer merges the context.md / lexical precedence layers
    # (filesystem) on top. The execute tri-state renders without a flag.
    return item


def _file_from_index(entry: dict[str, Any]) -> dict[str, Any]:
    """A file-store outputs-index entry -> a canvas file row (authoritative path + companion kind)."""
    ext = (entry.get("ext") or "").lower()
    kind = " · ".join(x for x in (entry.get("type"), entry.get("status")) if x) or "filed"
    return {
        "n": entry.get("filename"),
        "ext": _EXT_MAP.get(ext, "md"),
        "kind": kind,
        "path": entry.get("rel_path") or entry.get("abs_path") or entry.get("filename"),
    }


def build_seed(
    header: dict[str, Any],
    rows: list[dict[str, Any]],
    outputs_index: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """outputs_index: optional list of file-store artefacts. When supplied, each row's note-derived
    file pointers are RESOLVED against it by filename (confirmed full path + real kind/status from
    the companion, unresolved pointers dropped). When absent (v1 — no vault), the note-scraped
    files[] from map_row is kept as a fallback."""
    proj = header.get("project") or {}
    frame: dict[str, Any] = {
        "life": proj.get("life") or "",
        "focus": proj.get("focus") or "",
        "name": proj.get("name") or "",
        # url is the project self-link — a SCRIPT-GENERATED permalink (the gtd_project_plan tool's
        # permalink builder), never computed here or by the agent. We only carry it through.
        "url": proj.get("permalink") or "",
    }
    # Project-level notes matter for the canvas frame region (pinned Outcome/Now + carousel). Parsed
    # with the SAME parse_note as item notes, so the frame gets {t, d, s, b?} — full bodies included.
    proj_notes = [parse_note(n) for n in (proj.get("notes") or [])]
    if proj_notes:
        frame["notes"] = proj_notes
    # Project-level support files: reference-folder artefacts NOT owned by a specific action
    # (source_action empty) — i.e. genuine project support material, not an action's output. Resolved
    # from the file-store outputs index (authoritative paths), de-duped by filename.
    if outputs_index is not None:
        seen, refs = set(), []
        for e in outputs_index:
            fn = e.get("filename")
            if (
                e.get("folder") == "reference"
                and not e.get("source_action")
                and fn
                and fn not in seen
            ):
                seen.add(fn)
                refs.append(_file_from_index(e))
        if refs:
            frame["files"] = refs
    # Dual-mode artefact attribution (robust to both situations):
    #  - AUTHORITATIVE: file-store companion carries `source_action` (the owning RTM item id) →
    #    attach the artefact to THAT action, regardless of which note mentioned the path.
    #  - FALLBACK: artefacts WITHOUT a source_action are resolved via note-derived path pointers
    #    matched by basename against the index. So pre-backlink artefacts still attach.
    idx = None  # basename → entry, only for entries WITHOUT a source_action (fallback pool)
    by_action: dict[
        str, list[dict[str, Any]]
    ] = {}  # source_action → [entries] (authoritative pool)
    if outputs_index is not None:
        idx = {}
        for e in outputs_index:
            if not e.get("filename"):
                continue
            owner = str(e.get("source_action") or "")
            if owner:
                by_action.setdefault(owner, []).append(e)
            else:
                idx[e["filename"]] = e

    seed = [map_row(r) for r in rows]
    ids = {it.get("id") for it in seed}
    for it in seed:
        # deps: resolve to in-plan siblings only, then drop the raw stash
        raw_deps = it.pop("_deps_raw", None)
        if raw_deps:
            sib = [d for d in raw_deps if d in ids and d != it.get("id")]
            if sib:
                it["deps"] = sib
        # files: authoritative backlink first, then note-scrape fallback for un-backlinked artefacts
        raw_files = it.pop("_files_raw", [])
        if outputs_index is not None and idx is not None:
            seen, resolved = set(), []
            for e in by_action.get(str(it.get("id") or ""), []):  # authoritative: owns this action
                if e.get("filename") and e["filename"] not in seen:
                    seen.add(e["filename"])
                    resolved.append(_file_from_index(e))
            for p in raw_files:  # fallback: note-scrape basename
                base = p.rsplit("/", 1)[-1]
                if base in idx and base not in seen:
                    seen.add(base)
                    resolved.append(_file_from_index(idx[base]))
            it["files"] = resolved
    # open rows first, completed (history) rows after — the template renders them inert.
    seed.sort(key=lambda it: 1 if it.get("hx") else 0)
    return {"mode": "existing", "frame": frame, "seed": seed}
