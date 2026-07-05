"""Tests for plan_graph — the deterministic DAG / judgement / timeline-order engine."""

from rtm_mcp.plan_graph import build_graph

HEADER = {"project": {"id": "P"}}


def _row(
    rid, tags=None, deps=None, completed=0, due="", start="", estimate="", name=None, priority=""
):
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
        "priority": priority,
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


class TestBand:
    """MoSCoW band joins the within-tier sort (2026-07-05): tier → band → due/start → input.
    Mirrors the gtd plugin's `test_plan_graph.py` TestBand suite one-for-one."""

    def test_must_sorts_above_could_within_tier(self):
        rows = [_row("C", priority="Low"), _row("M", priority="High")]
        g = build_graph(HEADER, rows)
        assert g["order"] == ["M", "C"]  # Must above Could, input order overridden

    def test_untriaged_sorts_after_could(self):
        rows = [_row("U"), _row("C", priority="Low")]
        g = build_graph(HEADER, rows)
        assert g["order"] == ["C", "U"]  # `!-` is debt — visibly last

    def test_full_band_sequence(self):
        rows = [
            _row("U"),
            _row("C", priority="Low"),
            _row("S", priority="Medium"),
            _row("M", priority="High"),
        ]
        g = build_graph(HEADER, rows)
        assert g["order"] == ["M", "S", "C", "U"]

    def test_numeric_priority_surface_accepted(self):
        # draft-board / canvas rows carry "1"/"2"/"3" rather than the RTM API words
        rows = [_row("C", priority="3"), _row("M", priority="1")]
        g = build_graph(HEADER, rows)
        assert g["order"] == ["M", "C"]

    def test_band_beats_date_within_tier(self):
        rows = [_row("C", priority="Low", due="2026-07-01"), _row("M", priority="High")]
        g = build_graph(HEADER, rows)
        assert g["order"] == ["M", "C"]  # band before due/start

    def test_tier_outranks_band(self):
        # a quick-win Could still displays above a non-quick Must: readiness/leverage beat importance
        rows = [_row("M", priority="High"), _row("C", tags=["action", "quick_win"], priority="Low")]
        g = build_graph(HEADER, rows)
        assert g["order"] == ["C", "M"]

    def test_band_never_violates_topology(self):
        # Must consumer of a Could producer: the DAG is absolute
        rows = [_row("P", priority="Low"), _row("Q", deps=["P"], priority="High")]
        g = build_graph(HEADER, rows)
        assert g["order"].index("P") < g["order"].index("Q")

    def test_pin_outranks_band(self):
        rows = [_row("M", priority="High"), _row("C", priority="Low")]
        g = build_graph(HEADER, rows, manual_order=["C", "M"])
        assert g["order"] == ["C", "M"]  # Paul's pin wins over the band sort

    def test_band_change_flips_fingerprint(self):
        base = build_graph(HEADER, [_row("1", priority="Low")])["fingerprint"]
        assert base != build_graph(HEADER, [_row("1", priority="High")])["fingerprint"]
        assert base != build_graph(HEADER, [_row("1")])["fingerprint"]  # band → untriaged
        assert base == build_graph(HEADER, [_row("1", priority="Low")])["fingerprint"]


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


def _tok(rid, deps=None, token=None):
    """A row carrying an optional template-child token (repeating templated project)."""
    r = _row(rid, deps=deps or [])
    if token is not None:
        r["template_child_id"] = token
    return r


class TestTemplateChildTokenResolution:
    """resolve-references: token-space deps/pins resolve to the current occurrence's re-keyed
    ids via `template_child_id`; a one-off project (no tokens) is byte-unchanged. Mirrors the
    gtd `test_plan_graph_series.py` cases."""

    def _edges(self, g):
        return {(e["src"], e["dst"]) for e in g["edges"]}

    def test_token_dep_resolves_to_current_id(self):
        rows = [_tok("201", token="c1"), _tok("202", deps=["c1"], token="c2")]
        g = build_graph(HEADER, rows)
        assert ("201", "202") in self._edges(g)
        assert g["judgement"]["202"]["blocked"] is True
        assert g["judgement"]["202"]["blockers"] == ["201"]

    def test_stale_id_without_token_is_dropped(self):
        # a raw upstream id from a PRIOR occurrence (not current, not a token) → dropped
        rows = [_tok("201", token="c1"), _tok("202", deps=["999999"], token="c2")]
        g = build_graph(HEADER, rows)
        assert self._edges(g) == set()
        assert g["judgement"]["202"]["blocked"] is False

    def test_mixed_raw_current_id_and_token(self):
        rows = [
            _tok("201", token="c1"),
            _tok("202", deps=["201"], token="c2"),  # raw current id
            _tok("203", deps=["c2"], token="c3"),  # token
        ]
        g = build_graph(HEADER, rows)
        assert self._edges(g) == {("201", "202"), ("202", "203")}

    def test_token_pin_resolves(self):
        rows = [_tok("201", token="c1"), _tok("202", token="c2")]
        g = build_graph(HEADER, rows, manual_order=["c2", "c1"])  # pin in token-space
        assert g["manual_order"] == ["202", "201"]

    def test_stale_pin_entry_without_token_dropped(self):
        rows = [_tok("201", token="c1")]
        g = build_graph(HEADER, rows, manual_order=["c1", "999999"])
        assert g["manual_order"] == ["201"]

    def test_no_tokens_is_unchanged(self):
        # token_map empty → raw-id deps + pin behave exactly as before
        rows = [_row("1"), _row("2", deps=["1"]), _row("3", deps=["2"])]
        g = build_graph(HEADER, rows, manual_order=["3", "1"])
        assert self._edges(g) == {("1", "2"), ("2", "3")}
        assert g["manual_order"] == ["3", "1"]
