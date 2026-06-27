"""Tests for the portfolio-index builder (src/rtm_mcp/project_index.py)."""

from rtm_mcp.project_index import build_actions, build_foci, build_index

AREA1 = "area1"
AREA2 = "area2"
P1 = "p1"


def _t(
    id,
    name="Task",
    parent="",
    list_id="L1",
    priority="N",
    completed=None,
    due=None,
    tags=None,
    notes=None,
    modified=None,
):
    """Task dict in the shape parse_tasks_response emits (subset used by build_index)."""
    return {
        "id": id,
        "taskseries_id": "ts" + id,
        "list_id": list_id,
        "name": name,
        "due": due,
        "start": None,
        "completed": completed,
        "deleted": None,
        "priority": priority,
        "estimate": None,
        "tags": tags or [],
        "notes": notes or [],
        "url": None,
        "parent_task_id": parent or None,
        "modified": modified,
    }


def _note(body, created="2026-06-15T10:00:00Z"):
    """Raw RTM note dict (body in the $t XML text node)."""
    return {"id": "n", "created": created, "title": "", "$t": body}


def _depends_on(upstream_id):
    return _note(
        f'DEPENDS-ON\nUpstream RTM IDs:\n  task_id: "{upstream_id}"\n'
        '  list_id: "L1"\nStatus: active\n'
    )


def _area(id, name, life=None, tags=None):
    return _t(
        id, name=name, tags=tags if tags is not None else (["focus"] + ([life] if life else []))
    )


def _portfolio():
    """A small multi-project account: one active project under AREA1 with three incomplete
    children (one blocked, dates incl. an overdue one), plus excluded projects."""
    return [
        _area(AREA1, "Sam — University", life="personal"),
        _area(AREA2, "Work — Platform", life="work"),
        _t(
            P1,
            name="Open days",
            parent=AREA1,
            priority="2",
            tags=["personal", "project"],
            modified="2026-06-20T23:30:00Z",  # BST → 2026-06-21 local
        ),
        # numeric child ids: DEPENDS-ON round-trips via a digits-only task_id regex (real RTM ids)
        _t("101", name="Attend webinar", parent=P1, due="2026-07-03T00:00:00Z", tags=["action"]),
        _t(
            "102",
            name="Book travel",
            parent=P1,
            due="2026-06-10T00:00:00Z",  # overdue
            tags=["action"],
            notes=[_depends_on("101")],  # blocked by sibling 101
        ),
        _t("103", name="Hear back", parent=P1, due="2026-07-15T00:00:00Z", tags=["waiting_for"]),
        # excluded projects
        _t("ps", name="Someday idea", parent=AREA2, tags=["work", "project", "someday"]),
        _t("ph", name="On hold", parent=AREA2, tags=["work", "project", "hold"]),
        _t("pt", name="Test project", parent=AREA1, tags=["personal", "project", "test"]),
        _t(
            "pc",
            name="Done project",
            parent=AREA2,
            tags=["work", "project"],
            completed="2026-06-01T00:00:00Z",
        ),
    ]


def _p1(rows):
    return next(r for r in rows if r["project_id"] == P1)


class TestSelection:
    def test_active_project_included(self):
        ids = {r["project_id"] for r in build_index(_portfolio())}
        assert P1 in ids

    def test_test_tag_excluded(self):
        ids = {r["project_id"] for r in build_index(_portfolio())}
        assert "pt" not in ids

    def test_someday_excluded_by_default(self):
        ids = {r["project_id"] for r in build_index(_portfolio())}
        assert "ps" not in ids

    def test_someday_included_when_opted_in(self):
        ids = {r["project_id"] for r in build_index(_portfolio(), include_someday=True)}
        assert "ps" in ids

    def test_hold_always_excluded(self):
        ids = {r["project_id"] for r in build_index(_portfolio(), include_someday=True)}
        assert "ph" not in ids

    def test_completed_project_excluded(self):
        ids = {r["project_id"] for r in build_index(_portfolio())}
        assert "pc" not in ids

    def test_empty_when_no_projects(self):
        assert build_index([_area(AREA1, "Sam — University")]) == []


class TestShape:
    def test_field_set(self):
        row = _p1(build_index(_portfolio()))
        assert set(row) == {
            "life",
            "focus",
            "focus_id",
            "project",
            "project_id",
            "priority",
            "open_count",
            "blocked_count",
            "next_tickle",
            "updated",
        }

    def test_project_name(self):
        assert _p1(build_index(_portfolio()))["project"] == "Open days"


class TestResolution:
    def test_life_from_tag(self):
        assert _p1(build_index(_portfolio()))["life"] == "personal"

    def test_focus_from_parent(self):
        row = _p1(build_index(_portfolio()))
        assert row["focus"] == "Sam — University"
        assert row["focus_id"] == AREA1

    def test_top_level_project_is_unfiled_not_dropped(self):
        parsed = [_t("top", name="Loose project", tags=["work", "project"])]
        rows = build_index(parsed)
        assert len(rows) == 1
        assert rows[0]["focus"] == "(unfiled)"
        assert rows[0]["focus_id"] == ""

    def test_priority_mapping(self):
        assert _p1(build_index(_portfolio()))["priority"] == "2"

    def test_priority_none_maps_to_empty(self):
        parsed = [
            _area(AREA1, "Sam — University"),
            _t(P1, name="Open days", parent=AREA1, priority="N", tags=["personal", "project"]),
        ]
        assert _p1(build_index(parsed))["priority"] == ""

    def test_updated_localised_to_account_tz(self):
        # modified is 2026-06-20T23:30:00Z → 2026-06-21 in Europe/London (BST); a raw [:10] would
        # wrongly yield 2026-06-20.
        row = _p1(build_index(_portfolio(), timezone="Europe/London"))
        assert row["updated"] == "2026-06-21"


class TestCounts:
    def test_open_count_all_incomplete_children(self):
        # a1 (action) + a2 (action) + wf1 (waiting_for) — all incomplete children counted.
        assert _p1(build_index(_portfolio()))["open_count"] == 3

    def test_blocked_count_from_depends_on_edge(self):
        # a2 depends on the open sibling a1 → exactly one blocked child.
        assert _p1(build_index(_portfolio()))["blocked_count"] == 1

    def test_next_tickle_earliest_including_overdue(self):
        # earliest open due across a1 (07-03), a2 (06-10 overdue), wf1 (07-15) → the overdue one.
        assert _p1(build_index(_portfolio()))["next_tickle"] == "2026-06-10"

    def test_next_tickle_empty_when_no_dated_items(self):
        parsed = [
            _area(AREA1, "Sam — University"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("a1", name="Undated", parent=P1, tags=["action"]),
        ]
        assert _p1(build_index(parsed))["next_tickle"] == ""


class TestSort:
    def test_sorted_by_life_then_focus_then_project(self):
        parsed = [
            _area(AREA1, "Sam — University"),
            _area(AREA2, "Work — Platform"),
            _t("wproj", name="Zeta", parent=AREA2, tags=["work", "project"]),
            _t("pproj", name="Alpha", parent=AREA1, tags=["personal", "project"]),
        ]
        order = [r["project_id"] for r in build_index(parsed)]
        # personal sorts before work
        assert order == ["pproj", "wproj"]


class TestFoci:
    def test_lists_all_focus_areas_including_empty(self):
        # AREA2 has only excluded projects under it (someday/hold/test/done) → no active project,
        # yet it must still appear in the focus list because it carries #focus.
        ids = {f["focus_id"] for f in build_foci(_portfolio())}
        assert ids == {AREA1, AREA2}

    def test_field_set(self):
        foci = build_foci(_portfolio())
        assert all(set(f) == {"focus_id", "focus", "life"} for f in foci)

    def test_life_from_tag(self):
        by_id = {f["focus_id"]: f for f in build_foci(_portfolio())}
        assert by_id[AREA1]["life"] == "personal"
        assert by_id[AREA2]["life"] == "work"

    def test_test_tag_excluded(self):
        parsed = [_area("aT", "Test focus", tags=["focus", "work", "test"])]
        assert build_foci(parsed) == []

    def test_hold_excluded(self):
        parsed = [_area("aH", "Held focus", tags=["focus", "work", "hold"])]
        assert build_foci(parsed) == []

    def test_someday_gated_by_include_someday(self):
        parsed = [_area("aS", "Someday focus", tags=["focus", "work", "someday"])]
        assert build_foci(parsed) == []
        assert {f["focus_id"] for f in build_foci(parsed, include_someday=True)} == {"aS"}

    def test_untagged_area_not_a_focus(self):
        # an Area-of-Focus parent that carries no #focus tag is NOT listed (the membership marker).
        parsed = [_area("aP", "Plain area", tags=[])]
        assert build_foci(parsed) == []

    def test_sorted_by_life_then_focus(self):
        order = [f["focus_id"] for f in build_foci(_portfolio())]
        assert order == [AREA1, AREA2]  # personal before work


class TestActions:
    def test_lists_incomplete_children_of_active_project(self):
        actions = build_actions(_portfolio())
        assert {a["action_id"] for a in actions} == {"101", "102", "103"}

    def test_field_set_and_attribution(self):
        a = next(a for a in build_actions(_portfolio()) if a["action_id"] == "101")
        assert set(a) == {
            "action_id",
            "name",
            "project_id",
            "project",
            "focus",
            "life",
            "due",
            "priority",
            "blocked",
        }
        assert a["name"] == "Attend webinar"
        assert a["project_id"] == P1
        assert a["project"] == "Open days"
        assert a["focus"] == "Sam — University"
        assert a["life"] == "personal"

    def test_test_tagged_action_excluded(self):
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("a1", name="Real", parent=P1, tags=["action"]),
            _t("a2", name="Hidden", parent=P1, tags=["action", "test"]),
        ]
        assert {a["action_id"] for a in build_actions(parsed)} == {"a1"}

    def test_action_under_excluded_project_not_emitted(self):
        # children under a #someday project are not emitted by default.
        parsed = [
            _area(AREA2, "Work — Platform", life="work"),
            _t("ps", name="Someday idea", parent=AREA2, tags=["work", "project", "someday"]),
            _t("sa", name="Someday action", parent="ps", tags=["action"]),
        ]
        assert build_actions(parsed) == []
        assert {a["action_id"] for a in build_actions(parsed, include_someday=True)} == {"sa"}

    def test_top_level_project_action_is_unfiled(self):
        parsed = [
            _t("top", name="Loose project", tags=["work", "project"]),
            _t("ta", name="Loose action", parent="top", tags=["action"]),
        ]
        a = build_actions(parsed)[0]
        assert a["focus"] == "(unfiled)"
        assert a["project"] == "Loose project"

    def test_sorted_grouped_deterministically(self):
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("b", name="Beta", parent=P1, tags=["action"]),
            _t("a", name="Alpha", parent=P1, tags=["action"]),
        ]
        names = [a["name"] for a in build_actions(parsed)]
        assert names == ["Alpha", "Beta"]


class TestActionUrgencyFields:
    def _by_id(self, **kwargs):
        return {a["action_id"]: a for a in build_actions(_portfolio(), **kwargs)}

    def test_due_carried_and_empty_when_absent(self):
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("d", name="Dated", parent=P1, due="2026-07-03T00:00:00Z", tags=["action"]),
            _t("u", name="Undated", parent=P1, tags=["action"]),
        ]
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["d"]["due"] == "2026-07-03"
        assert by_id["u"]["due"] == ""

    def test_due_localised_to_account_tz(self):
        # due at 23:00Z → next calendar day in Europe/London (BST), matching the next_tickle /
        # canvas date convention; a raw [:10] would wrongly yield the prior day.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("d", name="BST due", parent=P1, due="2026-06-20T23:00:00Z", tags=["action"]),
        ]
        local = build_actions(parsed, timezone="Europe/London")[0]
        assert local["due"] == "2026-06-21"
        raw = build_actions(parsed)[0]  # no tz → raw-UTC fallback
        assert raw["due"] == "2026-06-20"

    def test_priority_encoding(self):
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("p1", name="High", parent=P1, priority="1", tags=["action"]),
            _t("pn", name="None", parent=P1, priority="N", tags=["action"]),
        ]
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["p1"]["priority"] == "1"
        assert by_id["pn"]["priority"] == ""

    def test_blocked_matches_plan_graph(self):
        # 102 depends on the open sibling 101 → blocked; 101 has no upstream → not blocked. Same
        # judgement that gives the project blocked_count == 1.
        by_id = self._by_id()
        assert by_id["102"]["blocked"] is True
        assert by_id["101"]["blocked"] is False

    def test_blocked_false_when_upstream_not_in_project_rows(self):
        # an upstream that is completed or cross-project is not in the fetched incomplete rows, so
        # the edge resolves to nothing → not blocked (consistent with blocked_count).
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t(
                "201",
                name="Waiting on external",
                parent=P1,
                tags=["action"],
                notes=[_depends_on("999999")],  # upstream absent from the fetched set
            ),
        ]
        assert build_actions(parsed)[0]["blocked"] is False

    def test_waiting_for_and_calendar_carry_due(self):
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("wf", name="Hear back", parent=P1, due="2026-07-15T00:00:00Z", tags=["waiting_for"]),
            _t(
                "cal",
                name="Open day visit",
                parent=P1,
                due="2026-07-20T00:00:00Z",
                tags=["calendar"],
            ),
        ]
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["wf"]["due"] == "2026-07-15"  # chase/tickle date
        assert by_id["cal"]["due"] == "2026-07-20"  # calendar date
