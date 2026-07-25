#!/usr/bin/env python
"""D9 — the tool-naming conformance check (CONTRIBUTING § 2.7).

Flags any tool whose **name form disagrees with its `readOnlyHint` annotation**: an imperative
verb segment on a read, or a result-noun suffix on a write. It introspects the LIVE server, so it
can never drift from what is actually advertised.

**Report-only at v3.0.0, blocking at v3.1.0.** It cannot block while the deprecated aliases are
exposed, because the aliases *are* the non-conformant names — it would fire on all 25 by
construction. `--strict` exits non-zero and is what CI runs once they are gone.

**A name matching neither lexicon is reported `unclassifiable` and NEVER silently passes.** That
rule is the point of the check, not a detail of it. A control that quietly passes what it does not
recognise is the same silent failure this programme has now found five times — the MilkScript
guard idiom, a `Phase:` regex against a field named `State:`, a `completedAfter:"N days ago"`
filter RTM ignores, an audit threshold measuring bytes when the property was coupling, and a
first-token-vs-whole-line `State:` parse. It is also precisely how a novel verb would escape.

Usage:
    uv run python scripts/check-tool-naming.py            # report-only (exit 0)
    uv run python scripts/check-tool-naming.py --strict   # exit 1 on any finding
    uv run python scripts/check-tool-naming.py --json     # machine-readable
"""

import argparse
import asyncio
import json
import sys

#: Imperative verb segments — a COMMAND's marker. Sourced from the operations the suite actually
#: performs; extend deliberately, and say so in the debrief when you do.
IMPERATIVE_SEGMENTS = frozenset(
    {
        "add",
        "annotate",
        "apply",
        "attach",
        "capture",
        "check",
        "classify",
        "close",
        "commit",
        "complete",
        "consolidate",
        "create",
        "delete",
        "drain",
        "edit",
        "link",
        "move",
        "post",
        "resolve",
        "seed",
        "set",
        "stamp",
        "sweep",
        "transition",
        "undo",
    }
)

#: Result-noun suffixes — a QUERY's marker. The tool is named for the thing it returns.
RESULT_NOUNS = frozenset(
    {
        "candidates",
        "canvas",
        "context",
        "gaps",
        "index",
        "inflight",
        "plan",
        "projects",
        "queue",
        "report",
        "shape",
        "state",
        "thread",
        "today",
    }
)

#: Documented adjective-filter reads: a query named for the PROPERTY it filters on rather than a
#: result noun. `gtd_item_stale` is the first — it is a read, it reads as a noun phrase, and it
#: passes the read/write test; it simply carries no result-noun suffix. Extending the query
#: lexicon was chosen over renaming a Wave 1 tool for a suffix (see the v3.0.0 debrief).
ADJECTIVE_FILTERS = frozenset({"stale"})

#: Names exempt by deliberate decision, each with its reason. Nothing is exempt by silence.
EXEMPT: dict[str, str] = {
    "gtd_next_actions": (
        "ubiquitous-language exception (D13) — 'Next Actions' is GTD's canonical list name and "
        "prefixing it degrades it; action-only, so the `item` umbrella would be wrong"
    ),
    "gtd_waiting_for_queue": "area is a lifecycle stage (D12); `_queue` is the result noun",
    "gtd_engage_seed": (
        "`seed` is the result noun here (the engage seed set), not the verb — a read named for "
        "what it returns"
    ),
}


def classify(name: str, read_only: bool) -> tuple[str, str]:
    """`(verdict, detail)` for one tool name. Verdict ∈ ok | finding | unclassifiable | exempt."""
    if name in EXEMPT:
        return "exempt", EXEMPT[name]

    segments = name.split("_")
    imperatives = [seg for seg in segments if seg in IMPERATIVE_SEGMENTS]
    suffix = segments[-1] if segments else ""
    has_result_noun = suffix in RESULT_NOUNS
    has_adjective_filter = suffix in ADJECTIVE_FILTERS

    # THE SUFFIX WINS over an imperative-looking segment elsewhere in the name. `_candidates`,
    # `_report` and friends are what the tool RETURNS, and an earlier segment is then a noun
    # adjunct naming the subject, not a verb. Without this ordering the check fires on the whole
    # `gtd_<shape>_candidates` detector family — `capture` in `gtd_capture_candidates` is the
    # contribution shape being detected, not an instruction to capture anything. (That was this
    # check's own first false positive, caught on its first run.)
    if read_only:
        if has_result_noun or has_adjective_filter:
            kind = "adjective-filter" if has_adjective_filter else "result-noun"
            return "ok", f"query, {kind} '{suffix}'"
        if imperatives:
            return (
                "finding",
                f"imperative segment {imperatives!r} on a READ-ONLY tool with no result-noun "
                f"suffix — a query is named for the thing it returns, not the operation",
            )
    else:
        if imperatives:
            return "ok", f"command, imperative {imperatives!r}"
        if has_result_noun or has_adjective_filter:
            return (
                "finding",
                f"result-noun suffix '{suffix}' on a WRITING tool — a command is named for the "
                f"operation, not the result",
            )
    return (
        "unclassifiable",
        f"name matches neither lexicon (suffix '{suffix}', read_only={read_only}) — extend a "
        f"lexicon or EXEMPT deliberately; it must not pass by silence",
    )


async def collect() -> list[dict[str, object]]:
    from rtm_mcp.server import mcp
    from rtm_mcp.tools.gtd import DEPRECATED_ALIASES

    deprecated = set(DEPRECATED_ALIASES) | {"gtd_query"}
    rows: list[dict[str, object]] = []
    for tool in await mcp.list_tools():
        mcp_tool = tool.to_mcp_tool()
        name = mcp_tool.name
        if not name.startswith("gtd_"):
            continue  # bare-verb RTM primitives are outside the domain-composition standard
        read_only = bool(getattr(mcp_tool.annotations, "readOnlyHint", False))
        verdict, detail = classify(name, read_only)
        rows.append(
            {
                "tool": name,
                "read_only": read_only,
                "verdict": "deprecated" if name in deprecated else verdict,
                "detail": (
                    "deprecated alias — non-conformant BY CONSTRUCTION, removed at v3.1.0"
                    if name in deprecated
                    else detail
                ),
            }
        )
    return sorted(rows, key=lambda r: str(r["tool"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true", help="exit 1 on any finding (v3.1.0+)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    rows = asyncio.run(collect())
    findings = [r for r in rows if r["verdict"] == "finding"]
    unclassifiable = [r for r in rows if r["verdict"] == "unclassifiable"]

    if args.json:
        print(json.dumps({"rows": rows}, indent=2))
    else:
        buckets: dict[str, int] = {}
        for r in rows:
            buckets[str(r["verdict"])] = buckets.get(str(r["verdict"]), 0) + 1
        print("D9 tool-naming conformance — report-only at v3.0.0\n")
        for verdict in ("finding", "unclassifiable", "exempt", "ok", "deprecated"):
            if verdict in buckets:
                print(f"  {verdict:16} {buckets[verdict]:3}")
        for label, group in (("FINDINGS", findings), ("UNCLASSIFIABLE", unclassifiable)):
            if group:
                print(f"\n{label}:")
                for r in group:
                    print(f"  {r['tool']}\n      {r['detail']}")
        if not findings and not unclassifiable:
            print("\nNo findings. Every non-deprecated gtd tool classifies and conforms.")

    if args.strict and (findings or unclassifiable):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
