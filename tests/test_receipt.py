"""The teaching receipt (v4.0.0) — the contract, and the two rules that make it worth having.

**What these tests are actually defending.** The receipt exists because the hosted client
deletes an undeclared argument before this server sees it, so a misspelt OPTIONAL modifier
produces a silent partial write. Nothing server-side can detect that, so the receipt makes the
OUTCOME unmissable instead. Two properties carry the whole design and each has a test that
fails loudly if it regresses:

1. **The receipt is attached to every governed write and to no read** — asserted by iterating
   the REAL server, not a fixture, because the failure mode is "someone added a tool and it
   silently shipped without one".
2. **It is advisory data, never a gate** — a caller that ignores all three fields still gets a
   correct, complete result, and no receipt path performs a write.

The advisory's fire rate is measured here rather than asserted at a threshold: the trial has to
report whether it is useful or noisy, and a test that pinned a number would just encode
today's guess.
"""

from __future__ import annotations

import inspect
from typing import Any, ClassVar

import pytest

from rtm_mcp import receipt
from rtm_mcp.error_codes import ErrorCode
from rtm_mcp.receipt import (
    RECEIPT_DOC,
    RECEIPT_FIELDS,
    RECEIPT_REASONS,
    attach,
    build_advisory,
    build_guidance,
    build_markup_advisory,
    detect_leaked_markup,
    is_facet,
    not_applied_entry,
)
from rtm_mcp.server import mcp


async def _tools() -> dict[str, Any]:
    return {t.name: t for t in await mcp.list_tools()}


def _is_governed_write(name: str, mcp_tool: Any) -> bool:
    """The same gate `tools/gtd.py::_with_receipt` applies — a gtd tool that is not read-only."""
    return name.startswith("gtd_") and not getattr(mcp_tool.annotations, "readOnlyHint", False)


class TestReceiptReasonVocabulary:
    """`not_applied[].reason` is the fourth scoped view of the ONE `ErrorCode` registry."""

    def test_every_receipt_reason_is_a_registry_member(self):
        assert RECEIPT_REASONS
        for reason in RECEIPT_REASONS:
            assert isinstance(reason, ErrorCode)

    def test_receipt_reasons_are_outcomes_not_failures(self):
        # The widening of the registry from "failure" to "outcome" is deliberate and recorded.
        # These three must never leak onto an envelope `error.code`, which is what would make
        # a non-failure look like one to a consumer branching on it.
        assert {r.value for r in RECEIPT_REASONS} == {
            "no_change",
            "no_durable_write",
            "not_eligible",
        }

    def test_every_not_applied_call_site_uses_a_receipt_reason(self):
        """Derived from source, so a new site using (say) `task_not_found` fails here.

        A `not_applied[]` entry reporting a *failure* code would be a category error: the write
        succeeded, and the caller would branch as though it had not."""
        import ast

        from rtm_mcp.tools import gtd

        tree = ast.parse(inspect.getsource(gtd))
        used: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Name) and fn.id == "not_applied_entry"):
                continue
            for kw in node.keywords:
                if kw.arg == "reason" and isinstance(kw.value, ast.Attribute):
                    used.add(kw.value.attr)
        assert used, "no not_applied_entry call sites found — the derivation has gone blind"
        allowed = {r.name for r in RECEIPT_REASONS}
        assert used <= allowed, f"non-receipt reason used in not_applied[]: {used - allowed}"


class TestNotAppliedEntry:
    def test_carries_the_contract_fields(self):
        e = not_applied_entry(
            "transition:add",
            reason=ErrorCode.NO_CHANGE,
            detail="already present on the item before this call.",
            requested=["work"],
            item_id="t1",
        )
        assert e == {
            "op": "transition:add",
            "reason": "no_change",
            "detail": "already present on the item before this call.",
            "id": "t1",
            "requested": ["work"],
        }

    def test_reason_serialises_as_a_plain_string(self):
        # `ErrorCode` is a str-mixin, but the wire value must be the bare string so a consumer
        # comparing to "no_change" matches without importing the enum.
        e = not_applied_entry("x", reason=ErrorCode.NO_CHANGE, detail="d")
        assert type(e["reason"]) is str and e["reason"] == "no_change"

    def test_optional_keys_are_omitted_not_nulled(self):
        e = not_applied_entry("x", reason=ErrorCode.NOT_ELIGIBLE, detail="d")
        assert "id" not in e and "requested" not in e


class TestAdvisory:
    """Fires on absence of EVERY optional — the one signal that survives a client-side strip."""

    def test_fires_when_no_optional_arrived(self):
        msg = build_advisory(
            "gtd_inbox_capture", ["source_type", "pre_analysis"], ["source_type", "pre_analysis"]
        )
        assert msg and "source_type" in msg and "pre_analysis" in msg

    def test_names_the_absent_parameters(self):
        # Naming them is the actionable part: the caller is being asked to compare against an
        # intent only it knows, which it cannot do against "no optional parameters were received".
        msg = build_advisory("t", ["due", "energy"], ["due", "energy"])
        assert "due" in msg and "energy" in msg

    def test_silent_when_any_optional_arrived(self):
        # THE noise rule. Before this was fixed the advisory fired on any absent optional, which
        # measured 82% of governed-write calls in the suite; correcting it to all-absent gave 17%.
        assert build_advisory("t", ["b"], ["a", "b"]) is None

    def test_silent_when_the_tool_declares_no_optionals(self):
        # Absence carries no information there — gtd_item_set_redaction is the live example.
        assert build_advisory("t", [], []) is None

    def test_offers_both_recorded_causes_and_asserts_neither(self):
        """The advisory must say why absence is worth mentioning WITHOUT asserting one cause.

        **This test previously asserted the opposite** — it was
        `test_explains_that_a_misspelt_optional_is_dropped_client_side`, and it checked only
        that the message contained "drop". That passed happily while the message told every
        caller, as fact, that a client had dropped a misspelt name.

        Measured 2026-08-01 across the whole transcript population: the advisory has fired
        twice, and that cause was the actual cause **neither time** (once a legitimately bare
        call; once tool-call markup folded into a sibling string, where nothing was misspelt
        and nothing was dropped). The wrong cause was not inert — it sent a hand-off brief
        hunting a client-side strip that had never happened.

        So the rule is now: name the observation, offer both recorded causes, commit to
        neither. The markup cause must come first — it is the one the caller can check itself.
        """
        msg = build_advisory("t", ["a"], ["a"])
        assert msg
        lower = msg.lower()
        # Both causes present.
        assert "markup" in lower, "the markup cause must be named"
        assert "drop" in lower, "the client-strip cause must still be named"
        # The observation is framed as an observation, not a diagnosis.
        assert "the cause is not visible from here" in lower
        # The markup cause is actionable, so it leads.
        assert lower.index("markup") < lower.index("misspelt")

    def test_does_not_assert_a_single_cause_as_fact(self):
        """The exact phrasing that made the v6.0.4 advisory wrong, pinned as forbidden.

        A bare "it did not arrive: a misspelt optional is dropped …" reads as a diagnosis. The
        guard is deliberately on the *asserting* construction rather than on the words, since
        the words themselves remain legitimate inside the enumerated causes above.
        """
        msg = build_advisory("t", ["a"], ["a"])
        assert msg
        assert "arrive: a misspelt optional is dropped" not in msg

    def test_control_flags_are_not_facets(self):
        """A boolean is a mode switch, not data, so it can never be silently lost.

        This is a correctness rule, not tuning: `confirm_destructive` going missing gets the
        call REJECTED, and `dry_run` / `timestamp` going missing changes behaviour the response
        then states. Only a value-bearing parameter can vanish and leave a write looking
        complete — which is the single failure the advisory exists for."""
        assert not is_facet(True)
        assert not is_facet(False)

    def test_value_bearing_optionals_are_facets(self):
        assert is_facet(None)  # the overwhelmingly common default in this server
        assert is_facet("")
        assert is_facet(0)  # an int carries a value; only bool is a switch

    def test_bool_is_excluded_even_though_it_is_an_int_subclass(self):
        # `isinstance(True, int)` is True in Python, so a naive int check would misclassify.
        assert is_facet(1) and not is_facet(True)

    def test_caps_the_names_it_renders(self):
        many = [f"p{i}" for i in range(30)]
        msg = build_advisory("t", many, many)
        assert msg and "more" in msg


class TestGuidance:
    """Narrowed in v4.1.0 to the two branches that say something the other fields do not.

    The trial measured 56 of 62 emissions as the full-rejection branch — a restatement of the
    `rejected[]` array in the same payload. A field that usually repeats its neighbour trains a
    caller to skip it, which costs the two branches below that are actually worth reading."""

    def test_none_on_a_clean_full_success(self):
        assert build_guidance({"applied": [{"op": "a"}], "errors": [], "not_applied": []}) is None

    def test_silent_on_a_full_rejection(self):
        # DROPPED in v4.1.0. rejected[] already lists every reason; guidance added only a count.
        g = build_guidance({"applied": [], "rejected": [{"reason": "x"}], "not_applied": []})
        assert g is None

    def test_partial_write_is_named_as_partial(self):
        # The branch that justifies the field: some writes are durable. Saying only "an error
        # occurred" would invite a blind retry that double-applies the ops that succeeded.
        g = build_guidance({"applied": [{"op": "a"}], "errors": [{"op": "b"}], "not_applied": []})
        assert g and "PARTIAL" in g and "batch_undo" in g

    def test_partial_write_outranks_not_applied(self):
        # Severity ordering is unchanged where both conditions hold.
        g = build_guidance(
            {"applied": [{"op": "a"}], "errors": [{"op": "b"}], "not_applied": [{"op": "c"}]}
        )
        assert g and "PARTIAL" in g

    def test_not_applied_produces_guidance(self):
        g = build_guidance({"applied": [{"op": "a"}], "errors": [], "not_applied": [{"op": "b"}]})
        assert g and "not_applied[]" in g

    def test_silent_on_a_bare_zero_applied_response(self):
        # Also dropped in v4.1.0, as a consequence of "only where it says something new":
        # `applied: []` IS the statement. CONSEQUENCE, flagged in the debrief — an
        # explicitly-empty payload (items=[]) now carries no interpretive signal at all.
        assert build_guidance({"applied": [], "errors": [], "not_applied": []}) is None

    def test_silent_for_a_payload_with_no_applied_key(self):
        # gtd_item_set_redaction returns {task_id, redacted} — no batch, nothing to say.
        assert build_guidance({"task_id": "c1", "redacted": True, "not_applied": []}) is None


class TestAttach:
    def test_adds_all_three_fields(self):
        data: dict[str, Any] = {"applied": [{"op": "a"}]}
        attach(data, tool_name="t", absent_optional=[], declared_optional=["x"])
        assert all(f in data for f in RECEIPT_FIELDS)

    def test_not_applied_is_empty_not_absent(self):
        # Zero-not-absent: a consumer must be able to branch on it unconditionally.
        data: dict[str, Any] = {"applied": [{"op": "a"}]}
        attach(data, tool_name="t", absent_optional=[], declared_optional=["x"])
        assert data["not_applied"] == []

    def test_preserves_entries_a_tool_body_already_added(self):
        entry = not_applied_entry("x", reason=ErrorCode.NO_CHANGE, detail="d")
        data: dict[str, Any] = {"applied": [], "not_applied": [entry]}
        attach(data, tool_name="t", absent_optional=[], declared_optional=[])
        assert data["not_applied"] == [entry]

    def test_guidance_sees_tool_populated_not_applied(self):
        # Ordering matters: guidance is derived last, so it can speak about what the body added.
        data: dict[str, Any] = {
            "applied": [{"op": "a"}],
            "not_applied": [not_applied_entry("x", reason=ErrorCode.NO_CHANGE, detail="d")],
        }
        attach(data, tool_name="t", absent_optional=[], declared_optional=[])
        assert data["guidance"] and "not_applied[]" in data["guidance"]

    def test_error_envelope_is_left_untouched(self):
        # `data.error` is the success|error discriminator. Hanging outcome fields off it would
        # blur exactly the branch consumers rely on — and a failure already teaches.
        data = {"error": {"code": "task_not_found", "message": "m", "rtm_code": None}}
        before = dict(data)
        attach(data, tool_name="t", absent_optional=["a"], declared_optional=["a"])
        assert data == before


class TestReceiptIsAttachedToTheRealServer:
    """Iterating the real server, because the failure mode is a tool shipping without one."""

    @pytest.mark.asyncio
    async def test_every_governed_write_documents_the_receipt(self):
        tools = await _tools()
        missing = [
            n
            for n, t in tools.items()
            if _is_governed_write(n, t.to_mcp_tool())
            and RECEIPT_DOC not in (t.to_mcp_tool().description or "")
        ]
        assert not missing, f"governed writes with no receipt in their description: {missing}"

    @pytest.mark.asyncio
    async def test_the_set_of_governed_writes_is_not_empty(self):
        # Guard-the-guard: if the gate stopped matching anything, every assertion above would
        # pass vacuously.
        tools = await _tools()
        writes = [n for n, t in tools.items() if _is_governed_write(n, t.to_mcp_tool())]
        assert len(writes) >= 20, f"only {len(writes)} governed writes matched — gate is wrong"

    @pytest.mark.asyncio
    async def test_no_read_carries_the_receipt(self):
        # A read has no answer to "did what I asked for land?", and putting a null advisory on
        # every read would be pure noise.
        tools = await _tools()
        leaked = [
            n
            for n, t in tools.items()
            if not _is_governed_write(n, t.to_mcp_tool())
            and RECEIPT_DOC in (t.to_mcp_tool().description or "")
        ]
        assert not leaked, f"reads advertising a receipt: {leaked}"

    @pytest.mark.asyncio
    async def test_the_receipt_doc_states_the_imperative(self):
        # Tier 1 has ~2 KB total, so the block must buy the instruction, not a description of it.
        assert "not_applied[]" in RECEIPT_DOC
        assert "before reporting success" in RECEIPT_DOC


class TestReceiptNeverWrites:
    """The hard invariant: the receipt is data, never a gate and never an action."""

    def test_the_module_is_a_pure_leaf(self):
        """Structural, not textual: it imports nothing that could reach RTM.

        `client.call` is the single chokepoint every RTM write goes through, so a module that
        cannot import a client cannot write. Asserted over the import graph rather than by
        grepping for "client", which only finds the word in the prose explaining the design."""
        import ast

        tree = ast.parse(inspect.getsource(receipt))
        internal: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.level or 0) > 0:
                internal.add(node.module or "")
            elif isinstance(node, ast.Import):
                internal.update(a.name for a in node.names if a.name.startswith("rtm_mcp"))
        assert internal == {"error_codes"}, f"receipt.py grew an import: {internal}"

    def test_nothing_in_the_module_is_async(self):
        # Every helper is synchronous, so no receipt path can await an RTM call even by accident.
        import ast

        tree = ast.parse(inspect.getsource(receipt))
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]


class TestTightenedParameters:
    """The eight payload parameters that were optional but never legitimately absent.

    BREAKING at v4.0.0 and justified: every call these now reject was already producing an
    empty or wrong outcome (an empty commit, a no-op, a note with a title and no content).
    Asserted against the ADVERTISED schema, because `required` is what a client enforces —
    a handler-side check would leave the schema still inviting the bad call.
    """

    #: tool -> the parameter that became required. Owned by this test rather than imported
    #: from a constant, so a parameter quietly loosened again fails here.
    TIGHTENED: ClassVar[dict[str, str]] = {
        "gtd_engage_commit": "items",
        "gtd_inbox_drain": "dispositions",
        "gtd_waiting_for_sweep": "verdicts",
        "gtd_cluster_consolidate": "moves",
        "gtd_item_transition_batch": "items",
        "gtd_project_create": "frame",
        "gtd_note_add": "narrative",
        "gtd_inbox_item_close": "derived_refs",
    }

    def test_the_list_is_the_briefed_eight(self):
        assert len(self.TIGHTENED) == 8

    @pytest.mark.asyncio
    async def test_each_is_advertised_required(self):
        tools = await _tools()
        for tool, param in self.TIGHTENED.items():
            schema = tools[tool].to_mcp_tool().inputSchema or {}
            assert param in set(schema.get("required") or []), f"{tool}.{param} is not required"

    @pytest.mark.asyncio
    async def test_none_advertises_a_nullable_type(self):
        # Required-but-nullable would be a loophole: an explicit null is the same empty call.
        # It also has to stay single-typed — this family bans advertised unions on params.
        tools = await _tools()
        for tool, param in self.TIGHTENED.items():
            prop = ((tools[tool].to_mcp_tool().inputSchema or {}).get("properties") or {})[param]
            assert "anyOf" not in prop, f"{tool}.{param} advertises a union"
            assert prop.get("type") != "null"

    @pytest.mark.asyncio
    async def test_absence_is_rejected_before_the_tool_body(self):
        """A call omitting the parameter fails, and fails without reaching RTM.

        Driven through the REAL server over an in-memory client, so this pins what a caller
        actually experiences rather than what a direct function call does."""
        from fastmcp.client import Client

        async with Client(mcp) as c:
            for tool, param in self.TIGHTENED.items():
                with pytest.raises(Exception) as exc:
                    await c.call_tool(tool, {})
                assert param in str(exc.value) or "required" in str(exc.value).lower(), (
                    f"{tool} did not name the missing {param}: {exc.value}"
                )


class TestReceiptSurvivesMcpSerialisation:
    """The values reach a client, not just the schema.

    Every other test here calls the tool function directly (the `FakeMCP` pattern), which
    bypasses FastMCP's result path entirely. A field can be present in the returned dict and
    still not reach a caller — `ToolResult` carries the payload TWICE, as `structured_content`
    and as a serialised text block, and a client may read either. This drives the real
    in-memory protocol layer and asserts the receipt arrives in both.

    SAFETY, learned the hard way while writing this: entering `Client(mcp)` runs the server's
    real lifespan, which builds an RTMClient from the on-disk config and OVERWRITES the module
    global — so patching `server._client` beforehand is silently discarded and the call goes to
    the live account. Two guards, because one is not enough: `RTMConfig.load` is stubbed
    unconfigured so the lifespan cannot construct a client at all, and the fake is installed
    INSIDE the context, after the lifespan has run. `get_client` reads the global per call, so
    the late install is what the tool actually sees.
    """

    @pytest.mark.asyncio
    async def test_receipt_arrives_in_both_result_representations(self, monkeypatch):
        import json
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp.client import Client

        from rtm_mcp import server
        from rtm_mcp.config import RTMConfig
        from tests.test_tools.test_gtd_tools import _redaction_dispatch, _redaction_tree

        monkeypatch.setattr(RTMConfig, "load", classmethod(lambda cls: RTMConfig()))

        # gtd_item_set_redaction is the sharpest probe: it declares NO optional parameters, so
        # a clean call must produce not_applied=[] with advisory=None — the exact zero-not-absent
        # shape a consumer branches on.
        fake = MagicMock()
        fake.call = AsyncMock(side_effect=_redaction_dispatch(_redaction_tree()))
        fake.config = MagicMock(strict_tags=False)
        fake.timeline_id = "tl1"
        fake.record_transaction = MagicMock()
        fake.get_account_tags = AsyncMock(return_value={"redacted"})
        fake.get_timezone = AsyncMock(return_value="Europe/London")
        fake.close = AsyncMock()  # the lifespan awaits close() on teardown

        async with Client(server.mcp) as c:
            monkeypatch.setattr(server, "_client", fake)
            res = await c.call_tool("gtd_item_set_redaction", {"task_id": "c1", "redacted": True})

        assert fake.call.await_count, "the fake client was bypassed — the test proved nothing"

        data = res.structured_content["data"]
        assert data["not_applied"] == []  # zero-not-absent, over the protocol
        assert data["guidance"] is None
        assert data["advisory"] is None  # declares no optionals -> never advises
        assert data["redacted"] is True  # the pre-existing contract is intact

        # The text block a client may read instead of the structured content.
        text = "".join(getattr(b, "text", "") for b in res.content)
        assert "not_applied" in text, "receipt missing from the serialised text block"
        assert json.loads(text)["data"]["not_applied"] == []


#: The 2026-08-01 live incident, byte-exact from the Desktop audit log (audit.jsonl:4739,
#: toolu_018X5Di4RQ9EKtkBCPUTYjU2). Kept verbatim because a paraphrase would not prove the
#: detector catches the thing that actually happened.
LIVE_LEAK = (
    "…how a defect outlives its own fix.</narrative>\n"
    '<parameter name="sources">["AI Memory general/…", "gtd v0.206.0 …", "RTM 1218844852 — …"]'
)

#: The other measured dialect — a bare closing tag, no `<parameter name=` opener anywhere.
#: `gtd_inbox_item_annotate`, 2026-07-26, which silently lost its `questions` array.
LIVE_LEAK_BARE = (
    "…a distinct action, not a citation problem.</analysis_body>\n"
    '<questions>["Run the four prove re-runs now?","May I close this item?"]</questions>\n'
    "</invoke>"
)


class TestDetectLeakedMarkup:
    """The tool-scoped anchor: a closing tag is a finding only when it names a parameter THIS
    tool declares. That scoping is the whole precision story — measured over 13,435 real RTM
    calls it fired 7 times with zero false positives."""

    def test_catches_the_live_incident_and_names_the_lost_parameter(self):
        found = detect_leaked_markup(
            {"narrative": LIVE_LEAK}, {"narrative", "sources", "ai_context", "note_type"}
        )
        assert found == [{"param": "narrative", "closed": ["narrative"], "lost": ["sources"]}]

    def test_catches_the_bare_tag_dialect_and_still_names_what_was_lost(self):
        """The majority of measured events, and the case that taught the predicate something.

        There is no `<parameter name=` opener here at all, so a detector anchored on that would
        miss it — which is why the anchor is the CLOSING tag. But the dialect is not
        information-poor: `</analysis_body>` is followed by `<questions>…</questions>`, and
        `questions` is ALSO a declared parameter of this tool. A closing tag naming a declared
        parameter other than the carrier IS the lost parameter, so both dialects reduce to one
        `lost` field. This assertion originally expected `[]` and the code was right."""
        found = detect_leaked_markup(
            {"analysis_body": LIVE_LEAK_BARE}, {"analysis_body", "questions", "rename"}
        )
        assert found == [
            {
                "param": "analysis_body",
                "closed": ["analysis_body", "questions"],
                "lost": ["questions"],
            }
        ]

    def test_the_anchor_is_the_tools_own_parameter_names(self):
        """The same string is a finding on one tool and silent on another. Nothing else in the
        predicate does any work — this is what buys the zero false-positive rate."""
        assert detect_leaked_markup({"narrative": LIVE_LEAK}, {"narrative"})
        assert detect_leaked_markup({"body": LIVE_LEAK}, {"body", "summary"}) == []

    def test_an_html_document_is_not_a_finding(self):
        """THE measured false-positive that a naive `</…>` predicate produces. A real live call
        passed a full HTML document to `add_note`; none of those tags is an `add_note`
        parameter, so the anchor stays silent while a bare predicate would have fired."""
        html = "<html><head><style>a{}</style></head><body><script>x</script></body></html>"
        assert (
            detect_leaked_markup({"note_text": html}, {"note_text", "note_title", "note_id"}) == []
        )

    def test_prose_naming_a_parameter_without_a_closing_tag_is_not_a_finding(self):
        text = "The `sources` parameter did not arrive; see <parameter name=…> in the debrief."
        assert detect_leaked_markup({"narrative": text}, {"narrative", "sources"}) == []

    def test_non_strings_and_empties_are_skipped(self):
        supplied = {"items": ["</narrative>"], "count": 3, "flag": True, "narrative": ""}
        assert detect_leaked_markup(supplied, {"items", "count", "flag", "narrative"}) == []

    def test_reports_every_affected_parameter_deterministically(self):
        found = detect_leaked_markup(
            {"summary": "x</summary>", "narrative": LIVE_LEAK}, {"summary", "narrative", "sources"}
        )
        assert [f["param"] for f in found] == ["narrative", "summary"]  # sorted, not call order


class TestMarkupAdvisory:
    def test_none_when_nothing_was_found(self):
        assert build_markup_advisory("gtd_note_add", []) is None

    def test_names_the_carrier_the_tag_and_the_lost_parameter(self):
        found = detect_leaked_markup({"narrative": LIVE_LEAK}, {"narrative", "sources"})
        msg = build_markup_advisory("gtd_note_add", found)
        assert msg
        assert "`narrative`" in msg and "`</narrative>`" in msg and "`sources`" in msg
        assert "VERBATIM" in msg  # the caller must know the text was written, not dropped

    def test_says_it_did_not_block(self):
        """The anchor cannot separate a genuine leak from a note DOCUMENTING one, and this repo
        journals its own defects through these very tools. Saying so is part of the contract."""
        found = detect_leaked_markup({"narrative": LIVE_LEAK}, {"narrative", "sources"})
        msg = build_markup_advisory("gtd_note_add", found) or ""
        assert "Nothing was blocked" in msg

    def test_markup_outranks_the_bare_call_advisory_because_it_explains_it(self):
        data = {"applied": [{"op": "note"}]}
        found = detect_leaked_markup({"narrative": LIVE_LEAK}, {"narrative", "sources"})
        attach(
            data,
            tool_name="gtd_note_add",
            absent_optional=["ai_context", "sources"],  # bare-call would ALSO fire
            declared_optional=["ai_context", "sources"],
            leaked=found,
        )
        assert "Tool-call markup arrived" in data["advisory"]
        assert "No optional parameter reached" not in data["advisory"]

    def test_it_fires_where_the_bare_call_advisory_is_silent(self):
        """**The partial-loss blind spot, closed for the one detectable cause.**

        `build_advisory` returns None unless EVERY facet is absent, so a call that supplies one
        facet and loses another says nothing — 15 of the 25 governed writes have that gap. Here
        `ai_context` was supplied and `sources` was lost, so the bare-call advisory is silent by
        construction and this is the only thing that speaks.
        """
        assert build_advisory("gtd_note_add", ["sources"], ["ai_context", "sources"]) is None
        data = {"applied": [{"op": "note"}]}
        attach(
            data,
            tool_name="gtd_note_add",
            absent_optional=["sources"],
            declared_optional=["ai_context", "sources"],
            leaked=detect_leaked_markup({"narrative": LIVE_LEAK}, {"narrative", "sources"}),
        )
        assert data["advisory"] and "`sources`" in data["advisory"]

    def test_it_is_advisory_and_never_touches_not_applied_or_guidance(self):
        """A hard invariant: the receipt must never become a gate, and a detection is not a
        failed operation. `not_applied[]` means 'you asked and nothing was written'; here the
        write happened."""
        data = {"applied": [{"op": "note"}]}
        attach(
            data,
            tool_name="gtd_note_add",
            absent_optional=[],
            declared_optional=["sources"],
            leaked=detect_leaked_markup({"narrative": LIVE_LEAK}, {"narrative", "sources"}),
        )
        assert data["not_applied"] == []
        assert data["guidance"] is None


class TestTheDetectorRunsOnTheRealServer:
    """**The anti-vacuity test.** Every assertion above exercises a pure function, and all of
    them would pass unchanged against a server that never calls it — which is precisely the
    failure mode this whole investigation was about (`test_middleware.py` says the same thing
    about the parameter gate). This drives the real in-memory protocol layer end to end.

    Same safety discipline as `TestReceiptSurvivesMcpSerialisation`: `RTMConfig.load` is stubbed
    so the lifespan cannot build a real client, and the fake is installed INSIDE the context
    after the lifespan has overwritten the global.
    """

    @pytest.mark.asyncio
    async def test_a_leaked_narrative_produces_the_advisory_over_the_protocol(self, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp.client import Client

        from rtm_mcp import server
        from rtm_mcp.config import RTMConfig

        monkeypatch.setattr(RTMConfig, "load", classmethod(lambda cls: RTMConfig()))

        async def dispatch(method, **kwargs):
            if method == "rtm.tasks.getList":
                return {
                    "tasks": {
                        "list": [
                            {
                                "id": "L1",
                                "taskseries": [
                                    {
                                        "id": "ts1",
                                        "name": "A task",
                                        "tags": [],
                                        "notes": [],
                                        "task": [{"id": "t1", "completed": ""}],
                                    }
                                ],
                            }
                        ]
                    }
                }
            return {"transaction": {"id": "tx1", "undoable": "1"}}

        fake = MagicMock()
        fake.call = AsyncMock(side_effect=dispatch)
        fake.config = MagicMock(strict_tags=False)
        fake.timeline_id = "tl1"
        fake.record_transaction = MagicMock()
        fake.get_timezone = AsyncMock(return_value="Europe/London")
        fake.get_account_tags = AsyncMock(return_value=set())
        fake.close = AsyncMock()

        async with Client(server.mcp) as c:
            monkeypatch.setattr(server, "_client", fake)
            res = await c.call_tool(
                "gtd_note_add",
                {
                    "task_ref": "t1",
                    "note_type": "CONTEXT",
                    "summary": "a summary",
                    "narrative": f"Some genuine prose. {LIVE_LEAK}",
                },
            )

        assert fake.call.await_count, "the fake client was bypassed — the test proved nothing"
        data = res.structured_content["data"]
        advisory = data["advisory"] or ""
        assert "Tool-call markup arrived" in advisory, "the detector did not run on the real path"
        assert "`sources`" in advisory
        # ADVISORY, not a gate: the note was still written.
        assert data["applied"], "the detection must not have blocked the write"

    @pytest.mark.asyncio
    async def test_a_clean_call_produces_no_markup_advisory(self, monkeypatch):
        """The guard-the-guard. Without it the test above passes against a detector that fires
        on everything, which would be worse than no detector at all."""
        from unittest.mock import AsyncMock, MagicMock

        from fastmcp.client import Client

        from rtm_mcp import server
        from rtm_mcp.config import RTMConfig

        monkeypatch.setattr(RTMConfig, "load", classmethod(lambda cls: RTMConfig()))

        async def dispatch(method, **kwargs):
            if method == "rtm.tasks.getList":
                return {
                    "tasks": {
                        "list": [
                            {
                                "id": "L1",
                                "taskseries": [
                                    {
                                        "id": "ts1",
                                        "name": "A task",
                                        "tags": [],
                                        "notes": [],
                                        "task": [{"id": "t1", "completed": ""}],
                                    }
                                ],
                            }
                        ]
                    }
                }
            return {"transaction": {"id": "tx1", "undoable": "1"}}

        fake = MagicMock()
        fake.call = AsyncMock(side_effect=dispatch)
        fake.config = MagicMock(strict_tags=False)
        fake.timeline_id = "tl1"
        fake.record_transaction = MagicMock()
        fake.get_timezone = AsyncMock(return_value="Europe/London")
        fake.get_account_tags = AsyncMock(return_value=set())
        fake.close = AsyncMock()

        async with Client(server.mcp) as c:
            monkeypatch.setattr(server, "_client", fake)
            res = await c.call_tool(
                "gtd_note_add",
                {
                    "task_ref": "t1",
                    "note_type": "CONTEXT",
                    "summary": "a summary",
                    "narrative": "Ordinary prose about </head> and <parameter name=x> in passing.",
                    "sources": ["a source"],
                },
            )

        data = res.structured_content["data"]
        assert "Tool-call markup arrived" not in (data["advisory"] or "")


class TestReceiptDocIsVersionIndependent:
    """The appended block must not leave source indentation in the advertised description.

    This guards a real cross-version bug that CI caught and a local run could not. Python 3.13+
    dedents docstrings at COMPILE time; 3.11 and 3.12 do not. `inspect.getdoc` dedents by the
    common leading whitespace of the continuation lines — so composing from the RAW `__doc__`
    and appending an UNINDENTED block drops that common prefix to zero, and every line keeps its
    source indentation on 3.11/3.12 only. Measured on CI: `gtd_item_set_redaction` was 1,946
    bytes on 3.14 and 2,106 on 3.12, which also broke the committed fingerprints.

    Asserted on the wrapper directly, so it holds whatever Python the suite happens to run on.
    """

    def test_wrapping_normalises_before_appending(self):
        from rtm_mcp.tools.gtd import _with_receipt

        async def sample(ctx: Any, thing: str = "") -> dict[str, Any]:
            """GTD — a sample governed write.

            A continuation line that is indented in source.

            Returns:
                {"applied": [...]}.
            """
            return {"data": {}}

        wrapped = _with_receipt(sample, None)
        doc = inspect.getdoc(wrapped) or ""
        body = [ln for ln in doc.splitlines() if "indented in source" in ln]
        assert body, "the original docstring body was lost"
        assert not body[0].startswith(" "), (
            f"source indentation leaked into the advertised description: {body[0]!r}. "
            "Compose from inspect.getdoc(fn), not fn.__doc__."
        )
        assert doc.endswith(RECEIPT_DOC)

    @pytest.mark.asyncio
    async def test_every_advertised_description_is_fully_dedented(self):
        """The same property on the REAL server, checked precisely.

        The signature of the bug is that the docstring's own common indentation survives. So:
        strip the appended block (whose lines are unindented by construction and would mask the
        measurement), then assert the remaining body still reaches column 0 somewhere. Pre-fix on
        3.11/3.12 every original line sat at 8+; post-fix the minimum is 0 on every version.

        A deep-indented line on its own is NOT the bug — a two-level `Args:` continuation is
        legitimately 8 spaces after a correct dedent, which is why the naive check was wrong."""
        tools = await _tools()
        offenders = {}
        for name, tool in tools.items():
            mcp_tool = tool.to_mcp_tool()
            if not _is_governed_write(name, mcp_tool):
                continue
            body = (mcp_tool.description or "").replace(RECEIPT_DOC, "")
            lines = [ln for ln in body.splitlines()[1:] if ln.strip()]
            if lines and min(len(ln) - len(ln.lstrip()) for ln in lines) != 0:
                offenders[name] = min(len(ln) - len(ln.lstrip()) for ln in lines)
        assert not offenders, (
            f"descriptions still carrying their source indentation (min indent per tool): "
            f"{offenders}. Compose from inspect.getdoc(fn), not fn.__doc__."
        )


class TestOutOfScopeOfEmptyRejection:
    """The four categories the v5.0.0 empty-payload rule must NOT touch.

    Each is here for a different reason, and each is easy to break with a careless
    generalisation of the rule — which is why they are asserted rather than assumed. The
    behavioural half (the eight tools actually rejecting) lives in
    `tests/test_tools/test_gtd_tools.py`, where the client fixtures are.
    """

    @pytest.mark.asyncio
    async def test_rtm_tool_help_with_no_argument_still_returns_the_index(self):
        """The one most likely to be broken: it superficially resembles the empty case.

        `rtm_tool_help()` is a designed VIEW SELECTOR shipped in v3.3.0 — no argument returns
        the whole-server index, a name returns one contract. Treating the no-arg call as an
        empty payload would regress a shipped feature."""
        tools = await _tools()
        schema = tools["rtm_tool_help"].to_mcp_tool().inputSchema or {}
        assert not (schema.get("required") or []), (
            "rtm_tool_help must take NO required parameter — the no-arg call IS the index view"
        )

    @pytest.mark.asyncio
    async def test_no_argument_tools_take_no_required_parameter(self):
        # Nothing can be empty on these, so the rule can never apply.
        tools = await _tools()
        for name in ("get_tags", "check_auth", "test_connection"):
            schema = tools[name].to_mcp_tool().inputSchema or {}
            assert not (schema.get("required") or []), f"{name} grew a required parameter"

    @pytest.mark.asyncio
    async def test_genuine_optional_facets_stay_optional(self):
        # Absence AND emptiness are legitimate — an action often has no due date. These are
        # covered by the receipt, never by rejection.
        tools = await _tools()
        schema = tools["gtd_item_create"].to_mcp_tool().inputSchema or {}
        required = set(schema.get("required") or [])
        for param in ("due", "energy", "comms", "extra_tags", "context_note"):
            assert param in (schema.get("properties") or {}), f"gtd_item_create.{param} vanished"
            assert param not in required, f"gtd_item_create.{param} was wrongly made required"

    @pytest.mark.asyncio
    async def test_control_flags_are_untouched(self):
        # A mode switch, not data — the same reasoning as receipt.is_facet.
        tools = await _tools()
        for tool, flag in (
            ("gtd_engage_commit", "confirm_destructive"),
            ("gtd_item_stamp_tokens", "dry_run"),
            ("gtd_note_add", "timestamp"),
        ):
            schema = tools[tool].to_mcp_tool().inputSchema or {}
            assert flag in (schema.get("properties") or {})
            assert flag not in set(schema.get("required") or []), f"{tool}.{flag} became required"
