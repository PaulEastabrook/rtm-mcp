"""Pure-builder tests for `gtd_reports` and `tag_report` — the six remaining Wave 1 reads.

As with `test_engine_report.py`, the source scripts are not an oracle. Where a builder
deliberately diverges from its `.ms` (the dropped `isSubtask:true`, the four life contexts, the
sort-then-cap order, the verified `completedWithin:` cohort) there is a test naming the
divergence, so a future reader cannot mistake it for drift.
"""

from datetime import UTC, datetime, timedelta

from rtm_mcp.gtd_reports import (
    LIFE_ORDER,
    STATE_ORDER,
    build_dependency_gaps,
    build_focus_index,
    build_item_stale,
    build_review_report,
    build_workload_report,
    has_depends_on_note,
)
from rtm_mcp.tag_report import (
    CANONICAL_TAGS,
    LIFE_CONTEXT_TAGS,
    build_tag_report,
    classify_tag,
)

NOW = "2026-07-25T09:00:00Z"
TODAY = "2026-07-25"


def _iso(days_ago):
    return (datetime(2026, 7, 25, 9, 0, tzinfo=UTC) - timedelta(days=days_ago)).isoformat()


def _t(task_id, name="task", tags=(), parent=None, **over):
    task = {
        "id": task_id,
        "taskseries_id": f"s{task_id}",
        "list_id": "100",
        "name": name,
        "tags": list(tags),
        "notes": [],
        "parent_task_id": parent,
        "completed": None,
        "due": None,
        "priority": "N",
        "estimate": None,
        "created": _iso(100),
        "modified": _iso(1),
    }
    task.update(over)
    return task


def _depends_note():
    return {"id": "n1", "$t": "2026-07-01 — DEPENDS-ON — upstream\nStatus: active\n"}


# --------------------------------------------------------------------------- #
# gtd_dependency_gaps
# --------------------------------------------------------------------------- #


class TestDependencyGaps:
    def _estate(self):
        return [
            _t("p1", "Big project", ["project", "work"]),
            _t("c1", "child a", ["action"], parent="p1"),
            _t("c2", "child b", ["action"], parent="p1"),
            _t("c3", "child c", ["action"], parent="p1"),
            _t("p2", "Graphed project", ["project", "work"]),
            _t("c4", "child d", ["action"], parent="p2", notes=[_depends_note()]),
            _t("c5", "child e", ["action"], parent="p2"),
            _t("p3", "Thin project", ["project", "work"]),
            _t("c6", "child f", ["action"], parent="p3"),
            _t("p4", "Held project", ["project", "work", "hold"]),
            _t("c7", "child g", ["action"], parent="p4"),
            _t("c8", "child h", ["action"], parent="p4"),
        ]

    def test_eligible_is_the_ungraphed_multi_child_set(self):
        out = build_dependency_gaps(self._estate())
        assert [r["project_id"] for r in out["eligible"]] == ["p1"]
        assert out["eligible"][0]["open_child_count"] == 3

    def test_every_exclusion_is_reported_with_a_reason(self):
        out = build_dependency_gaps(self._estate())
        reasons = {r["project_id"]: r["reason"] for r in out["skipped"]}
        assert reasons == {
            "p2": "graph_already_captured",
            "p3": "too_few_open_children",
            "p4": "disqualifying_tag",
        }

    def test_a_resolved_depends_on_still_counts_as_captured(self):
        estate = self._estate()
        for t in estate:
            if t["id"] == "c4":
                t["notes"] = [{"id": "n", "$t": "2026-07-01 — DEPENDS-ON — up\nStatus: resolved\n"}]
        out = build_dependency_gaps(estate)
        assert "p2" not in [r["project_id"] for r in out["eligible"]]

    def test_depends_on_must_be_the_note_TITLE_not_prose(self):
        assert (
            has_depends_on_note({"notes": [{"$t": "2026-07-01 — CONTEXT — x\nDEPENDS-ON later"}]})
            is False
        )
        assert has_depends_on_note({"notes": [_depends_note()]}) is True

    def test_completed_children_do_not_keep_a_project_eligible(self):
        estate = [
            _t("p", "P", ["project"]),
            _t("a", "a", ["action"], parent="p"),
            _t("b", "b", ["action"], parent="p", completed=_iso(1)),
        ]
        out = build_dependency_gaps(estate)
        assert [r["reason"] for r in out["skipped"]] == ["too_few_open_children"]

    def test_cap_is_applied_AFTER_the_largest_first_sort(self):
        """The `.ms` truncated during the scan in RTM's arbitrary order and sorted the survivors,
        so `max_projects` did not return the largest projects it claimed to."""
        estate = []
        for size, pid in ((2, "small"), (5, "big"), (3, "mid")):
            estate.append(_t(pid, pid, ["project"]))
            estate += [_t(f"{pid}{i}", "c", ["action"], parent=pid) for i in range(size)]
        out = build_dependency_gaps(estate, max_projects=1)
        assert [r["project_id"] for r in out["eligible"]] == ["big"]
        assert out["capped"] is True and out["eligible_total"] == 3

    def test_no_cap_when_zero(self):
        out = build_dependency_gaps(self._estate(), max_projects=0)
        assert out["capped"] is False

    def test_the_vault_caveat_rides_in_the_payload(self):
        out = build_dependency_gaps([])
        assert "context.md" in out["vault_filter_pending"]


# --------------------------------------------------------------------------- #
# gtd_review_report
# --------------------------------------------------------------------------- #


class TestReviewReport:
    def test_completions_and_additions_are_counted_by_life_context(self):
        incomplete = [
            _t("1", "new work", ["action", "work"], created=_iso(2)),
            _t("2", "old work", ["action", "work"], created=_iso(90)),
            _t("3", "new personal", ["waiting_for", "personal"], created=_iso(1)),
        ]
        completed = [_t("9", "done", ["action", "work"], completed=_iso(2))]
        out = build_review_report(incomplete, completed, [], days=7, now=NOW, today=TODAY)
        assert out["added"]["by_life_context"]["work"] == 1
        assert out["added"]["by_life_context"]["personal"] == 1
        assert out["added"]["total"] == 2
        assert out["completed"]["by_life_context"]["work"] == 1

    def test_the_fourth_life_context_is_not_dropped(self):
        """Every script hard-coded work/personal/leanworking; `client` is canonical."""
        assert "client" in LIFE_ORDER and "client" in LIFE_CONTEXT_TAGS
        out = build_review_report(
            [_t("1", "c", ["action", "client"], created=_iso(2))],
            [],
            [],
            days=7,
            now=NOW,
            today=TODAY,
        )
        assert out["added"]["by_life_context"]["client"] == 1

    def test_items_with_no_life_context_are_counted_not_discarded(self):
        out = build_review_report(
            [_t("1", "x", ["action"], created=_iso(2))],
            [_t("2", "y", ["action"], completed=_iso(1))],
            [],
            days=7,
            now=NOW,
            today=TODAY,
        )
        assert out["added"]["no_life_context"] == 1
        assert out["completed"]["no_life_context"] == 1

    def test_projects_and_foci_are_excluded_from_the_completion_count(self):
        completed = [
            _t("1", "p", ["project", "work"], completed=_iso(1)),
            _t("2", "f", ["focus", "work"], completed=_iso(1)),
            _t("3", "a", ["action", "work"], completed=_iso(1)),
        ]
        out = build_review_report([], completed, [], days=7, now=NOW, today=TODAY)
        assert out["completed"]["total"] == 1

    def test_current_state_is_life_by_workflow_state(self):
        incomplete = [
            _t("1", "a", ["action", "work"]),
            _t("2", "w", ["waiting_for", "work"]),
            _t("3", "p", ["project", "work"]),
        ]
        out = build_review_report(incomplete, [], [], days=7, now=NOW, today=TODAY)
        work = out["current_state"]["work"]
        assert work["by_workflow_state"]["action"] == 1
        assert work["by_workflow_state"]["waiting_for"] == 1
        assert work["total"] == 3

    def test_overdue_and_inbox_depth(self):
        incomplete = [
            _t("1", "late", ["action", "work"], due="2026-07-20T00:00:00Z"),
            _t("2", "soon", ["action", "work"], due="2026-07-30T00:00:00Z"),
        ]
        out = build_review_report(incomplete, [], [_t("i", "x")], days=7, now=NOW, today=TODAY)
        assert out["overdue_count"] == 1
        assert out["inbox_depth"] == 1

    def test_velocity_direction(self):
        grow = build_review_report(
            [_t("1", "a", ["action", "work"], created=_iso(1))],
            [],
            [],
            days=7,
            now=NOW,
            today=TODAY,
        )
        assert grow["velocity"] == {"net_change": 1, "direction": "growing"}
        shrink = build_review_report(
            [],
            [_t("9", "d", ["action", "work"], completed=_iso(1))],
            [],
            days=7,
            now=NOW,
            today=TODAY,
        )
        assert shrink["velocity"]["direction"] == "shrinking"

    def test_undated_creation_is_counted_not_assumed_recent(self):
        out = build_review_report(
            [_t("1", "x", ["action", "work"], created=None)], [], [], days=7, now=NOW, today=TODAY
        )
        assert out["added"]["undated_creation"] == 1 and out["added"]["total"] == 0


# --------------------------------------------------------------------------- #
# gtd_item_stale
# --------------------------------------------------------------------------- #


class TestItemStale:
    def test_only_items_past_the_threshold_are_returned(self):
        tasks = [
            _t("1", "old", ["action"], modified=_iso(40)),
            _t("2", "fresh", ["action"], modified=_iso(2)),
        ]
        out = build_item_stale(tasks, days=30, now=NOW, today=TODAY)
        assert [r["task_id"] for r in out["rows"]] == ["1"]
        assert out["rows"][0]["age_days"] == 40

    def test_someday_is_excluded_because_it_is_meant_to_sit(self):
        tasks = [_t("1", "s", ["action", "someday"], modified=_iso(100))]
        assert build_item_stale(tasks, days=30, now=NOW, today=TODAY)["count"] == 0

    def test_top_level_projects_and_foci_ARE_included(self):
        """Divergence: `stale-items.ms` filtered `isSubtask:true`, making every top-level project
        and Area of Focus structurally invisible to a hygiene report."""
        tasks = [
            _t("p", "project", ["project"], parent=None, modified=_iso(60)),
            _t("f", "focus", ["focus"], parent=None, modified=_iso(60)),
            _t("c", "child", ["action"], parent="p", modified=_iso(60)),
        ]
        out = build_item_stale(tasks, days=30, now=NOW, today=TODAY)
        assert out["by_state"] == {"action": 1, "focus": 1, "project": 1}

    def test_rows_sort_oldest_first(self):
        tasks = [
            _t("1", "a", ["action"], modified=_iso(40)),
            _t("2", "b", ["action"], modified=_iso(90)),
        ]
        out = build_item_stale(tasks, days=30, now=NOW, today=TODAY)
        assert [r["task_id"] for r in out["rows"]] == ["2", "1"]

    def test_completed_and_test_items_are_excluded(self):
        tasks = [
            _t("1", "done", ["action"], modified=_iso(60), completed=_iso(1)),
            _t("2", "test", ["action", "test"], modified=_iso(60)),
        ]
        assert build_item_stale(tasks, days=30, now=NOW, today=TODAY)["count"] == 0

    def test_missing_modification_is_counted_not_assumed_stale(self):
        out = build_item_stale(
            [_t("1", "x", ["action"], modified=None)], days=30, now=NOW, today=TODAY
        )
        assert out["count"] == 0 and out["undated_modification"] == 1


# --------------------------------------------------------------------------- #
# gtd_workload_report
# --------------------------------------------------------------------------- #


class TestWorkloadReport:
    def test_cells_are_life_by_workflow_state(self):
        tasks = [
            _t("1", "a", ["action", "work"]),
            _t("2", "b", ["action", "work"]),
            _t("3", "c", ["waiting_for", "personal"]),
        ]
        out = build_workload_report(tasks, today=TODAY)
        assert out["by_life_context"]["work"]["by_workflow_state"]["action"]["count"] == 2
        assert out["by_life_context"]["personal"]["by_workflow_state"]["waiting_for"]["count"] == 1
        assert out["totals"]["count"] == 3

    def test_estimates_are_summed_for_every_state_not_only_actions(self):
        """`workload-balance.ms` summed estimates for `action` alone; a waiting-for or calendar
        entry carrying an estimate is real committed time."""
        tasks = [
            _t("1", "a", ["action", "work"], estimate="PT2H"),
            _t("2", "w", ["waiting_for", "work"], estimate="PT30M"),
        ]
        out = build_workload_report(tasks, today=TODAY)
        assert out["by_life_context"]["work"]["estimate_minutes"] == 150
        assert out["by_life_context"]["work"]["estimate_hours"] == 2.5

    def test_coverage_pct_shows_the_hours_figure_is_a_floor(self):
        tasks = [
            _t("1", "a", ["action", "work"], estimate="PT1H"),
            _t("2", "b", ["action", "work"]),
            _t("3", "c", ["action", "work"]),
            _t("4", "d", ["action", "work"]),
        ]
        out = build_workload_report(tasks, today=TODAY)
        assert out["by_life_context"]["work"]["estimate_coverage_pct"] == 25

    def test_unclassified_items_are_counted_not_dropped(self):
        tasks = [_t("1", "no life", ["action"]), _t("2", "no state", ["work"])]
        out = build_workload_report(tasks, today=TODAY)
        assert out["unclassified_count"] == 2 and out["totals"]["count"] == 0

    def test_every_life_context_and_state_is_present_even_when_empty(self):
        out = build_workload_report([], today=TODAY)
        assert set(out["by_life_context"]) == set(LIFE_ORDER)
        assert set(out["by_life_context"]["work"]["by_workflow_state"]) == set(STATE_ORDER)


# --------------------------------------------------------------------------- #
# gtd_focus_index
# --------------------------------------------------------------------------- #


class TestFocusIndex:
    def _estate(self):
        return [
            _t("f1", "Engineering leadership", ["focus", "work"]),
            _t("p1", "Hire an EM", ["project", "work"], parent="f1"),
            _t("p2", "AI policy", ["project", "work"], parent="f1"),
            _t("a1", "loose action", ["action", "work"], parent="f1"),
            _t("f2", "Home", ["focus", "personal"]),
            _t("f3", "Parked", ["focus", "work", "someday"]),
            _t("f4", "Held", ["focus", "work", "hold"]),
        ]

    def test_rows_carry_project_and_direct_item_counts(self):
        out = build_focus_index(self._estate(), today=TODAY)
        by_id = {r["focus_id"]: r for r in out["rows"]}
        assert by_id["f1"]["project_count"] == 2
        assert by_id["f1"]["direct_item_count"] == 1
        assert by_id["f2"]["project_count"] == 0

    def test_the_active_gate_matches_gtd_project_index(self):
        out = build_focus_index(self._estate(), today=TODAY)
        ids = {r["focus_id"] for r in out["rows"]}
        assert ids == {"f1", "f2"}, "#hold always out, #someday opt-in"
        opted = build_focus_index(self._estate(), include_someday=True, today=TODAY)
        assert "f3" in {r["focus_id"] for r in opted["rows"]}

    def test_grouped_by_life_context_in_canonical_order(self):
        out = build_focus_index(self._estate(), today=TODAY)
        assert [r["life"] for r in out["rows"]] == ["work", "personal"]
        assert out["by_life_context"] == {"work": 1, "personal": 1}

    def test_a_focus_with_no_life_context_sorts_last_and_is_counted(self):
        estate = [*self._estate(), _t("f5", "Untagged", ["focus"])]
        out = build_focus_index(estate, today=TODAY)
        assert out["rows"][-1]["focus_id"] == "f5"
        assert out["unclassified_count"] == 1

    def test_redaction_is_surfaced_never_enforced(self):
        """The v1.30.0 curtain-not-vault invariant: the flag is emitted, the data still flows."""
        estate = [_t("f1", "Private area", ["focus", "work", "redacted"])]
        row = build_focus_index(estate, today=TODAY)["rows"][0]
        assert row["redacted"] is True
        assert row["focus"] == "Private area" and row["life"] == "work"

    def test_a_project_tagged_focus_is_not_an_area(self):
        estate = [_t("x", "both", ["focus", "project", "work"])]
        assert build_focus_index(estate, today=TODAY)["count"] == 0


# --------------------------------------------------------------------------- #
# gtd_tag_report
# --------------------------------------------------------------------------- #


class TestTagReport:
    def test_classification_is_three_way(self):
        assert classify_tag("work")[0] == "canonical"
        assert classify_tag("q_action")[0] == "canonical"  # derived q_<entity-type>
        assert classify_tag("architect_capture") == ("family", "architect")
        assert classify_tag("ai_research_optin") == ("family", "ai_optin")
        assert classify_tag("alex")[0] == "people"
        assert classify_tag("next_action")[0] == "retired"
        assert classify_tag("wrok")[0] == "non_canonical"

    def test_the_taxonomy_the_script_missed_is_canonical_here(self):
        """`tag-audit.ms` carried a 24-tag list; each of these was absent and would have been
        reported as 'outside taxonomy'."""
        for tag in (
            "client",
            "focus",
            "hold",
            "quick_win",
            "single_action",
            "high_energy",
            "low_energy",
            "redacted",
            "q_pending",
            "auto_closed",
            "ai_chat",
            "ai_progress_deferred",
        ):
            assert tag in CANONICAL_TAGS, tag

    def test_family_prefix_alone_is_not_a_member(self):
        assert classify_tag("architect_")[0] == "non_canonical"
        assert classify_tag("ai_optin")[0] == "non_canonical"

    def test_unused_non_canonical_tags_are_the_deletion_candidates(self):
        tasks = [_t("1", "x", ["work", "wrok"])]
        out = build_tag_report(["work", "wrok", "typo_tag"], tasks, today=TODAY)
        assert [r["name"] for r in out["non_canonical_active"]] == ["wrok"]
        assert [r["name"] for r in out["non_canonical_unused"]] == ["typo_tag"]

    def test_retired_tag_still_in_use_is_its_own_finding(self):
        out = build_tag_report(["next_action"], [_t("1", "x", ["next_action"])], today=TODAY)
        assert [r["name"] for r in out["retired_in_use"]] == ["next_action"]
        assert out["non_canonical_active"] == []

    def test_usage_counts_come_from_one_task_scan(self):
        tasks = [_t("1", "a", ["wrok"]), _t("2", "b", ["wrok"])]
        out = build_tag_report(["wrok"], tasks, today=TODAY)
        assert out["non_canonical_active"][0]["active_count"] == 2

    def test_minimum_tag_set_gaps(self):
        tasks = [
            _t("1", "no life", ["action", "using_device"]),
            _t("2", "no state", ["work", "using_device"]),
            _t("3", "no context", ["action", "work"]),
        ]
        out = build_tag_report([], tasks, today=TODAY)
        mts = out["minimum_tag_set"]
        assert mts["missing_life_context_count"] == 1
        assert mts["missing_workflow_state_count"] == 1
        assert mts["actions_missing_action_context_count"] == 1
        assert mts["missing_life_context_sample"][0]["task_id"] == "1"

    def test_a_tag_on_tasks_but_absent_from_the_account_list_is_surfaced(self):
        out = build_tag_report(["work"], [_t("1", "x", ["work", "ghost"])], today=TODAY)
        assert out["orphaned_in_use"] == ["ghost"]

    def test_the_people_caveat_rides_in_the_payload(self):
        assert "typo" in build_tag_report([], [], today=TODAY)["people_caveat"]
