"""Merge the plan-graph overlay onto the canvas seed, and the lean (inline) transform.

Pure (no IO). Byte-compatible port of the merge helpers in the gtd plugin's
`skills/gtd/scripts/build_canvas.py` (`_apply_graph` + `_lean_seed`). These two functions are the
byte-compat-critical glue between `canvas_seed.build_seed` (the rendered shape) and
`plan_graph.build_graph` (the deterministic overlay):

- ``apply_graph`` reorders the seed rows by the graph's TIMELINE order and stamps the render-only
  judgement: ``quick`` (when an item is ``quick_ready``) and ``deps`` (the sorted set of in-plan
  producer ids from the graph edges). It does NOT add a ``blocked`` or integer ``order`` field —
  the canvas template derives ``blocked`` from ``deps[]`` and reads order from the array order.
- ``lean_seed`` drops note bodies (``b``) and caps each item's ``notes[]`` to ``note_cap``, setting
  an honest ``nc`` (true total) when it caps — the inline-widget (html-lean) payload profile.
"""

from typing import Any


def apply_graph(seed: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Reorder the seed by the graph's TIMELINE order and stamp judgement (quick + deps) onto each
    item, so the canvas pill surface is always populated from the graph — render-only. Mutates and
    returns the same seed dict."""
    items = {it.get("id"): it for it in seed["seed"] if it.get("id")}
    judge = graph.get("judgement", {})
    # edges → consumer:[producers] (siblings), to drive the template's blocked/gating from the graph
    deps_by: dict[str, list[str]] = {}
    for e in graph.get("edges", []):
        deps_by.setdefault(e["dst"], []).append(e["src"])
    for rid, it in items.items():
        j = judge.get(rid)
        if j:
            if j.get("quick_ready"):
                it["quick"] = 1
            if deps_by.get(rid):
                it["deps"] = sorted(set(deps_by[rid]))
    order = [rid for rid in graph.get("order", []) if rid in items]
    ordered = [items[rid] for rid in order]
    # any item not in the graph order (defensive) keeps its place at the end, history last
    leftover = [it for it in seed["seed"] if it.get("id") not in set(order)]
    seed["seed"] = ordered + leftover
    return seed


def lean_seed(seed: dict[str, Any], note_cap: int = 3) -> dict[str, Any]:
    """Inline-render transform (html-lean profile). Drops full note bodies (`b`) everywhere and caps
    each item's notes[] to note_cap, so the canvas fragment is small enough to hand to a host
    inline-widget tool. The "+N more — open in RTM" line (driven by `nc`) keeps the cap honest, and
    the dropped bodies stay one click away via each row's deep link. Frame (project-level) notes
    keep every gist but also shed their bodies. Mutates and returns the same seed dict."""

    def _strip_bodies(notes: list[dict[str, Any]] | None) -> None:
        for n in notes or []:
            n.pop("b", None)

    _strip_bodies(seed.get("frame", {}).get("notes"))
    for it in seed.get("seed", []):
        notes = it.get("notes") or []
        _strip_bodies(notes)
        if note_cap is not None and note_cap >= 0 and len(notes) > note_cap:
            it["nc"] = it.get("nc") or len(notes)  # true total, so "+N more in RTM" stays honest
            it["notes"] = notes[:note_cap]
    return seed
