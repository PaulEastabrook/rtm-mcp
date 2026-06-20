"""The deterministic project plan-graph engine.

Pure (no IO), stdlib-only. Byte-compatible port of the gtd plugin's
`skills/gtd/scripts/plan_graph.py` (`build_graph` + helpers); the CLI shim from the reference is
dropped. A project plan is a typed producer→consumer DAG, not a list. This overlay is
AUGMENTATION — it never writes RTM and never pushes sibling order to RTM (the API can't take it).

It takes the comprehensive envelope rows (from `project_plan.build_envelope` /
`canvas_seed.parse_envelope`) and produces:

  build_graph(header, rows, outputs_index=None, context_deps=None, lexical_deps=None,
              manual_order=None)
      -> {
           "nodes":  [{id, kind, name, done, estimate_min, ...}],
           "edges":  [{src, dst, via}],          # producer src → consumer dst; via=what flows
           "judgement": {id: {blocked, blockers[], quick, quick_ready}},
           "order":  [id, ...],                  # derived TIMELINE order (see below)
           "cycles": [[id,...], ...],            # advisory only — NEVER blocks
           "fingerprint": "<hex>",               # change-detection key for the persisted cache
           "manual_order": [id, ...],            # the persisted user pin, cleaned to current ids
         }

In the v1 canvas read path the server calls this with `(header, rows)` only — so edges derive
solely from active DEPENDS-ON notes (`row.deps`); `outputs_index` / `context_deps` /
`lexical_deps` / `manual_order` stay empty (they need vault access — a later DC). The parameters
are kept so that path can be added without changing the signature.

ORDER (reads top-to-bottom as a TIMELINE): topological as the hard constraint (never before your
inputs); within a ready cohort the tier order is 2-min unblockers → 2-min items → other
unblockers → the rest, tie-broken by due/start date then original input order. Completed
(history) items sort last. CYCLES are detected and returned as advisory `cycles`; the order falls
back gracefully (the weakest back-edge is ignored for layering) so a list always renders.
"""

import hashlib
import re
from itertools import pairwise
from typing import Any

_DIGITS = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?$")


def _estimate_minutes(est: str | None) -> int | None:
    """RTM estimate string → minutes (None if absent/unparseable). Mirrors rtm-mcp parse_estimate."""
    if not est:
        return None
    m = _DIGITS.match(est.strip())
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    h = re.search(r"(\d+)\s*hour", est)
    mi = re.search(r"(\d+)\s*min", est)
    if h or mi:
        return (int(h.group(1)) * 60 if h else 0) + (int(mi.group(1)) if mi else 0)
    return None


def _kind(row: dict[str, Any]) -> str:
    tags = row.get("tags") or []
    if "waiting_for" in tags:
        return "waiting_for"
    if "calendar_entry" in tags:
        return "calendar"
    return "action"


def build_graph(header: dict[str, Any], rows: list[dict[str, Any]],
                outputs_index: list[dict[str, Any]] | None = None,
                context_deps: dict[str, list[str]] | None = None,
                lexical_deps: dict[str, list[str]] | None = None,
                manual_order: list[str] | None = None) -> dict[str, Any]:
    context_deps = context_deps or {}
    lexical_deps = lexical_deps or {}
    ids = [str(r.get("id")) for r in rows]
    id_set = set(ids)
    by_id = {str(r.get("id")): r for r in rows}

    nodes = []
    for r in rows:
        rid = str(r.get("id"))
        est = _estimate_minutes(r.get("estimate"))
        nodes.append({
            "id": rid, "kind": _kind(r), "name": r.get("name") or "",
            "done": bool(r.get("completed")), "due": r.get("due") or "",
            "start": r.get("start") or "", "estimate_min": est,
        })

    # ── edges (producer → consumer), deterministic-first ──────────────────
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()

    def add_edge(producer: Any, consumer: Any, via: str) -> None:
        producer, consumer = str(producer), str(consumer)
        if producer in id_set and consumer in id_set and producer != consumer:
            key = (producer, consumer)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({"src": producer, "dst": consumer, "via": via})

    # 1. DEPENDS-ON notes: row.deps = upstream producers this row consumes
    for r in rows:
        for up in (r.get("deps") or []):
            add_edge(up, r.get("id"), "depends-on")
    # 2. output-consumption via source_action: if a row's notes reference an artefact owned by
    #    another row, that row consumes the owner's output → owner(producer) → row(consumer)
    if outputs_index:
        owner_by_name = {str(e.get("filename")): str(e.get("source_action") or "")
                         for e in outputs_index if e.get("filename") and e.get("source_action")}
        for r in rows:
            consumer = str(r.get("id"))
            mentioned = set()
            for p in (r.get("files") or []):
                mentioned.add(p.rsplit("/", 1)[-1])
            for n in (r.get("notes") or []):
                body = n.get("body") or ""
                for fn in owner_by_name:
                    if fn in body:
                        mentioned.add(fn)
            for fn in mentioned:
                owner = owner_by_name.get(fn, "")
                if owner and owner != consumer:
                    add_edge(owner, consumer, "output:" + fn)
    # 3 + 4. context.md and lexical (passed in)
    for consumer, ups in context_deps.items():
        for up in ups:
            add_edge(up, consumer, "context.md")
    for consumer, ups in lexical_deps.items():
        for up in ups:
            add_edge(up, consumer, "lexical")

    # ── blocked / quick judgement ─────────────────────────────────────────
    upstreams: dict[str, list[str]] = {rid: [] for rid in ids}
    for e in edges:
        upstreams[e["dst"]].append(e["src"])

    judgement: dict[str, dict[str, Any]] = {}
    for rid in ids:
        node = by_id[rid]
        done = bool(node.get("completed"))
        open_blockers = [u for u in upstreams[rid]
                         if not by_id[u].get("completed")]      # upstream not yet done
        blocked = len(open_blockers) > 0
        kind = _kind(node)
        # quick (2-min rule): READ from the persisted #quick_win tag — the judgement is made at GTD
        # write-time (clarify / creation / adjustment), not recomputed here. Structural guards still
        # hold: action/calendar only, unblocked, not done; waiting_for never quick (even if mis-tagged).
        quick = (kind in ("action", "calendar") and not blocked and not done
                 and "quick_win" in (node.get("tags") or []))
        judgement[rid] = {"blocked": blocked, "blockers": open_blockers,
                          "quick": bool(quick),
                          "quick_ready": bool(quick and not blocked)}

    # ── cycle detection (advisory) ────────────────────────────────────────
    cycles = _find_cycles(ids, upstreams)
    cycle_edges = _weak_back_edges(cycles, edges)   # edges to ignore for layering only

    # ── timeline order: topological layering + tiered ready cohort, manual pin honoured ──
    clean_manual = [i for i in (manual_order or []) if i in id_set]
    order = _timeline_order(ids, by_id, upstreams, judgement, cycle_edges, clean_manual)

    fingerprint = _fingerprint(header, rows)
    return {"nodes": nodes, "edges": edges, "judgement": judgement,
            "order": order, "cycles": cycles, "fingerprint": fingerprint,
            "manual_order": clean_manual}


def _find_cycles(ids: list[str], upstreams: dict[str, list[str]]) -> list[list[str]]:
    """Return a list of cycles (each a list of node ids). Advisory only."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {i: WHITE for i in ids}
    cycles: list[list[str]] = []
    stack: list[str] = []

    def visit(u: str) -> None:
        colour[u] = GREY
        stack.append(u)
        for v in upstreams.get(u, []):       # follow producer edges
            if colour[v] == GREY:
                if v in stack:
                    cycles.append([*stack[stack.index(v):], v])
            elif colour[v] == WHITE:
                visit(v)
        stack.pop()
        colour[u] = BLACK

    for i in ids:
        if colour[i] == WHITE:
            visit(i)
    return cycles


def _weak_back_edges(cycles: list[list[str]], edges: list[dict[str, str]]) -> set[tuple[str, str]]:
    """Pick one edge per cycle to ignore for layering (the last edge in the detected cycle)."""
    ignore: set[tuple[str, str]] = set()
    for cyc in cycles:
        for a, b in pairwise(cyc):
            ignore.add((b, a))   # producer→consumer direction stored as (src,dst)
            break
    return ignore


def _timeline_order(ids: list[str], by_id: dict[str, dict[str, Any]],
                    upstreams: dict[str, list[str]], judgement: dict[str, dict[str, Any]],
                    cycle_edges: set[tuple[str, str]],
                    manual_order: list[str] | None = None) -> list[str]:
    """Topological layering (natural-sequence spine) with the tiered ready-cohort sort.

    When `manual_order` is given (Paul's drag-drop pin), it takes precedence over the cosmetic
    tiering WITHIN each topologically-ready cohort: pinned items sort by their pin index and ahead
    of unpinned items; unpinned items (added since the pin) keep the tiered/date sort and fall to
    the back of the cohort. The layering loop is unchanged, so the topological constraint (never a
    consumer before its producer) is preserved — the pin can reorder independent siblings, not the
    DAG."""
    # effective upstreams excluding the ignored back-edges (so cycles still layer)
    eff = {rid: [u for u in upstreams[rid] if (u, rid) not in cycle_edges] for rid in ids}
    placed: set[str] = set()
    order: list[str] = []
    open_ids = [i for i in ids if not by_id[i].get("completed")]
    done_ids = [i for i in ids if by_id[i].get("completed")]
    manual_rank = {rid: i for i, rid in enumerate(manual_order or []) if rid in set(ids)}

    def tier(rid: str) -> int:
        j = judgement[rid]
        # lower tier sorts earlier
        if j["quick"] and not j["blocked"]:
            return 0                                   # 2-min unblocker
        if j["quick"]:
            return 1                                   # 2-min item
        if not j["blocked"]:
            return 2                                   # other unblocker (ready)
        return 3                                       # blocked / the rest

    def sort_key(rid: str) -> tuple[Any, ...]:
        n = by_id[rid]
        pinned = rid in manual_rank
        # pinned items: (0, pin-index) — reproduce the drag order, ahead of unpinned.
        # unpinned items: (1, tier, …) — the original tiered/date sort, after the pinned ones.
        return (0 if pinned else 1,
                manual_rank[rid] if pinned else tier(rid),
                n.get("due") or "9999-99-99", n.get("start") or "9999-99-99",
                ids.index(rid))

    remaining = list(open_ids)
    guard = 0
    while remaining and guard < len(ids) + 5:
        guard += 1
        ready = [r for r in remaining if all(u in placed or u not in open_ids for u in eff[r])]
        if not ready:                                   # residual cycle — release all remaining
            ready = list(remaining)
        ready.sort(key=sort_key)
        for r in ready:
            order.append(r)
            placed.add(r)
        remaining = [r for r in remaining if r not in placed]
    order.extend(done_ids)                              # completed (history) last
    return order


def _fingerprint(header: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Stable hash over the INPUTS that meaningfully affect order + judgement — node set, per-node
    name/state/dates/estimate/tags, and the deterministic edge *inputs* (deps + artefact filenames +
    notes-digest). Deliberately NOT over the computed edges: the overlay's edge set may include
    consumer-added lexical edges, but the fingerprint must stay stable across that enrichment so a
    'hit' (inputs unchanged) reuses the cached graph. Any meaningful input change flips this."""
    h = hashlib.sha256()
    proj = header.get("project") or {}
    h.update((str(proj.get("id")) + "|").encode())
    for r in sorted(rows, key=lambda x: str(x.get("id"))):
        notes_digest = "".join(sorted((n.get("date", "") + ":" + (n.get("summary") or "")[:60])
                                      for n in (r.get("notes") or [])))
        h.update("|".join([
            str(r.get("id")), r.get("name") or "", str(r.get("completed") or 0),
            r.get("due") or "", r.get("start") or "", r.get("estimate") or "",
            ",".join(sorted(r.get("tags") or [])),
            ",".join(sorted(str(d) for d in (r.get("deps") or []))),
            ",".join(sorted(p.rsplit("/", 1)[-1] for p in (r.get("files") or []))),
            str(len(r.get("notes") or [])), notes_digest,
        ]).encode())
    return h.hexdigest()[:16]
