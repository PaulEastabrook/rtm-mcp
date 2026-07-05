"""Tests for order_note — the ORDER note contract (order-note/1), DC-4.

Mirrors the gtd plugin's `test_order_note.py` (parity is provable case-for-case), plus the
server-specific title-line-in-body tolerance and `from_envelope` coverage.
"""

import json

import pytest

from rtm_mcp.order_note import SCHEMA, checksum, from_envelope, make, parse, resolve


def _note(
    nid,
    ids,
    at="2026-07-05T09:41:12Z",
    local="2026-07-05 10:41",
    source="board-commit",
    mangle=None,
):
    title, body = make(ids, source, at, local)
    if mangle:
        title, body = mangle(title, body)
    return {"id": nid, "title": title, "body": body}


class TestMakeParse:
    def test_round_trip(self):
        title, body = make(
            ["11", "22", "33"], "board-commit", "2026-07-05T09:41:12Z", "2026-07-05 10:41"
        )
        assert title == "2026-07-05 10:41 — ORDER — 3 items"
        p = parse(title, body)
        assert p["valid"], p["errors"]
        assert p["order"] == ["11", "22", "33"]
        assert p["source"] == "board-commit"

    def test_singular_item_title(self):
        title, _ = make(["11"], "backfill", "2026-07-05T09:41:12Z", "2026-07-05 10:41")
        assert title == "2026-07-05 10:41 — ORDER — 1 item"

    def test_unknown_source_rejected_at_write(self):
        with pytest.raises(ValueError):
            make(["1"], "weekly-review", "2026-07-05T09:41:12Z", "2026-07-05 10:41")

    def test_checksum_mismatch_fails_closed(self):
        n = _note("1", ["11", "22"], mangle=lambda t, b: (t, b.replace('"11", "22"', '"22", "11"')))
        p = parse(n["title"], n["body"])
        assert not p["valid"]
        assert any("sha256" in e for e in p["errors"])
        assert p["order"] == []

    def test_count_mismatch_fails_closed(self):
        n = _note("1", ["11", "22"], mangle=lambda t, b: (t, b.replace('"count": 2', '"count": 3')))
        assert not parse(n["title"], n["body"])["valid"]

    def test_title_count_disagreement_fails_closed(self):
        n = _note("1", ["11", "22"], mangle=lambda t, b: (t.replace("2 items", "5 items"), b))
        p = parse(n["title"], n["body"])
        assert not p["valid"]
        assert any("title" in e for e in p["errors"])

    def test_duplicate_ids_invalid(self):
        body = json.dumps(
            {
                "schema": SCHEMA,
                "order": ["1", "1"],
                "count": 2,
                "sha256": checksum(["1", "1"]),
                "source": "board-commit",
                "at": "2026-07-05T09:41:12Z",
            }
        )
        assert not parse("2026-07-05 10:41 — ORDER — 2 items", body)["valid"]

    def test_non_json_body_invalid(self):
        p = parse("2026-07-05 10:41 — ORDER — 2 items", "11, 22")
        assert not p["valid"]
        assert any("JSON" in e for e in p["errors"])

    def test_wrong_schema_invalid(self):
        n = _note("1", ["11"], mangle=lambda t, b: (t, b.replace("order-note/1", "order-note/9")))
        assert not parse(n["title"], n["body"])["valid"]

    def test_bad_at_invalid(self):
        n = _note(
            "1", ["11"], mangle=lambda t, b: (t, b.replace("2026-07-05T09:41:12Z", "yesterday"))
        )
        assert not parse(n["title"], n["body"])["valid"]

    def test_title_line_in_body_tolerated(self):
        """RTM storage reality: the title is the note body's FIRST LINE (there is no separate
        title field), so a read path hands back title\\nJSON as the body — one leading ORDER
        title line is stripped before the strict-JSON parse."""
        title, body = make(["11", "22"], "board-commit", "2026-07-05T09:41:12Z", "2026-07-05 10:41")
        p = parse(title, f"{title}\n{body}")
        assert p["valid"], p["errors"]
        assert p["order"] == ["11", "22"]


class TestResolve:
    def test_latest_valid_wins_by_at(self):
        notes = [
            _note("1", ["a1", "a2"], at="2026-07-01T08:00:00Z"),
            _note("2", ["b1", "b2"], at="2026-07-05T08:00:00Z"),
        ]
        r = resolve(notes)
        assert r["order"] == ["b1", "b2"]
        assert r["note_id"] == "2"

    def test_at_tie_broken_by_note_id_desc(self):
        notes = [
            _note("10", ["a1"], at="2026-07-05T08:00:00Z"),
            _note("9", ["b1"], at="2026-07-05T08:00:00Z"),
        ]
        assert resolve(notes)["order"] == ["a1"]

    def test_invalid_latest_falls_back_to_previous_valid(self):
        notes = [
            _note("1", ["a1", "a2"], at="2026-07-01T08:00:00Z"),
            _note("2", ["b1", "b2"], at="2026-07-05T08:00:00Z", mangle=lambda t, b: (t, b[:-20])),
        ]  # truncated/corrupted
        r = resolve(notes)
        assert r["order"] == ["a1", "a2"]
        assert [i["id"] for i in r["invalid"]] == ["2"]

    def test_no_order_notes_returns_none(self):
        r = resolve([{"id": "5", "title": "2026-07-01 — CONTEXT — something", "body": "x"}])
        assert r["order"] is None
        assert r["invalid"] == []

    def test_non_order_notes_ignored_not_flagged(self):
        notes = [
            {"id": "5", "title": "2026-07-01 — DECISION — pick ORDER of play", "body": "x"},
            _note("6", ["a1"]),
        ]
        r = resolve(notes)
        assert r["order"] == ["a1"]
        assert r["invalid"] == []

    def test_deterministic_across_input_order(self):
        notes = [
            _note(str(i), [f"x{i}"], at=f"2026-07-0{1 + i % 5}T08:00:00Z") for i in range(1, 6)
        ]
        assert resolve(notes) == resolve(list(reversed(notes)))


class TestFromEnvelope:
    def test_resolves_from_header_project_notes(self):
        title, body = make(["c2", "c1"], "board-commit", "2026-07-05T09:41:12Z", "2026-07-05 10:41")
        env = {
            "header": {
                "project": {
                    "notes": [
                        {
                            "id": "n1",
                            "date": "2026-07-04",
                            "summary": "INCEPTION",
                            "body": "INCEPTION",
                        },
                        # The envelope note shape: summary = the title first-line; body = the
                        # full stored body (title line + JSON — the RTM storage reality).
                        {
                            "id": "n2",
                            "date": "2026-07-05",
                            "summary": title,
                            "body": f"{title}\n{body}",
                        },
                    ]
                }
            },
            "rows": [],
        }
        r = from_envelope(env)
        assert r["order"] == ["c2", "c1"]
        assert r["note_id"] == "n2"

    def test_empty_envelope_returns_none(self):
        assert from_envelope({"header": {"project": {}}, "rows": []})["order"] is None
