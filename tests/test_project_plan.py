"""Tests for the project-plan envelope builder (src/rtm_mcp/project_plan.py)."""

from rtm_mcp.config import RTM_WEB_BASE_URL
from rtm_mcp.project_plan import (
    SCHEMA,
    build_envelope,
    resolve_focus,
    resolve_project,
)

PROJECT_ID = "1195689993"
LIST_ID = "49657585"
AREA_ID = "957240854"  # the project's parent — deliberately NOT in the fetched set


def _t(
    id,
    name="Task",
    parent="",
    list_id=LIST_ID,
    priority="N",
    completed=None,
    due=None,
    start=None,
    estimate=None,
    url=None,
    tags=None,
    notes=None,
    deleted=None,
):
    """Build a task dict in the shape parse_tasks_response emits."""
    return {
        "id": id,
        "taskseries_id": "ts" + id,
        "list_id": list_id,
        "name": name,
        "due": due,
        "start": start,
        "completed": completed,
        "deleted": deleted,
        "priority": priority,
        "estimate": estimate,
        "tags": tags or [],
        "notes": notes or [],
        "url": url,
        "parent_task_id": parent or None,
    }


def _note(body, created="2026-06-15T10:00:00Z"):
    """Raw RTM note dict (body in the $t XML text node)."""
    return {"id": "n", "created": created, "title": "", "$t": body}


def _sample_parsed():
    depends = _note(
        "2026-06-15 — DEPENDS-ON — needs upstream\n"
        'Upstream RTM IDs:\n  task_id: "1200224403"\n  list_id: "49657585"\n'
        "Status: active\n"
    )
    files_note = _note(
        "ref: AI Memory/personal/sam/reference/notes.md\n"
        "idx: AI Memory/personal/sam/reference/_index.md\n"
        "out: output/draft.md\n"
    )
    return [
        _t(
            PROJECT_ID,
            name="Sam's university open days",
            parent=AREA_ID,
            tags=["ai_conversation", "personal", "project"],
            notes=[_note("2026-04-05 — INCEPTION — the project")],
        ),
        _t(
            "c1",
            name="Attend webinar",
            parent=PROJECT_ID,
            priority="1",
            due="2026-07-03T00:00:00Z",
            tags=["action"],
            notes=[depends, files_note],
        ),
        _t(
            "c2",
            name="Done thing",
            parent=PROJECT_ID,
            completed="2026-06-15T12:00:00Z",
            tags=["action"],
        ),
        _t("c3", name=None, parent=PROJECT_ID, estimate=None, url=None),
        _t("g1", name="grandchild", parent="c1"),  # NOT a direct child → not a row
    ]


class TestBuildEnvelope:
    def test_header_shape(self):
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        h = env["header"]
        assert h["type"] == "header"
        assert h["schema"] == SCHEMA == "project-plan-seed/3"
        assert h["projectId"] == PROJECT_ID
        assert h["project"]["name"] == "Sam's university open days"
        assert h["project"]["life"] == "personal"  # first life-context tag
        assert h["project"]["listId"] == LIST_ID
        assert h["project"]["files"] == []  # INCEPTION note carries no filed path
        assert h["rowCount"] == 3  # c1, c2, c3 — grandchild excluded

    def test_header_redacted_flag(self):
        # header.project.redacted derives from the project task's own #redacted tag (drives the
        # canvas frame's locked screen). Absent tag → False.
        assert (
            build_envelope(_sample_parsed(), PROJECT_ID)["header"]["project"]["redacted"] is False
        )
        redacted = [
            _t(PROJECT_ID, parent=AREA_ID, tags=["project", "personal", "redacted"]),
            _t("c1", parent=PROJECT_ID, tags=["action"]),
        ]
        assert build_envelope(redacted, PROJECT_ID)["header"]["project"]["redacted"] is True

    def test_project_permalink_includes_absent_ancestor(self):
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        assert h_perma(env) == f"{RTM_WEB_BASE_URL}#list/{LIST_ID}/{AREA_ID}/{PROJECT_ID}"

    def test_project_notes_full_body_from_dollar_t(self):
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        notes = env["header"]["project"]["notes"]
        assert notes[0]["body"] == "2026-04-05 — INCEPTION — the project"
        assert notes[0]["summary"] == "2026-04-05 — INCEPTION — the project"
        assert notes[0]["date"] == "2026-06-15"

    def test_note_objects_carry_note_id(self):
        # DC-4: the ORDER-note resolver tie-breaks by RTM note id, so every envelope note
        # object (header.project.notes AND row notes) carries `id` — additive to the
        # project-plan-seed/3 reference shape.
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        assert env["header"]["project"]["notes"][0]["id"] == "n"
        row_notes = [n for r in env["rows"] for n in r["notes"]]
        assert row_notes and all(n["id"] == "n" for n in row_notes)

    def test_project_level_files_from_project_notes(self):
        # Project-level support material: filed paths scraped from the PROJECT's own notes,
        # AI Memory/ prefix stripped — the analog of row files[] (additive to the envelope).
        parsed = [
            _t(
                PROJECT_ID,
                parent=AREA_ID,
                tags=["project", "personal"],
                notes=[_note("REFERENCE: AI Memory/personal/sam/reference/cert.pdf")],
            ),
            _t("c1", parent=PROJECT_ID, tags=["action"]),
        ]
        env = build_envelope(parsed, PROJECT_ID)
        assert env["header"]["project"]["files"] == ["personal/sam/reference/cert.pdf"]

    def test_row_priority_word_form_and_permalink(self):
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        c1 = _row(env, "c1")
        assert c1["priority"] == "High"
        assert c1["due"] == "2026-07-03"
        assert c1["completed"] == 0
        assert c1["permalink"] == f"{RTM_WEB_BASE_URL}#list/{LIST_ID}/{AREA_ID}/{PROJECT_ID}/c1"

    def test_row_deps_and_files(self):
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        c1 = _row(env, "c1")
        assert c1["deps"] == ["1200224403"]
        # AI Memory/ prefix stripped; _-prefixed companion dropped; output/ kept; dedup by basename
        assert c1["files"] == ["personal/sam/reference/notes.md", "output/draft.md"]
        assert c1["noteCount"] == 2

    def test_completed_row(self):
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        c2 = _row(env, "c2")
        assert c2["completed"] == 1
        assert c2["completedDate"] == "2026-06-15"
        assert c2["priority"] == "NoPriority"

    def test_none_coerced_to_empty_string(self):
        env = build_envelope(_sample_parsed(), PROJECT_ID)
        c3 = _row(env, "c3")
        assert c3["name"] == ""
        assert c3["estimate"] == ""
        assert c3["url"] == ""
        assert c3["start"] == ""

    def test_resolved_dep_is_skipped(self):
        parsed = [
            _t(PROJECT_ID, parent=AREA_ID, tags=["project"]),
            _t(
                "c1",
                parent=PROJECT_ID,
                notes=[
                    _note('DEPENDS-ON\nUpstream RTM IDs:\n  task_id: "999"\nStatus: resolved\n')
                ],
            ),
        ]
        env = build_envelope(parsed, PROJECT_ID)
        assert _row(env, "c1")["deps"] == []

    def test_missing_project_yields_empty_header(self):
        # build_envelope tolerates an absent project (the tool guards against this separately)
        env = build_envelope([_t("c1", parent="someotherid")], PROJECT_ID)
        assert env["header"]["project"]["name"] == ""
        assert env["header"]["rowCount"] == 0
        assert env["rows"] == []


class TestTimezoneLocalisation:
    """Date fields are localised to the account tz before truncation (RTM returns UTC)."""

    def _wf(self, due=None, completed=None, note_created=None):
        notes = [_note("body", created=note_created)] if note_created else None
        return [
            _t(PROJECT_ID, parent=AREA_ID, tags=["project", "personal"]),
            _t(
                "c1",
                parent=PROJECT_ID,
                tags=["waiting_for"],
                due=due,
                completed=completed,
                notes=notes,
            ),
        ]

    def test_bst_midnight_due_keeps_local_day(self):
        # The exact live failure: a 22 Jun BST date-only due is on the wire as 21 Jun 23:00 UTC.
        env = build_envelope(
            self._wf(due="2026-06-21T23:00:00Z"), PROJECT_ID, timezone="Europe/London"
        )
        assert _row(env, "c1")["due"] == "2026-06-22"

    def test_gmt_due_unaffected(self):
        env = build_envelope(
            self._wf(due="2026-03-06T00:00:00Z"), PROJECT_ID, timezone="Europe/London"
        )
        assert _row(env, "c1")["due"] == "2026-03-06"

    def test_real_time_of_day_truncates_to_local_day(self):
        # 23:30 UTC on 21 Jun is 00:30 BST on 22 Jun → local calendar day is 22 Jun.
        env = build_envelope(
            self._wf(due="2026-06-21T23:30:00Z"), PROJECT_ID, timezone="Europe/London"
        )
        assert _row(env, "c1")["due"] == "2026-06-22"

    def test_no_timezone_falls_back_to_raw_truncation(self):
        env = build_envelope(self._wf(due="2026-06-21T23:00:00Z"), PROJECT_ID)  # tz omitted
        assert _row(env, "c1")["due"] == "2026-06-21"  # documented fallback, never raises

    def test_completed_date_localised(self):
        env = build_envelope(
            self._wf(completed="2026-06-21T23:30:00Z"), PROJECT_ID, timezone="Europe/London"
        )
        assert _row(env, "c1")["completedDate"] == "2026-06-22"

    def test_note_date_localised(self):
        env = build_envelope(
            self._wf(due="2026-07-01T00:00:00Z", note_created="2026-06-21T23:00:00Z"),
            PROJECT_ID,
            timezone="Europe/London",
        )
        assert _row(env, "c1")["notes"][0]["date"] == "2026-06-22"


class TestResolveProject:
    def _projects(self):
        return [
            _t("p1", name="Alpha plan", tags=["project", "personal"]),
            _t("p2", name="Alpha plan", tags=["project", "work"]),
            _t("p3", name="Beta plan", tags=["project"]),
            _t("p4", name="Done alpha", tags=["project"], completed="2026-01-01T00:00:00Z"),
            _t("p5", name="Test alpha", tags=["project", "test"]),
            _t("n1", name="Alpha note", tags=["action"]),  # not project-tagged
        ]

    def test_single_match(self):
        res = resolve_project(self._projects(), "Beta plan")
        assert res["project"]["id"] == "p3"

    def test_multiple_matches_returns_candidates(self):
        res = resolve_project(self._projects(), "Alpha plan")
        assert "candidates" in res
        ids = {c["id"] for c in res["candidates"]}
        assert ids == {"p1", "p2"}  # completed/test/non-project excluded

    def test_no_match(self):
        res = resolve_project(self._projects(), "Nonexistent")
        assert "error" in res

    def test_exact_beats_substring(self):
        parsed = [
            _t("p1", name="Open days", tags=["project"]),
            _t("p2", name="Open days summer trip", tags=["project"]),
        ]
        res = resolve_project(parsed, "Open days")
        assert res["project"]["id"] == "p1"


class TestResolveFocus:
    def _parsed(self):
        # Areas of focus carry no marker tag — they are the PARENTS of #project tasks.
        return [
            _t("a1", name="Personal"),
            _t("a2", name="Work"),
            _t("p1", name="Proj A", parent="a1", tags=["project", "personal"]),
            _t("p2", name="Proj B", parent="a2", tags=["project", "work"]),
        ]

    def test_by_name(self):
        assert resolve_focus(self._parsed(), "Personal")["focus"]["id"] == "a1"

    def test_by_id(self):
        # an explicit parent id the caller names resolves directly (even with no project under it)
        assert resolve_focus(self._parsed(), "a2")["focus"]["id"] == "a2"

    def test_substring_match(self):
        assert resolve_focus(self._parsed(), "person")["focus"]["id"] == "a1"

    def test_ambiguous_name_returns_candidates(self):
        parsed = [
            _t("a1", name="Family"),
            _t("a2", name="Family"),
            _t("p1", name="P1", parent="a1", tags=["project"]),
            _t("p2", name="P2", parent="a2", tags=["project"]),
        ]
        res = resolve_focus(parsed, "Family")
        assert {c["id"] for c in res["candidates"]} == {"a1", "a2"}

    def test_no_match_is_actionable_error(self):
        res = resolve_focus(self._parsed(), "Ghost")
        assert "error" in res
        assert "list_tasks" in res["error"]

    def test_empty_focus_error(self):
        assert "error" in resolve_focus(self._parsed(), "")

    def test_area_without_projects_not_matched_by_name(self):
        # an area with no project under it is not in the derived area set — pass its id instead
        parsed = [_t("a9", name="Empty Area")]
        assert "error" in resolve_focus(parsed, "Empty Area")


def h_perma(env):
    return env["header"]["project"]["permalink"]


def _row(env, row_id):
    return next(r for r in env["rows"] if r["id"] == row_id)
