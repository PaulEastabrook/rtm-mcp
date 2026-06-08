"""Tests for the strict-tag guard (src/rtm_mcp/strict_tags.py)."""

import pytest

from rtm_mcp.strict_tags import (
    enforce_strict_tags,
    extract_smartadd_tags,
    normalize_tag,
    split_tags,
)


class _FakeConfig:
    def __init__(self, strict_tags: bool) -> None:
        self.strict_tags = strict_tags


class _FakeClient:
    """Minimal client stand-in for enforce_strict_tags.

    Returns successive tag batches so a force_refresh can reveal a tag that the
    first (stale) read was missing.
    """

    def __init__(self, strict_tags: bool, tag_batches: list[set[str]]) -> None:
        self.config = _FakeConfig(strict_tags)
        self._batches = tag_batches
        self._idx = 0
        self.calls = 0

    async def get_account_tags(self, *, force_refresh: bool = False) -> set[str]:
        self.calls += 1
        batch = self._batches[min(self._idx, len(self._batches) - 1)]
        self._idx += 1
        return batch


class TestNormalizeAndSplit:
    def test_normalize(self) -> None:
        assert normalize_tag("  Work ") == "work"

    def test_split_drops_empties_and_dedupes(self) -> None:
        assert split_tags("work, , Work ,personal,") == ["work", "personal"]

    def test_split_empty_string(self) -> None:
        assert split_tags("") == []


class TestExtractSmartAdd:
    def test_basic(self) -> None:
        assert extract_smartadd_tags("Call mom #family #urgent") == ["family", "urgent"]

    def test_normalizes_and_dedupes(self) -> None:
        assert extract_smartadd_tags("x #Work y #work") == ["work"]

    def test_ignores_midword_hash(self) -> None:
        assert extract_smartadd_tags("learn C# today") == []

    def test_no_tags(self) -> None:
        assert extract_smartadd_tags("plain name") == []


class TestEnforce:
    @pytest.mark.asyncio
    async def test_off_is_noop(self) -> None:
        client = _FakeClient(strict_tags=False, tag_batches=[set()])
        assert await enforce_strict_tags(client, ["anything"], tool="t") is None
        assert client.calls == 0  # never consults the account when off

    @pytest.mark.asyncio
    async def test_empty_request_is_noop(self) -> None:
        client = _FakeClient(strict_tags=True, tag_batches=[{"work"}])
        assert await enforce_strict_tags(client, [], tool="t") is None
        assert client.calls == 0

    @pytest.mark.asyncio
    async def test_existing_tag_allowed(self) -> None:
        client = _FakeClient(strict_tags=True, tag_batches=[{"work", "personal"}])
        assert await enforce_strict_tags(client, ["work"], tool="t") is None

    @pytest.mark.asyncio
    async def test_unknown_tag_rejected(self) -> None:
        client = _FakeClient(strict_tags=True, tag_batches=[{"work"}, {"work"}])
        err = await enforce_strict_tags(client, ["nope"], tool="add_task_tags")
        assert err is not None
        assert err["rejected_tags"] == ["nope"]
        assert err["strict_tag_mode"] is True
        # Cache-miss safety: it re-fetched once before failing.
        assert client.calls == 2

    @pytest.mark.asyncio
    async def test_live_refetch_resolves_stale_cache(self) -> None:
        # First batch is stale (missing the tag); the force-refresh reveals it.
        client = _FakeClient(strict_tags=True, tag_batches=[{"work"}, {"work", "justmade"}])
        assert await enforce_strict_tags(client, ["justmade"], tool="t") is None
        assert client.calls == 2
