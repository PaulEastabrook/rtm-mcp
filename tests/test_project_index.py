"""Tests for the portfolio-index builder (src/rtm_mcp/project_index.py)."""

from rtm_mcp.canvas_overlay import apply_graph
from rtm_mcp.canvas_seed import build_seed
from rtm_mcp.plan_graph import build_graph
from rtm_mcp.project_index import build_actions, build_foci, build_index
from rtm_mcp.project_plan import build_envelope

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
    estimate=None,
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
        "estimate": estimate,
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
            "ai_quick",
            "ai_now",
            "ai_later",
            "chat_count",
            "chat_review_count",
            "waiting_count",
            "redacted",
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


class TestAIProgressCounts:
    def test_ai_quick_counts_unblocked_quick_win_actions(self):
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("q1", name="Quick action", parent=P1, tags=["action", "quick_win"]),
            _t("q2", name="Quick calendar", parent=P1, tags=["calendar_entry", "quick_win"]),
        ]
        assert _p1(build_index(parsed))["ai_quick"] == 2

    def test_ai_quick_excludes_blocked_quick_win(self):
        # a quick-win blocked by an open upstream is not do-able now → not counted (quick_ready
        # already requires unblocked, matching the canvas quickReady predicate). Numeric ids: the
        # DEPENDS-ON task_id is extracted with a digits-only regex.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("201", name="Upstream", parent=P1, tags=["action"]),
            _t(
                "202",
                name="Blocked quick",
                parent=P1,
                tags=["action", "quick_win"],
                notes=[_depends_on("201")],
            ),
        ]
        row = _p1(build_index(parsed))
        assert row["ai_quick"] == 0
        assert row["blocked_count"] == 1

    def test_ai_quick_excludes_waiting_for_quick_win(self):
        # structural guard: a waiting-for is never quick even if mis-tagged #quick_win.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("w", name="Chase", parent=P1, tags=["waiting_for", "quick_win"]),
        ]
        assert _p1(build_index(parsed))["ai_quick"] == 0

    def test_ai_now_counts_progress_requested_excludes_blocked(self):
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("n1", name="Now item", parent=P1, tags=["action", "ai_progress_requested"]),
            _t("301", name="Upstream", parent=P1, tags=["action"]),
            _t(
                "302",
                name="Blocked now",
                parent=P1,
                tags=["action", "ai_progress_requested"],
                notes=[_depends_on("301")],
            ),
        ]
        assert _p1(build_index(parsed))["ai_now"] == 1

    def test_ai_later_counts_progress_deferred_including_blocked(self):
        # "later" means queued-until-unblocked, so a blocked later IS counted.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("l1", name="Later item", parent=P1, tags=["action", "ai_progress_deferred"]),
            _t("401", name="Upstream", parent=P1, tags=["action"]),
            _t(
                "402",
                name="Blocked later",
                parent=P1,
                tags=["action", "ai_progress_deferred"],
                notes=[_depends_on("401")],
            ),
        ]
        # both deferred items counted (later = queued-until-unblocked); 402 is genuinely blocked.
        result = build_index(parsed)
        assert _p1(result)["ai_later"] == 2
        assert _p1(result)["blocked_count"] == 1

    def test_zero_when_no_ai_flagged_work(self):
        # present (not absent) and zero for a project with no AI-flagged items.
        row = _p1(build_index(_portfolio()))
        assert row["ai_quick"] == 0
        assert row["ai_now"] == 0
        assert row["ai_later"] == 0

    def test_counts_match_canvas_classification(self):
        # one source of truth: the index counts equal the tallies over the canvas seed built via the
        # pure path (build_envelope → build_seed → build_graph → apply_graph).
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("q", name="Quick", parent=P1, tags=["action", "quick_win"]),
            _t("n", name="Now", parent=P1, tags=["action", "ai_progress_requested"]),
            _t("l", name="Later", parent=P1, tags=["action", "ai_progress_deferred"]),
            _t("plain", name="Plain", parent=P1, tags=["action"]),
        ]
        env = build_envelope(parsed, P1)
        seed = apply_graph(
            build_seed(env["header"], env["rows"]), build_graph(env["header"], env["rows"])
        )
        canvas_quick = sum(1 for it in seed["seed"] if it.get("quick"))
        canvas_now = sum(1 for it in seed["seed"] if it.get("prog") == "now")
        canvas_later = sum(1 for it in seed["seed"] if it.get("prog") == "later")

        row = _p1(build_index(parsed))
        assert row["ai_quick"] == canvas_quick == 1
        assert row["ai_now"] == canvas_now == 1
        assert row["ai_later"] == canvas_later == 1


class TestConversationCounts:
    def _proj(self, children):
        return [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            *children,
        ]

    def test_counts_incomplete_ai_chat_and_review(self):
        # Acceptance #1: two #ai_chat items (one also #ai_output_review_needed) + one COMPLETED
        # #ai_chat item → chat_count 2, chat_review_count 1 (completed excluded).
        parsed = self._proj(
            [
                _t("c1", "Chat one", parent=P1, tags=["action", "ai_chat"]),
                _t(
                    "c2",
                    "Chat two",
                    parent=P1,
                    tags=["action", "ai_chat", "ai_output_review_needed"],
                ),
                _t(
                    "c3",
                    "Done chat",
                    parent=P1,
                    tags=["action", "ai_chat"],
                    completed="2026-06-01T00:00:00Z",
                ),
            ]
        )
        row = _p1(build_index(parsed))
        assert row["chat_count"] == 2
        assert row["chat_review_count"] == 1

    def test_zero_when_no_conversation_items(self):
        # Acceptance #2.
        row = _p1(build_index(self._proj([_t("a1", "Plain", parent=P1, tags=["action"])])))
        assert row["chat_count"] == 0
        assert row["chat_review_count"] == 0

    def test_review_is_subset_not_additive(self):
        # an item tagged both counts ONCE in chat_count and once in chat_review_count.
        parsed = self._proj(
            [_t("c1", "Both", parent=P1, tags=["action", "ai_chat", "ai_output_review_needed"])]
        )
        row = _p1(build_index(parsed))
        assert row["chat_count"] == 1
        assert row["chat_review_count"] == 1

    def test_project_scoped_conversation_counts_the_project(self):
        # a project task carrying the tags itself is one more subject.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(
                P1,
                name="Open days",
                parent=AREA1,
                tags=["personal", "project", "ai_chat", "ai_output_review_needed"],
            ),
            _t("c1", "Item chat", parent=P1, tags=["action", "ai_chat"]),
        ]
        row = _p1(build_index(parsed))
        assert row["chat_count"] == 2  # the project + one item
        assert row["chat_review_count"] == 1  # the project

    def test_always_present_zero_not_absent(self):
        row = _p1(build_index(_portfolio()))
        assert row["chat_count"] == 0
        assert row["chat_review_count"] == 0


class TestEngageCounts:
    def _proj(self, children):
        return [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            *children,
        ]

    def test_waiting_count_counts_incomplete_waiting_fors(self):
        parsed = self._proj(
            [
                _t("w1", "Hear back A", parent=P1, tags=["waiting_for"]),
                _t("w2", "Hear back B", parent=P1, tags=["waiting_for"]),
                _t("a1", "Do a thing", parent=P1, tags=["action"]),  # not a waiting-for
                _t(
                    "w3",
                    "Done chase",
                    parent=P1,
                    tags=["waiting_for"],
                    completed="2026-06-01T00:00:00Z",  # completed → excluded
                ),
            ]
        )
        assert _p1(build_index(parsed))["waiting_count"] == 2

    def test_waiting_count_matches_canvas_kind(self):
        # a #calendar_entry is not a waiting-for; only #waiting_for counts (the canvas r.k parity).
        parsed = self._proj(
            [
                _t("w", "Chase", parent=P1, tags=["waiting_for"]),
                _t("c", "Calendar", parent=P1, tags=["calendar_entry"]),
            ]
        )
        assert _p1(build_index(parsed))["waiting_count"] == 1

    def test_waiting_count_present_and_zero_when_none(self):
        # always present; 0 (not absent) when the project has no waiting-fors.
        parsed = self._proj([_t("a1", "Action", parent=P1, tags=["action"])])
        assert _p1(build_index(parsed))["waiting_count"] == 0
        # and the _portfolio fixture (one #waiting_for child, 103) reports 1.
        assert _p1(build_index(_portfolio()))["waiting_count"] == 1


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
        assert all(set(f) == {"focus_id", "focus", "life", "redacted"} for f in foci)

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
            "type",
            "due",
            "priority",
            "blocked",
            "estimate",
            "contexts",
            "energy",
            "exec",
            "redacted",
        }
        assert a["name"] == "Attend webinar"
        assert a["project_id"] == P1
        assert a["project"] == "Open days"
        assert a["focus"] == "Sam — University"
        assert a["life"] == "personal"
        # baseline: an un-annotated action → all engage fields at their absent value.
        assert a["estimate"] is None
        assert a["contexts"] == []
        assert a["energy"] is None
        assert a["exec"] is None

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

    def test_type_matches_canvas_classification(self):
        # same r.k classification gtd_project_canvas applies: #waiting_for → waiting_for,
        # #calendar_entry → calendar, otherwise action.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("act", name="A next action", parent=P1, tags=["action"]),
            _t("wf", name="A chase", parent=P1, tags=["waiting_for"]),
            _t("cal", name="A calendar item", parent=P1, tags=["calendar_entry"]),
            _t("bare", name="Untagged child", parent=P1, tags=[]),
        ]
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["act"]["type"] == "action"
        assert by_id["wf"]["type"] == "waiting_for"
        assert by_id["cal"]["type"] == "calendar"
        assert by_id["bare"]["type"] == "action"  # default kind

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


class TestActionEngageFields:
    """The engage-lens funnel fields on action rows (Allen four-criteria: context / time / energy /
    priority). Each is independently absent-able — a null exempts, never hides."""

    def _wrap(self, *children):
        return [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            *children,
        ]

    def test_estimate_normalised_to_minutes(self):
        parsed = self._wrap(
            _t("m", name="Half hour", parent=P1, estimate="30 minutes", tags=["action"]),
            _t("hm", name="ISO", parent=P1, estimate="PT1H30M", tags=["action"]),
            _t("none", name="Unsized", parent=P1, tags=["action"]),
        )
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["m"]["estimate"] == 30
        assert by_id["hm"]["estimate"] == 90
        assert by_id["none"]["estimate"] is None  # unset → null, exempt from the time filter

    def test_contexts_pass_through_verbatim(self):
        parsed = self._wrap(
            _t(
                "c",
                name="Two contexts",
                parent=P1,
                tags=["action", "location_home", "using_device"],
            ),
            _t("cn", name="No context", parent=P1, tags=["action"]),
        )
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        # canonical _CONTEXT_TAGS order: using_device before location_home
        assert by_id["c"]["contexts"] == ["using_device", "location_home"]
        assert by_id["cn"]["contexts"] == []

    def test_energy_mapping(self):
        parsed = self._wrap(
            _t("hi", name="High", parent=P1, tags=["action", "high_energy"]),
            _t("lo", name="Low", parent=P1, tags=["action", "low_energy"]),
            _t(
                "both",
                name="Contradiction",
                parent=P1,
                tags=["action", "high_energy", "low_energy"],
            ),
            _t("neither", name="Unrated", parent=P1, tags=["action"]),
        )
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["hi"]["energy"] == "high"
        assert by_id["lo"]["energy"] == "low"
        assert by_id["both"]["energy"] is None  # both tags → data error → null
        assert by_id["neither"]["energy"] is None

    def test_exec_values(self):
        parsed = self._wrap(
            _t("q", name="Quick", parent=P1, tags=["action", "quick_win"]),
            _t("n", name="Now", parent=P1, tags=["action", "ai_progress_requested"]),
            _t("l", name="Later", parent=P1, tags=["action", "ai_progress_deferred"]),
            _t("plain", name="Plain", parent=P1, tags=["action"]),
        )
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["q"]["exec"] == "quick"
        assert by_id["n"]["exec"] == "now"
        assert by_id["l"]["exec"] == "later"
        assert by_id["plain"]["exec"] is None  # classifier abstains

    def test_exec_now_directive_wins_over_quick(self):
        # precedence now > later > quick: an explicit progress-now directive wins over the derived
        # 2-minute judgement even when the item is also a #quick_win.
        parsed = self._wrap(
            _t(
                "qn",
                name="Quick+now",
                parent=P1,
                tags=["action", "quick_win", "ai_progress_requested"],
            ),
        )
        assert build_actions(parsed)[0]["exec"] == "now"

    def test_exec_blocked_now_abstains(self):
        # a blocked progress-now item is excluded from ai_now AND from exec (both None) — consistent.
        # (DEPENDS-ON upstreams are matched by a digits-only regex → numeric ids required.)
        parsed = self._wrap(
            _t("301", name="Upstream", parent=P1, tags=["action"]),
            _t(
                "302",
                name="Blocked now",
                parent=P1,
                tags=["action", "ai_progress_requested"],
                notes=[_depends_on("301")],
            ),
        )
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["302"]["blocked"] is True
        assert by_id["302"]["exec"] is None

    def test_exec_tallies_match_project_counts(self):
        # one classifier, two aggregations: over non-overlapping rows, the per-action exec buckets
        # reproduce the project's ai_quick / ai_now / ai_later counts exactly.
        children = [
            _t("q", name="Quick", parent=P1, tags=["action", "quick_win"]),
            _t("n", name="Now", parent=P1, tags=["action", "ai_progress_requested"]),
            _t("l", name="Later", parent=P1, tags=["action", "ai_progress_deferred"]),
            _t("plain", name="Plain", parent=P1, tags=["action"]),
        ]
        parsed = self._wrap(*children)
        proj_row = _p1(build_index(parsed))
        actions = [a for a in build_actions(parsed) if a["project_id"] == P1]
        assert sum(1 for a in actions if a["exec"] == "quick") == proj_row["ai_quick"] == 1
        assert sum(1 for a in actions if a["exec"] == "now") == proj_row["ai_now"] == 1
        assert sum(1 for a in actions if a["exec"] == "later") == proj_row["ai_later"] == 1


class TestRedaction:
    def test_project_row_redacted_flag(self):
        # build_index row carries the project's own #redacted state; absent tag → False.
        assert _p1(build_index(_portfolio()))["redacted"] is False
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project", "redacted"]),
            _t("101", name="Attend webinar", parent=P1, tags=["action"]),
        ]
        assert _p1(build_index(parsed))["redacted"] is True

    def test_action_row_redacted_flag(self):
        # build_actions row carries the action's OWN #redacted state (board redacts items too); under
        # a non-redacted parent, only the item's own tag drives it.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("101", name="Secret", parent=P1, tags=["action", "redacted"]),
            _t("102", name="Open", parent=P1, tags=["action"]),
        ]
        by_id = {a["action_id"]: a for a in build_actions(parsed)}
        assert by_id["101"]["redacted"] is True
        assert by_id["102"]["redacted"] is False

    def test_action_redacted_cascades_from_project(self):
        # a redacted PROJECT shields every child action (server-derived cascade), even one with no
        # #redacted tag of its own.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project", "redacted"]),
            _t("101", name="Under redacted project", parent=P1, tags=["action"]),
        ]
        assert build_actions(parsed)[0]["redacted"] is True

    def test_action_redacted_cascades_from_focus(self):
        # a redacted Area of Focus shields the actions of its projects too.
        parsed = [
            _area(AREA1, "Sam — University", tags=["focus", "personal", "redacted"]),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t("101", name="Under redacted focus", parent=P1, tags=["action"]),
        ]
        assert build_actions(parsed)[0]["redacted"] is True

    def test_shielded_action_still_carries_engage_fields(self):
        # Redaction is a CLIENT-side viewing curtain, not a server data vault: a shielded row
        # (via a CASCADE here — a redacted project) still carries its full engage data. The server
        # only SURFACES the `redacted` flag; the client shields the display. The server must never
        # ENFORCE redaction by suppressing fields — this is the guard that stops that creeping back.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project", "redacted"]),
            _t(
                "101",
                name="Hidden work",
                parent=P1,
                estimate="30 minutes",
                tags=["action", "location_home", "high_energy", "ai_progress_requested"],
            ),
        ]
        a = build_actions(parsed)[0]
        assert a["redacted"] is True
        assert a["estimate"] == 30
        assert a["contexts"] == ["location_home"]
        assert a["energy"] == "high"
        assert a["exec"] == "now"

    def test_own_tag_shielded_action_still_carries_engage_fields(self):
        # The same, but the row is shielded by its OWN #redacted tag (not a cascade) — full data
        # flows behind the flag either way.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),
            _t(P1, name="Open days", parent=AREA1, tags=["personal", "project"]),
            _t(
                "101",
                name="Hidden work",
                parent=P1,
                estimate="30 minutes",
                tags=[
                    "action",
                    "redacted",
                    "location_home",
                    "high_energy",
                    "ai_progress_requested",
                ],
            ),
        ]
        a = build_actions(parsed)[0]
        assert a["redacted"] is True
        assert a["estimate"] == 30
        assert a["contexts"] == ["location_home"]
        assert a["energy"] == "high"
        assert a["exec"] == "now"

    def test_focus_row_redacted_flag(self):
        # build_foci row carries the Area-of-Focus task's own #redacted state — the navigator
        # collapses a redacted focus to a single "Redacted Area of Focus" row.
        parsed = [
            _area(AREA1, "Sam — University", life="personal"),  # untagged → False
            _area(AREA2, "Hive Mind", tags=["focus", "work", "redacted"]),
        ]
        by_id = {f["focus_id"]: f for f in build_foci(parsed)}
        assert by_id[AREA1]["redacted"] is False
        assert by_id[AREA2]["redacted"] is True


class TestCompletedRowGuards:
    """All per-project counts and the action index must exclude completed
    children uniformly — the pure builders can't assume a status:incomplete
    read (gtd_apply_canvas_commit's read already spans completed)."""

    def _portfolio_with_completed_child(self):
        return [
            _area(AREA1, "Area", life="personal"),
            _t(P1, name="Proj", parent=AREA1, tags=["personal", "project"]),
            _t("201", name="Open action", parent=P1, due="2026-07-10T00:00:00Z", tags=["action"]),
            _t(
                "202",
                name="Done early",
                parent=P1,
                due="2026-01-01T00:00:00Z",  # earlier than the open due
                completed="2026-01-02T00:00:00Z",
                tags=["action", "ai_progress_deferred", "waiting_for", "ai_chat"],
            ),
        ]

    def test_counts_exclude_completed_children(self):
        row = build_index(self._portfolio_with_completed_child())[0]
        assert row["open_count"] == 1
        assert row["ai_later"] == 0  # completed #ai_progress_deferred must not count
        assert row["waiting_count"] == 0
        assert row["chat_count"] == 0

    def test_next_tickle_ignores_completed_due(self):
        row = build_index(self._portfolio_with_completed_child())[0]
        assert row["next_tickle"] == "2026-07-10"

    def test_build_actions_excludes_completed_children(self):
        actions = build_actions(self._portfolio_with_completed_child())
        assert [a["action_id"] for a in actions] == ["201"]
