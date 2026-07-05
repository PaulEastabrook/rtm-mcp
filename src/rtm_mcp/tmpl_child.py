"""Template-child token stamping — the `tmpl-child/1` write grammar (WRITE side).

Pure (no IO) helpers backing token stamping for repeating templated projects
(repeating-templated-project Wave B). A durable per-child token (8 lowercase hex) rides a
TMPL-CHILD note that RTM copies verbatim onto every new occurrence, so the token — and any
DEPENDS-ON dep authored against it — survives the re-keying that recurrence performs on
`task_id`/`taskseries_id`. The READ side already resolves these tokens
(`project_plan._extract_deps_and_files` surfaces `row.template_child_id` + token-space deps;
`plan_graph._resolve_ref` maps a token to the current occurrence's id, v1.24.0); this module
WRITES them.

Grammar (note-shape-catalogue § 5b, ratified — do not vary):
    TMPL-CHILD note: title  `YYYY-MM-DD — TMPL-CHILD — <slug>`
                     body   `{"schema": "tmpl-child/1", "template_child_id": "<slug>"}`
    DEPENDS-ON gains an additive `Template-child-id: "<upstream-slug>"` line (the raw
    `task_id:` line is retained as the human/fallback reference).

RTM note storage reality (verified live 2026-07-05): `rtm.tasks.notes.add`/`.edit` store the
body as ``<note_title>\n<note_text>`` and return an EMPTY title field on read (the same fact the
CHAT/ORDER note grammars rely on). So a note round-trips as (first-line title, remaining-lines
text): to append a line we split the read body on the first newline, keep line 1 as the title,
and edit with the remainder + the new line as the text.

One-off projects are never stamped — no `is_repeating` ⇒ no children pass the caller's gate ⇒
`token_map` stays empty ⇒ the read path is byte-identical (the one-off parity golden proves it).
"""

import re
import secrets
from collections.abc import Callable
from typing import Any

SCHEMA = "tmpl-child/1"
# The row's own token (JSON body of a tmpl-child/1 note) and the DEPENDS-ON token line — the
# same patterns the read side matches, kept here so the write side detects idempotently by the
# exact shape the reader will later resolve.
_CHILD_TOKEN_RE = re.compile(r'"template_child_id"\s*:\s*"([^"]+)"')
_TOKEN_LINE_RE = re.compile(r'Template-child-id:\s*"?([A-Za-z0-9_-]+)"?')
_UPSTREAM_TASK_RE = re.compile(r'task_id:\s*"?(\d+)"?')


def new_slug() -> str:
    """A fresh 8-lowercase-hex template-child token (``secrets.token_hex(4)``)."""
    return secrets.token_hex(4)


def make_tmpl_child_note(slug: str, date_str: str) -> tuple[str, str]:
    """(note_title, note_text) for a TMPL-CHILD note. `date_str` is a localised ``YYYY-MM-DD``."""
    return (
        f"{date_str} — TMPL-CHILD — {slug}",
        f'{{"schema": "{SCHEMA}", "template_child_id": "{slug}"}}',
    )


def note_child_token(body: str) -> str:
    """The template-child slug a `tmpl-child/1` note body carries, or "" when absent/invalid.

    The validator per § 5b: the body must name the `tmpl-child/1` schema AND carry a non-empty
    `template_child_id` — a title-line-only match (the slug appears in the TMPL-CHILD title too)
    is not enough, which is why the JSON key is required."""
    if SCHEMA not in body:
        return ""
    m = _CHILD_TOKEN_RE.search(body)
    return m.group(1) if m else ""


def is_active_depends_on(body: str) -> bool:
    """True for an ACTIVE DEPENDS-ON note body — the reader's exact gate (literal ``DEPENDS-ON``,
    status not resolved/obsolete). These are the notes the back-fill re-authors in token-space, so
    detection matches `project_plan._extract_deps_and_files` line-for-line."""
    if "DEPENDS-ON" not in body:
        return False
    si = body.find("Status:")
    status = body[si + 7 : si + 40] if si >= 0 else ""
    return "resolved" not in status and "obsolete" not in status


def depends_on_upstream_id(body: str) -> str:
    """The raw upstream `task_id` from a DEPENDS-ON body, or "" when absent (the id we map to the
    upstream child's slug to author the token line)."""
    m = _UPSTREAM_TASK_RE.search(body)
    return m.group(1) if m else ""


def has_token_line(body: str) -> bool:
    """True when a DEPENDS-ON body already carries a `Template-child-id:` line (idempotency)."""
    return bool(_TOKEN_LINE_RE.search(body))


def add_token_line(body: str, upstream_slug: str) -> tuple[str, str]:
    """Split a read note body into (note_title, note_text) with the additive `Template-child-id:`
    line appended to the text — the form `rtm.tasks.notes.edit` round-trips (stored body =
    ``title\ntext``, so the re-read body is the original + the new line)."""
    title, _, rest = body.partition("\n")
    rest = rest.rstrip("\n")
    line = f'Template-child-id: "{upstream_slug}"'
    return title, (f"{rest}\n{line}" if rest else line)


def plan_backfill(
    children: list[dict[str, Any]], *, slug_gen: Callable[[], str] = new_slug
) -> dict[str, Any]:
    """Compute the idempotent token back-fill plan for a repeating project's open children.

    `children`: ``[{"id", "name", "notes": [{"id", "body"}]}]`` — the project's open child tasks
    with their raw note (id, body) pairs.

    Returns:
        {
          "assign":    {child_id: slug},   # unstamped children → a fresh unique slug (TMPL-CHILD)
          "tokens":    {child_id: slug},   # every child's effective slug (existing OR newly assigned)
          "dep_edits": [{child_id, note_id, upstream_id, upstream_slug, note_title, note_text}],
        }

    Idempotent: a child already carrying a `tmpl-child/1` token keeps it (never re-slugged — RTM
    has already propagated that identity across occurrences); a DEPENDS-ON note already carrying
    the `Template-child-id:` line is left alone. A dep whose upstream is not among the stamped open
    siblings (e.g. a completed upstream) keeps its raw `task_id` — the line is only authored when
    the upstream slug is known. `slug_gen` is injectable for deterministic tests."""
    # 1. Existing tokens (read from each child's tmpl-child/1 note, first wins).
    tokens: dict[str, str] = {}
    used: set[str] = set()
    for ch in children:
        for n in ch.get("notes") or []:
            tok = note_child_token(n.get("body") or "")
            if tok:
                tokens[ch["id"]] = tok
                used.add(tok)
                break

    # 2. Assign a fresh unique slug to each unstamped child.
    assign: dict[str, str] = {}
    for ch in children:
        if ch["id"] in tokens:
            continue
        slug = slug_gen()
        while slug in used:
            slug = slug_gen()
        used.add(slug)
        assign[ch["id"]] = slug
        tokens[ch["id"]] = slug

    # 3. Re-author each active DEPENDS-ON note lacking the token line, when the upstream slug is
    #    resolvable among these siblings.
    dep_edits: list[dict[str, Any]] = []
    for ch in children:
        for n in ch.get("notes") or []:
            body = n.get("body") or ""
            if not is_active_depends_on(body) or has_token_line(body):
                continue
            up_id = depends_on_upstream_id(body)
            up_slug = tokens.get(up_id)
            if not up_slug:
                continue  # upstream not a stamped open sibling — keep the raw id fallback
            note_title, note_text = add_token_line(body, up_slug)
            dep_edits.append(
                {
                    "child_id": ch["id"],
                    "note_id": n.get("id"),
                    "upstream_id": up_id,
                    "upstream_slug": up_slug,
                    "note_title": note_title,
                    "note_text": note_text,
                }
            )

    return {"assign": assign, "tokens": tokens, "dep_edits": dep_edits}
