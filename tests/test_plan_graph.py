"""Tests for plan_graph — the deterministic DAG / judgement / timeline-order engine."""

from rtm_mcp.plan_graph import build_graph

HEADER = {"project": {"id": "P"}}


def _row(rid, tags=None, deps=None, completed=0, due="", start="", estimate="", name=None):
    return {
        "id": rid,
        "tags": tags or ["action"],
        "deps": deps or [],
        "completed": completed,
        "due": due,
        "start": start,
        "estimate": estimate,
        "name": name or rid,
        "notes": [],
    }


class TestEdgesAndBlocked:
    def test_depends_on_edge_and_blocked(self):
        rows = [_row("a"), _row("b", deps=["a"])]
        g = build_graph(HEADER, rows)
        assert {"src": "a", "dst": "b", "via": "depends-on"} in g["edges"]
        assert g["judgement"]["b"]["blocked"] is True
        assert g["judgement"]["a"]["blocked"] is False

    def test_completed_upstream_unblocks(self):
        rows = [_row("a", completed=1), _row("b", deps=["a"])]
        g = build_graph(HEADER, rows)
        assert g["judgement"]["b"]["blocked"] is False

    def test_external_dep_not_a_sibling_is_dropped(self):
        rows = [_row("b", deps=["external"])]
        g = build_graph(HEADER, rows)
        assert g["edges"] == []
        assert g["judgement"]["b"]["blocked"] is False


class TestQuick:
    def test_quick_from_tag_when_ready(self):
        rows = [_row("q", tags=["action", "quick_win"])]
        g = build_graph(HEADER, rows)
        assert g["judgement"]["q"]["quick"] is True
        assert g["judgement"]["q"]["quick_ready"] is True

    def test_blocked_quick_is_not_quick(self):
        rows = [_row("a"), _row("q", tags=["action", "quick_win"], deps=["a"])]
        g = build_graph(HEADER, rows)
        assert g["judgement"]["q"]["quick"] is False  # blocked → not quick
        assert g["judgement"]["q"]["quick_ready"] is False

    def test_waiting_for_never_quick(self):
        rows = [_row("w", tags=["waiting_for", "quick_win"])]
        g = build_graph(HEADER, rows)
        assert g["judgement"]["w"]["quick"] is False


class TestOrder:
    def test_quick_unblocker_sorts_before_plain(self):
        rows = [_row("n", tags=["action"]), _row("q", tags=["action", "quick_win"])]
        g = build_graph(HEADER, rows)
        assert g["order"].index("q") < g["order"].index("n")

    def test_producer_before_consumer(self):
        rows = [_row("b", deps=["a"]), _row("a")]
        g = build_graph(HEADER, rows)
        assert g["order"].index("a") < g["order"].index("b")

    def test_completed_sorts_last(self):
        rows = [_row("done", completed=1), _row("open")]
        g = build_graph(HEADER, rows)
        assert g["order"][-1] == "done"


class TestManualOrder:
    """The manual-order pin (DC-4: derived from the latest valid ORDER note). Clamping-parity
    cases mirror the gtd plugin's `test_plan_graph.py` TestManualOrder suite one-for-one."""

    def test_pin_reorders_independent_siblings(self):
        rows = [_row("A"), _row("B")]  # both ready, independent
        assert build_graph(HEADER, rows)["order"] == ["A", "B"]  # input order by default
        pinned = build_graph(HEADER, rows, manual_order=["B", "A"])["order"]
        assert pinned == ["B", "A"]  # the drag pin is reproduced

    def test_pin_cannot_violate_topology(self):
        # consumer pinned ahead of its producer — the DAG must still win
        rows = [_row("1"), _row("2", deps=["1"])]
        g = build_graph(HEADER, rows, manual_order=["2", "1"])
        assert g["order"].index("1") < g["order"].index("2")

    def test_unpinned_items_fall_after_pinned_in_cohort(self):
        rows = [_row("A"), _row("B"), _row("C")]  # three independent, ready
        g = build_graph(HEADER, rows, manual_order=["C"])  # only C pinned
        assert g["order"] == ["C", "A", "B"]  # C first, rest keep input order

    def test_pin_returned_cleaned_to_current_ids(self):
        rows = [_row("1"), _row("2")]
        g = build_graph(HEADER, rows, manual_order=["2", "1", "999"])  # 999 no longer in plan
        assert g["manual_order"] == ["2", "1"]  # stale id dropped, order preserved

    def test_no_pin_is_unchanged_behaviour(self):
        rows = [_row("A"), _row("B", deps=["A"]), _row("C")]
        base = build_graph(HEADER, rows)["order"]
        assert base == build_graph(HEADER, rows, manual_order=None)["order"]
        assert base == build_graph(HEADER, rows, manual_order=[])["order"]

    def test_pin_is_not_part_of_fingerprint(self):
        rows = [_row("A"), _row("B")]
        assert (
            build_graph(HEADER, rows)["fingerprint"]
            == build_graph(HEADER, rows, manual_order=["B", "A"])["fingerprint"]
        )


class TestCyclesAndFingerprint:
    def test_cycle_detected_and_order_still_complete(self):
        rows = [_row("c1", deps=["c2"]), _row("c2", deps=["c1"])]
        g = build_graph(HEADER, rows)
        assert g["cycles"]  # advisory cycle reported
        assert set(g["order"]) == {"c1", "c2"}  # order still renders everything

    def test_fingerprint_stable_and_change_sensitive(self):
        rows = [_row("a", name="Alpha")]
        fp1 = build_graph(HEADER, rows)["fingerprint"]
        fp2 = build_graph(HEADER, [_row("a", name="Alpha")])["fingerprint"]
        fp3 = build_graph(HEADER, [_row("a", name="Beta")])["fingerprint"]
        assert fp1 == fp2
        assert fp1 != fp3
