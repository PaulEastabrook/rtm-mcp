"""Tests for canvas_seed — the project-plan-seed envelope → canvas seed mapper."""

from rtm_mcp.canvas_seed import (
    build_seed,
    map_comms,
    map_context,
    map_kind,
    map_priority,
    map_row,
    parse_file,
    parse_note,
)


class TestScalarMappers:
    def test_map_kind_from_tags(self):
        assert map_kind(["waiting_for"]) == "waiting_for"
        assert map_kind(["calendar_entry"]) == "calendar"
        assert map_kind(["action"]) == "action"
        assert map_kind([]) == "action"

    def test_map_priority_word_to_code(self):
        assert map_priority("High") == "1"
        assert map_priority("Medium") == "2"
        assert map_priority("Low") == "3"
        assert map_priority("NoPriority") == ""
        assert map_priority(None) == ""

    def test_map_context_default(self):
        assert map_context(["location_office"]) == "location_office"
        assert map_context(["action"]) == "using_device"  # default

    def test_map_comms_optional(self):
        assert map_comms(["conversation_email"]) == "conversation_email"
        assert map_comms(["action"]) == ""


class TestParseNote:
    def test_dash_type_form_keeps_body(self):
        n = parse_note(
            {
                "date": "2026-04-06",
                "summary": "— CONTEXT — Talked to Sam",
                "body": "— CONTEXT — Talked to Sam\nmore detail",
            }
        )
        assert n["t"] == "CONTEXT"
        assert n["s"] == "Talked to Sam"
        assert n["b"] == "— CONTEXT — Talked to Sam\nmore detail"

    def test_colon_type_form(self):
        n = parse_note(
            {
                "date": "2026-04-06",
                "summary": "2026-04-06 OUTPUT: Delivered the draft",
                "body": "2026-04-06 OUTPUT: Delivered the draft",
            }
        )
        assert n["t"] == "OUTPUT"
        assert n["s"] == "Delivered the draft"
        # body retains the date/type prefix the gist stripped → differs from gist → kept
        assert n["b"] == "2026-04-06 OUTPUT: Delivered the draft"

    def test_plain_note_omits_body(self):
        n = parse_note({"date": "", "summary": "Plain note", "body": "Plain note"})
        assert n["t"] == "NOTE"
        assert n["s"] == "Plain note"
        assert "b" not in n


class TestParseFile:
    def test_filed_output_path(self):
        f = parse_file("work/Area/project/output/report.pdf")
        assert f == {
            "n": "report.pdf",
            "ext": "pdf",
            "kind": "output",
            "path": "work/Area/project/output/report.pdf",
        }

    def test_reference_kind(self):
        f = parse_file("personal/x/reference/notes.md")
        assert f is not None
        assert f["kind"] == "reference"

    def test_non_filed_path_rejected(self):
        assert parse_file("Downloads/foo.pdf") is None
        assert parse_file("") is None
        assert parse_file(None) is None


class TestMapRow:
    def test_action_gets_context_comms_priority(self):
        item = map_row(
            {
                "id": "c1",
                "name": "A",
                "tags": ["action", "location_office", "conversation_email"],
                "priority": "High",
                "completed": 0,
                "permalink": "u",
                "notes": [],
                "files": [],
            }
        )
        assert item["k"] == "action"
        assert item["c"] == "location_office"
        assert item["m"] == "conversation_email"
        assert item["p"] == "1"
        assert "hx" not in item

    def test_waiting_for_carries_due(self):
        item = map_row(
            {
                "id": "w",
                "name": "W",
                "tags": ["waiting_for"],
                "due": "2026-07-01",
                "completed": 0,
                "permalink": "u",
                "notes": [],
                "files": [],
            }
        )
        assert item["k"] == "waiting_for"
        assert item["d"] == "2026-07-01"
        assert "c" not in item  # no context on waiting-for

    def test_completed_becomes_history_row(self):
        item = map_row(
            {
                "id": "d",
                "name": "D",
                "tags": ["action"],
                "completed": 1,
                "completedDate": "2026-06-15",
                "permalink": "u",
                "notes": [],
                "files": [],
            }
        )
        assert item["hx"] == 1
        assert item["cd"] == "2026-06-15"

    def test_nc_honest_when_notes_capped(self):
        item = map_row(
            {
                "id": "c",
                "name": "C",
                "tags": ["action"],
                "completed": 0,
                "permalink": "u",
                "noteCount": 5,
                "notes": [{"date": "", "summary": "one", "body": "one"}],
                "files": [],
            }
        )
        assert item["nc"] == 5  # true total exceeds emitted notes


class TestBuildSeed:
    def _header(self):
        return {
            "project": {
                "id": "P",
                "life": "work",
                "name": "Proj",
                "permalink": "http://rtm/P",
                "notes": [{"date": "2026-01-01", "summary": "INCEPTION", "body": "INCEPTION"}],
            }
        }

    def _rows(self):
        return [
            {
                "id": "c1",
                "name": "First",
                "tags": ["action"],
                "priority": "NoPriority",
                "completed": 0,
                "due": "",
                "permalink": "u1",
                "deps": ["c2"],
                "files": [],
                "noteCount": 0,
                "notes": [],
            },
            {
                "id": "c2",
                "name": "Second",
                "tags": ["action"],
                "priority": "NoPriority",
                "completed": 0,
                "due": "",
                "permalink": "u2",
                "deps": ["zzz"],
                "files": [],
                "noteCount": 0,
                "notes": [],
            },
            {
                "id": "c3",
                "name": "Done",
                "tags": ["action"],
                "priority": "NoPriority",
                "completed": 1,
                "completedDate": "2026-06-10",
                "due": "",
                "permalink": "u3",
                "deps": [],
                "files": [],
                "noteCount": 0,
                "notes": [],
            },
        ]

    def test_frame_and_mode(self):
        seed = build_seed(self._header(), self._rows())
        assert seed["mode"] == "existing"
        assert seed["frame"]["life"] == "work"
        assert seed["frame"]["name"] == "Proj"
        assert seed["frame"]["url"] == "http://rtm/P"
        assert seed["frame"]["notes"][0]["t"] == "NOTE"

    def test_deps_filtered_to_siblings(self):
        seed = build_seed(self._header(), self._rows())
        by_id = {it["id"]: it for it in seed["seed"]}
        assert by_id["c1"]["deps"] == ["c2"]  # in-plan sibling kept
        assert "deps" not in by_id["c2"]  # "zzz" not a sibling → dropped

    def test_open_before_completed(self):
        seed = build_seed(self._header(), self._rows())
        order = [it["id"] for it in seed["seed"]]
        assert order.index("c3") == len(order) - 1  # completed history last
        assert order.index("c1") < order.index("c3")

    def test_frame_files_from_project_files_v1(self):
        # v1 / vault-companion branch (outputs_index=None): frame.files comes from the project's
        # own note-scraped files, mapped via parse_file (non-filed paths rejected).
        header = self._header()
        header["project"]["files"] = ["work/area/proj/reference/cert.pdf", "scratch.md"]
        seed = build_seed(header, self._rows())
        files = seed["frame"]["files"]
        assert [f["n"] for f in files] == ["cert.pdf"]  # only the genuine filed artefact
        assert files[0]["kind"] == "reference"
