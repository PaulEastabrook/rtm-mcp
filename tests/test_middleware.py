"""Tests for the unknown-parameter rejection middleware.

**These run through the REAL server via an in-memory client**, not against the middleware
class in isolation. A test that constructed `RejectUnknownParameters` and called its hook
directly would pass just as happily on a server that never registered it — a vacuous pass.

The assertion that matters is `test_rejection_performs_no_write`. The rest are about
ergonomics; that one is about integrity.

**CORRECTED 2026-07-26 — what these tests do and do not prove.** They pin the MESSAGE, not
the existence of a gate. Measured on the pinned stack, a bare fastmcp 3.4.4 server with no
middleware already rejects an undeclared argument at pydantic's call-schema binding, before
the tool body; v3.1.0 (no `middleware.py`) does too. So the original framing — "no validator
ran on that path at all" — was wrong: one did, with a worse message. And the rejection is
**unreachable through the Claude Desktop host**, which strips undeclared keys client-side
before they reach the wire (see `middleware.py`). A sweep of 2,517 transcripts found no
caller ever receiving it through the MCP boundary. These tests exercise the in-memory and
stdio transports, which do forward — so they are honest about the server's behaviour and
say nothing about live reachability.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import rtm_mcp.server as server
from rtm_mcp.client import RTMClient
from rtm_mcp.middleware import RejectUnknownParameters


@pytest.fixture
def rtm_client(monkeypatch):
    """Install a mock RTM client as the server's global, and hand it back for assertions.

    Every RTM call goes through `client.call`, so `call.await_count == 0` is the whole
    no-write proof — it holds regardless of which tool the call was aimed at.
    """
    client = AsyncMock()
    client.config = MagicMock(strict_tags=False)
    monkeypatch.setattr(server, "_client", client)
    return client


@pytest.fixture
async def mcp_client():
    async with Client(server.mcp) as client:
        yield client


class TestRegistration:
    def test_middleware_is_registered_on_the_real_server(self):
        """Guard-the-guard: every other test here would pass vacuously against a server
        that had lost the registration only if it ALSO lost the rejection — but a future
        refactor that moves registration behind a flag defaulting off would be silent."""
        assert any(isinstance(m, RejectUnknownParameters) for m in server.mcp.middleware), (
            "RejectUnknownParameters is not registered on rtm_mcp.server.mcp"
        )


class TestValidCallsPassUnchanged:
    async def test_call_with_only_valid_parameters_succeeds(self, mcp_client):
        """`gtd_item_shape` is offline (zero RTM calls), so this isolates the middleware
        from every other failure mode."""
        result = await mcp_client.call_tool(
            "gtd_item_shape", {"name": "Draft the quarterly board update"}
        )

        assert result.structured_content["data"]["shape"] == "draft"

    async def test_call_with_no_parameters_at_all_succeeds(self, monkeypatch, mock_config):
        """A parameterless tool must not trip the empty-set arithmetic.

        Uses a REAL client — `get_rate_limit_status` reads in-memory limiter state and
        makes no API call, and a mock's attributes do not serialise through the output
        schema."""
        monkeypatch.setattr(server, "_client", RTMClient(mock_config))
        async with Client(server.mcp) as client:
            result = await client.call_tool("get_rate_limit_status", {})

        assert "bucket_capacity" in result.structured_content["data"]


class TestUnknownParameterRejected:
    async def test_unknown_parameter_raises(self, mcp_client):
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool(
                "gtd_item_shape", {"name": "Draft something", "tpye": "action"}
            )

        assert "unknown parameter" in str(exc.value)

    async def test_message_names_the_unknown_parameter_and_the_valid_set(self, mcp_client):
        """Naming the accepted parameters is what turns the rejection into the answer."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool(
                "gtd_inbox_capture", {"text": "capture me", "type_tags": ["x"]}
            )
        message = str(exc.value)

        assert "type_tags" in message
        assert "gtd_inbox_capture" in message
        for valid in ("text", "source_type", "source_body", "pre_analysis"):
            assert valid in message

    async def test_every_unknown_parameter_is_named_not_just_the_first(self, mcp_client):
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool(
                "gtd_inbox_capture", {"text": "capture me", "type_tags": ["x"], "life": "work"}
            )
        message = str(exc.value)

        assert "type_tags" in message
        assert "life" in message

    async def test_rejection_performs_no_write(self, mcp_client, rtm_client):
        """THE assertion. A rejected call must not reach RTM at all — not a read, not a
        write, not the timeline fetch. `client.call` is the single chokepoint every tool
        goes through, so zero awaits is the complete proof."""
        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "gtd_inbox_capture", {"text": "capture me", "type_tags": ["improvement_candidate"]}
            )

        assert rtm_client.call.await_count == 0

    async def test_the_rejection_actually_emits_a_record(self, mcp_client, caplog):
        """Per the v3.0.1 lesson (`test_logging.py`): a control whose only output is a log
        record is unobservable if that record reaches no handler, and its absence is
        indistinguishable from a clean estate. `caplog` is used WITHOUT `set_level` —
        setting it would configure the thing under test."""
        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "gtd_item_shape", {"name": "Draft something", "tpye": "action"}
            )

        records = [r for r in caplog.records if "unknown parameter" in r.getMessage()]
        assert records, "the rejection emitted no record"
        assert records[0].levelno == logging.WARNING
        assert "tpye" in records[0].getMessage()


class TestRequiredParameterValidationUndisturbed:
    async def test_missing_required_parameter_still_rejects(self, mcp_client, rtm_client):
        """The direction that already worked must keep working — this fix adds a check,
        it does not replace one."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool("gtd_inbox_capture", {})
        message = str(exc.value)

        assert "text" in message
        assert "unknown parameter" not in message
        assert rtm_client.call.await_count == 0


class TestProtocolKeys:
    """The brief asked whether protocol-level keys arrive inside `arguments` and, if so,
    for a passlist. Measured on fastmcp 3.4.4: they do not, and a passlist would be
    actively worse — so there is none. These tests pin the measurement, because "no
    passlist" is only correct for as long as both halves below stay true."""

    def test_meta_is_a_sibling_field_not_an_argument(self):
        """`_meta` is a declared field on CallToolRequestParams aliased `_meta`, so
        pydantic parses it OUT of the params object rather than into `arguments`."""
        import mcp.types as mcp_types

        assert mcp_types.CallToolRequestParams.model_fields["meta"].alias == "_meta"
        assert "meta" in mcp_types.CallToolRequestParams.model_fields
        assert "arguments" in mcp_types.CallToolRequestParams.model_fields

    async def test_meta_inlined_into_arguments_is_rejected_by_us_with_the_better_message(
        self, mcp_client
    ):
        """A client that inlines `_meta` is rejected either way — FastMCP's own signature
        binding refuses it downstream ("Unexpected keyword argument"). Rejecting here
        instead means the caller gets the diagnostic message naming the valid set."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool(
                "gtd_item_shape",
                {"name": "Draft the quarterly board update", "_meta": {"progressToken": "abc"}},
            )
        message = str(exc.value)

        assert "_meta" in message
        assert "unknown parameter" in message

    async def test_underscore_prefix_is_not_a_free_pass(self, mcp_client):
        """The rejected alternative: an `_`-prefix rule would have let `_type_tags`
        through as though it were protocol."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool(
                "gtd_item_shape", {"name": "Draft something", "_type_tags": ["x"]}
            )

        assert "_type_tags" in str(exc.value)


class TestUnknownTool:
    async def test_unknown_tool_is_not_this_middlewares_error(self, mcp_client):
        """Pre-empting the dispatcher would replace a precise "no such tool" with a
        confusing "no such parameter"."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool("no_such_tool_exists", {"whatever": 1})

        assert "unknown parameter" not in str(exc.value)


class TestHistoricalRegression:
    async def test_the_exact_call_that_raised_the_defect(self, mcp_client, rtm_client):
        """RTM 1218862042. This call returned a confident success whose `capture:tags` entry
        (the server's own `#ai_conversation` write) was misread as the tag write landing.

        CORRECTED 2026-07-26: the silence was the CLIENT's, not this server's. The incident is
        on record in a Desktop local-agent transcript, and its undeclared keys were stripped by
        the host before the wire — the pre-gate server (v3.1.0) was executed against that exact
        argument shape and refuses it. So this test pins the rejection this server gives when a
        caller actually forwards the argument; it does not reproduce the incident."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool(
                "gtd_inbox_capture",
                {
                    "text": "MCP tool calls silently accept unknown parameters",
                    "type_tags": ["improvement_candidate"],
                },
            )
        message = str(exc.value)

        assert "type_tags" in message
        assert "['pre_analysis', 'source_body', 'source_type', 'text']" in message
        assert rtm_client.call.await_count == 0


class TestRejectionTeaches:
    """v3.3.0 — the rejection stopped merely refusing and started teaching.

    Before this, the gate returned the bare valid NAMES: no purpose, no types, no
    required/optional, no enums, and a pointer to "the tool description" carrying no payload
    for a caller that cannot see the listing. Every fact needed to retry correctly already
    existed in the advertised schema and was simply discarded.

    These assert on the message a real client receives, through the real server — the only
    place the teaching either arrives or does not.
    """

    async def test_rejection_states_what_the_tool_is_for(self, mcp_client):
        """The wrong-TOOL case, which is what the original defect actually was: capture was
        the wrong tool for tagging, so naming its parameters alone could not have helped."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool(
                "gtd_inbox_capture", {"text": "x", "type_tags": ["improvement_candidate"]}
            )
        message = str(exc.value)
        assert "What gtd_inbox_capture is for:" in message
        assert "GTD" in message

    async def test_rejection_types_each_parameter_and_marks_required(self, mcp_client):
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool("gtd_inbox_capture", {"text": "x", "bogus": 1})
        message = str(exc.value)
        assert "text (string, required)" in message
        assert "optional" in message

    async def test_rejection_suggests_the_probable_typo(self, mcp_client):
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool("gtd_inbox_capture", {"text": "x", "txt": "y"})
        message = str(exc.value)
        assert "Did you mean" in message and "text" in message

    async def test_rejection_carries_the_combination_rules_a_schema_cannot_state(self, mcp_client):
        """`gtd_inbox_capture` is text-only by design — a rule JSON Schema has no way to
        express, and exactly the rule the original caller violated."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool("gtd_inbox_capture", {"text": "x", "type_tags": ["a"]})
        assert "TEXT ONLY" in str(exc.value)

    async def test_rejection_points_at_the_help_payload(self, mcp_client):
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool("gtd_inbox_capture", {"text": "x", "bogus": 1})
        message = str(exc.value)
        assert 'rtm_tool_help("gtd_inbox_capture")' in message
        assert "rtm_tool_help()" in message  # the index, for a wrong-tool caller

    async def test_the_richer_rejection_still_writes_nothing(self, mcp_client, rtm_client):
        """The assertion that must never regress: `client.call` is the single chokepoint every
        tool goes through, so zero awaits is the complete proof."""
        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "gtd_item_create", {"name": "x", "kind": "action", "bogus": True}
            )
        assert rtm_client.call.await_count == 0

    async def test_a_zero_parameter_tool_still_rejects_cleanly(self, mcp_client, rtm_client):
        """No parameter table to render — the rejection must still be coherent rather than
        rendering an empty list and losing its footing."""
        with pytest.raises(ToolError) as exc:
            await mcp_client.call_tool("get_lists", {"nonsense": 1})
        message = str(exc.value)
        assert "nonsense" in message and "rtm_tool_help" in message
        assert rtm_client.call.await_count == 0
