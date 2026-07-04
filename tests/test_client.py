"""Tests for RTM client."""

import time

import httpx
import pytest
import respx

from rtm_mcp.client import ACCOUNT_TAGS_TTL_SECONDS, RTMClient, TransactionEntry
from rtm_mcp.config import RTM_API_URL, RTMConfig
from rtm_mcp.exceptions import RTMAuthError, RTMError, RTMNetworkError, RTMRateLimitError
from rtm_mcp.rate_limiter import RateLimitStats, TokenBucket


@pytest.fixture
def client(mock_config: RTMConfig) -> RTMClient:
    """Create a test client."""
    return RTMClient(mock_config)


class TestRTMClient:
    """Test RTMClient functionality."""

    def test_sign_request(self, client: RTMClient) -> None:
        """Test MD5 signing."""
        params = {"api_key": "test", "method": "rtm.test.echo"}
        signature = client._sign(params)

        # Verify signature format
        assert len(signature) == 32
        assert all(c in "0123456789abcdef" for c in signature)

        # Verify signature is reproducible
        assert client._sign(params) == signature

    def test_sign_order_independent(self, client: RTMClient) -> None:
        """Test that signing is order-independent."""
        params1 = {"a": "1", "b": "2", "c": "3"}
        params2 = {"c": "3", "a": "1", "b": "2"}

        assert client._sign(params1) == client._sign(params2)

    @respx.mock
    @pytest.mark.asyncio
    async def test_call_success(self, client: RTMClient) -> None:
        """Test successful API call."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "test": "hello"}},
            )
        )

        result = await client.call("rtm.test.echo", test="hello")

        assert result["stat"] == "ok"
        assert result["test"] == "hello"

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_settings_cache_shared(self, client: RTMClient) -> None:
        """get_timezone and get_default_list_id share one cached settings fetch."""
        route = respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "rsp": {
                        "stat": "ok",
                        "settings": {
                            "timezone": "Europe/London",
                            "defaultlist": "51526642",
                        },
                    }
                },
            )
        )

        assert await client.get_default_list_id() == "51526642"
        assert await client.get_timezone() == "Europe/London"
        # Repeated access is served from cache.
        assert await client.get_default_list_id() == "51526642"

        # A single rtm.settings.getList request serves both accessors.
        assert route.call_count == 1

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_default_list_id_absent(self, client: RTMClient) -> None:
        """No defaultlist configured → get_default_list_id returns None."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "settings": {"timezone": "UTC"}}},
            )
        )

        assert await client.get_default_list_id() is None

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_account_tags_cache_ttl_and_normalize(self, client: RTMClient) -> None:
        """Account tags are normalized + cached with a TTL; force_refresh bypasses."""
        route = respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "rsp": {
                        "stat": "ok",
                        "tags": {
                            "tag": [
                                {"name": "Work"},
                                {"name": "PERSONAL"},
                                {"name": "waiting_for"},
                            ],
                        },
                    }
                },
            )
        )

        tags = await client.get_account_tags()
        assert tags == {"work", "personal", "waiting_for"}  # trimmed + lower-cased
        assert route.call_count == 1

        # Within TTL → served from cache.
        await client.get_account_tags()
        assert route.call_count == 1

        # force_refresh bypasses the cache.
        await client.get_account_tags(force_refresh=True)
        assert route.call_count == 2

        # Expire the TTL → next call refetches.
        client._account_tags_fetched_at = time.monotonic() - (ACCOUNT_TAGS_TTL_SECONDS + 1)
        await client.get_account_tags()
        assert route.call_count == 3

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_account_tags_empty(self, client: RTMClient) -> None:
        """An account with no tags yields an empty set."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(200, json={"rsp": {"stat": "ok", "tags": {}}})
        )
        assert await client.get_account_tags() == set()
        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_call_auth_error(self, client: RTMClient) -> None:
        """Test auth error handling."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "rsp": {
                        "stat": "fail",
                        "err": {"code": "98", "msg": "Login failed"},
                    }
                },
            )
        )

        with pytest.raises(RTMAuthError):
            await client.call("rtm.test.echo")

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_call_generic_error(self, client: RTMClient) -> None:
        """Test generic error handling."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "rsp": {
                        "stat": "fail",
                        "err": {"code": "999", "msg": "Unknown error"},
                    }
                },
            )
        )

        with pytest.raises(RTMError) as exc_info:
            await client.call("rtm.test.echo")

        assert "Unknown error" in str(exc_info.value)

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_timeline(self, client: RTMClient) -> None:
        """Test timeline creation."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "timeline": "12345"}},
            )
        )

        timeline = await client.get_timeline()
        assert timeline == "12345"

        # Should cache and return same timeline
        timeline2 = await client.get_timeline()
        assert timeline2 == "12345"

        await client.close()


class TestTransactionLog:
    """Test transaction log functionality."""

    def test_record_transaction(self, client: RTMClient) -> None:
        """Test recording a transaction."""
        client.record_transaction("tx1", "add_task", True, "Created task: Buy milk")

        entry = client.get_transaction("tx1")
        assert entry is not None
        assert entry.transaction_id == "tx1"
        assert entry.method == "add_task"
        assert entry.undoable is True
        assert entry.undone is False
        assert entry.summary == "Created task: Buy milk"

    def test_mark_undone(self, client: RTMClient) -> None:
        """Test marking a transaction as undone."""
        client.record_transaction("tx1", "add_task", True)
        client.mark_undone("tx1")

        entry = client.get_transaction("tx1")
        assert entry is not None
        assert entry.undone is True

    def test_mark_undone_unknown_id(self, client: RTMClient) -> None:
        """Test marking unknown transaction (no-op)."""
        client.mark_undone("nonexistent")
        # Should not raise

    def test_get_transaction_unknown(self, client: RTMClient) -> None:
        """Test looking up unknown transaction."""
        assert client.get_transaction("nonexistent") is None

    def test_get_all_transactions_order(self, client: RTMClient) -> None:
        """Test that transactions are returned in insertion order."""
        client.record_transaction("tx1", "add_task", True, "First")
        client.record_transaction("tx2", "complete_task", True, "Second")
        client.record_transaction("tx3", "delete_task", False, "Third")

        all_tx = client.get_all_transactions()
        assert len(all_tx) == 3
        assert all_tx[0].transaction_id == "tx1"
        assert all_tx[1].transaction_id == "tx2"
        assert all_tx[2].transaction_id == "tx3"

    def test_get_all_transactions_returns_copy(self, client: RTMClient) -> None:
        """Test that get_all_transactions returns a copy."""
        client.record_transaction("tx1", "add_task", True)
        all_tx = client.get_all_transactions()
        all_tx.clear()
        assert len(client.get_all_transactions()) == 1

    def test_timeline_properties_before_write(self, client: RTMClient) -> None:
        """Test timeline properties before any writes."""
        assert client.timeline_id is None
        assert client.timeline_created_at is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeline_properties_after_write(self, client: RTMClient) -> None:
        """Test timeline properties are set after get_timeline."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "timeline": "99999"}},
            )
        )

        await client.get_timeline()
        assert client.timeline_id == "99999"
        assert client.timeline_created_at is not None

        await client.close()

    def test_transaction_entry_dataclass(self) -> None:
        """Test TransactionEntry defaults."""
        entry = TransactionEntry(transaction_id="tx1", method="test", undoable=True)
        assert entry.undone is False
        assert entry.summary == ""


class TestTokenBucketIntegration:
    """Test token bucket integration in RTMClient."""

    def test_client_has_bucket(self, client: RTMClient) -> None:
        assert isinstance(client.bucket, TokenBucket)
        assert client.bucket.capacity == 100  # From mock_config

    def test_client_has_stats(self, client: RTMClient) -> None:
        assert isinstance(client.rate_limit_stats, RateLimitStats)

    def test_refill_rate_uses_safety_margin(self) -> None:
        config = RTMConfig(
            api_key="k",
            shared_secret="s",
            auth_token="t",
            safety_margin=0.2,
        )
        client = RTMClient(config)
        assert client.bucket.refill_rate == pytest.approx(0.8)

    @respx.mock
    @pytest.mark.asyncio
    async def test_request_records_stats(self, client: RTMClient) -> None:
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "test": "hello"}},
            )
        )

        await client.call("rtm.test.echo", test="hello")
        assert client.rate_limit_stats.requests_last_60s() >= 1

        await client.close()


class TestRetry503:
    """Test HTTP 503 retry behavior."""

    @pytest.fixture
    def retry_client(self) -> RTMClient:
        """Client with small retry delays for fast tests."""
        config = RTMConfig(
            api_key="k",
            shared_secret="s",
            auth_token="t",
            bucket_capacity=100,
            max_retries=2,
            retry_delay_first=0.01,
            retry_delay_subsequent=0.01,
        )
        return RTMClient(config)

    @respx.mock
    @pytest.mark.asyncio
    async def test_503_then_success(self, retry_client: RTMClient) -> None:
        """First request returns 503, second succeeds."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(200, json={"rsp": {"stat": "ok", "data": "ok"}}),
        ]

        result = await retry_client.call("rtm.test.echo")
        assert result["stat"] == "ok"
        assert retry_client.rate_limit_stats.http_503_count_session == 1
        assert retry_client.rate_limit_stats.retries_last_60s() == 1

        await retry_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_503_twice_then_success(self, retry_client: RTMClient) -> None:
        """Two 503s followed by success."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json={"rsp": {"stat": "ok"}}),
        ]

        result = await retry_client.call("rtm.test.echo")
        assert result["stat"] == "ok"
        assert retry_client.rate_limit_stats.http_503_count_session == 2
        assert retry_client.rate_limit_stats.retries_last_60s() == 2

        await retry_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_503_exhausts_retries(self, retry_client: RTMClient) -> None:
        """Three consecutive 503s should raise RTMRateLimitError."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(503),
        ]

        with pytest.raises(RTMRateLimitError, match="503 after 3 attempts"):
            await retry_client.call("rtm.test.echo")

        assert retry_client.rate_limit_stats.http_503_count_session == 3

        await retry_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_429_not_retried(self, retry_client: RTMClient) -> None:
        """HTTP 429 should raise immediately, no retry."""
        respx.get(RTM_API_URL).mock(return_value=httpx.Response(429))

        with pytest.raises(RTMRateLimitError, match="Rate limit exceeded"):
            await retry_client.call("rtm.test.echo")

        # Only 1 request, no retries
        assert retry_client.rate_limit_stats.requests_last_60s() == 1
        assert retry_client.rate_limit_stats.retries_last_60s() == 0

        await retry_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_500_not_retried(self, retry_client: RTMClient) -> None:
        """HTTP 500 should raise immediately, no retry."""
        respx.get(RTM_API_URL).mock(return_value=httpx.Response(500))

        with pytest.raises(RTMNetworkError, match="HTTP error: 500"):
            await retry_client.call("rtm.test.echo")

        assert retry_client.rate_limit_stats.retries_last_60s() == 0

        await retry_client.close()


class TestConnectionRetry:
    """Test connection-level retry behavior."""

    @pytest.fixture
    def conn_client(self) -> RTMClient:
        """Client with fast connection retry delays."""
        config = RTMConfig(
            api_key="k",
            shared_secret="s",
            auth_token="t",
            bucket_capacity=100,
            conn_max_retries=3,
            conn_retry_delay_first=0.01,
            conn_retry_delay_subsequent=0.01,
        )
        return RTMClient(config)

    @respx.mock
    @pytest.mark.asyncio
    async def test_connect_error_retries_then_succeeds(self, conn_client: RTMClient) -> None:
        """ConnectError followed by success should work."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.Response(200, json={"rsp": {"stat": "ok", "data": "ok"}}),
        ]

        result = await conn_client.call("rtm.test.echo")
        assert result["stat"] == "ok"
        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 1

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_connect_error_exhausts_retries(self, conn_client: RTMClient) -> None:
        """Four consecutive ConnectErrors should raise RTMNetworkError."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
        ]

        with pytest.raises(RTMNetworkError, match="Connection failed after 4 attempts"):
            await conn_client.call("rtm.test.echo")

        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 3

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_on_read_retries(self, conn_client: RTMClient) -> None:
        """TimeoutException on a read operation should retry."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.ReadTimeout("timed out"),
            httpx.Response(200, json={"rsp": {"stat": "ok"}}),
        ]

        result = await conn_client.call("rtm.test.echo")
        assert result["stat"] == "ok"
        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 1

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_on_write_raises_immediately(self, conn_client: RTMClient) -> None:
        """TimeoutException on a write operation should NOT retry."""
        # First: timeline creation succeeds (GET)
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "timeline": "12345"}},
            )
        )
        # Then: the write times out (POST)
        respx.post(RTM_API_URL).mock(side_effect=httpx.ReadTimeout("timed out"))

        with pytest.raises(RTMNetworkError, match="ambiguous"):
            await conn_client.call("rtm.tasks.add", require_timeline=True, name="Test")

        # No connection retries should have been recorded
        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 0

        await conn_client.close()

    @pytest.mark.asyncio
    async def test_tls_cert_error_not_retried(self, conn_client: RTMClient) -> None:
        """TLS certificate error should fail immediately without retry."""
        import ssl as _ssl
        from unittest.mock import AsyncMock, patch

        cert_err = _ssl.SSLCertVerificationError("certificate verify failed")
        connect_err = httpx.ConnectError("TLS error")
        connect_err.__cause__ = cert_err

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=connect_err)
        mock_http.is_closed = False

        with (
            patch.object(conn_client, "_get_http", return_value=mock_http),
            pytest.raises(RTMNetworkError, match="TLS certificate"),
        ):
            await conn_client.call("rtm.test.echo")

        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_connection_retry_does_not_consume_extra_tokens(
        self, conn_client: RTMClient
    ) -> None:
        """Connection retries should not consume additional rate limit tokens."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"rsp": {"stat": "ok"}}),
        ]

        await conn_client.call("rtm.test.echo")
        # Only 1 request should be recorded (the outer loop ran once)
        assert conn_client.rate_limit_stats.requests_last_60s() == 1

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_final_error_includes_details(self, conn_client: RTMClient) -> None:
        """Exhausted retries should include error type, count, and elapsed time."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
        ]

        with pytest.raises(RTMNetworkError) as exc_info:
            await conn_client.call("rtm.test.echo")

        msg = str(exc_info.value)
        assert "ConnectError" in msg
        assert "retries: 3" in msg
        assert "elapsed:" in msg

        await conn_client.close()


class TestPostGetSplit:
    """Test that reads use GET and writes use POST."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_read_uses_get(self, client: RTMClient) -> None:
        """Read operations (require_timeline=False) should use GET."""
        route = respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "test": "hello"}},
            )
        )

        await client.call("rtm.test.echo", test="hello")
        assert route.called

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_write_uses_post(self, client: RTMClient) -> None:
        """Write operations (require_timeline=True) should use POST."""
        # First call: get_timeline (GET)
        # Second call: the actual write (POST)
        get_route = respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "timeline": "12345"}},
            )
        )
        post_route = respx.post(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "list": {}}},
            )
        )

        await client.call("rtm.tasks.add", require_timeline=True, name="Test")
        assert get_route.called  # timeline creation uses GET
        assert post_route.called  # write operation uses POST

        await client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_write_sends_params_as_form_data(self, client: RTMClient) -> None:
        """Write operations should send params as POST form data, not query params."""
        # Timeline creation (GET)
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={"rsp": {"stat": "ok", "timeline": "12345"}},
            )
        )
        # Capture the POST request
        post_route = respx.post(RTM_API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "rsp": {"stat": "ok", "note": {"id": "1", "title": "My Title", "$t": "Body"}}
                },
            )
        )

        await client.call(
            "rtm.tasks.notes.add",
            require_timeline=True,
            note_title="My Title",
            note_text="Body text",
        )

        # Verify the POST request was made
        assert post_route.called
        request = post_route.calls[0].request
        # POST form data should be in the body, not the URL
        body = request.content.decode()
        assert "note_title=My+Title" in body or "note_title=My%20Title" in body

        await client.close()


class TestRTMConfig:
    """Test configuration loading."""

    def test_is_configured(self) -> None:
        """Test configuration validation."""
        # Not configured
        config = RTMConfig()
        assert not config.is_configured()

        # Partially configured
        config = RTMConfig(api_key="key")
        assert not config.is_configured()

        # Fully configured (note: auth_token uses alias "token")
        config = RTMConfig(
            api_key="key",
            shared_secret="secret",
            token="token",
        )
        assert config.is_configured()


class TestTransportErrorHandling:
    """Connect-phase vs mid-flight transport error classification."""

    @pytest.fixture
    def conn_client(self) -> RTMClient:
        config = RTMConfig(
            api_key="k",
            shared_secret="s",
            auth_token="t",
            bucket_capacity=100,
            conn_max_retries=3,
            conn_retry_delay_first=0.01,
            conn_retry_delay_subsequent=0.01,
        )
        return RTMClient(config)

    @respx.mock
    @pytest.mark.asyncio
    async def test_connect_timeout_on_write_retries(self, conn_client: RTMClient) -> None:
        """ConnectTimeout on a write IS retried — the connection was never
        established, so the request cannot have been processed."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(200, json={"rsp": {"stat": "ok", "timeline": "12345"}})
        )
        route = respx.post(RTM_API_URL)
        route.side_effect = [
            httpx.ConnectTimeout("handshake timed out"),
            httpx.Response(200, json={"rsp": {"stat": "ok"}}),
        ]

        result = await conn_client.call("rtm.tasks.add", require_timeline=True, name="Test")
        assert result["stat"] == "ok"
        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 1

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_pool_timeout_on_write_retries(self, conn_client: RTMClient) -> None:
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(200, json={"rsp": {"stat": "ok", "timeline": "12345"}})
        )
        route = respx.post(RTM_API_URL)
        route.side_effect = [
            httpx.PoolTimeout("no connection available"),
            httpx.Response(200, json={"rsp": {"stat": "ok"}}),
        ]

        result = await conn_client.call("rtm.tasks.add", require_timeline=True, name="Test")
        assert result["stat"] == "ok"

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_read_error_on_read_retries(self, conn_client: RTMClient) -> None:
        """A mid-flight ReadError (TCP reset) on a read is safe to replay."""
        route = respx.get(RTM_API_URL)
        route.side_effect = [
            httpx.ReadError("connection reset by peer"),
            httpx.Response(200, json={"rsp": {"stat": "ok"}}),
        ]

        result = await conn_client.call("rtm.test.echo")
        assert result["stat"] == "ok"
        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 1

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_read_error_on_write_raises_wrapped(self, conn_client: RTMClient) -> None:
        """A mid-flight ReadError on a write is ambiguous: no retry, and it must
        surface as RTMNetworkError, not a raw httpx exception."""
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(200, json={"rsp": {"stat": "ok", "timeline": "12345"}})
        )
        respx.post(RTM_API_URL).mock(side_effect=httpx.ReadError("connection reset"))

        with pytest.raises(RTMNetworkError, match="mid-flight"):
            await conn_client.call("rtm.tasks.add", require_timeline=True, name="Test")

        assert conn_client.rate_limit_stats.conn_retries_last_60s() == 0

        await conn_client.close()

    @respx.mock
    @pytest.mark.asyncio
    async def test_non_json_response_raises_network_error(self, conn_client: RTMClient) -> None:
        respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(200, text="<html>gateway error</html>")
        )

        with pytest.raises(RTMNetworkError, match="non-JSON"):
            await conn_client.call("rtm.test.echo")

        await conn_client.close()


class TestSessionCacheRobustness:
    @pytest.mark.asyncio
    async def test_settings_failure_not_cached(self, client: RTMClient) -> None:
        """A transient settings failure must not disable timezone localisation
        for the whole session — the next consumer retries."""
        from unittest.mock import AsyncMock

        client.call = AsyncMock(
            side_effect=[
                RTMError("boom"),
                {"settings": {"timezone": "Europe/London"}},
            ]
        )

        assert await client.get_timezone() is None
        assert await client.get_timezone() == "Europe/London"
        assert client.call.await_count == 2

        # Third consumer hits the cache — no further API call.
        assert await client.get_timezone() == "Europe/London"
        assert client.call.await_count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_concurrent_get_timeline_creates_one_timeline(self, client: RTMClient) -> None:
        """Two concurrent first writes must share one timeline (undo depends on
        the log matching the timeline the writes executed under)."""
        import asyncio

        route = respx.get(RTM_API_URL).mock(
            return_value=httpx.Response(200, json={"rsp": {"stat": "ok", "timeline": "111"}})
        )

        t1, t2 = await asyncio.gather(client.get_timeline(), client.get_timeline())
        assert t1 == t2 == "111"
        assert route.call_count == 1

        await client.close()
