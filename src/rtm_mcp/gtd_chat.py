"""Pure helpers for the GTD in-board AI conversation surface (the ``CHAT`` note class).

Pure (no IO). Backs the ``gtd_chat_post`` / ``gtd_chat_thread`` domain tools: the CHAT-note
**title grammar**, the posture **mode body-footer** round-trip, the **turn selector/parser**, the
**turn attachments** (server-derived ``files[]`` from OUTPUT/``FILING:`` notes + ``links[]`` from
``LINK:`` trailer lines — the gtd plugin's ``note-shape-catalogue.md`` § 3 / ``chat-reply-style.md``
§ 2 grammars, mirrored server-side; for a ``#project`` target the FILING scan also covers the
project's descendant tree via ``project_descendants``, with ``item_id``/``item_name`` provenance),
and the two **drain-signal tag** constants. Keeping the
grammar parse here (no client) makes every case unit-testable directly, matching
``project_plan.py`` / ``canvas_seed.py`` / ``canvas_commit.py``.

A CHAT turn is one RTM note on the *target task* (the project task for project-scope; the item task
for item-scope), titled::

    YYYY-MM-DD HH:MM — CHAT — <role> — <scope>

``<role>`` is ``me`` (Paul) or ``ai`` (the worker's reply); ``<scope>`` is a short display label
(the *attachment task* is the real scope). The body is the message text, optionally followed by a
``Mode: discuss|act`` footer line recording a ``me`` turn's requested posture.

The two tags — ``ai_chat_requested`` (the worker's durable work-list signal) and ``ai_chat`` (the
has-a-thread marker) — are RTM tag names (stored without ``#``). They are **provisioned
account-side**, never minted by the server: the strict-tag existence gate guards the one add path.
gtd owns the canonical CHAT grammar definition; this module mirrors it for the server side.
"""

import re
from datetime import UTC, datetime
from typing import Any

from .parsers import ensure_list, extract_note_body
from .project_plan import _PROJECT_TAG, _TEST_TAG, _ancestor_chain
from .strict_tags import normalize_tag

# Drain-signal tags (bare RTM names — no '#'). Account-provisioned; never minted here.
AI_CHAT_REQUESTED = "ai_chat_requested"  # worker work-list signal (a me-turn awaits a reply)
AI_CHAT = "ai_chat"  # has-a-thread marker (left in place once a thread exists)
# Read-only status signal (also account-provisioned, never minted here): the worker has produced
# output that awaits Paul's review. Read by gtd_chat_inflight to derive the "awaiting_review" state.
AI_OUTPUT_REVIEW_NEEDED = "ai_output_review_needed"

VALID_ROLES = frozenset({"me", "ai"})
VALID_MODES = frozenset({"discuss", "act"})

# Title grammar: "YYYY-MM-DD HH:MM — CHAT — <role> — <scope>" (space-em-dash-space separators).
_TITLE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) — CHAT — (me|ai) — (.*)$")
# Mode footer: a final "Mode: discuss|act" line (case-insensitive on the keyword).
_MODE_FOOTER_RE = re.compile(r"^Mode:\s*(discuss|act)\s*$", re.IGNORECASE)

# ── Turn-attachment grammars (note-shape-catalogue § 3 / chat-reply-style § 2) ──────────────
# OUTPUT note title (the body's first line, like every note): "YYYY-MM-DD — OUTPUT — <summary>",
# HH:MM optional; em-dash canonical, en-dash tolerated on parse (catalogue § 1). The summary
# becomes the attached files' display label.
_OUTPUT_TITLE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?\s*[—–]\s*OUTPUT\s*[—–]\s*(.*)$"  # noqa: RUF001 — en-dash tolerated by design
)
# "FILING: <vault-relative path> (+ .meta.md)" — line-anchored inside an OUTPUT note body. The
# labelled continuation form ends the FILING line with a dash and puts the path on the NEXT line.
_FILING_LINE_RE = re.compile(r"^FILING:\s*(.*)$")
_COMPANION_MARKER_RE = re.compile(r"\s*\(\+\s*\.meta\.md\)\s*$")
# "LINK: <url> — <label>" trailer lines in a turn's own text. The value—label separator is an
# em/en-dash or hyphen with surrounding whitespace — the same split the board's chatParseTrailer
# uses, so server- and client-parsed values compare equal.
_LINK_LINE_RE = re.compile(r"^LINK:\s*(.+)$")
_TRAILER_SPLIT_RE = re.compile(r"^(.*?)\s+[—–-]\s+(.*)$")  # noqa: RUF001 — en-dash tolerated by design


def local_stamp(timezone: str | None) -> str:
    """The current 'YYYY-MM-DD HH:MM' wall-clock stamp localised to *timezone* (UTC fallback).

    Graceful like ``parsers._convert_rtm_date``: an unknown/unset zone falls back to UTC, never
    raises. This is the only clock-dependent helper here; the title format itself is pure.
    """
    tzinfo: Any = UTC
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            tzinfo = ZoneInfo(timezone)
        except Exception:
            tzinfo = UTC
    return datetime.now(tzinfo).strftime("%Y-%m-%d %H:%M")


def format_chat_title(stamp: str, role: str, scope: str) -> str:
    """Build a CHAT note title from a pre-computed local *stamp* ('YYYY-MM-DD HH:MM')."""
    return f"{stamp} — CHAT — {role} — {scope}"


def parse_chat_title(title: str) -> dict[str, str] | None:
    """Parse a CHAT note title → ``{stamp, role, scope}``; ``None`` if it is not a CHAT turn."""
    m = _TITLE_RE.match(title or "")
    if not m:
        return None
    return {"stamp": m.group(1), "role": m.group(2), "scope": m.group(3)}


def append_mode_footer(text: str, mode: str | None) -> str:
    """Append a ``Mode: <mode>`` footer line to *text* when *mode* is set (else *text* verbatim)."""
    if not mode:
        return text
    body = (text or "").rstrip("\n")
    return f"{body}\n\nMode: {mode}"


def parse_body(body: str) -> tuple[str, str | None]:
    """Split a CHAT body into ``(message_text, mode)``.

    A trailing ``Mode: discuss|act`` line (the posture footer) is stripped from the returned text
    and surfaced as *mode*; with no footer the original body is returned unchanged and *mode* is
    ``None``.
    """
    text = body or ""
    lines = text.rstrip().split("\n")
    if lines:
        m = _MODE_FOOTER_RE.match(lines[-1].strip())
        if m:
            remaining = "\n".join(lines[:-1]).rstrip()
            return remaining, m.group(1).lower()
    return text, None


def parse_turn(note: dict[str, Any]) -> dict[str, Any] | None:
    """Parse one RTM note dict into a CHAT turn, or ``None`` if it is not a CHAT note.

    The CHAT title is the **first line of the note body**, not the note's ``title`` field: the RTM
    API has no separate note-title field, so the write path stores ``title\\nmessage`` in the single
    body field and ``rtm.tasks.getList`` returns an empty ``title``. We therefore split the body on
    its first newline — line 1 is the candidate title (run the CHAT selector against it) and lines
    2..N are the message text (then strip a trailing ``Mode:`` footer as usual). A single-line body
    (title only, no message) yields a turn with empty ``text`` — valid, not dropped.

    Returns ``{note_id, role, scope, text, created}`` plus ``mode`` when a footer is present.
    Robust to notes authored by either ``gtd_chat_post`` or a worker's direct ``add_note`` call,
    and to both note-body shapes (``$t`` and ``body``) via ``parsers.extract_note_body``.
    """
    first_line, _, rest = (extract_note_body(note) or "").partition("\n")
    parsed = parse_chat_title(first_line)
    if not parsed:
        return None
    text, mode = parse_body(rest)
    turn: dict[str, Any] = {
        "note_id": note.get("id"),
        "role": parsed["role"],
        "scope": parsed["scope"],
        "text": text,
        "created": note.get("created"),
    }
    if mode:
        turn["mode"] = mode
    return turn


def _clean_filing_path(raw: str) -> str | None:
    """Normalise one FILING payload → the vault-relative path, or ``None`` when malformed.

    Strips the ``(+ .meta.md)`` companion marker. An absolute (leading ``/``) or backslashed path
    is malformed per the catalogue — skipped, never "repaired" (the gtd notes-audit owns flagging
    those); the path must reach the client verbatim so it compares equal to a ``FILED:`` echo.
    """
    path = _COMPANION_MARKER_RE.sub("", raw).strip()
    if not path or path.startswith("/") or "\\" in path:
        return None
    return path


def parse_filings(body: str) -> list[str]:
    """Vault-relative paths from the ``FILING:`` lines of one OUTPUT note body.

    Handles both catalogue § 3 forms: the single-line ``FILING: <path> (+ .meta.md)`` and the
    labelled continuation (a FILING line ending with a dash, the path on the next line). One path
    per FILING line; malformed paths are skipped.
    """
    lines = (body or "").split("\n")
    paths: list[str] = []
    i = 0
    while i < len(lines):
        m = _FILING_LINE_RE.match(lines[i].strip())
        if m:
            rest = m.group(1).strip()
            if rest.endswith(("—", "–", "-")) and i + 1 < len(lines):  # noqa: RUF001 — en-dash tolerated
                i += 1
                rest = lines[i].strip()
            path = _clean_filing_path(rest)
            if path:
                paths.append(path)
        i += 1
    return paths


def parse_output_note(note: dict[str, Any]) -> dict[str, Any] | None:
    """Parse one RTM note into a filed-artefact record, or ``None`` if not a filing OUTPUT note.

    Selector: the body's first line (the title — same RTM convention as CHAT) must be an
    OUTPUT-typed title; FILING lines in any other note type are ignored (catalogue § 3 pins the
    grammar to OUTPUT notes — historic ``FILING``-typed notes predate the convention and must not
    match). Returns ``{note_id, label, created, paths}`` with *label* = the title's summary
    segment; ``None`` when no valid FILING path is present.
    """
    first_line, _, rest = (extract_note_body(note) or "").partition("\n")
    m = _OUTPUT_TITLE_RE.match(first_line.strip())
    if not m:
        return None
    paths = parse_filings(rest)
    if not paths:
        return None
    return {
        "note_id": note.get("id"),
        "label": m.group(1).strip(),
        "created": note.get("created"),
        "paths": paths,
    }


def parse_links(text: str) -> list[dict[str, str]]:
    """``LINK: <url> — <label>`` trailer lines from a turn's text → ``[{url, label}]``.

    Line-anchored, uppercase keyword; the value—label separator is an em/en-dash or hyphen with
    surrounding whitespace (no separator → label ``""``). The trailer lines are left IN the text —
    the board strips them client-side, and removing them here would break the stage-1 fallback
    parse on older boards.
    """
    links: list[dict[str, str]] = []
    for line in (text or "").split("\n"):
        m = _LINK_LINE_RE.match(line.strip())
        if not m:
            continue
        rest = m.group(1).strip()
        sm = _TRAILER_SPLIT_RE.match(rest)
        if sm:
            links.append({"url": sm.group(1).strip(), "label": sm.group(2).strip()})
        else:
            links.append({"url": rest, "label": ""})
    return links


def _after(created: str | None, since: str) -> bool:
    """True when note *created* is strictly after *since* (ISO-8601). String-compare fallback."""
    if not created:
        return False
    try:
        c = datetime.fromisoformat(created.replace("Z", "+00:00"))
        s = datetime.fromisoformat(since.replace("Z", "+00:00"))
        return c > s
    except Exception:
        return created > since


def _not_after(a: str, b: str) -> bool:
    """True when *a* <= *b* (ISO-8601 compare, string fallback — RTM values are uniform UTC)."""
    try:
        return datetime.fromisoformat(a.replace("Z", "+00:00")) <= datetime.fromisoformat(
            b.replace("Z", "+00:00")
        )
    except Exception:
        return a <= b


def _attach_filings(
    turns: list[dict[str, Any]],
    sources: list[tuple[dict[str, Any], dict[str, str] | None]],
) -> None:
    """Attach filed artefacts from OUTPUT notes to their ``ai`` turns (in place).

    Time-correlation, conservative by design (board-chat enrichment § 2.8): an OUTPUT note
    attaches to the EARLIEST ``ai`` turn whose ``created`` >= the note's ``created`` — the worker
    files first, then writes the reply, so the filing falls in the window
    ``(previous ai turn, this ai turn]``. An OUTPUT note after the last ``ai`` turn (or with no
    ``created``) attaches to nothing — unattached is correct, never guess.

    *sources* is ``(note, provenance)`` pairs: provenance is ``None`` for the target task's own
    notes (the item-scope v1 shape — no extra fields) or ``{item_id, item_name}`` for a note
    scanned from a project descendant (stage 2b), merged into each file entry so the board can
    show which child action filed the artefact.

    *turns* must already be sorted oldest-first with ``files`` lists present.
    """
    ai_turns = [t for t in turns if t["role"] == "ai" and t.get("created")]
    if not ai_turns:
        return
    for note, provenance in sources:
        out = parse_output_note(note)
        if out is None or not out.get("created"):
            continue
        target = next((t for t in ai_turns if _not_after(out["created"], t["created"])), None)
        if target is None:
            continue
        for path in out["paths"]:
            entry = {"path": path, "label": out["label"], "note_id": out["note_id"]}
            if provenance:
                entry.update(provenance)
            target["files"].append(entry)


def project_descendants(parsed: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    """All descendant tasks of *project_id* — the same ≤3-level ``parent_task_id`` tree
    ``gtd_project_plan`` walks — breadth-first, the project itself excluded.

    Backs ``gtd_chat_thread``'s project-scope FILING scan (stage 2b): a project's artefacts are
    filed against its child actions, so the OUTPUT-note scan must cover the whole subtree.
    Deleted rows are excluded (mirroring ``project_plan.build_envelope``'s child selection);
    COMPLETED descendants are included — a completed action's filed output is still a project
    output. Cycle-guarded via a seen-set, so corrupted parent chains can't loop.
    """
    project_id = str(project_id)
    kids: dict[str, list[dict[str, Any]]] = {}
    for t in parsed:
        pid = str(t.get("parent_task_id") or "")
        if pid and not t.get("deleted"):
            kids.setdefault(pid, []).append(t)
    out: list[dict[str, Any]] = []
    seen = {project_id}
    queue = [project_id]
    while queue:
        for child in kids.get(queue.pop(0), []):
            cid = str(child.get("id") or "")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append(child)
            queue.append(cid)
    return out


def build_thread(
    notes: Any,
    *,
    since: str | None = None,
    descendants: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the CHAT thread for a task: its CHAT turns oldest-first, non-CHAT notes excluded.

    *notes* is the raw note collection from a parsed task (``ensure_list``-normalised). When *since*
    is given (ISO-8601), only turns created strictly after it are returned (incremental poll).

    Every turn additionally carries the server-derived attachments (always present, ``[]`` when
    none — zero-not-absent, like the index counts):

    - ``files``: filed artefacts from the task's OUTPUT/``FILING:`` notes, time-correlated to the
      ``ai`` turn that reported them (see ``_attach_filings``) as ``{path, label, note_id}`` —
      *path* is the vault-relative path verbatim (compares equal to a ``FILED:`` trailer echo, so
      the board can prefer ``files[]`` and suppress its own parse), *label* the OUTPUT note's
      title summary, *note_id* the OUTPUT note (provenance). Only ``ai`` turns attach files.
    - ``links``: ``LINK: <url> — <label>`` trailer lines parsed from the turn's own text as
      ``{url, label}``; the trailer lines stay IN ``text`` (the board strips them client-side).

    *descendants* (stage 2b, project scope): parsed task dicts — the project's descendant tree
    from ``project_descendants`` — whose OUTPUT notes are ALSO scanned for filings, each entry
    additionally carrying ``item_id``/``item_name`` (the descendant that filed it). Turns still
    come only from *notes* (a descendant's own CHAT thread is a separate conversation). Scan
    order is the target's own notes first, then each descendant's in the given (breadth-first)
    order — deterministic. ``None``/empty keeps the item-scope v1 shape byte-identical.

    Attachment correlation runs over the FULL thread before the *since* filter — a window anchored
    on an earlier ``ai`` turn must not shift when the poll is incremental.
    """
    notes_list = [n for n in ensure_list(notes) if isinstance(n, dict)]
    turns: list[dict[str, Any]] = []
    for note in notes_list:
        turn = parse_turn(note)
        if turn is None:
            continue
        turn["files"] = []
        turn["links"] = parse_links(turn["text"])
        turns.append(turn)
    turns.sort(key=lambda t: t.get("created") or "")
    sources: list[tuple[dict[str, Any], dict[str, str] | None]] = [(n, None) for n in notes_list]
    for d in descendants or []:
        provenance = {"item_id": str(d.get("id") or ""), "item_name": d.get("name") or ""}
        for n in ensure_list(d.get("notes") or []):
            if isinstance(n, dict):
                sources.append((n, provenance))
    _attach_filings(turns, sources)
    if since:
        turns = [t for t in turns if _after(t.get("created"), since)]
    return turns


# Ordering rank for the live band: active work first, then output awaiting review, then idle threads.
_STATUS_RANK = {"in_flight": 0, "awaiting_review": 1, "open": 2}


def _inflight_status(tags: set[str]) -> str:
    """Derive an in-flight item's status from its tags (precedence: in_flight > awaiting_review >
    open). `#ai_chat_requested` = a me-turn awaits the worker; `#ai_output_review_needed` = the
    worker produced output awaiting review; otherwise a thread merely exists (`#ai_chat`)."""
    if AI_CHAT_REQUESTED in tags:
        return "in_flight"
    if AI_OUTPUT_REVIEW_NEEDED in tags:
        return "awaiting_review"
    return "open"


def build_inflight(parsed: list[dict[str, Any]]) -> dict[str, Any]:
    """Flat parsed tasks → the cross-project live-band set for the conversation cockpit (F3).

    Selection: incomplete tasks carrying `#ai_chat` (an open CHAT thread), NOT `#test` — the thread
    lives on active work, mirroring `gtd_chat_thread`'s resolution discipline. Each item carries the
    context the band needs to render a chip and load+open it:
        {task_id, name, scope ("item"|"project"), status ("in_flight"|"awaiting_review"|"open"),
         project_id, project_name, last_activity}.

    - `scope` = "project" when the task itself carries `#project`, else "item".
    - `project_id`/`project_name` = the nearest `#project` ancestor (the task itself when it IS a
      project). Resolved by walking `parent_task_id` via `project_plan._ancestor_chain`. A loose item
      with no `#project` ancestor keeps `project_id=""`/`project_name=""` (chip shows; can't load).
    - `last_activity` = the most-recent CHAT note's `created` (RTM's UTC value, not re-localised —
      the localised display stamp lives in the note title), `""` when there are no CHAT turns.

    Sorted by status (in_flight → awaiting_review → open), then most-recent activity, then name — a
    deterministic urgency order. Returns `{"items": [...], "count": len(items)}` (empty → count 0).
    """
    by_id = {t["id"]: t for t in parsed}
    items: list[dict[str, Any]] = []

    for t in parsed:
        tags = {normalize_tag(tg) for tg in (t.get("tags") or [])}
        if AI_CHAT not in tags or _TEST_TAG in tags or t.get("completed"):
            continue

        scope = "project" if _PROJECT_TAG in tags else "item"
        # nearest #project ancestor (self when this task is a project) — the chain is
        # root-first, so walk it leaf-first: the first #project-tagged entry from the
        # leaf end is the NEAREST enclosing project (root-first would pick the topmost
        # when projects nest, e.g. P1 → P2 → item must attribute to P2).
        proj = None
        for aid in reversed(_ancestor_chain(t["id"], by_id)):
            row = by_id.get(aid)
            if row and _PROJECT_TAG in {normalize_tag(tg) for tg in (row.get("tags") or [])}:
                proj = row
                break

        turns = build_thread(t.get("notes") or [])
        last_activity = turns[-1]["created"] if turns else ""

        items.append(
            {
                "task_id": t["id"],
                "name": t.get("name") or "",
                "scope": scope,
                "status": _inflight_status(tags),
                "project_id": proj["id"] if proj else "",
                "project_name": (proj.get("name") or "") if proj else "",
                "last_activity": last_activity or "",
            }
        )

    # Stable multi-pass sort (least-significant key first): status asc, then last_activity desc
    # (most-recent first; undated "" sorts last under reverse), then name asc. No clock dependency,
    # so the order is deterministic.
    items.sort(key=lambda i: i["name"].lower())
    items.sort(key=lambda i: i["last_activity"], reverse=True)
    items.sort(key=lambda i: _STATUS_RANK.get(i["status"], 9))
    return {"items": items, "count": len(items)}
