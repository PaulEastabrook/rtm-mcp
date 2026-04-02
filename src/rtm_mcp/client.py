"""Async RTM API client with signing, rate limiting, retry, and timezone caching."""

import asyncio
import hashlib
import logging
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from .config import RTM_API_URL, RTMConfig
from .exceptions import RTMError, RTMNetworkError, RTMRateLimitError, raise_for_error
from .rate_limiter import RateLimitStats, TokenBucket

logger = logging.getLogger(__name__)


def _is_tls_cert_error(exc: Exception) -> bool:
    """Check whether *exc* wraps a TLS certificate verification failure."""
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return True
        cause = getattr(cause, "__cause__", None)
    return False


def sign_request(shared_secret: str, params: dict[str, str]) -> str:
    """Generate MD5 API signature for RTM request parameters."""
    sorted_params = sorted(params.items())
    param_string = "".join(f"{k}{v}" for k, v in sorted_params)
    return hashlib.md5((shared_secret + param_string).encode()).hexdigest()


@dataclass
class TransactionEntry:
    """Record of a single write operation for timeline introspection and batch undo."""

    transaction_id: str
    method: str
    undoable: bool
    undone: bool = False
    summary: str = ""


class RTMClient:
    """Async Remember The Milk API client.

    Features:
    - MD5 request signing (via module-level ``sign_request()``)
    - POST for writes, GET for reads
    - Timeline management for write operations
    - Token bucket rate limiting with HTTP 503 retry
    - Connection-level retry for transient network errors
    - Timezone caching (one API call per session)
    - Transaction log for undo / batch_undo
    - Connection pooling via httpx
    """

    def __init__(self, config: RTMConfig):
        self.config = config
        self._timeline: str | None = None
        self._timeline_created_at: str | None = None
        self._http: httpx.AsyncClient | None = None
        # Rate limiting
        refill_rate = 1.0 * (1.0 - config.safety_margin)
        self._bucket = TokenBucket(
            capacity=config.bucket_capacity,
            refill_rate=refill_rate,
        )
        self._rate_limit_stats = RateLimitStats()
        # Transaction log
        self._transaction_log: list[TransactionEntry] = []
        self._transaction_index: dict[str, TransactionEntry] = {}
        # Cached settings
        self._cached_timezone: str | None = None
        self._timezone_fetched: bool = False

    async def _get_http(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=5),
            )
        return self._http

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http:
            await self._http.aclose()
            self._http = None

    def _sign(self, params: dict[str, str]) -> str:
        """Generate MD5 API signature."""
        return sign_request(self.config.shared_secret, params)

    @property
    def bucket(self) -> TokenBucket:
        """The token bucket rate limiter."""
        return self._bucket

    @property
    def rate_limit_stats(self) -> RateLimitStats:
        """Request statistics for diagnostics."""
        return self._rate_limit_stats

    async def call(
        self,
        method: str,
        *,
        require_timeline: bool = False,
        **params: Any,
    ) -> dict[str, Any]:
        """Make an authenticated RTM API call.

        Args:
            method: RTM API method (e.g., 'rtm.tasks.getList')
            require_timeline: Whether to include a timeline (for write ops)
            **params: Additional parameters

        Returns:
            API response dict (without 'rsp' wrapper)

        Raises:
            RTMError: On API errors
            RTMNetworkError: On connection errors (after retries exhausted)
            RTMRateLimitError: After exhausting retries on HTTP 503
        """
        # Build request params once (deterministic, safe to retry)
        request_params: dict[str, str] = {
            "method": method,
            "api_key": self.config.api_key,
            "auth_token": self.config.auth_token,
            "format": "json",
            "v": "2",
        }

        if require_timeline:
            request_params["timeline"] = await self.get_timeline()

        for key, value in params.items():
            if value is not None:
                request_params[key] = str(value)

        request_params["api_sig"] = self._sign(request_params)

        request_type = "write" if require_timeline else "read"
        is_write = require_timeline
        max_attempts = self.config.max_retries + 1

        for attempt in range(max_attempts):
            await self._bucket.acquire()
            self._rate_limit_stats.record_request(request_type)

            try:
                response = await self._attempt_http(
                    method, request_params, is_write,
                )

                # Handle 503 (rate limit drop tier) before raise_for_status
                if response.status_code == 503:
                    self._rate_limit_stats.record_503()
                    if attempt < max_attempts - 1:
                        delay = (
                            self.config.retry_delay_first
                            if attempt == 0
                            else self.config.retry_delay_subsequent
                        )
                        logger.warning(
                            "RTM API %s returned 503 (attempt %d/%d), pausing %.1fs",
                            method, attempt + 1, max_attempts, delay,
                        )
                        self._bucket.pause(delay)
                        self._rate_limit_stats.record_retry()
                        continue
                    raise RTMRateLimitError(
                        f"RTM API returned 503 after {max_attempts} attempts"
                    )

                response.raise_for_status()

                result = response.json()
                rsp = result.get("rsp", {})

                logger.debug("RTM API %s raw response: %s", method, rsp)

                if rsp.get("stat") != "ok":
                    err = rsp.get("err", {})
                    code = int(err.get("code", 0))
                    msg = err.get("msg", "Unknown error")
                    raise_for_error(code, msg)

                return rsp

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RTMRateLimitError("Rate limit exceeded") from e
                raise RTMNetworkError(f"HTTP error: {e.response.status_code}") from e

        # Should not reach here, but safety net
        raise RTMNetworkError(f"RTM API call failed after {max_attempts} attempts")

    async def _attempt_http(
        self,
        method: str,
        request_params: dict[str, str],
        is_write: bool,
    ) -> httpx.Response:
        """Dispatch an HTTP request with connection-level retry.

        Retries on transient connection errors (ConnectError, and
        TimeoutException for reads).  Does NOT consume additional rate
        limit tokens on retry — the request never reached the server.

        Write operations that time out are NOT retried because the
        request may have been sent and processed, risking duplication.
        TLS certificate validation errors are never retried.
        """
        conn_max = self.config.conn_max_retries
        start = time.monotonic()
        last_exc: Exception | None = None

        for conn_attempt in range(conn_max + 1):
            try:
                http = await self._get_http()
                if is_write:
                    return await http.post(RTM_API_URL, data=request_params)
                else:
                    return await http.get(RTM_API_URL, params=request_params)

            except httpx.TimeoutException as e:
                if is_write:
                    # Write may have been sent — don't retry
                    elapsed = time.monotonic() - start
                    raise RTMNetworkError(
                        f"Write request timed out (ambiguous — request may have "
                        f"been processed). Error: timeout, retries: 0, "
                        f"elapsed: {elapsed:.1f}s"
                    ) from e
                last_exc = e

            except httpx.ConnectError as e:
                # Don't retry TLS certificate validation failures
                if _is_tls_cert_error(e):
                    raise RTMNetworkError(
                        "TLS certificate verification failed"
                    ) from e
                last_exc = e

            # If we get here, the request failed with a retryable error
            if conn_attempt < conn_max:
                delay = (
                    self.config.conn_retry_delay_first
                    if conn_attempt == 0
                    else self.config.conn_retry_delay_subsequent
                )
                logger.warning(
                    "RTM API %s connection error (attempt %d/%d): %s, "
                    "retrying in %.1fs",
                    method, conn_attempt + 1, conn_max + 1,
                    type(last_exc).__name__, delay,
                )
                self._rate_limit_stats.record_conn_retry()
                await asyncio.sleep(delay)

        # All connection retries exhausted
        elapsed = time.monotonic() - start
        error_type = type(last_exc).__name__ if last_exc else "Unknown"
        raise RTMNetworkError(
            f"Connection failed after {conn_max + 1} attempts. "
            f"Error: {error_type}, retries: {conn_max}, "
            f"elapsed: {elapsed:.1f}s"
        ) from last_exc

    async def get_timeline(self) -> str:
        """Get or create a timeline for write operations.

        Timelines are required for all write operations and can be used
        to undo operations via rtm.transactions.undo.
        """
        if self._timeline is None:
            result = await self.call("rtm.timelines.create")
            self._timeline = str(result["timeline"])
            self._timeline_created_at = datetime.now().isoformat()
        return self._timeline

    async def get_timezone(self) -> str | None:
        """Get the user's timezone (cached after first fetch).

        Returns the IANA timezone string (e.g. 'Europe/London') or None
        if the settings call fails.
        """
        if not self._timezone_fetched:
            try:
                result = await self.call("rtm.settings.getList")
                self._cached_timezone = result.get("settings", {}).get("timezone")
            except Exception:
                pass
            self._timezone_fetched = True
        return self._cached_timezone

    @property
    def timeline_id(self) -> str | None:
        """The current session's timeline ID, or None if no writes yet."""
        return self._timeline

    @property
    def timeline_created_at(self) -> str | None:
        """ISO timestamp of when the timeline was created."""
        return self._timeline_created_at

    def record_transaction(
        self, transaction_id: str, method: str, undoable: bool, summary: str = ""
    ) -> None:
        """Record a write operation in the session transaction log."""
        entry = TransactionEntry(
            transaction_id=transaction_id,
            method=method,
            undoable=undoable,
            summary=summary,
        )
        self._transaction_log.append(entry)
        self._transaction_index[transaction_id] = entry

    def mark_undone(self, transaction_id: str) -> None:
        """Mark a transaction as undone."""
        entry = self._transaction_index.get(transaction_id)
        if entry:
            entry.undone = True

    def get_transaction(self, transaction_id: str) -> TransactionEntry | None:
        """Look up a transaction by ID."""
        return self._transaction_index.get(transaction_id)

    def get_all_transactions(self) -> list[TransactionEntry]:
        """Return the full transaction log in chronological order."""
        return list(self._transaction_log)

    async def test_echo(self) -> dict[str, Any]:
        """Test API connectivity (rtm.test.echo)."""
        return await self.call("rtm.test.echo", test="hello")

    async def check_token(self) -> dict[str, Any]:
        """Check if auth token is valid (rtm.auth.checkToken)."""
        return await self.call("rtm.auth.checkToken")


class RTMAuthFlow:
    """Handle RTM authentication flow (frob → token)."""

    def __init__(self, api_key: str, shared_secret: str):
        self.api_key = api_key
        self.shared_secret = shared_secret

    def _sign(self, params: dict[str, str]) -> str:
        """Generate MD5 signature."""
        return sign_request(self.shared_secret, params)

    async def get_frob(self) -> str:
        """Get a frob for authentication."""
        params = {
            "method": "rtm.auth.getFrob",
            "api_key": self.api_key,
            "format": "json",
        }
        params["api_sig"] = self._sign(params)

        async with httpx.AsyncClient() as http:
            response = await http.get(RTM_API_URL, params=params)
            response.raise_for_status()
            result = response.json()

            if result["rsp"]["stat"] != "ok":
                err = result["rsp"].get("err", {})
                raise RTMError(err.get("msg", "Failed to get frob"))

            return result["rsp"]["frob"]

    def get_auth_url(self, frob: str, perms: str = "delete") -> str:
        """Generate auth URL for user to visit.

        Args:
            frob: Frob from get_frob()
            perms: Permission level (read, write, delete)

        Returns:
            URL for user to authorize the app
        """
        from .config import RTM_AUTH_URL

        params = {
            "api_key": self.api_key,
            "perms": perms,
            "frob": frob,
        }
        params["api_sig"] = self._sign(params)

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{RTM_AUTH_URL}?{query}"

    async def get_token(self, frob: str) -> tuple[str, dict[str, Any]]:
        """Exchange frob for auth token.

        Args:
            frob: Authorized frob

        Returns:
            Tuple of (token, user_info)
        """
        params = {
            "method": "rtm.auth.getToken",
            "api_key": self.api_key,
            "frob": frob,
            "format": "json",
        }
        params["api_sig"] = self._sign(params)

        async with httpx.AsyncClient() as http:
            response = await http.get(RTM_API_URL, params=params)
            response.raise_for_status()
            result = response.json()

            if result["rsp"]["stat"] != "ok":
                err = result["rsp"].get("err", {})
                raise RTMError(err.get("msg", "Failed to get token"))

            auth = result["rsp"]["auth"]
            return auth["token"], auth.get("user", {})
