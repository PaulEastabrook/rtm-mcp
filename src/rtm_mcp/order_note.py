"""The ORDER note contract (`order-note/1`) — durable manual plan-order intent (DC-4).

Pure (no IO), stdlib-only. Byte-compatible port of the gtd plugin's
`skills/gtd/scripts/order_note.py` (`make`/`parse`/`resolve`/`from_envelope` + `checksum`;
the CLI shim from the reference is dropped). The canonical grammar lives gtd-side in
`references/note-shape-catalogue.md` § 4a; both membrane sides run the same parse, so the
resolved order is identical everywhere.

The ORDER note is the SINGLE durable record of Paul's manual plan-order preference, living
on the RTM **project task** — RTM is the system of record for order *intent*; the
plan-graph `manual_order` is pure derivation (parsed from the latest valid ORDER note on
every read, never independently persisted state). RTM has no sibling-order field, so this
note IS how a board drag survives; it is append-only (superseded notes are retained —
latest-valid-wins makes pruning unnecessary).

TITLE:  ``YYYY-MM-DD HH:MM — ORDER — <n> items``      (account-localised wall-clock;
        singular "1 item")
BODY:   one strict JSON object, nothing else:
  {"schema": "order-note/1",
   "order": ["<rtm_task_id>", ...],                    # open-item ids, dragged sequence
   "count": <int == len(order)>,
   "sha256": "<first 16 hex of sha256 over '\\n'.join(order)>",
   "source": "board-commit" | "canvas-commit" | "backfill",
   "at": "<ISO-8601 UTC, e.g. 2026-07-05T09:41:12Z>"}

VERIFIABILITY: `count` and `sha256` are self-checks — a truncated, hand-edited, or
corrupted body fails closed (the note is ignored; resolution falls back to the next-latest
valid note). Duplicate ids, empty lists, unknown schema, malformed JSON: all invalid.

RESOLUTION (deterministic): latest valid wins — sort by `at` desc, then note id desc
(int-normalised), then checksum desc. Invalid notes never block; they are reported for
advisory surfacing.

ENGINE SEMANTICS (unchanged, `plan_graph.py`): the resolved order biases cosmetic tiering
only, never topology; unlisted ids fall to their cohort end; departed ids are pruned;
excluded from the overlay fingerprint (a preference, not an input).
"""

import hashlib
import json
import re
from typing import Any

SCHEMA = "order-note/1"
SOURCES = ("board-commit", "canvas-commit", "backfill")
# Space + EM DASH (U+2014) + space — the canonical note-title separator.
TITLE_RX = re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}\s*—\s*ORDER\s*—\s*(\d+)\s+items?\s*$")
_AT_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def checksum(ids: list[str]) -> str:
    """First 16 hex chars of sha256 over the newline-joined id list."""
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()[:16]


def make(ids: list[Any], source: str, at_utc: str, at_local: str) -> tuple[str, str]:
    """Writer helper: returns (title, body) for a conformant ORDER note."""
    ids = [str(i) for i in ids]
    if source not in SOURCES:
        raise ValueError(f"unknown source: {source!r}")
    title = f"{at_local} — ORDER — {len(ids)} item{'' if len(ids) == 1 else 's'}"
    body = json.dumps(
        {
            "schema": SCHEMA,
            "order": ids,
            "count": len(ids),
            "sha256": checksum(ids),
            "source": source,
            "at": at_utc,
        },
        ensure_ascii=False,
    )
    return title, body


def parse(title: str, body: str | None) -> dict[str, Any]:
    """Parse + verify one ORDER note. Returns {valid, order, at, source, errors[]}.
    Fails closed: any conformance breach → valid=False with named errors.

    RTM storage reality: the note title is the body's FIRST LINE (there is no separate
    title field), so some read paths hand back a body that still carries the title line.
    Tolerated deterministically: one leading line matching the ORDER title grammar is
    stripped before the strict-JSON parse; anything else extra remains invalid."""
    errors = []
    if not TITLE_RX.match(title or ""):
        errors.append("title: must be 'YYYY-MM-DD HH:MM — ORDER — <n> items'")
    body = body or ""
    first, _, rest = body.partition("\n")
    if TITLE_RX.match(first):
        body = rest
    try:
        obj = json.loads(body or "")
    except (ValueError, TypeError):
        return {
            "valid": False,
            "order": [],
            "at": None,
            "source": None,
            "errors": [*errors, "body: not valid JSON"],
        }
    if not isinstance(obj, dict):
        return {
            "valid": False,
            "order": [],
            "at": None,
            "source": None,
            "errors": [*errors, "body: not a JSON object"],
        }
    if obj.get("schema") != SCHEMA:
        errors.append(f"schema: expected {SCHEMA!r}")
    order = obj.get("order")
    if (
        not isinstance(order, list)
        or not order
        or not all(isinstance(i, str) and i.strip() for i in order)
    ):
        errors.append("order: must be a non-empty list of non-empty id strings")
        order = []
    elif len(set(order)) != len(order):
        errors.append("order: duplicate ids")
    if order and obj.get("count") != len(order):
        errors.append("count: does not match len(order)")
    if order and obj.get("sha256") != checksum(order):
        errors.append("sha256: checksum mismatch")
    if obj.get("source") not in SOURCES:
        errors.append(f"source: must be one of {', '.join(SOURCES)}")
    at = obj.get("at")
    if not (isinstance(at, str) and _AT_RX.match(at)):
        errors.append("at: must be an ISO-8601 UTC timestamp")
        at = None
    m = TITLE_RX.match(title or "")
    if m and order and int(m.group(1)) != len(order):
        errors.append("title: item count disagrees with body")
    valid = not errors
    return {
        "valid": valid,
        "order": order if valid else [],
        "at": at,
        "source": obj.get("source"),
        "errors": errors,
    }


def resolve(notes: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Deterministic resolution over a task's notes: latest valid ORDER wins.

    notes: [{"id": <note id>, "title": <first line>, "body": <rest>}, ...]
    Returns {"order": [ids]|None, "note_id": ..., "at": ..., "invalid": [{id, errors}]}.
    Sort: `at` desc, then note id desc (int-normalised, falling back to string), then
    the order checksum desc — the final key makes resolution fully deterministic even
    when a read path carries no note ids and two notes share a wall-clock second."""
    candidates, invalid = [], []
    for n in notes or []:
        title = n.get("title") or ""
        if "ORDER" not in title:
            continue
        if not re.search(r"—\s*ORDER\s*—", title):
            continue
        p = parse(title, n.get("body"))
        if p["valid"]:
            candidates.append((p["at"], _idkey(n.get("id")), checksum(p["order"]), n.get("id"), p))
        else:
            invalid.append({"id": n.get("id"), "errors": p["errors"]})
    if not candidates:
        return {"order": None, "note_id": None, "at": None, "invalid": invalid}
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    at, _, _, note_id, p = candidates[0]
    return {"order": p["order"], "note_id": note_id, "at": at, "invalid": invalid}


def from_envelope(env: dict[str, Any]) -> dict[str, Any]:
    """Resolve the ORDER preference straight from a project-plan-seed envelope.

    The envelope's `header.project.notes` raw shape is [{date, summary, body, id?}, ...]
    (summary = the title first-line). One derivation for every consumer — the gtd overlay
    refresh (plan_graph_refresh) and this server's thin plan-graph — so there is exactly
    one truth and one parse."""
    raw = ((env.get("header") or {}).get("project") or {}).get("notes") or []
    return resolve(
        [
            {"id": n.get("id"), "title": n.get("summary") or "", "body": n.get("body") or ""}
            for n in raw
        ]
    )


def _idkey(nid: Any) -> tuple[int, int, str]:
    try:
        return (0, int(nid), "")
    except (TypeError, ValueError):
        return (1, 0, str(nid or ""))
