"""Cross-repo parity guard for the plan_graph engine (gtd A2.1 Piece 0a).

rtm-mcp's `src/rtm_mcp/plan_graph.py` and the gtd plugin's
`plugins/gtd/skills/gtd/scripts/plan_graph.py` are byte-compatible-by-hand ports
of one algorithm. This test pins THIS repo's engine to a shared golden
(`plan_graph_parity_golden.json`); the gtd repo carries an identical golden + test
(`test_plan_graph_parity.py`). If either engine drifts, its test fails.

Regenerate the golden ONLY when both engines change in lockstep, and update BOTH copies.
"""

import json
import os

from rtm_mcp.plan_graph import build_graph

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "plan_graph_parity_golden.json")) as f:
    GOLDEN = json.load(f)

THIN_KEYS = ("edges", "judgement", "order", "cycles", "fingerprint")


def test_matches_cross_repo_golden():
    g = build_graph(GOLDEN["input"]["header"], GOLDEN["input"]["rows"])
    out = {k: g[k] for k in THIN_KEYS}
    assert out == GOLDEN["expected"], (
        "rtm-mcp plan_graph output drifted from the cross-repo parity golden. The "
        "rtm-mcp and gtd plan_graph engines must stay byte-compatible - fix the drift, "
        "or, if the change is intentional and applied to BOTH engines, regenerate the "
        "golden and update both repos' copies in lockstep."
    )
