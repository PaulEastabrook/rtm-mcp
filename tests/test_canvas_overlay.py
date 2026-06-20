"""Tests for canvas_overlay — apply_graph (merge) and lean_seed (inline transform)."""

from rtm_mcp.canvas_overlay import apply_graph, lean_seed


class TestApplyGraph:
    def _seed(self):
        return {
            "mode": "existing",
            "frame": {},
            "seed": [
                {"e": 1, "id": "a", "k": "action", "t": "A", "notes": []},
                {"e": 1, "id": "b", "k": "action", "t": "B", "notes": []},
            ],
        }

    def _graph(self):
        return {
            "order": ["b", "a"],
            "judgement": {"a": {"quick_ready": True}, "b": {"quick_ready": False}},
            "edges": [{"src": "a", "dst": "b", "via": "depends-on"}],
        }

    def test_reorders_by_graph_order(self):
        seed = apply_graph(self._seed(), self._graph())
        assert [it["id"] for it in seed["seed"]] == ["b", "a"]

    def test_stamps_quick_and_deps_only(self):
        seed = apply_graph(self._seed(), self._graph())
        by_id = {it["id"]: it for it in seed["seed"]}
        assert by_id["a"]["quick"] == 1
        assert "quick" not in by_id["b"]
        assert by_id["b"]["deps"] == ["a"]  # sorted producer set
        # the overlay must NOT add blocked / integer-order fields (template derives blocked)
        for it in seed["seed"]:
            assert "blocked" not in it
            assert "order" not in it

    def test_items_missing_from_order_kept_at_end(self):
        seed = self._seed()
        seed["seed"].append({"e": 1, "id": "c", "k": "action", "t": "C", "notes": []})
        graph = self._graph()  # order only mentions a, b
        out = apply_graph(seed, graph)
        assert out["seed"][-1]["id"] == "c"


class TestLeanSeed:
    def test_strips_bodies_and_caps_notes(self):
        seed = {
            "frame": {"notes": [{"t": "NOTE", "d": "", "s": "g", "b": "full"}]},
            "seed": [
                {
                    "id": "a",
                    "notes": [
                        {"t": "A", "d": "", "s": "1", "b": "b1"},
                        {"t": "B", "d": "", "s": "2", "b": "b2"},
                        {"t": "C", "d": "", "s": "3", "b": "b3"},
                        {"t": "D", "d": "", "s": "4", "b": "b4"},
                    ],
                }
            ],
        }
        out = lean_seed(seed, note_cap=3)
        assert "b" not in out["frame"]["notes"][0]  # frame body dropped
        item = out["seed"][0]
        assert len(item["notes"]) == 3  # capped
        assert all("b" not in n for n in item["notes"])  # bodies dropped
        assert item["nc"] == 4  # honest true total

    def test_no_nc_when_under_cap(self):
        seed = {"frame": {}, "seed": [{"id": "a", "notes": [{"t": "A", "d": "", "s": "1"}]}]}
        out = lean_seed(seed, note_cap=3)
        assert "nc" not in out["seed"][0]
