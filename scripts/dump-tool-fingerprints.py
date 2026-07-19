#!/usr/bin/env python
"""Emit the committed tool-fingerprints.json — per-tool schema fingerprints for the family standard.

The architect's weekly tool-detection scan (marketplace commit 3e9775c24) diffs these per-tool
`sha256` fingerprints to raise `schema-changed` events, and downstream interface-proof currency keys
on them (RTM 1217273393). Contract: the family MCP tool-documentation standard § 5 "Schema
fingerprints" (`plugin-marketplace-git-ops/.../mcp-tool-documentation-standard.md`).

A fingerprint is the `sha256` of the canonical JSON (`sort_keys=True`, compact separators) of a
tool's `{"description", "inputSchema", "annotations", "outputSchema"}` (null for an absent member),
taken from the REAL server via the same `list_tools()` → `to_mcp_tool()` introspection as
`tests/test_tool_schemas.py`. Tool names are fully qualified (`mcp__rtm__<tool>`) to remove any
composing ambiguity for the consumer.

Freshness is enforced by the repo, not the consumer: `tests/test_tool_schemas.py` recomputes this map
and asserts equality with the committed file, so a schema change without a regenerated file fails CI.

Regenerate (also `make fingerprints`):

    uv run python scripts/dump-tool-fingerprints.py

Run without arguments to overwrite `tool-fingerprints.json` at the repo root; pass `--check` to only
verify the committed file's `tools` map is current (non-zero exit on drift), matching the CI test.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from rtm_mcp import __version__
from rtm_mcp.server import mcp

SCHEMA_VERSION = 1
# The connector slug the architect composes qualified names from (`mcp__rtm__<tool>`) — deliberately
# NOT the FastMCP internal name ("rtm-mcp"); the standard's example is `"server": "rtm"`.
SERVER = "rtm"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "tool-fingerprints.json"


def _fingerprint(mcp_tool) -> str:
    """sha256 over canonical JSON of the four schema members (null for an absent member)."""
    ann = mcp_tool.annotations
    obj = {
        "description": mcp_tool.description,
        "inputSchema": mcp_tool.inputSchema,
        "annotations": ann.model_dump(mode="json", exclude_none=True) if ann is not None else None,
        "outputSchema": mcp_tool.outputSchema,
    }
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def compute_fingerprints() -> dict[str, str]:
    """Map each fully-qualified tool name (`mcp__rtm__<tool>`) to its schema fingerprint."""
    if hasattr(mcp, "list_tools"):  # FastMCP 3.x
        tools = {t.name: t for t in await mcp.list_tools()}
    else:  # pragma: no cover — FastMCP 2.x fallback
        tools = await mcp.get_tools()
    return {
        f"mcp__{SERVER}__{name}": _fingerprint(tool.to_mcp_tool())
        for name, tool in sorted(tools.items())
    }


def build_document(tools: dict[str, str]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "server": SERVER,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_version": __version__,
        "tools": tools,
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed tools map is current; do not write (non-zero exit on drift)",
    )
    args = parser.parse_args()

    tools = await compute_fingerprints()

    if args.check:
        if not OUTPUT_PATH.exists():
            print(f"missing {OUTPUT_PATH.name} — run: make fingerprints", file=sys.stderr)
            return 1
        committed = json.loads(OUTPUT_PATH.read_text())
        if committed.get("tools") != tools:
            print(
                f"{OUTPUT_PATH.name} is stale — tool schemas changed. Run: make fingerprints",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT_PATH.name} is current ({len(tools)} tools).")
        return 0

    OUTPUT_PATH.write_text(json.dumps(build_document(tools), indent=2) + "\n")
    print(f"Wrote {OUTPUT_PATH.name} ({len(tools)} tools, source_version {__version__}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
