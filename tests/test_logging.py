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
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rtm_mcp.list_targets import enforce_list_target
from rtm_mcp.note_shape import enforce_note_shape
from rtm_mcp.server import (
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_LEVEL,
    LOG_BACKUP_COUNT,
    LOG_FILE_NAME,
    LOG_MAX_BYTES,
    configure_logging,
    resolve_log_dir,
)
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
        """Two handlers since v5.1.0 — stderr plus the file sink — and still exactly two after a
        second call. A `FileHandler` holds an open descriptor, so stacking would leak one per
        call as well as duplicating every record."""
        monkeypatch.delenv("RTM_LOG_LEVEL", raising=False)
        first = configure_logging()
        second = configure_logging()
        try:
            assert first is second
            assert len(second.handlers) == 2
            assert sum(isinstance(h, RotatingFileHandler) for h in second.handlers) == 1
        finally:
            for h in list(second.handlers):
                second.removeHandler(h)
                h.close()
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


#: Fires a REAL write gate in a child process, then reports on stdout whether it rejected.
#: Deliberately a gate rather than a bare `logger.warning`: the property under test is that the
#: server's own controls stay observable, and a gate is what the sink exists for.
_GATE_PROBE = """
from unittest.mock import MagicMock
from rtm_mcp.server import configure_logging
from rtm_mcp.note_shape import enforce_note_shape

configure_logging()
client = MagicMock(config=MagicMock(strict_notes="shape"))
rejected = enforce_note_shape(client, "a malformed title", "", tool="add_note")
print("REJECTED" if rejected is not None else "ALLOWED")
"""


def _run_probe(log_dir: str) -> subprocess.CompletedProcess:
    """Run the gate probe with **fd 2 redirected to /dev/null** — the Desktop-spawned reality.

    `stderr=DEVNULL` is the whole point: it reproduces the measured condition (`lsof` + `stat`
    on a Desktop-spawned server) in which the stderr handler writes into nothing. A test that
    captured stderr instead would pass against a server with no sink at all.
    """
    env = os.environ | {"RTM_LOG_DIR": log_dir}
    env.pop("RTM_LOG_LEVEL", None)
    return subprocess.run(
        [sys.executable, "-c", _GATE_PROBE],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=60,
        check=False,
    )


class TestTheSinkThatSurvivesDevNull:
    """The v5.1.0 sink, and the one property that justifies it.

    On a Desktop-spawned server **fd 2 is `/dev/null`**, so every gate WARNING was destroyed. In
    an interactive session that is redundant — the caller already gets a typed error — but in a
    headless flow the error goes to an *agent*, which handles or retries it, and Paul never
    learns it happened. These tests therefore run the gate in a child process with fd 2 actually
    redirected, because an in-process test asserting "the record was emitted" passes today and
    proves nothing about the case that motivated the change.
    """

    def test_a_gate_warning_reaches_the_file_when_stderr_is_devnull(self, tmp_path):
        """THE test. Without the file sink this cannot pass — see the counterfactual below."""
        log_dir = tmp_path / "logs"
        probe = _run_probe(str(log_dir))

        assert probe.returncode == 0, "the server must start with the sink configured"
        assert "REJECTED" in probe.stdout, "the gate did not fire — the test proved nothing"

        written = (log_dir / LOG_FILE_NAME).read_text(encoding="utf-8")
        assert "strict_notes(shape)" in written
        assert "REJECTED" in written
        assert "a malformed title" in written, "the offending title must be in the record"

    def test_without_the_sink_the_gate_fires_and_leaves_no_trace(self, tmp_path):
        """The counterfactual, run mechanically rather than asserted in prose.

        Point the sink at an unopenable path so no file handler is attached, and the child is
        exactly the pre-v5.1.0 server: the gate still fires, still rejects, still logs — and the
        record goes nowhere, because the only handler left writes to `/dev/null`. That is the
        blindness this change removes, and it is why the test above is not decoration.
        """
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        probe = _run_probe(str(blocker / "logs"))

        assert probe.returncode == 0, "an unopenable sink must never stop the server"
        assert "REJECTED" in probe.stdout, "the gate must still enforce with no sink"
        assert not (blocker / "logs").exists()

    def test_the_stderr_handler_is_still_attached(self, configured):
        """Additive, never a replacement — a terminal-launched server must behave as before."""
        streams = [getattr(h, "stream", None) for h in configured.handlers]
        assert sys.stderr in streams or sys.__stderr__ in streams

    def test_the_sink_honours_RTM_LOG_LEVEL(self, monkeypatch, tmp_path):
        """The level lives on the tree and both handlers sit at NOTSET, so one env var governs
        both channels. If the file handler carried its own level they could disagree, and the
        surviving channel would be the one nobody configured."""
        monkeypatch.setenv("RTM_LOG_DIR", str(tmp_path))
        monkeypatch.setenv("RTM_LOG_LEVEL", "DEBUG")
        tree = configure_logging()
        try:
            logging.getLogger("rtm_mcp.probe").debug("debug reaches the file too")
            for h in tree.handlers:
                h.flush()
            assert "debug reaches the file too" in (tmp_path / LOG_FILE_NAME).read_text()
        finally:
            for h in list(tree.handlers):
                tree.removeHandler(h)
                h.close()
            tree.setLevel(logging.NOTSET)

    def test_rotation_is_bounded(self, monkeypatch, tmp_path):
        """A sink an operator has to prune is one that eventually gets deleted. Driven with a
        tiny cap so rollover actually happens — the shipped 1 MiB would need a huge test."""
        monkeypatch.setenv("RTM_LOG_DIR", str(tmp_path))
        monkeypatch.delenv("RTM_LOG_LEVEL", raising=False)
        monkeypatch.setattr("rtm_mcp.server.LOG_MAX_BYTES", 512)
        tree = configure_logging()
        try:
            for i in range(400):
                logging.getLogger("rtm_mcp.probe").warning("filler record %03d", i)
            for h in tree.handlers:
                h.flush()
        finally:
            for h in list(tree.handlers):
                tree.removeHandler(h)
                h.close()
            tree.setLevel(logging.NOTSET)

        files = sorted(tmp_path.glob(f"{LOG_FILE_NAME}*"))
        assert 1 < len(files) <= LOG_BACKUP_COUNT + 1, "rollover must happen AND stay bounded"

    def test_the_bounds_are_the_shipped_ones(self, configured):
        handler = next(h for h in configured.handlers if isinstance(h, RotatingFileHandler))
        assert (handler.maxBytes, handler.backupCount) == (LOG_MAX_BYTES, LOG_BACKUP_COUNT)

    def test_an_unopenable_sink_says_so_rather_than_failing_silently(
        self, monkeypatch, tmp_path, caplog
    ):
        """Applies § 7a's own level rule to the sink's failure: a silent fallback to stderr
        recreates the exact blindness being fixed, so the degradation is announced at WARNING.

        Observed via `caplog` rather than a handler attached to the tree — `configure_logging`
        removes every existing handler before it runs, so a probe installed beforehand is gone
        by the time the record fires. (Learned the hard way; left here so the next author does
        not repeat it.)
        """
        blocker = tmp_path / "not-a-directory"
        blocker.write_text("", encoding="utf-8")
        monkeypatch.setenv("RTM_LOG_DIR", str(blocker / "logs"))
        monkeypatch.delenv("RTM_LOG_LEVEL", raising=False)

        tree = configure_logging()
        try:
            assert not any(isinstance(h, RotatingFileHandler) for h in tree.handlers)
            assert len(tree.handlers) == 1, "stderr must survive the sink's failure"
        finally:
            for h in list(tree.handlers):
                tree.removeHandler(h)
                h.close()
            tree.setLevel(logging.NOTSET)

        assert any(
            r.levelno == logging.WARNING and "log file sink unavailable" in r.getMessage()
            for r in caplog.records
        )

    def test_the_default_location_is_config_state_not_the_repo_clone(self, monkeypatch):
        """The launch config runs `uv run --project <clone>`, so the process CAN write to the
        working tree. Logs there would mean .gitignore maintenance, `git status` noise, and a
        real chance of committing them — so the sink is a sibling of config.json instead."""
        monkeypatch.delenv("RTM_LOG_DIR", raising=False)
        assert resolve_log_dir() == DEFAULT_LOG_DIR
        assert Path.home() / ".config" / "rtm-mcp" / "logs" == DEFAULT_LOG_DIR

        repo_root = Path(__file__).resolve().parents[1]
        assert repo_root not in DEFAULT_LOG_DIR.parents

    def test_the_location_is_overridable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("RTM_LOG_DIR", f"  {tmp_path}  ")
        assert resolve_log_dir() == tmp_path

    def test_a_blank_override_falls_back_rather_than_writing_to_cwd(self, monkeypatch):
        """`Path("")` is `.` — an empty env var would silently put the sink in whatever
        directory the server happened to start in."""
        monkeypatch.setenv("RTM_LOG_DIR", "   ")
        assert resolve_log_dir() == DEFAULT_LOG_DIR


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
