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

    def test_explains_that_a_misspelt_optional_is_dropped_client_side(self):
        # The advisory has to say WHY absence is worth mentioning, or it reads as pedantry.
        msg = build_advisory("t", ["a"], ["a"])
        assert msg and "drop" in msg.lower()

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
        "gtd_note_add": "body",
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
