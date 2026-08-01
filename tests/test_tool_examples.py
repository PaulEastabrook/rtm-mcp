"""Every `EXAMPLES` entry is a CALLABLE call — asserted against the live advertised schema.

**Why this test exists.** `tool_help.EXAMPLES` is prose, so nothing checked it. Two of the entries
a caller is most likely to reach for were wrong for months: `gtd_project_create`'s items example
had drifted from its own parameter schema printed immediately above it, and `gtd_item_create`'s two
examples named **three parameters that do not exist** (`contexts`, `life`, `waiting_on`) while
omitting every required one. Anyone following either failed — and in a live incident on 2026-07-31
someone did, because an example beside a schema is read *instead of* the schema, not after it.

`make fingerprints` cannot catch this: a fingerprint hashes the advertised schema, and an example
is a string inside it. But the property is mechanically checkable, so it is checked here rather
than trusted:

1. every example parses as a Python call expression;
2. it names a tool that exists on the server;
3. every keyword argument it passes is a parameter that tool declares;
4. every REQUIRED parameter is either passed or deliberately exempted below.

Introspects the real server (`rtm_mcp.server.mcp`) exactly as `tests/test_tool_schemas.py` does, so
it can never drift from what is actually advertised.
"""

from __future__ import annotations

import ast

import pytest

from rtm_mcp.server import mcp
from rtm_mcp.tool_help import EXAMPLES

#: Examples that deliberately omit a required parameter, with the reason. An entry here is a
#: judgement on the record, not a way to silence the check — keep it empty unless there is a real
#: reason an example should show an incomplete call.
REQUIRED_OMISSION_EXEMPTIONS: dict[str, str] = {}


def _calls() -> list[tuple[str, str, ast.Call]]:
    """(tool_name, source, parsed call) for every example, with the trailing `# comment` kept.

    An example may carry a trailing comment; `ast.parse` handles that natively, so the strings are
    parsed as written rather than pre-stripped — which is the point, since a caller reads them as
    written too."""
    out: list[tuple[str, str, ast.Call]] = []
    for name, examples in EXAMPLES.items():
        for src in examples:
            tree = ast.parse(src.strip(), mode="eval")
            assert isinstance(tree.body, ast.Call), f"{name}: example is not a call — {src!r}"
            out.append((name, src, tree.body))
    return out


async def _params() -> dict[str, tuple[set[str], set[str]]]:
    """tool name → (every declared parameter, the required ones), from the LIVE advertised schema.

    Tolerates both FastMCP majors exactly as `tests/test_tool_schemas.py::_tools` does — 3.x
    exposes `list_tools()` returning a list, 2.x exposed `get_tools()` returning a keyed dict."""
    if hasattr(mcp, "list_tools"):
        tools = {t.name: t for t in await mcp.list_tools()}
    else:  # pragma: no cover — FastMCP 2.x fallback
        tools = await mcp.get_tools()
    out: dict[str, tuple[set[str], set[str]]] = {}
    for name, tool in tools.items():
        schema = tool.to_mcp_tool().inputSchema or {}
        out[name] = (
            set((schema.get("properties") or {}).keys()),
            set(schema.get("required") or []),
        )
    return out


class TestExamplesMatchTheAdvertisedSchema:
    async def test_every_example_targets_a_real_tool(self) -> None:
        declared = await _params()
        for name, src, call in _calls():
            assert name in declared, f"EXAMPLES key {name!r} is not a registered tool"
            called = getattr(call.func, "id", None)
            assert called == name, f"{name}: example calls {called!r} — {src!r}"

    async def test_no_example_passes_an_undeclared_keyword(self) -> None:
        """The defect that motivated the test: `contexts=`, `life=`, `waiting_on=` never existed."""
        declared = await _params()
        offences: list[str] = []
        for name, src, call in _calls():
            params, _ = declared[name]
            for kw in call.keywords:
                if kw.arg is not None and kw.arg not in params:
                    offences.append(f"{name}: `{kw.arg}` is not a parameter — {src!r}")
        assert not offences, "Examples name parameters that do not exist:\n" + "\n".join(offences)

    async def test_no_example_uses_positional_arguments(self) -> None:
        """MCP tools are called by name; a positional example teaches a call that cannot be made."""
        for name, src, call in _calls():
            assert not call.args, f"{name}: example passes positionally — {src!r}"

    async def test_every_example_supplies_the_required_parameters(self) -> None:
        """An example omitting a required parameter fails for anyone who follows it verbatim."""
        declared = await _params()
        offences: list[str] = []
        for name, src, call in _calls():
            if name in REQUIRED_OMISSION_EXEMPTIONS:
                continue
            _, required = declared[name]
            passed = {kw.arg for kw in call.keywords if kw.arg is not None}
            missing = sorted(required - passed - {"ctx"})
            if missing:
                offences.append(f"{name}: missing required {missing} — {src!r}")
        assert not offences, "Examples omit required parameters:\n" + "\n".join(offences)

    @pytest.mark.parametrize("tool", ["gtd_project_create", "gtd_canvas_commit"])
    async def test_item_bearing_examples_key_the_name_on_text(self, tool: str) -> None:
        """The regression pin for the incident: a draft keyed on `name` creates empty-named items.

        Both canvas surfaces key an item's name on `text`; `gtd_item_create` keys it on `name`. An
        example on either canvas surface showing `"name"` inside `items[]` / `adds[]` walks the
        caller straight into the failure, which is what happened."""
        for name, src, call in _calls():
            if name != tool:
                continue
            for kw in call.keywords:
                if kw.arg not in ("items", "adds"):
                    continue
                for element in getattr(kw.value, "elts", []):
                    keys = {
                        k.value for k in getattr(element, "keys", []) if isinstance(k, ast.Constant)
                    }
                    assert "name" not in keys, f"{tool}: example keys an item on `name` — {src!r}"
                    assert "text" in keys, f"{tool}: example item has no `text` — {src!r}"
