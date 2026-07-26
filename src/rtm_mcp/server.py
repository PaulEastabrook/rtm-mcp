"""RTM MCP Server - Main entry point."""

import inspect
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
`add_task`, `complete_task`, `delete_task`, `postpone_task`, `move_task`, the `set_task_*`
setters, `set_parent_task`, notes (`add_note`, `edit_note`, `get_task_notes`), lists
(`get_lists`, `add_list`, `rename_list`), tags (`add_task_tags`, `set_task_tags`,
`get_tags`), deep links (`get_task_url`), and utilities (`undo`, `batch_undo`,
`parse_time`, `get_settings`, `test_connection`).
Keywords: task, to-do, reminder, due date, priority, tag, list, note, recurrence,
estimate, RTM.

**GTD domain compositions** (55, `gtd_` prefix) speak Getting Things Done rather than
mapping 1:1 to an API method: inbox and capture (`gtd_inbox_*`), projects and plans
(`gtd_project_*`, `gtd_canvas_commit`), items (`gtd_item_*`), next actions and today
(`gtd_next_actions`, `gtd_item_today`), waiting-fors, reviews and hygiene reports
(`gtd_*_report`, `gtd_*_candidates`), the engage sweep (`gtd_engage_*`), in-board
conversations (`gtd_chat_*`), and the AI surface (`gtd_surface_*`).
Keywords: GTD, next action, inbox, clarify, weekly review, project plan, waiting for, area
of focus, someday, engage, blocked, dependency, canvas.

**Start with `rtm_tool_help()`.** No argument returns the whole-server index — one purpose
line per tool, the cheap "which tool?" answer. A tool name returns that tool's full
contract: the combination rules the JSON schema cannot express, worked examples, every
return case, the typed-error catalogue with recovery, and which tools feed into it.

Writes carry a `transaction_id`; `undo` / `batch_undo` reverse them. Destructive tools
require `confirm_destructive=True`. A call carrying a parameter the tool does not define is
rejected with the accepted set named, and nothing written.

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

    Scoped to the `rtm_mcp` tree rather than the root logger, so importing this package as a
    library never hijacks the host application's logging. Propagation is left ON so pytest's
    `caplog` still sees records; `lastResort` does not double-emit, because it fires only when no
    handler is found anywhere in the chain.

    Idempotent: calling it twice replaces the handler rather than stacking duplicates.
    """
    resolved = (level or os.getenv("RTM_LOG_LEVEL") or DEFAULT_LOG_LEVEL).strip().upper()
    numeric = getattr(logging, resolved, None)
    if not isinstance(numeric, int):
        numeric = logging.INFO

    handler = logging.StreamHandler()  # stderr — NEVER stdout, see the docstring
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    tree = logging.getLogger("rtm_mcp")
    for existing in list(tree.handlers):
        tree.removeHandler(existing)
    tree.addHandler(handler)
    tree.setLevel(numeric)
    return tree


def main() -> None:
    """Run the MCP server."""
    configure_logging()
    mcp.run()


if __name__ == "__main__":
    main()
