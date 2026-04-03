"""Tests for utility MCP tools via mocked RTM client."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from rtm_mcp.client import TransactionEntry


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
    # Sync methods must not be AsyncMock to avoid coroutine warnings
    client.mark_undone = MagicMock()
    client.record_transaction = MagicMock()
    client.get_transaction = MagicMock(return_value=None)
    client.get_all_transactions = MagicMock(return_value=[])
    type(client).timeline_id = PropertyMock(return_value=None)
    type(client).timeline_created_at = PropertyMock(return_value=None)
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
        client.mark_undone.assert_called_once_with("tx123")

    @pytest.mark.asyncio
    async def test_failure(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(side_effect=Exception("Cannot undo"))

        result = await tools["undo"](FakeContext(), transaction_id="tx456")
        assert result["data"]["status"] == "error"
        assert "Cannot undo" in result["data"]["error"]
        client.mark_undone.assert_not_called()


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


# ---------------------------------------------------------------------------
# batch_undo
# ---------------------------------------------------------------------------

class TestBatchUndo:
    @pytest.mark.asyncio
    async def test_undo_multiple(self, util_tools):
        tools, client = util_tools
        entries = [
            TransactionEntry("tx1", "add_task", True, summary="First"),
            TransactionEntry("tx2", "complete_task", True, summary="Second"),
            TransactionEntry("tx3", "delete_task", True, summary="Third"),
        ]
        client.get_all_transactions = MagicMock(return_value=entries)
        client.get_transaction = MagicMock(side_effect=lambda tid: next(
            (e for e in entries if e.transaction_id == tid), None
        ))
        client.call = AsyncMock(return_value={"stat": "ok"})
        type(client).timeline_id = PropertyMock(return_value="tl1")

        result = await tools["batch_undo"](FakeContext(), transaction_ids=["tx1", "tx3"])
        # Should undo tx3 first (most recent), then tx1
        assert result["data"]["undone"] == ["tx3", "tx1"]
        assert result["data"]["skipped"] == []
        assert result["data"]["failed"] is None
        assert result["data"]["timeline_id"] == "tl1"

    @pytest.mark.asyncio
    async def test_unknown_transaction_id(self, util_tools):
        tools, client = util_tools
        client.get_transaction = MagicMock(return_value=None)

        result = await tools["batch_undo"](FakeContext(), transaction_ids=["unknown1"])
        assert "error" in result["data"]
        assert "unknown1" in result["data"]["error"]

    @pytest.mark.asyncio
    async def test_skip_already_undone(self, util_tools):
        tools, client = util_tools
        entry_done = TransactionEntry("tx1", "add_task", True, undone=True)
        entry_pending = TransactionEntry("tx2", "complete_task", True)
        client.get_all_transactions = MagicMock(return_value=[entry_done, entry_pending])
        client.get_transaction = MagicMock(side_effect=lambda tid: {
            "tx1": entry_done, "tx2": entry_pending
        }.get(tid))
        client.call = AsyncMock(return_value={"stat": "ok"})
        type(client).timeline_id = PropertyMock(return_value="tl1")

        result = await tools["batch_undo"](FakeContext(), transaction_ids=["tx1", "tx2"])
        assert "tx1" in result["data"]["skipped"]
        assert "tx2" in result["data"]["undone"]

    @pytest.mark.asyncio
    async def test_stop_on_failure(self, util_tools):
        tools, client = util_tools
        entries = [
            TransactionEntry("tx1", "add_task", True),
            TransactionEntry("tx2", "complete_task", True),
            TransactionEntry("tx3", "delete_task", True),
        ]
        client.get_all_transactions = MagicMock(return_value=entries)
        client.get_transaction = MagicMock(side_effect=lambda tid: next(
            (e for e in entries if e.transaction_id == tid), None
        ))
        # tx3 succeeds, tx2 fails
        client.call = AsyncMock(side_effect=[
            {"stat": "ok"},  # tx3
            Exception("Server error"),  # tx2
        ])
        type(client).timeline_id = PropertyMock(return_value="tl1")

        result = await tools["batch_undo"](
            FakeContext(), transaction_ids=["tx1", "tx2", "tx3"],
        )
        assert result["data"]["undone"] == ["tx3"]
        assert result["data"]["failed"]["transaction_id"] == "tx2"
        assert "Server error" in result["data"]["failed"]["error"]
        # tx1 should not have been attempted
        assert "tx1" not in result["data"]["undone"]
        assert "tx1" not in result["data"]["skipped"]

    @pytest.mark.asyncio
    async def test_reverse_chronological_order(self, util_tools):
        """Verify undo happens most-recent-first regardless of input order."""
        tools, client = util_tools
        entries = [
            TransactionEntry("tx1", "a", True),
            TransactionEntry("tx2", "b", True),
            TransactionEntry("tx3", "c", True),
        ]
        client.get_all_transactions = MagicMock(return_value=entries)
        client.get_transaction = MagicMock(side_effect=lambda tid: next(
            (e for e in entries if e.transaction_id == tid), None
        ))
        call_order = []
        async def track_call(*args, **kwargs):
            call_order.append(kwargs.get("transaction_id"))
            return {"stat": "ok"}
        client.call = AsyncMock(side_effect=track_call)
        type(client).timeline_id = PropertyMock(return_value="tl1")

        # Pass in forward order; should still undo in reverse
        await tools["batch_undo"](FakeContext(), transaction_ids=["tx1", "tx2", "tx3"])
        assert call_order == ["tx3", "tx2", "tx1"]

    @pytest.mark.asyncio
    async def test_marks_undone_on_success(self, util_tools):
        tools, client = util_tools
        entry = TransactionEntry("tx1", "add_task", True)
        client.get_all_transactions = MagicMock(return_value=[entry])
        client.get_transaction = MagicMock(return_value=entry)
        client.call = AsyncMock(return_value={"stat": "ok"})
        type(client).timeline_id = PropertyMock(return_value="tl1")

        await tools["batch_undo"](FakeContext(), transaction_ids=["tx1"])
        client.mark_undone.assert_called_once_with("tx1")


# ---------------------------------------------------------------------------
# get_timeline_info
# ---------------------------------------------------------------------------

class TestGetTimelineInfo:
    @pytest.mark.asyncio
    async def test_no_timeline(self, util_tools):
        tools, _client = util_tools
        # defaults from fixture: timeline_id=None, get_all_transactions=[]

        result = await tools["get_timeline_info"](FakeContext())
        assert result["data"]["timeline_id"] is None
        assert result["data"]["transaction_count"] == 0
        assert result["data"]["transactions"] == []

    @pytest.mark.asyncio
    async def test_with_transactions(self, util_tools):
        tools, client = util_tools
        entries = [
            TransactionEntry("tx1", "add_task", True, summary="Added task"),
            TransactionEntry("tx2", "complete_task", True, undone=True, summary="Completed"),
        ]
        client.get_all_transactions = MagicMock(return_value=entries)
        type(client).timeline_id = PropertyMock(return_value="tl42")
        type(client).timeline_created_at = PropertyMock(return_value="2026-04-01T10:00:00")

        result = await tools["get_timeline_info"](FakeContext())
        assert result["data"]["timeline_id"] == "tl42"
        assert result["data"]["created_at"] == "2026-04-01T10:00:00"
        assert result["data"]["transaction_count"] == 2

        tx_list = result["data"]["transactions"]
        assert tx_list[0]["transaction_id"] == "tx1"
        assert tx_list[0]["undoable"] is True
        assert tx_list[0]["undone"] is False
        assert tx_list[1]["transaction_id"] == "tx2"
        assert tx_list[1]["undone"] is True


# ---------------------------------------------------------------------------
# get_rate_limit_status
# ---------------------------------------------------------------------------

class TestGetRateLimitStatus:
    @pytest.mark.asyncio
    async def test_returns_all_fields(self, util_tools):
        tools, client = util_tools

        mock_bucket = MagicMock()
        mock_bucket.tokens_available = 2.5
        mock_stats = MagicMock()
        mock_stats.requests_last_60s = MagicMock(return_value=10)
        mock_stats.retries_last_60s = MagicMock(return_value=1)
        mock_stats.http_503_count_session = 2
        mock_config = MagicMock()
        mock_config.bucket_capacity = 3
        mock_config.safety_margin = 0.1

        client.bucket = mock_bucket
        client.rate_limit_stats = mock_stats
        client.config = mock_config

        result = await tools["get_rate_limit_status"](FakeContext())
        data = result["data"]
        assert data["tokens_available"] == 2.5
        assert data["bucket_capacity"] == 3
        assert data["refill_rate"] == 0.9
        assert data["safety_margin"] == 0.1
        assert data["requests_last_60s"] == 10
        assert data["retries_last_60s"] == 1
        assert data["http_503_count_session"] == 2


# ---------------------------------------------------------------------------
# get_task_url
# ---------------------------------------------------------------------------

class TestGetTaskUrl:
    @pytest.mark.asyncio
    async def test_by_name_with_hierarchy(self, util_tools):
        """Task found by name, with 3-level hierarchy → full URL."""
        tools, client = util_tools

        # find_task fetches all incomplete tasks
        all_tasks_response = {"tasks": {"list": [
            {"id": "1", "taskseries": [
                {"id": "ts_100", "name": "Focus area", "parent_task_id": "",
                 "tags": [], "notes": [], "url": "", "location_id": "",
                 "created": "", "modified": "2026-01-01T00:00:00Z",
                 "task": [{"id": "100", "due": "", "has_due_time": "0",
                           "start": "", "has_start_time": "0",
                           "completed": "", "deleted": "", "priority": "N",
                           "postponed": "0", "estimate": ""}]},
                {"id": "ts_200", "name": "Project X", "parent_task_id": "100",
                 "tags": [], "notes": [], "url": "", "location_id": "",
                 "created": "", "modified": "2026-01-02T00:00:00Z",
                 "task": [{"id": "200", "due": "", "has_due_time": "0",
                           "start": "", "has_start_time": "0",
                           "completed": "", "deleted": "", "priority": "N",
                           "postponed": "0", "estimate": ""}]},
                {"id": "ts_300", "name": "Do the thing", "parent_task_id": "200",
                 "tags": [], "notes": [], "url": "", "location_id": "",
                 "created": "", "modified": "2026-01-03T00:00:00Z",
                 "task": [{"id": "300", "due": "", "has_due_time": "0",
                           "start": "", "has_start_time": "0",
                           "completed": "", "deleted": "", "priority": "N",
                           "postponed": "0", "estimate": ""}]},
            ]},
        ]}}

        lists_response = {"lists": {"list": [
            {"id": "1", "name": "Processed", "deleted": "0",
             "locked": "0", "archived": "0", "position": "0", "smart": "0"},
        ]}}

        async def mock_call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return all_tasks_response
            if method == "rtm.lists.getList":
                return lists_response
            return {}

        client.call = AsyncMock(side_effect=mock_call)

        result = await tools["get_task_url"](
            FakeContext(), task_name="Do the thing",
        )
        data = result["data"]
        assert data["url"] == "https://www.rememberthemilk.com/app/#list/1/100/200/300"
        assert data["task_name"] == "Do the thing"
        assert data["list_name"] == "Processed"
        assert len(data["hierarchy"]) == 3
        assert data["hierarchy"][0]["name"] == "Focus area"
        assert data["hierarchy"][2]["name"] == "Do the thing"

    @pytest.mark.asyncio
    async def test_by_ids_top_level(self, util_tools):
        """Explicit IDs, no parents → short URL."""
        tools, client = util_tools

        task_response = {"tasks": {"list": [
            {"id": "5", "taskseries": [
                {"id": "ts_10", "name": "Solo", "parent_task_id": "",
                 "tags": [], "notes": [], "url": "", "location_id": "",
                 "created": "", "modified": "",
                 "task": [{"id": "10", "due": "", "has_due_time": "0",
                           "start": "", "has_start_time": "0",
                           "completed": "", "deleted": "", "priority": "N",
                           "postponed": "0", "estimate": ""}]},
            ]},
        ]}}

        lists_response = {"lists": {"list": [
            {"id": "5", "name": "Inbox", "deleted": "0",
             "locked": "1", "archived": "0", "position": "0", "smart": "0"},
        ]}}

        async def mock_call(method, **kwargs):
            if method == "rtm.tasks.getList":
                return task_response
            if method == "rtm.lists.getList":
                return lists_response
            return {}

        client.call = AsyncMock(side_effect=mock_call)

        result = await tools["get_task_url"](
            FakeContext(),
            task_id="10", taskseries_id="ts_10", list_id="5",
        )
        data = result["data"]
        assert data["url"] == "https://www.rememberthemilk.com/app/#list/5/10"
        assert data["task_name"] == "Solo"
        assert len(data["hierarchy"]) == 1

    @pytest.mark.asyncio
    async def test_task_not_found(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"tasks": {"list": []}})

        result = await tools["get_task_url"](
            FakeContext(), task_name="nonexistent",
        )
        assert "error" in result["data"]


# ---------------------------------------------------------------------------
# get_list_url
# ---------------------------------------------------------------------------

class TestGetListUrl:
    @pytest.mark.asyncio
    async def test_by_name(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"lists": {"list": [
            {"id": "42", "name": "Processed", "deleted": "0",
             "locked": "0", "archived": "0", "position": "0", "smart": "0"},
        ]}})

        result = await tools["get_list_url"](
            FakeContext(), list_name="Processed",
        )
        data = result["data"]
        assert data["url"] == "https://www.rememberthemilk.com/app/#list/42"
        assert data["list_name"] == "Processed"
        assert data["list_id"] == "42"

    @pytest.mark.asyncio
    async def test_by_id(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"lists": {"list": [
            {"id": "42", "name": "Processed", "deleted": "0",
             "locked": "0", "archived": "0", "position": "0", "smart": "0"},
        ]}})

        result = await tools["get_list_url"](
            FakeContext(), list_id="42",
        )
        data = result["data"]
        assert data["url"] == "https://www.rememberthemilk.com/app/#list/42"
        assert data["list_name"] == "Processed"

    @pytest.mark.asyncio
    async def test_list_not_found(self, util_tools):
        tools, client = util_tools
        client.call = AsyncMock(return_value={"lists": {"list": [
            {"id": "1", "name": "Inbox", "deleted": "0",
             "locked": "1", "archived": "0", "position": "0", "smart": "0"},
        ]}})

        result = await tools["get_list_url"](
            FakeContext(), list_name="NonExistent",
        )
        assert "error" in result["data"]

    @pytest.mark.asyncio
    async def test_neither_name_nor_id(self, util_tools):
        tools, client = util_tools

        result = await tools["get_list_url"](FakeContext())
        assert "error" in result["data"]
