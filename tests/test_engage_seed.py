"""Tests for the engage-seed builder (src/rtm_mcp/engage_seed.py).

Covers the overdue-set selection, the server-derived flags (kind / has_deadline / blocked /
postponed / suggested), the redaction cascade, and the CURTAIN-NOT-VAULT invariant (the seed emits
the flag but never suppresses a field). Input dicts are in the shape parse_tasks_response emits.
"""

from rtm_mcp.engage_seed import build_engage_seed

TODAY = "2026-07-15"


def _t(
    id,
    name="Task",
    parent="",
    list_id="L1",
    completed=None,
    due=None,
    has_due_time=False,
    postponed=0,
    tags=None,
    notes=None,
):
    return {
        "id": id,
        "taskseries_id": "ts" + id,
        "list_id": list_id,
        "name": name,
        "due": due,
        "has_due_time": has_due_time,
        "start": None,
        "completed": completed,
        "deleted": None,
        "priority": "N",
        "postponed": postponed,
        "estimate": None,
        "tags": tags or [],
        "notes": notes or [],
        "url": None,
        "parent_task_id": parent or None,
        "modified": None,
    }


def _note(body, created="2026-06-15T10:00:00Z"):
    return {"id": "n", "created": created, "title": "", "$t": body}


def _depends_on(upstream_id):
    return _note(
        f'DEPENDS-ON\nUpstream RTM IDs:\n  task_id: "{upstream_id}"\n'
        '  list_id: "L1"\nStatus: active\n'
    )


class TestSelection:
    def test_overdue_and_due_today_included_future_excluded(self):
        parsed = [
            _t("a", "Overdue", due="2026-07-10", tags=["action"]),
            _t("b", "Due today", due=TODAY, tags=["action"]),
            _t("c", "Future", due="2026-08-01", tags=["action"]),
            _t("d", "Undated", due=None, tags=["action"]),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        ids = {r["id"] for r in seed["items"]}
        assert ids == {"a", "b"}
        assert seed["current_date"] == TODAY
        assert seed["count"] == 2

    def test_completed_test_someday_excluded(self):
        parsed = [
            _t("a", due="2026-07-10", tags=["action"], completed="2026-07-11T00:00:00Z"),
            _t("b", due="2026-07-10", tags=["action", "test"]),
            _t("c", due="2026-07-10", tags=["action", "someday"]),
            _t("d", due="2026-07-10", tags=["action"]),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        assert {r["id"] for r in seed["items"]} == {"d"}

    def test_sorted_by_due_then_name(self):
        parsed = [
            _t("a", "Zebra", due="2026-07-10", tags=["action"]),
            _t("b", "Apple", due="2026-07-10", tags=["action"]),
            _t("c", "Early", due="2026-07-01", tags=["action"]),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        assert [r["id"] for r in seed["items"]] == ["c", "b", "a"]

    def test_empty(self):
        assert build_engage_seed([], today=TODAY) == {
            "items": [],
            "current_date": TODAY,
            "count": 0,
        }


class TestFlags:
    def test_kind_from_workflow_tag(self):
        parsed = [
            _t("a", due="2026-07-10", tags=["action"]),
            _t("w", due="2026-07-10", tags=["waiting_for"]),
            _t("c", due="2026-07-10", tags=["action", "calendar_entry"]),
            _t("p", due="2026-07-10", tags=["project"]),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        kinds = {r["id"]: r["kind"] for r in seed["items"]}
        assert kinds == {
            "a": "action",
            "w": "waiting_for",
            "c": "calendar_entry",
            "p": "project",
        }

    def test_has_deadline_from_has_due_time(self):
        parsed = [
            _t("timed", due="2026-07-10", has_due_time=True, tags=["action"]),
            _t("soft", due="2026-07-10", has_due_time=False, tags=["action"]),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        by = {r["id"]: r for r in seed["items"]}
        assert by["timed"]["has_deadline"] is True
        assert by["soft"]["has_deadline"] is False
        # a hard deadline pre-triages to keep; a soft action to next_actions
        assert by["timed"]["suggested"] == "keep"
        assert by["soft"]["suggested"] == "next_actions"

    def test_postponed_carried(self):
        parsed = [_t("a", due="2026-07-10", postponed=4, tags=["action"])]
        seed = build_engage_seed(parsed, today=TODAY)
        assert seed["items"][0]["postponed"] == 4

    def test_blocked_from_thin_plan_graph(self):
        # upstream 101 incomplete → downstream 102 blocked, both under project P.
        # DEPENDS-ON round-trips only via a digits-only task_id (real RTM ids).
        parsed = [
            _t("P", "Proj", parent="area", tags=["project"]),
            _t("area", "Area", tags=["focus"]),
            _t("101", "Upstream", parent="P", due="2026-07-10", tags=["action"]),
            _t(
                "102",
                "Downstream",
                parent="P",
                due="2026-07-10",
                tags=["action"],
                notes=[_depends_on("101")],
            ),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        by = {r["id"]: r for r in seed["items"]}
        assert by["102"]["blocked"] is True
        assert by["102"]["suggested"] == "resurface"  # blocked → resurface
        assert by["101"]["blocked"] is False

    def test_waiting_for_suggested_nudge(self):
        parsed = [_t("w", due="2026-07-10", tags=["waiting_for"])]
        seed = build_engage_seed(parsed, today=TODAY)
        assert seed["items"][0]["suggested"] == "nudge"


class TestRedactionCurtainNotVault:
    def test_own_redacted_flag(self):
        parsed = [_t("a", "Secret", due="2026-07-10", tags=["action", "redacted"])]
        seed = build_engage_seed(parsed, today=TODAY)
        assert seed["items"][0]["redacted"] is True
        # curtain-not-vault: the name and every flag still flow
        assert seed["items"][0]["name"] == "Secret"
        assert seed["items"][0]["kind"] == "action"

    def test_cascade_from_redacted_project(self):
        parsed = [
            _t("P", "Proj", parent="area", tags=["project", "redacted"]),
            _t("area", "Area", tags=["focus"]),
            _t("child", "Child", parent="P", due="2026-07-10", tags=["action"]),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        child = next(r for r in seed["items"] if r["id"] == "child")
        assert child["redacted"] is True
        assert child["name"] == "Child"  # full data still present

    def test_cascade_from_redacted_focus(self):
        parsed = [
            _t("P", "Proj", parent="area", tags=["project"]),
            _t("area", "Area", tags=["focus", "redacted"]),
            _t("child", "Child", parent="P", due="2026-07-10", tags=["action"]),
        ]
        seed = build_engage_seed(parsed, today=TODAY)
        child = next(r for r in seed["items"] if r["id"] == "child")
        assert child["redacted"] is True

    def test_unshielded_not_redacted(self):
        parsed = [_t("a", due="2026-07-10", tags=["action"])]
        seed = build_engage_seed(parsed, today=TODAY)
        assert seed["items"][0]["redacted"] is False

    def test_every_row_carries_full_field_set(self):
        # the curtain-not-vault guard — no field is ever null/stripped on a shielded row
        parsed = [_t("a", "Secret", due="2026-07-10", postponed=2, tags=["action", "redacted"])]
        row = build_engage_seed(parsed, today=TODAY)["items"][0]
        for k in (
            "id",
            "name",
            "kind",
            "has_deadline",
            "blocked",
            "postponed",
            "suggested",
            "redacted",
            "due",
        ):
            assert k in row, k
        assert row["name"] == "Secret"
        assert row["postponed"] == 2
