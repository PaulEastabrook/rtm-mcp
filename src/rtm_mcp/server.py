"""RTM MCP Server - Main entry point."""

import inspect
import logging
import logging.handlers
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

from .client import RTMClient
from .config import RTMConfig
from .exceptions import RTMAuthError
from .middleware import RejectUnknownParameters
from .tools import (
    register_gtd_tools,
    register_help_tools,
    register_list_tools,
    register_note_tools,
    register_task_tools,
    register_utility_tools,
)

# Global client instance
_client: RTMClient | None = None


@asynccontextmanager
async def lifespan(mcp: FastMCP) -> AsyncIterator[None]:
    """Manage server lifecycle - initialize and cleanup client."""
    global _client

    # Load config and create client
    config = RTMConfig.load()

    if not config.is_configured():
        # stderr: under the stdio transport stdout carries JSON-RPC frames, so a bare
        # print() there would corrupt the protocol stream.
        print("RTM not configured. Run: rtm-setup", file=sys.stderr)
        print(
            "Or set environment variables: RTM_API_KEY, RTM_SHARED_SECRET, RTM_AUTH_TOKEN",
            file=sys.stderr,
        )
    else:
        _client = RTMClient(config)

    try:
        yield
    finally:
        if _client:
            await _client.close()


async def get_client() -> RTMClient:
    """Get the RTM client instance.

    Raises RTMAuthError if not configured.
    """
    if _client is None:
        raise RTMAuthError("RTM not configured. Run: rtm-setup")
    return _client


# Create FastMCP server
mcp = FastMCP(
    name="rtm-mcp",
    instructions="""
RTM MCP Server — Remember The Milk task management, plus a GTD domain layer over it.

Two tool families. Pick the family first, then the tool.

**Generic RTM primitives** (44, bare verbs) map close to one RTM method each: `list_tasks`,
`add_task`, `complete_task`, `delete_task`, `move_task`, the `set_task_*` setters,
`set_parent_task`, notes (`add_note`, `edit_note`), lists (`get_lists`, `add_list`), tags
(`add_task_tags`, `set_task_tags`), and utilities (`undo`, `batch_undo`, `parse_time`).
Keywords: task, to-do, reminder, due date, priority, tag, list, note, recurrence, RTM.

**GTD domain compositions** (55, `gtd_` prefix) speak Getting Things Done rather than
mapping 1:1 to an API method: inbox and capture (`gtd_inbox_*`), projects and plans
(`gtd_project_*`, `gtd_canvas_commit`), items (`gtd_item_*`), next actions and today
(`gtd_next_actions`, `gtd_item_today`), reviews and hygiene reports (`gtd_*_report`,
`gtd_*_candidates`), the engage sweep (`gtd_engage_*`), conversations (`gtd_chat_*`), and
the AI surface (`gtd_surface_*`).
Keywords: GTD, next action, inbox, clarify, weekly review, project plan, waiting for, area
of focus, someday, engage, blocked, canvas.

**Start with `rtm_tool_help()`.** No argument returns the whole-server index — one purpose
line per tool, the cheap "which tool?" answer. A tool name returns that tool's full
contract: combination rules the schema cannot express, worked examples, every return case,
the typed-error catalogue with recovery, and which tools feed it.

Writes carry a `transaction_id`; `undo` / `batch_undo` reverse them. Destructive tools
require `confirm_destructive=True`. An undefined parameter is rejected, nothing written.

**Every `gtd_` write returns a receipt.** `applied[]` is what was written; `not_applied[]`
is what you asked for that was NOT, with a reason. Check `not_applied[]` before reporting
success — a write can succeed while doing less than you asked.

This product uses the Remember The Milk API but is not endorsed or certified by Remember
The Milk.
""",
    lifespan=lifespan,
)

# An unknown parameter is rejected at the call boundary rather than silently discarded.
# One middleware covers every tool in every module and cannot drift as tools are added —
# see `middleware.py` for why this rejects rather than warns.
mcp.add_middleware(RejectUnknownParameters(mcp))


# Register all tools
class _FullDocstringMCP:
    """Registration shim that advertises each tool's COMPLETE docstring.

    FastMCP 3.x parses a Google-style docstring with `griffe` and keeps only the **first
    text section** as the tool description (`utilities/docstring_parsing.py`); everything
    from `Args:` onwards — `Returns:`, the `Caveat`/`Examples` blocks — is parsed into
    other section kinds and then discarded. Measured on this server at the 2.x -> 3.x
    migration: **60,081 authored docstring characters became 34,854 — 42% lost.**

    The dropped material is the part a model most needs: `list_tasks`' RTM search-operator
    table and its "API order is NOT user-visible order" caveat, `add_task`'s Smart Add
    syntax, every gtd tool's governance contract.

    Passing `description=` explicitly overrides the truncation while FastMCP still lifts
    `Args:` into per-parameter descriptions — so this shim gets both. Applied at the single
    registration point below rather than at 56 call sites; never overrides a `description=`
    a tool passes deliberately.

    On fastmcp 2.x (where this server ran until v1.35.0) the whole docstring was advertised
    natively and no shim was needed. Ported from meistertask-mcp v0.4.0. Revisit if FastMCP
    changes this.
    """

    def __init__(self, inner: FastMCP) -> None:
        self._inner = inner

    def tool(self, *args, **kwargs):
        def decorator(fn):
            # Fresh mapping rather than mutating the closed-over kwargs, so one decorator
            # object applied twice cannot leak the first function's docstring onto the second.
            options = dict(kwargs)
            if "description" not in options:
                doc = inspect.getdoc(fn)
                if doc:
                    options["description"] = doc
            return self._inner.tool(*args, **options)(fn)

        return decorator

    def __getattr__(self, name):
        return getattr(self._inner, name)


_registrar = _FullDocstringMCP(mcp)

register_task_tools(_registrar, get_client)
register_list_tools(_registrar, get_client)
register_note_tools(_registrar, get_client)
register_utility_tools(_registrar, get_client)
register_gtd_tools(_registrar, get_client)
register_help_tools(_registrar, get_client)


#: Default level for the `rtm_mcp` logger tree. Overridable with RTM_LOG_LEVEL.
DEFAULT_LOG_LEVEL = "INFO"

#: The surviving sink's default home — a sibling of the server's existing state
#: (`~/.config/rtm-mcp/config.json`), reusing the `Path.home()/".config"/"rtm-mcp"` idiom
#: `config.py` already establishes. Deliberately NOT the repo clone: the launch config is
#: `uv run --project "$HOME/Documents/Code/rtm-mcp"`, so the process *could* write there, but
#: logs inside a git working tree mean `.gitignore` maintenance, `git status` noise, and a real
#: chance of committing them.
DEFAULT_LOG_DIR = Path.home() / ".config" / "rtm-mcp" / "logs"
LOG_FILE_NAME = "rtm-mcp.log"
#: Bounded rotation — 1 MiB per file plus 3 rollovers, a ~4 MiB ceiling that needs no
#: housekeeping. A sink an operator has to prune is a sink that eventually gets deleted.
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 3


def resolve_log_dir() -> Path:
    """Where the file sink writes. `RTM_LOG_DIR` overrides `DEFAULT_LOG_DIR`.

    Read from the environment directly rather than from `RTMConfig`, following the
    `RTM_LOG_LEVEL` precedent: logging is configured in `main()` *before* the config loads, and
    must stay working when that load fails — which is exactly when its records matter most.
    """
    override = (os.getenv("RTM_LOG_DIR") or "").strip()
    return Path(override).expanduser() if override else DEFAULT_LOG_DIR


def _build_file_handler(formatter: logging.Formatter) -> logging.Handler | None:
    """The rotating file handler, or None if the sink cannot be opened.

    Opened **eagerly** (not `delay=True`): a deferred open would move the failure to the first
    emit, inside logging's own error handling, which is where records go to die quietly. Failing
    here means the stderr handler — already attached — can report it.

    A sink that cannot be opened must never stop the server: the file is an *additional* channel,
    and refusing to start because a log directory is unwritable would turn an observability
    improvement into an outage.
    """
    try:
        log_dir = resolve_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / LOG_FILE_NAME,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setFormatter(formatter)
    return handler


def configure_logging(level: str | None = None) -> logging.Logger:
    """Configure the `rtm_mcp` logger tree — the thing whose absence made v3.0.0's records vanish.

    Until v3.0.1 this repo had NO logging configuration anywhere. Python's root logger defaults to
    WARNING and, with no handler, the `lastResort` fallback emits WARNING-and-above to stderr —
    so every INFO and DEBUG record the server produced was discarded before reaching a handler.
    Six of nine log statements were silent, including all three write-boundary gates and both
    deprecated-alias records. The alias record is Wave 3b's removal gate, so the gate was an
    instrument incapable of recording the thing it gates.

    **The handler MUST write to stderr.** This is a stdio MCP server: stdout carries the JSON-RPC
    protocol stream, and a handler on stdout corrupts it and breaks the server.
    `logging.StreamHandler()` defaults to stderr, which is why it is called with no argument here
    — do not pass `sys.stdout`. `tests/test_logging.py` asserts no handler is on stdout.

    **…and stderr is not enough, which is why there is also a file sink (v5.1.0).** On a
    Desktop-spawned server **fd 2 is `/dev/null`** (measured with `lsof` + `stat`), so every record
    the stderr handler writes is destroyed. That is not a nuisance: in a headless flow — a
    scheduled worker draining a work-list at 06:45 — a write-gate rejection returns a typed error
    to *an agent*, which handles or retries it, and Paul never learns it happened. The log was the
    only human-facing channel for those runs, and it was pointed at nothing.

    So a bounded `RotatingFileHandler` under `~/.config/rtm-mcp/logs/` is attached **alongside**
    the stderr handler, never instead of it — a terminal-launched server behaves exactly as before.
    The stderr handler is attached FIRST so that if the sink cannot be opened, the complaint has
    somewhere to go. Both handlers sit at `NOTSET`, so the tree's level (and therefore
    `RTM_LOG_LEVEL`) governs both.

    Scoped to the `rtm_mcp` tree rather than the root logger, so importing this package as a
    library never hijacks the host application's logging. Propagation is left ON so pytest's
    `caplog` still sees records; `lastResort` does not double-emit, because it fires only when no
    handler is found anywhere in the chain.

    Idempotent: calling it twice replaces the handlers rather than stacking duplicates, and
    **closes** the ones it removes — a `FileHandler` holds an open descriptor, so replacing without
    closing would leak one per call.
    """
    resolved = (level or os.getenv("RTM_LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()
    numeric = getattr(logging, resolved, None)
    if not isinstance(numeric, int):
        numeric = logging.INFO

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stream_handler = logging.StreamHandler()  # stderr — NEVER stdout, see the docstring
    stream_handler.setFormatter(formatter)

    tree = logging.getLogger("rtm_mcp")
    for existing in list(tree.handlers):
        tree.removeHandler(existing)
        existing.close()
    tree.addHandler(stream_handler)
    tree.setLevel(numeric)

    file_handler = _build_file_handler(formatter)
    if file_handler is not None:
        tree.addHandler(file_handler)
    else:
        # Reported through the handler that IS attached. WARNING, so it survives with no
        # configuration at all — the level rule in CONTRIBUTING § 7a, applied to the sink's
        # own failure: a silent fallback here would recreate the exact blindness being fixed.
        tree.warning(
            "log file sink unavailable at %s — records survive only on stderr, which is "
            "/dev/null under a Desktop-spawned server. Set RTM_LOG_DIR to a writable path.",
            resolve_log_dir(),
        )
    return tree


def main() -> None:
    """Run the MCP server."""
    configure_logging()
    mcp.run()


if __name__ == "__main__":
    main()
