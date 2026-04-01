"""Tests for utility MCP tools via mocked RTM client."""

from typing import Any
from unittest.mock import AsyncMock

import pytest


class FakeMCP:
    def __init__(self):
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn
        return decorator


class FakeContext:
    pass


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.call = AsyncMock()
    client.test_echo = AsyncMock()
    client.check_token = AsyncMock()
    return client


@pytest.fixture
def util_tools(mock_client):
    mcp = FakeMCP()
    from rtm_mcp.tools.utilities import register_utility_tools

    async def get_client():
        return mock_client

    register_utility_tools(mcp, get_client)
    return mcp.tools, mock_client


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

class TestTestConnection:
    @pytest.mark.asyncio
    async def test_success(self, util_tools):
        tools, client = util_tools
        client.test_echo = AsyncMock(return_value={"stat": "ok"})

        result = await tools["test_connection"](FakeContext())
        assert result["data"]["status"] == "connected"
        assert "response_time_ms" in result["data"]

    @pytest.mark.asyncio
    async def test_failure(self, util_tools):
        tools, client = util_tools
        client.test_echo = AsyncMock(side_effect=ConnectionError("timeout"))

        result = await tools["test_connection"](FakeContext())
        assert result["data"]["status"] == "error"
        assert "timeout" in result["data"]["error"]


# ---------------------------------------------------------------------------
# check_auth
# ---------------------------------------------------------------------------

class TestCheckAuth:
    @pytest.mark.asyncio
    async def test_authenticated(self, util_tools):
        tools, client = util_tools
        client.check_token = AsyncMock(return_value={
            "auth": {
                "token": "tok",
                "perms": "delete",
                "user": {"id": "1", "username": "testuser", "fullname": "Test User"},
            },
        })

        result = await tools["check_auth"](FakeContext())
        assert result["data"]["status"] == "authenticated"
        assert result["data"]["user"]["username"] == "testuser"
        assert result["data"]["permissions"] == "delete"

    @pytest.mark.asyncio
    async def test_not_authenticated(self, util_tools):
        tools, client = util_tools
        client.check_token = AsyncMock(side_effect=Exception("Invalid token"))

        result = await tools["check_auth"](FakeContext())
        assert result["data"]["status"] == "not_authenticated"


# ---------------------------------------------------------------------------
# get_tags
# ---------------------------------------------------------------------------

class TestGetTags:
    @pytest.mark.asyncio
    async def test_multiple_tags(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "tags": {"tag": [{"name": "work"}, {"name": "home"}, {"name": "alpha"}]},
        })

        result = await tools["get_tags"](FakeContext())
        assert result["data"]["count"] == 3
        # Should be sorted
        assert result["data"]["tags"][0]["name"] == "alpha"

    @pytest.mark.asyncio
    async def test_single_tag_as_dict(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "tags": {"tag": {"name": "solo"}},
        })

        result = await tools["get_tags"](FakeContext())
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_tag_as_string(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "tags": {"tag": "simple"},
        })

        result = await tools["get_tags"](FakeContext())
        assert result["data"]["count"] == 1
        assert result["data"]["tags"][0]["name"] == "simple"

    @pytest.mark.asyncio
    async def test_empty_tags(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"stat": "ok", "tags": {}})

        result = await tools["get_tags"](FakeContext())
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_tag_with_dollar_t_field(self, util_tools):
        """Some RTM responses use $t instead of name."""
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "tags": {"tag": [{"$t": "via_dollar_t"}]},
        })

        result = await tools["get_tags"](FakeContext())
        assert result["data"]["tags"][0]["name"] == "via_dollar_t"


# ---------------------------------------------------------------------------
# get_locations
# ---------------------------------------------------------------------------

class TestGetLocations:
    @pytest.mark.asyncio
    async def test_multiple_locations(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "locations": {
                "location": [
                    {"id": "1", "name": "Home", "latitude": "51.5", "longitude": "-0.1", "zoom": "10", "address": "London"},
                    {"id": "2", "name": "Office", "latitude": "40.7", "longitude": "-74.0", "zoom": "12", "address": "NYC"},
                ],
            },
        })

        result = await tools["get_locations"](FakeContext())
        assert result["data"]["count"] == 2
        assert result["data"]["locations"][0]["latitude"] == 51.5
        assert result["data"]["locations"][1]["zoom"] == 12

    @pytest.mark.asyncio
    async def test_single_location_as_dict(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "locations": {
                "location": {"id": "1", "name": "Home", "latitude": "0", "longitude": "0"},
            },
        })

        result = await tools["get_locations"](FakeContext())
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_location_no_zoom(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "locations": {
                "location": {"id": "1", "name": "Place", "latitude": "1", "longitude": "2"},
            },
        })

        result = await tools["get_locations"](FakeContext())
        assert result["data"]["locations"][0]["zoom"] is None

    @pytest.mark.asyncio
    async def test_empty_locations(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"stat": "ok", "locations": {}})

        result = await tools["get_locations"](FakeContext())
        assert result["data"]["count"] == 0


# ---------------------------------------------------------------------------
# get_settings
# ---------------------------------------------------------------------------

class TestGetSettings:
    @pytest.mark.asyncio
    async def test_european_12h(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "settings": {
                "timezone": "Europe/London",
                "dateformat": "0",
                "timeformat": "0",
                "defaultlist": "123",
                "language": "en",
            },
        })

        result = await tools["get_settings"](FakeContext())
        assert result["data"]["timezone"] == "Europe/London"
        assert "European" in result["data"]["date_format"]
        assert result["data"]["time_format"] == "12-hour"
        assert result["data"]["default_list_id"] == "123"

    @pytest.mark.asyncio
    async def test_american_24h(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "settings": {"dateformat": "1", "timeformat": "1"},
        })

        result = await tools["get_settings"](FakeContext())
        assert "American" in result["data"]["date_format"]
        assert result["data"]["time_format"] == "24-hour"


# ---------------------------------------------------------------------------
# parse_time
# ---------------------------------------------------------------------------

class TestParseTime:
    @pytest.mark.asyncio
    async def test_basic(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "time": {"$t": "2026-04-02T00:00:00Z", "precision": "date"},
        })

        result = await tools["parse_time"](FakeContext(), text="tomorrow")
        assert result["data"]["input"] == "tomorrow"
        assert result["data"]["parsed"] == "2026-04-02T00:00:00Z"
        assert result["data"]["precision"] == "date"

    @pytest.mark.asyncio
    async def test_with_timezone(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "time": {"$t": "2026-04-02T14:00:00Z", "precision": "time"},
        })

        await tools["parse_time"](
            FakeContext(), text="2pm", timezone="America/New_York",
        )
        # Verify timezone was passed to API
        call_kwargs = client.call.call_args.kwargs
        assert call_kwargs["timezone"] == "America/New_York"


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------

class TestUndo:
    @pytest.mark.asyncio
    async def test_success(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"stat": "ok"})

        result = await tools["undo"](FakeContext(), transaction_id="tx123")
        assert result["data"]["status"] == "success"
        assert result["data"]["transaction_id"] == "tx123"

    @pytest.mark.asyncio
    async def test_failure(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(side_effect=Exception("Cannot undo"))

        result = await tools["undo"](FakeContext(), transaction_id="tx456")
        assert result["data"]["status"] == "error"
        assert "Cannot undo" in result["data"]["error"]


# ---------------------------------------------------------------------------
# get_contacts
# ---------------------------------------------------------------------------

class TestGetContacts:
    @pytest.mark.asyncio
    async def test_multiple(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "contacts": {
                "contact": [
                    {"id": "1", "fullname": "Alice", "username": "alice"},
                    {"id": "2", "fullname": "Bob", "username": "bob"},
                ],
            },
        })

        result = await tools["get_contacts"](FakeContext())
        assert result["data"]["count"] == 2
        assert result["data"]["contacts"][0]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_single_as_dict(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "contacts": {"contact": {"id": "1", "fullname": "Solo", "username": "solo"}},
        })

        result = await tools["get_contacts"](FakeContext())
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_empty(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"stat": "ok", "contacts": {}})

        result = await tools["get_contacts"](FakeContext())
        assert result["data"]["count"] == 0


# ---------------------------------------------------------------------------
# get_groups
# ---------------------------------------------------------------------------

class TestGetGroups:
    @pytest.mark.asyncio
    async def test_group_with_members(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "groups": {
                "group": {
                    "id": "g1",
                    "name": "Team",
                    "contacts": {
                        "contact": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
                    },
                },
            },
        })

        result = await tools["get_groups"](FakeContext())
        assert result["data"]["count"] == 1
        assert result["data"]["groups"][0]["member_count"] == 3

    @pytest.mark.asyncio
    async def test_group_single_contact_as_dict(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={
            "stat": "ok",
            "groups": {
                "group": {
                    "id": "g1",
                    "name": "Duo",
                    "contacts": {"contact": {"id": "1"}},
                },
            },
        })

        result = await tools["get_groups"](FakeContext())
        assert result["data"]["groups"][0]["member_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_groups(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"stat": "ok", "groups": {}})

        result = await tools["get_groups"](FakeContext())
        assert result["data"]["count"] == 0
