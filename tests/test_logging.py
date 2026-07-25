"""Tests that the server's operational records actually EMIT.

**Every assertion here is on an emitted record, never on the source.** A test that checked the
call site existed — or grepped for the message string — would have passed against v3.0.0, a server
in which six of nine log statements reached no handler at all. That is precisely the bug's shape,
and it is why these tests capture stderr and inspect handlers rather than reading code.

The records under test are the ones whose ONLY output is the record: the three write-boundary
gates and the two deprecated-alias surfaces. If they do not emit, the control is unobservable and
its absence is indistinguishable from a clean estate.
"""

import logging
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from rtm_mcp.list_targets import enforce_list_target
from rtm_mcp.note_shape import enforce_note_shape
from rtm_mcp.server import DEFAULT_LOG_LEVEL, configure_logging
from rtm_mcp.strict_tags import enforce_strict_tags


class _FakeMCP:
    """Mirrors the FakeMCP in test_gtd_tools.py — the alias records live inside the gtd
    registration, so they need the tools registered to be exercised."""

    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self, *_args, **kwargs):
        def decorator(fn):
            self.tools[kwargs.get("name") or fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture
def gtd_registry():
    from rtm_mcp.tools.gtd import register_gtd_tools

    client = AsyncMock()
    client.config = MagicMock(strict_tags=False)
    client.get_timezone = AsyncMock(return_value="Europe/London")
    client.record_transaction = MagicMock()
    mcp = _FakeMCP()

    async def get_client():
        return client

    register_gtd_tools(mcp, get_client)
    return mcp.tools, client


@pytest.fixture
def configured(monkeypatch):
    """The server's own configuration, applied as `main()` applies it, then torn down.

    **Assertions below use `caplog` WITHOUT `set_level`/`at_level`, and that is deliberate.**
    caplog attaches its handler at the root logger, so a test that also *set* the level would
    pass against the broken v3.0.0 code — it would be configuring the very thing under test.
    Relying on the level this fixture's `configure_logging()` call sets means an INFO
    record reaches caplog only if the server really configured the tree, which is the property
    being tested.
    """
    monkeypatch.delenv("RTM_LOG_LEVEL", raising=False)
    tree = configure_logging()
    yield tree
    for h in list(tree.handlers):
        tree.removeHandler(h)
    tree.setLevel(logging.NOTSET)


class TestTheConfigurationItself:
    def test_stderr_only__stdout_carries_the_protocol(self, configured):
        """A stdio MCP server's stdout is the JSON-RPC stream. A handler there corrupts it and
        breaks the server outright — cheap test, total failure mode."""
        for handler in configured.handlers:
            stream = getattr(handler, "stream", None)
            assert stream is not sys.stdout, "a handler is writing to the protocol stream"
            assert stream is not sys.__stdout__

    def test_info_reaches_a_handler(self, configured, caplog):
        """The discriminating test: on v3.0.0 the effective level was WARNING (inherited from an
        unconfigured root), so this INFO record was dropped before any handler saw it."""
        logging.getLogger("rtm_mcp.probe").info("emission probe %s", 1)
        assert "emission probe 1" in caplog.text

    def test_a_record_actually_reaches_stderr(self, monkeypatch, capsys):
        """End-to-end, and the one test that proves the STREAM rather than the pipeline. Built
        inline so the handler binds the stream pytest has already swapped."""
        monkeypatch.delenv("RTM_LOG_LEVEL", raising=False)
        tree = configure_logging()
        try:
            logging.getLogger("rtm_mcp.probe").warning("stderr probe")
            captured = capsys.readouterr()
            assert "stderr probe" in captured.err
            assert captured.out == "", "nothing may reach stdout — it carries the protocol"
        finally:
            for h in list(tree.handlers):
                tree.removeHandler(h)
            tree.setLevel(logging.NOTSET)

    def test_the_level_is_env_overridable(self, monkeypatch, caplog):
        monkeypatch.setenv("RTM_LOG_LEVEL", "DEBUG")
        tree = configure_logging()
        try:
            logging.getLogger("rtm_mcp.probe").debug("debug probe")
            assert "debug probe" in caplog.text
        finally:
            for h in list(tree.handlers):
                tree.removeHandler(h)
            tree.setLevel(logging.NOTSET)

    def test_an_unparseable_level_falls_back_rather_than_crashing_the_server(self, monkeypatch):
        monkeypatch.setenv("RTM_LOG_LEVEL", "LOUDER")
        tree = configure_logging()
        try:
            assert tree.level == logging.INFO
        finally:
            for h in list(tree.handlers):
                tree.removeHandler(h)
            tree.setLevel(logging.NOTSET)

    def test_calling_twice_does_not_stack_handlers(self, monkeypatch):
        monkeypatch.delenv("RTM_LOG_LEVEL", raising=False)
        first = configure_logging()
        second = configure_logging()
        try:
            assert len(second.handlers) == 1 and first is second
        finally:
            for h in list(second.handlers):
                second.removeHandler(h)
            second.setLevel(logging.NOTSET)

    def test_default_level_shows_info(self, configured):
        assert DEFAULT_LOG_LEVEL == "INFO" and configured.level == logging.INFO


class TestTheGatesEmit:
    """All three write-boundary gates were silent for their entire lives."""

    def test_strict_notes_shape_emits_AND_rejects(self, configured, caplog):
        client = MagicMock(config=MagicMock(strict_notes="shape"))
        result = enforce_note_shape(client, "a malformed title", "", tool="add_note")
        err = caplog.text
        assert result is not None, "shape mode must still reject"
        assert "strict_notes(shape)" in err
        assert "REJECTED" in err
        assert "a malformed title" in err

    def test_strict_notes_warn_emits_AND_allows(self, configured, caplog):
        """The v3.0.0 defect in full: `warn` did not block, and its only other effect was a
        record that could not emit — so the observe-before-enforce mode observed nothing. Both
        halves are pinned, because fixing one without the other still leaves it useless."""
        client = MagicMock(config=MagicMock(strict_notes="warn"))
        result = enforce_note_shape(client, "a malformed title", "", tool="add_note")
        err = caplog.text
        assert result is None, "warn mode must ALLOW the write"
        assert "strict_notes(warn)" in err, "warn mode must OBSERVABLY warn"
        assert "ALLOWED (observe-before-enforce)" in err

    def test_strict_notes_off_stays_silent_and_inert(self, configured, caplog):
        client = MagicMock(config=MagicMock(strict_notes="off"))
        assert enforce_note_shape(client, "a malformed title", "", tool="add_note") is None
        assert caplog.text == "", "the default mode must not chatter"

    def test_list_target_gate_emits(self, configured, caplog):
        client = MagicMock(config=MagicMock(strict_list_targets=True))
        # `resolved` is a resolve_list_id result: the parsed list dict sits under `list`.
        resolved = {"list": {"name": "Smart List", "smart": True, "locked": False}}
        result = enforce_list_target(client, resolved, "Smart List", tool="add_task")
        err = caplog.text
        assert result is not None
        assert "strict_list_targets rejected" in err and "Smart List" in err

    async def test_strict_tag_gate_emits(self, configured, caplog):
        client = AsyncMock()
        client.config = MagicMock(strict_tags=True)
        client.get_account_tags = AsyncMock(return_value={"work"})
        result = await enforce_strict_tags(client, ["not_a_real_tag"], tool="add_task_tags")
        err = caplog.text
        assert result is not None
        assert "strict_tag_mode rejected" in err and "not_a_real_tag" in err


# The two deprecated-alias emission tests lived here until v3.1.0, which removed the aliases.
# Their record is gone with them; `TestNoRecordIsLeftAtInfoByAccident` below still pins the level
# of the surviving gate records, which is the property that mattered.


class TestTheSilentControlFoundBySweep:
    async def test_an_empty_allow_list_from_a_fetch_failure_is_announced(self, configured, caplog):
        """A failed `rtm.tags.getList` cached an EMPTY allow-list, so the strict-tag gate rejected
        every tag write while telling the caller its tags did not exist — true of an empty set and
        wholly misleading about the cause. Found by the v3.0.1 sweep for controls whose failure
        produces no record at all."""
        from rtm_mcp.client import RTMClient
        from rtm_mcp.config import RTMConfig

        client = RTMClient(RTMConfig(api_key="k", shared_secret="s", auth_token="t"))
        client.call = AsyncMock(side_effect=RuntimeError("RTM unreachable"))
        try:
            tags = await client.get_account_tags()
        finally:
            await client.close()
        err = caplog.text
        assert tags == set()
        assert "the strict-tag allow-list is EMPTY" in err
        assert "not a tag-vocabulary problem" in err


class TestNoRecordIsLeftAtInfoByAccident:
    def test_the_five_records_are_warning_level(self):
        """Not a source grep for the message — a source check of the LEVEL, which is the property
        that decides whether configuration is required for the record to survive. Every one of
        these emits with no configuration at all via logging's lastResort."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "rtm_mcp"
        sites = {
            "strict_tags.py": "strict_tag_mode rejected",
            "list_targets.py": "strict_list_targets rejected",
            "note_shape.py": "strict_notes(%s)",
        }
        for rel, needle in sites.items():
            text = (root / rel).read_text()
            for m in re.finditer(r"logger\.(\w+)\(\s*\n?\s*[\"']([^\"']*)", text):
                if needle.split("(")[0] in m.group(2):
                    assert m.group(1) == "warning", f"{rel}: {needle!r} is at {m.group(1)}"
