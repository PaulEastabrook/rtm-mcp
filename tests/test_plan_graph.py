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
