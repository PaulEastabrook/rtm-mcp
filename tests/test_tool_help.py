"""`rtm_tool_help` — the projection-agreement contract (the point of the affordance design).

Help is a PROJECTION of each tool's own advertised schema, not a second copy of it. So these
tests assert the projections AGREE with their source rather than re-stating what help should
say — a duplicated expectation would be exactly the drift the design exists to prevent.

The load-bearing tests here are the ones that iterate EVERY registered tool: the parameter
table equals the advertised `inputSchema`, the error catalogue is bounded by what the tool's
own source can actually reach, and the index purpose is a leading substring of the
description's first block. A tool added without a well-formed selection line fails here.
"""

import json

import pytest
import respx
from fastmcp import Client

from rtm_mcp import tool_help
from rtm_mcp.error_codes import ErrorCode
from rtm_mcp.guided_rejection import build_rejection, nearest_name, render_prose
from rtm_mcp.server import mcp
from rtm_mcp.tool_help import (
    RECOVERY,
    build_contract,
    build_index,
    purpose_line,
    purpose_sentence,
)

from .test_tool_schemas import _reachable_codes, _tool_sources


async def _views() -> list[dict]:
    """The same introspection the tool itself performs, so these tests exercise real input."""
    views = []
    for tool in await mcp.list_tools():
        advertised = tool.to_mcp_tool()
        ann = advertised.annotations
        views.append(
            {
                "name": tool.name,
                "description": advertised.description or "",
                "input_schema": advertised.inputSchema or {},
                "annotations": (ann.model_dump(mode="json", exclude_none=True) if ann else {}),
            }
        )
    return views


class TestIndexProjection:
    async def test_every_registered_tool_appears_in_the_index(self):
        views = await _views()
        index = build_index(views)
        listed = {t["tool"] for fam in index["families"].values() for t in fam["tools"]}
        assert listed == {v["name"] for v in views}
        assert index["tool_count"] == len(views)

    async def test_index_purpose_is_derived_from_the_description_not_restated(self):
        """The agreement assertion. Every index purpose must be a leading substring of the
        description's own first block — so the index can never promise a caller something the
        tool's description does not say."""
        divergent = {}
        for v in await _views():
            first_block = purpose_line(v["description"])
            shown = purpose_sentence(v["description"])
            trimmed = shown.removesuffix(" …")
            if not first_block.startswith(trimmed):
                divergent[v["name"]] = shown
        assert divergent == {}, (
            f"these index purposes are not prefixes of their own description: {divergent}"
        )

    async def test_every_tool_yields_a_non_empty_purpose(self):
        """A tool added without a well-formed selection line has no usable index entry, and
        must fail here rather than appearing as a blank row."""
        blank = [v["name"] for v in await _views() if not purpose_sentence(v["description"])]
        assert blank == [], f"tools with no derivable purpose line: {blank}"

    async def test_index_carries_the_taxonomy_naming_cannot_express(self):
        """The `gtd_` prefix separates 55 domain tools from 45 primitives but cannot separate
        the artifact-facing (BFF) tools INSIDE that prefix — which is why the taxonomy exists."""
        index = build_index(await _views())
        gtd = index["families"]["gtd"]["tools"]
        layers = {t["layer"] for t in gtd}
        assert "bff" in layers and "domain" in layers, (
            "the gtd family should split into bff and domain layers, else the taxonomy adds "
            f"nothing over the prefix: {layers}"
        )
        assert all(t["layer"] == "primitive" for t in index["families"]["rtm"]["tools"])

    async def test_index_stays_within_its_stated_budget(self):
        """The index is the cheap answer or it is pointless. It is deliberately NOT held to the
        brief's ~2 k tokens: that figure was computed from the docstrings' physically WRAPPED
        first lines, which cut mid-clause. A semantically complete first sentence costs ~3x
        that and is what a caller can actually select on. Still ~30x cheaper than the full
        advertised surface, and paid only on demand."""
        index = build_index(await _views())
        approx_tokens = len(json.dumps(index)) // 4
        assert approx_tokens < 8000, f"index has grown to ~{approx_tokens} tokens"


class TestContractProjection:
    async def test_every_tool_resolves_and_names_its_real_parameters(self):
        """Iterates all 100 tools: the contract's parameter table must equal the advertised
        `inputSchema` properties exactly — no invented params, none omitted."""
        mismatched = {}
        for v in await _views():
            contract = build_contract(v)
            named = [p["name"] for p in contract["parameters"]]
            advertised = list(v["input_schema"].get("properties") or {})
            if named != advertised:
                mismatched[v["name"]] = {"help": named, "schema": advertised}
        assert mismatched == {}, f"contract/schema parameter disagreement: {mismatched}"

    async def test_required_flags_and_enums_match_the_advertised_schema(self):
        wrong = {}
        for v in await _views():
            schema = v["input_schema"]
            required = set(schema.get("required") or ())
            props = schema.get("properties") or {}
            for p in build_contract(v)["parameters"]:
                spec = props[p["name"]]
                if p["required"] != (p["name"] in required):
                    wrong[f"{v['name']}.{p['name']}"] = "required flag"
                advertised_enum = spec.get("enum") or (spec.get("items") or {}).get("enum")
                if advertised_enum and p.get("enum") != list(advertised_enum):
                    wrong[f"{v['name']}.{p['name']}"] = "enum"
        assert wrong == {}, f"contract disagrees with the advertised schema: {wrong}"

    async def test_error_catalogue_claims_only_codes_the_tool_can_reach(self):
        """The contract must not teach recovery from a failure the tool cannot produce.
        Bounded against the SAME ast-derived reachable set the advertised-error-contract guard
        uses, so the two cannot disagree about what a tool can fail with."""
        sources = _tool_sources()
        overclaimed = {}
        for v in await _views():
            reachable = _reachable_codes(sources.get(v["name"], ""))
            if not reachable:
                continue
            claimed = {e["code"] for e in build_contract(v)["errors"]}
            extra = sorted(claimed - reachable)
            if extra:
                overclaimed[v["name"]] = extra
        assert overclaimed == {}, (
            f"help claims error codes these tools cannot actually produce: {overclaimed}"
        )

    async def test_every_error_code_has_recovery_guidance(self):
        """Additive guard: a new ErrorCode member ships with a recovery hint, or this fails.
        Without it a new code would silently degrade to the generic fallback."""
        missing = sorted(c.value for c in ErrorCode if c.value not in RECOVERY)
        assert missing == [], f"ErrorCode members with no RECOVERY entry: {missing}"

    async def test_posture_renders_the_annotations_a_client_may_never_show(self):
        for v in await _views():
            contract = build_contract(v)
            posture = contract["posture"]
            assert posture["summary"], v["name"]
            if not posture["read_only"]:
                assert "undo" in posture, f"{v['name']}: a write must name its undo path"

    async def test_destructive_tools_state_their_confirmation_requirement(self):
        for v in await _views():
            if "confirm_destructive" in (v["input_schema"].get("properties") or {}):
                assert "confirmation" in build_contract(v)["posture"], v["name"]

    async def test_identify_by_exactly_one_rule_is_derived_not_authored(self):
        """A tool taking both `task_name` and `task_id` carries the XOR rule automatically —
        that is ~30 tools kept correct without 30 hand-maintained entries."""
        checked = 0
        for v in await _views():
            props = set(v["input_schema"].get("properties") or {})
            if {"task_name", "task_id"} <= props:
                rules = build_contract(v)["combination_rules"]
                assert any("EXACTLY ONE" in r for r in rules), v["name"]
                checked += 1
        assert checked > 5, f"the derivation barely fired ({checked}) — is it still wired?"

    async def test_gtd_contracts_point_at_the_skill_rather_than_restating_it(self):
        """The membrane: the server holds mechanical contract, the plugin holds domain
        judgement. So a gtd contract emits a POINTER, never a copy of gtd's vocabulary."""
        for v in await _views():
            contract = build_contract(v)
            if contract["taxonomy"]["domain"] == "gtd":
                assert "gtd" in contract.get("see_also", ""), v["name"]

    async def test_collection_shaped_reads_are_classified_bff(self):
        """`gtd_surface_queue` is the measured case for why this table cannot stay descriptive.

        It returns an unbounded collection with a strict row schema — BFF behaviour — but was
        authored as an agent tool, so it was absent from `BFF_TOOLS` until 2026-07-31, when in
        chat it blew the tool-result ceiling on one surface and failed output validation outright
        on another. Membership is remembered rather than derived, and nothing flagged it.

        It is also `either`, not `artifact`: no board reads it. That is asserted because marking
        an agent-consumed tool `artifact` would be a false statement in `rtm_tool_help`, and
        because the awkwardness is the evidence that shape and audience are two axes.
        """
        tax = tool_help.taxonomy("gtd_surface_queue")
        assert tax["layer"] == "bff"
        assert tax["consumer"] == "either"

    async def test_a_two_mode_gate_names_both_modes_in_its_recovery(self):
        """`note_shape_rejected` is returned by TWO checks, and the hint must say so.

        The generic "every ErrorCode has a RECOVERY hint" assertion above passes on a hint that
        is *present and wrong* — which is what happened: v5.2.0 promoted the note gate from
        shape-only to shape-AND-vocabulary, and this hint kept advising about em-dashes and
        underscores while the vocabulary check returned the same code. A caller rejected on
        vocabulary read recovery for a problem they did not have.

        That is the silent-control pattern: a check reporting clean because it does not test for
        the thing it exists to catch. Coverage is not accuracy.
        """
        hint = tool_help.RECOVERY[ErrorCode.NOTE_SHAPE_REJECTED]
        assert "rejected_by" in hint, "must point at the field that discriminates the two checks"
        for mode in ("shape", "vocabulary"):
            assert mode in hint, f"the {mode!r} check is unmentioned"

    async def test_no_stale_bff_or_dual_consumer_entry(self):
        """Guards the authored tables against naming a tool that no longer exists."""
        names = {v["name"] for v in await _views()}
        assert names >= tool_help.BFF_TOOLS, sorted(tool_help.BFF_TOOLS - names)
        assert names >= tool_help.DUAL_CONSUMER, sorted(tool_help.DUAL_CONSUMER - names)
        assert set(tool_help.COMBINATION_RULES) <= names
        assert set(tool_help.EXAMPLES) <= names
        assert set(tool_help.CHAIN) <= names

    async def test_chain_edges_name_real_tools(self):
        names = {v["name"] for v in await _views()}
        dangling = {}
        for tool, edges in tool_help.CHAIN.items():
            bad = [t for t in (*edges["produced_by"], *edges["feeds_into"]) if t not in names]
            if bad:
                dangling[tool] = bad
        assert dangling == {}, f"chain edges naming non-existent tools: {dangling}"


class TestHelpToolEndToEnd:
    """Through the REAL server, because a projection that works in isolation but is not wired
    to the tool is the failure shape this repo has been bitten by before."""

    @respx.mock
    async def test_index_is_offline_and_touches_no_rtm_endpoint(self):
        """Zero HTTP is the complete proof: no route is registered, so any RTM call would
        raise rather than pass silently."""
        async with Client(mcp) as c:
            result = await c.call_tool("rtm_tool_help", {})
        assert respx.calls.call_count == 0
        data = result.structured_content["data"]
        assert data["tool_count"] >= 100

    @respx.mock
    async def test_named_contract_is_offline_too(self):
        async with Client(mcp) as c:
            result = await c.call_tool("rtm_tool_help", {"tool_name": "gtd_canvas_commit"})
        assert respx.calls.call_count == 0
        data = result.structured_content["data"]
        assert data["tool"] == "gtd_canvas_commit"
        assert data["combination_rules"] and data["examples"] and data["errors"]

    @respx.mock
    async def test_qualified_name_resolves(self):
        """A caller copying the name out of a client's tool listing gets the qualified form."""
        async with Client(mcp) as c:
            result = await c.call_tool("rtm_tool_help", {"tool_name": "mcp__rtm__list_tasks"})
        assert result.structured_content["data"]["tool"] == "list_tasks"

    @respx.mock
    async def test_unknown_tool_returns_a_typed_error_with_candidates(self):
        async with Client(mcp) as c:
            result = await c.call_tool("rtm_tool_help", {"tool_name": "gtd_canvas_comit"})
        error = result.structured_content["data"]["error"]
        assert error["code"] == ErrorCode.INVALID_INPUT.value
        assert "gtd_canvas_commit" in error["details"]["candidates"]

    async def test_the_help_tool_is_itself_within_the_selection_budget(self):
        """The standard's own surface must obey it — this shipped 2,841 bytes over on the
        first pass, which is precisely the drift the budget test exists to catch."""
        tools = {t.name: t for t in await mcp.list_tools()}
        desc = (tools["rtm_tool_help"].to_mcp_tool().description or "").encode()
        assert len(desc) <= 2048, f"rtm_tool_help's own description is {len(desc)} bytes"


class TestGuidedRejection:
    """Tier 3 — one shape, built from the tool's own schema."""

    def test_nearest_name_suggests_the_probable_typo(self):
        assert nearest_name("type_tags", ["text", "tags", "type"]) is not None
        assert nearest_name("completely_unrelated_xyz", ["text", "tags"]) is None

    def test_rejection_carries_purpose_params_and_a_help_pointer(self):
        rejection = build_rejection(
            "gtd_inbox_capture",
            problem="unknown parameter(s) ['type_tags'] for tool 'gtd_inbox_capture'.",
            purpose="GTD — capture raw text into the inbox.",
            parameters=[
                {"name": "text", "type": "string", "required": True, "description": "The text."}
            ],
            unknown=["type_tags"],
            rules=["Capture takes TEXT ONLY."],
        )
        assert rejection["no_write_performed"] is True
        assert rejection["accepted_parameters"] == ["text"]
        assert rejection["help"] == 'rtm_tool_help("gtd_inbox_capture")'
        prose = render_prose(rejection)
        for expected in ("type_tags", "text", "TEXT ONLY", "rtm_tool_help", "No write"):
            assert expected in prose, expected

    async def test_the_help_pointer_in_a_rejection_resolves_to_a_real_tool(self):
        """The pointer is only worth having if it lands. Asserted against the live server."""
        names = {t.name for t in await mcp.list_tools()}
        assert "rtm_tool_help" in names
        rejection = build_rejection("list_tasks", problem="x", parameters=[])
        assert rejection["help"] == 'rtm_tool_help("list_tasks")'
        assert "list_tasks" in names

    @pytest.mark.parametrize("arity", [{}, {"tool_name": "undo"}])
    @respx.mock
    async def test_both_arities_return_the_advertised_envelope(self, arity):
        async with Client(mcp) as c:
            result = await c.call_tool("rtm_tool_help", arity)
        assert "data" in result.structured_content
        assert "metadata" in result.structured_content


class TestTheReceiptContractNamesEveryAdvisoryProducer:
    """`RECEIPT_CONTRACT["advisory"]` is tier 2 — the place with no byte budget, and therefore
    the only surface that can describe the field in full.

    **It went stale twice before anything asserted on it.** It was written for the single
    bare-call producer, and neither v6.1.0 (leaked markup) nor v6.6.0 (name length) updated it,
    so for two releases it told a caller the field means one thing when it could mean three. A
    reader acting on it would have gone looking for a stripped optional on a call that had none.

    Asserted on the CONTRACT a caller actually receives, not on the module constant, so the
    projection is what is pinned.
    """

    async def test_it_describes_all_three_producers(self):
        view = next(v for v in await _views() if v["name"] == "gtd_item_create")
        advisory = build_contract(view)["receipt"]["advisory"]
        for producer, marker in (
            ("bare call", "none of this tool's optional parameters"),
            ("leaked markup", "<parameter name="),
            ("name length", "60 characters"),
        ):
            assert marker in advisory, f"the {producer} producer is undocumented in tier 2"

    async def test_it_says_the_field_never_blocks(self):
        # The hard invariant across all three producers — a caller must not treat it as a failure.
        view = next(v for v in await _views() if v["name"] == "gtd_item_create")
        assert "never blocking" in build_contract(view)["receipt"]["advisory"]
