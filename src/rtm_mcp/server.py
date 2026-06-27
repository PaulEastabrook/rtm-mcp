"""RTM MCP Server - Main entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from .client import RTMClient
from .config import RTMConfig
from .exceptions import RTMAuthError
from .tools import (
    register_gtd_tools,
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
        print("RTM not configured. Run: rtm-setup")
        print("Or set environment variables: RTM_API_KEY, RTM_SHARED_SECRET, RTM_AUTH_TOKEN")
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
RTM MCP Server - Remember The Milk task management for Claude.

This product uses the Remember The Milk API but is not endorsed or certified by Remember The Milk.

This server provides full access to Remember The Milk's task management features:

## Task Operations
- list_tasks: List tasks with filters (due date, tags, priority, list)
- add_task: Create tasks with Smart Add syntax (^date !priority #tags)
- complete_task / uncomplete_task: Mark tasks done or reopen
- delete_task: Remove tasks
- postpone_task: Push due date by one day
- set_task_*: Modify name, due date, priority, recurrence, estimate, URL
- move_task_priority: Shift priority up/down by one level
- set_parent_task: Move a task under a parent or promote to top-level

## Tag Operations
- add_task_tags / remove_task_tags: Incremental tag changes
- set_task_tags: Replace all tags on a task in one call
- get_tags: List all tags in use

## Note Operations
- add_note / edit_note / delete_note: Manage task notes
- get_task_notes: View all notes on a task

## List Operations
- get_lists: List all task lists
- add_list / rename_list / delete_list: Manage lists
- archive_list / unarchive_list: Archive management

## URL Tools
- get_task_url: Get RTM web UI URL for a task (includes full hierarchy path)
- get_list_url: Get RTM web UI URL for a list

## Utilities
- test_connection: Verify API connectivity
- check_auth: Verify authentication
- get_settings: View user preferences
- undo: Undo previous operation using transaction_id
- batch_undo: Undo multiple operations in reverse order
- get_timeline_info: View session timeline and transaction history
- get_rate_limit_status: View rate limiter status and request statistics

## GTD Tools (domain compositions, gtd_ prefix)
- gtd_project_plan: Read-only — returns a whole project plan (project + all
  descendant items + every note, full bodies) as the project-plan-seed envelope
  consumed by the GTD canvas, in one getList (plus a session-cached settings read
  so dates are shown in the account timezone). Identify by project_id or project_name.
- gtd_project_canvas: Read-only — the read-sibling of gtd_project_plan. Returns the
  canvas-ready seed ({mode, frame, seed}) with the deterministic plan-graph overlay
  applied (quick, sibling deps, dependency-respecting order). Each row also carries an
  optional prog ("now"/"later", from the #ai_progress_requested / #ai_progress_deferred
  tags) so the execute pill reflects committed state on reload. File objects (per-action
  and project-level frame.files) carry a meta block from the artefact's companion
  metadata when a read-only AI Memory vault is configured (RTM_VAULT_ROOT / AI_MEMORY_DIR
  or the host default); absent vault or companion → no meta. Identify by project_id
  or project_name.
- gtd_project_index: Read-only — the active-project portfolio for the canvas navigator (Phase C
  cockpit). Returns an object {projects, foci, actions}, all three sourced from one rtm.tasks.getList
  (plus the session-cached settings read for the tz); no write, no timeline. projects: one row per
  #project (incomplete, not #test; #hold always excluded, #someday excluded unless
  include_someday=True) carrying life, the parent Area-of-Focus (focus/focus_id), priority,
  open_count, blocked_count (children blocked by an open DEPENDS-ON upstream, via the thin
  plan-graph), next_tickle (earliest open due, incl. overdue) and updated. foci: every #focus area
  (same gate) as {focus_id, focus, life}, including foci with no active projects. actions: every
  incomplete child under an active project (not #test) as {action_id, name, project_id, project,
  focus, life, due, priority, blocked} for cockpit search/jump-to and the What's-hot band (due
  localised or "", priority "1"|"2"|"3"|"", blocked per the thin plan-graph). Backward-compatible
  for the navigator (reads data.projects).
- gtd_apply_canvas_commit: Constrained write — the single governed write surface for a
  project-plan-canvas commit (adds/edits/completes/removes/execute/notes). execute is a
  durable now/later split: now/quick → #ai_progress_requested; later →
  #ai_progress_deferred (switching state drops the stale sibling so an item never carries
  both). Validates the whole commit up-front (cross-project, strict-tag gate,
  Processed/non-smart list, destructive-confirm) and writes nothing if rejected; applies
  durable-first. On any successful commit it also stamps #ai_overlay_refresh_needed on the
  project (the gtd-side finalise engine drains it to refresh the persisted plan-graph overlay);
  that tag must exist in the account under strict-tag mode. Identify the project by project_id.
- gtd_create_project: Constrained write — the create-sibling of gtd_apply_canvas_commit:
  builds a NEW project from a canvas draft (frame {life, focus, name, outcome} + items[]),
  creating the project task under the resolved Area of Focus and its child items parented in
  dependency order, with tags/priorities/dates/estimates, DEPENDS-ON notes (in-draft deps →
  new RTM ids), execute progression signals, create-then-complete for already-done items, an
  INCEPTION note, and the #ai_project_needs_finalise mark (must exist in the account under
  strict-tag mode). Validates up-front (strict-tag gate, item types/execute/deps) and writes
  nothing if rejected. Identify the destination area by frame.focus (name or area task id;
  ambiguous name → candidates).

## Tool naming convention
- Bare verbs (add_task, list_tasks, get_task_notes) are generic RTM primitives,
  mapping 1:1 to an RTM API method.
- A `gtd_` prefix marks a GTD-shaped composition (a view over RTM data, not an RTM
  primitive). New domain compositions follow `<domain>_<concept-noun>`.

## Behavior Notes
- Default list: add_task WITHOUT a list_name routes to the user's configured
  default list (RTM Settings > General > Default List, also exposed as
  get_settings.default_list_id) — NOT the built-in "Inbox". RTM's raw API would
  use the built-in Inbox; this server resolves the user's default instead. Pass
  list_name to target a specific list. Falls back to the built-in Inbox only if
  no default is configured.
- Smart lists are read-only: get_lists reports "smart": true for smart lists
  (saved-search views). You cannot add_task or move_task into a smart list —
  use a regular (smart=false) list. The "locked" flag marks system lists
  (e.g. Inbox, Sent) that cannot be renamed or deleted.
- Strict-tag mode (ON by default; set env RTM_STRICT_TAGS=0 to disable): the
  server refuses to apply a tag that does not already exist in the account —
  add_task (SmartAdd #tokens), add_task_tags, and set_task_tags reject unknown
  tags with a guided error (remove_task_tags is never blocked). Call get_tags to
  see the existing set; a genuinely new tag must be created out-of-band in RTM
  first. This stops accidental tag creation via the MCP.

## Smart Add Syntax
When adding tasks, use Smart Add for quick entry:
- ^date: Due date (^tomorrow, ^next friday, ^dec 25)
- !priority: Priority level (!1 high, !2 medium, !3 low)
- #tag: Add tags (#work, #urgent)
- @location: Set location
- =estimate: Time estimate (=30min, =1h)
- *repeat: Recurrence (*daily, *every monday)

Example: "Call mom ^tomorrow !1 #family"
""",
    lifespan=lifespan,
)

# Register all tools
register_task_tools(mcp, get_client)
register_list_tools(mcp, get_client)
register_note_tools(mcp, get_client)
register_utility_tools(mcp, get_client)
register_gtd_tools(mcp, get_client)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
