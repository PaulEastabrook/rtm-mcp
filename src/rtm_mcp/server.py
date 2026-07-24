"""RTM MCP Server - Main entry point."""

import inspect
import sys
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
  tags) so the execute pill reflects committed state on reload, and redacted (bool, from
  the item's #redacted tag); frame.redacted is the project's own #redacted state (set/clear
  via gtd_set_redaction). File objects (per-action
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
  plan-graph), next_tickle (earliest open due, incl. overdue), updated, ai_quick/ai_now/ai_later
  (quick-win / progress-now / progress-later counts, mirroring gtd_project_canvas — the navigator's
  AI sort lens), chat_count/chat_review_count (incomplete #ai_chat / #ai_output_review_needed
  items — the navigator conversation chip + Conversations sort lens), and waiting_count (incomplete
  #waiting_for items — the Focus pill's waiting-for segment). foci: every #focus area
  (same gate) as {focus_id, focus, life, redacted (the area's #redacted state — collapses a whole
  focus to one "Redacted Area of Focus" row)}, including foci with no active projects. actions: every
  incomplete child under an active project (not #test) as {action_id, name, project_id, project,
  focus, life, type, due, priority, blocked, estimate, contexts, energy, exec, redacted} for cockpit
  search/jump-to, the What's-hot band, and the engage lens (type action|waiting_for|calendar per the
  canvas r.k, due localised or "", priority "1"|"2"|"3"|"", blocked per the thin plan-graph; the
  engage funnel fields estimate (minutes or null), contexts (action-context tags, may be []), energy
  (high|low|null), exec (quick|now|later|null — the execute classification behind the project ai_*
  tallies)). redacted on an action is server-derived and CASCADES (own #redacted OR a redacted
  project / focus); a shielded action carries no engage data (estimate/energy/exec null, contexts []).
  Project rows carry redacted from their own tag. Backward-compatible for the navigator (reads
  data.projects; the new action fields are additive).
- gtd_apply_canvas_commit: Constrained write — the single governed write surface for a
  project-plan-canvas commit (adds/edits/completes/removes/execute/notes). execute is a
  durable now/later split: now/quick → #ai_progress_requested; later →
  #ai_progress_deferred (switching state drops the stale sibling so an item never carries
  both); "off" clears the directive (removes any of #ai_progress_requested /
  #ai_progress_deferred / #ai_deferred_pending_unblock; idempotent, fires no engine).
  Validates the whole commit up-front (cross-project, strict-tag gate,
  Processed/non-smart list, destructive-confirm) and writes nothing if rejected; applies
  durable-first. An optional scope label ("instant"|"item"|"project"|"plan", default "plan")
  places the one per-commit audit note: instant/item on the referenced item, project on the
  project entity (distinctly titled), plan the project-level COMMIT note (an unknown value is
  rejected). The project-entity verbs are permitted — project_id itself is an accepted target for
  rename (edits.text), add-project-note (notes[project_id]), complete (completes) and delete
  (removes); the carve-out is project_id-only, covering edits/notes/completes/removes
  (execute/order stay child-only). On any successful commit it also stamps #ai_overlay_refresh_needed on the
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
- gtd_stamp_tokens: Constrained write — stamp durable template-child tokens (tmpl-child/1) on a
  repeating templated project's children so its dependencies survive recurrence. A bounded,
  idempotent back-fill: for each unstamped open child it writes a TMPL-CHILD note, and re-authors
  each active DEPENDS-ON note with the additive Template-child-id line (RTM copies the notes onto
  each new occurrence, so one stamp propagates forward). Keyed by project_id (must be is_repeating),
  or omit to sweep every active repeating project; dry_run previews without writing. One-off
  projects are never stamped; a second run is a no-op. Writes no tag (no strict-tag interaction).
- gtd_chat_post: Constrained write — post one turn of the in-board AI conversation surface
  (the CHAT note class) to a task and manage the worker's drain signal in one signed call. A
  "me" turn (Paul) stamps #ai_chat_requested + #ai_chat; an "ai" turn (the worker reply)
  removes #ai_chat_requested and leaves #ai_chat. The note is titled
  "YYYY-MM-DD HH:MM — CHAT — <role> — <scope>" (localised); a "me" turn's mode (discuss|act) is
  recorded as a body footer. Pass only task_id (series/list resolved internally from one
  getList). Tag adds pass the strict-tag gate — #ai_chat_requested / #ai_chat must exist in the
  account (provision once); a missing tag rejects with nothing written.
- gtd_chat_thread: Read-only — return just the CHAT turns for a task (the cheap poll path vs
  re-reading the whole canvas). One rtm.tasks.getList (spanning incomplete + completed, so a prior
  conversation stays viewable after the task is done); no write, no timeline. Returns
  {task_id, turns:[{note_id, role, scope, mode?, text, created, files, links}], requested} — turns
  oldest-first, non-CHAT notes excluded; `requested` is whether #ai_chat_requested is set (a
  "thinking…" state without a second call; naturally False for a completed task). Each turn carries
  server-derived attachments (always present, [] when none): files = [{path, label, note_id}] from
  OUTPUT notes' FILING: lines (vault-relative path verbatim — it equals a FILED:
  trailer echo, so clients should prefer files[] and suppress their own FILED: parse),
  time-correlated to the earliest ai turn created at-or-after the filing (a filing after the last
  ai turn attaches to nothing). An item target scans its own notes only; a #project target
  additionally scans the project's descendant tasks (children + grandchildren, completed included —
  a project's artefacts are filed against its child actions), each descendant-filed entry carrying
  extra provenance fields item_id/item_name (the descendant that filed it); the gate is the
  #project tag, not subtask presence — still one getList. links = [{url, label}] from
  "LINK: <url> — <label>" trailer lines
  in the turn's own text (trailer lines stay in `text`). `since` (ISO-8601) returns only later
  turns for incremental polling. Posting still requires an incomplete task (gtd_chat_post rejects a
  completed one with a read-only error).
- gtd_chat_inflight: Read-only — the conversation cockpit's cross-project live band: every incomplete
  item with an open CHAT thread (#ai_chat), across all lists/projects, in one rtm.tasks.getList (no
  write, no timeline, no settings read). Returns {items:[{task_id, name, scope (item|project), status
  (in_flight|awaiting_review|open), project_id, project_name, last_activity}], count}, sorted status →
  recency → name. status from tags (#ai_chat_requested→in_flight; else #ai_output_review_needed→
  awaiting_review; else open); project_id/name = nearest #project ancestor. Reads existing chat
  signals — no new tag, vault-free.
- gtd_set_redaction: Constrained write — mark or unmark a task's #redacted viewing curtain, the
  single governed surface the sandboxed board is given for redaction (it may not call the bare
  add_task_tags / remove_task_tags primitives). Resolves the task's triple by task_id from one
  rtm.tasks.getList (incomplete + completed, so done items redact too); redacted=true → addTags
  #redacted (strict-tag gated — #redacted must exist in the account); redacted=false → removeTags
  #redacted (never gated). Records the transaction (undoable) and writes a one-line REDACTION audit
  note on the item (no #ai_conversation — a viewing change, not an AI write). Pairs with the derived
  `redacted` field on gtd_project_canvas / gtd_project_index. A viewing-layer curtain, not a
  server-side vault.
- gtd_engage_seed: Read-only — the overdue + soft-parked set for the engage renegotiation sweep.
  One rtm.tasks.getList (status:incomplete) + the cached settings read; returns every incomplete
  dated item on-or-before today (NOT #test / #someday, all kinds) with server-derived flags: kind,
  has_deadline (= RTM has_due_time, a timed due = the GTD hard landscape), blocked (the thin
  plan-graph), postponed, the deterministic pre-triage `suggested` verdict, and redacted (+ the
  localised current_date). Curtain-not-vault: emits `redacted` but never suppresses a field.
- gtd_apply_engage_commit: Constrained write — the governed commit for an engage-sweep batch (gtd's
  Anti-Corruption Layer over the board's advisory askClaude). Accepts {items:[{id, verdict,
  date_phrase?, note?}]} and re-validates everything server-side (kind/has_deadline/blocked re-derived —
  client flags never trusted); dates resolve through parse_time (Europe/London, authoritative). Maps
  each legal verdict to its RTM write (next_actions/resurface → clear due; today/bump → set due;
  defer_start → set start; nudge → re-tickle; someday → #someday; to_calendar → #calendar_entry;
  draft → #ai_progress_requested; keep/do_now → no-op; drop → soft-delete), #ai_conversation on every
  write, someday/resurface signal the progression engine (#ai_overlay_refresh_needed on the nearest
  #project). An optional per-item `note` — a short PROGRESS steer (≤500 chars) — is consumed only by
  draft/do_now/nudge: sanitised (untrusted advisory data, never influences legality) and attached as a
  STEER note that shapes the AI first-pass; a malformed note is dropped with a per-item warning (the
  verdict write stands), and a repeat of the same steer is idempotent. HARD-FAIL: an off-enum /
  type-illegal / hallucinated-date / not-found item rejects the whole batch with nothing written. One
  undoable batch. No new tag.

### GTD Phase 0 reads (typed detectors + collection/context — all read-only)
Native typed ports of the hidden MilkScript detectors, plus new collection/context reads. Each
returns a compact GTD-shaped projection (typed rows with kind / priority / deep link) instead of a
raw list_tasks echo; all read-only (only rtm.tasks.getList + the cached settings read).
- gtd_reassessment_candidates: open #ai_contrib_drafted/#ai_prep_drafted contributions due for
  reassessment (port of reassessment-candidates.ms).
- gtd_unblock_candidates: actions that may now be unblockable across five source classes (deferred,
  overdue waiting-fors, active BLOCKER/DEPENDS-ON notes, stale speculative) — port of unblock-candidates.ms.
- gtd_decision_candidates / gtd_deliverable_candidates / gtd_research_candidates: incomplete actions
  whose names read as a decision / deliverable / research task (lexical ports; research defaults to a
  2-day horizon).
- gtd_calendar_prep_candidates: upcoming #calendar_entry items needing prep (port of calendar-prep-candidates.ms).
- gtd_capture_candidates: recent AI contributions whose artefacts may hold promotion candidates.
- gtd_topic_clusters: cross-project tag/person clusters (candidate emergent projects/themes).
- gtd_health_check: systemic health audit (stuck projects, missing tags, stale waiting-fors, dated actions).
- gtd_query: one GTD collection view — next actions by context, today's field, or a focus area's projects.
- gtd_inbox_state: the three Inbox_Stuff health signals (depth / unprocessed / awaiting-review) in one read.
- gtd_waiting_for_queue: the waiting-for chase queue with a >14-day staleness flag.
- gtd_context: the STATE-first note-reading-protocol bundle for one task (task + notes + siblings +
  ancestry) resolved by id or name.

### GTD Phase 1 writes (governed, additive — the everyday write path)
Four governed write tools that collapse the generic multi-call dance into one atomic call, with
validate-then-apply (a rejected write mutates NOTHING), true post-state (the real id triple, never
an echo), and the durable orchestration signal stamped atomically. They carry the Tier-1
shared-kernel promotion: the seven structural GTD vocabularies (life_context, kind, action_context,
energy, comms, MoSCoW priority, note_type) are now server-owned advisory enums.
- gtd_create_item: create ONE clarified action / waiting_for / calendar_entry under a parent — the
  server materialises the structural tags from typed facets (a calendar entry gets `action` +
  `calendar_entry`), sets the MoSCoW band, resolves the due phrase via parse_time, writes an
  optional CONTEXT note, and stamps `#ai_overlay_refresh_needed` on the nearest #project ancestor.
  Definition-of-Ready is HARD-GATED per kind.
- gtd_add_note: write a conforming journal note — the server builds the
  `YYYY-MM-DD [HH:MM] — TYPE — summary` title and validates body block order. Journalling types
  only; STATE gets its snapshot marker and is latest-wins (the prior STATE note is never deleted).
- gtd_capture: atomic Inbox_Stuff capture — task (verbatim, parse disabled) + SOURCE note +
  `#ai_conversation`. Staged RAW: no life-context/workflow-state tags (there is no tag parameter);
  `pre_analysis` adds an AI ANALYSIS note + `#ai_review`.
- gtd_transition_state: validated tag transition that stamps the orchestration signal atomically,
  so the caller no longer carries the remembered-fire responsibility. Guards the "exactly one per
  task" invariants over the RESULTING tag set.

### GTD Phase 2 writes (density, dependency, bulk)
- gtd_complete_action: DESTRUCTIVE — the dense completion. Writes the COMPLETION note (or an
  OUTCOME note for a #calendar_entry) BEFORE completing, resolves #ai_output_review_needed →
  #ai_output_approved, completes the task, writes a CASCADE note on the parent project, and stamps
  #ai_overlay_refresh_needed. RETURNS `fanout_events` (completed / waiting_for_resolved /
  calendar_entry_completed / decided) as DATA — those are gtd progression-fanout EVENT names, not
  RTM tags, and a server cannot invoke an agent. Undo via batch_undo.
- gtd_close_inbox_item: DESTRUCTIVE — closes the clarify loop: a COMPLETION note listing every
  derived item, then completes the source. The item is COMPLETED, never deleted (audit record).
  Refuses to close if a derived id cannot be resolved.
- gtd_set_properties: batch scalar edits in one call. Applies the SERIES GUARD — priority and
  estimate are taskseries-level in RTM, so the write collapses to one per series and is redirected
  to the nearest-active occurrence; divergent bands are surfaced, never silently picked.
- gtd_link_dependency: writes a conforming DEPENDS-ON note on the DEPENDENT task + stamps the
  overlay-refresh signal. The context.md mirror is a VAULT write and stays gtd-side (the membrane).
- gtd_batch_transition: DESTRUCTIVE — bulk state transition, ALL-OR-NOTHING, stamping the
  orchestration signal for every item. Closes the silent per-item fan-out gap the generic bulk tag
  path leaves.

### GTD Phase 3 writes (process ops — apply a REVIEWED verdict set)
All three APPLY a set the caller already reviewed and approved; they never fetch-and-decide.
DESTRUCTIVE, undoable via batch_undo. Whole-set validation first — one invalid item writes
NOTHING; a mid-apply API failure returns a resumable results/remaining split. The orchestration
signal is stamped ONCE per affected project, and fan-out EVENT names are returned as data, never
written as tags. Throughput (measured): RTM has NO multi-task write endpoint, so N items cost N
rate-limited calls; at most 50 items apply per call and the tail returns in `remaining`.
- gtd_inbox_zero: apply an approved Inbox_Stuff disposition set (verb: tag | move | complete |
  leave). Review with gtd_inbox_state.
- gtd_chase_sweep: apply an approved chase verdict set over waiting-fors (retickle needs new_due,
  resolved via parse_time before any write | convert_to_action swaps waiting_for→action AND clears
  the tickle | complete | leave). Review with gtd_waiting_for_queue.
- gtd_consolidate_apply: apply an approved consolidation move set (reparent | link_dependency |
  complete | promote). Review with gtd_topic_clusters.

### GTD Phase 4a writes (note family, note-edit, dependency-flip)
- gtd_attach_output: writes the OUTPUT note (with the line-anchored FILING: link the reader parses)
  on the action + appends the row to the project's OUTPUTS register. Single-note model (the
  validate-note.py / gtd_chat_thread shape), not the GMI two-note pair.
- gtd_attach_contribution: CONTRIB | CONTRIB-UPDATE | PREP | SOURCE-DRAFT note + the variant's tag
  (ai_contrib_drafted / ai_prep_drafted / ai_speculative). speculative needs #ai_speculative
  provisioned (D8).
- gtd_annotate_clarification: the Inbox_Stuff Processor's write — AI ANALYSIS note (+ optional
  CLARIFYING QUESTIONS block) + optional rename + #ai_review.
- gtd_edit_note: the ONLY mutate-in-place note verb, DELIBERATELY BOUNDED — replace_substring |
  replace_line | set_frontmatter_key | retitle (re-validates the title grammar). No free-form
  overwrite exists; the bounded op-set IS the safety property.
- gtd_link_dependency gains mode='resolve'|'obsolete' — flips an existing DEPENDS-ON note's
  Status: active → resolved|obsolete and appends `Resolved at: <date>` (default mode='create'
  unchanged).
NOTE: gtd_transition_state already accepts the #ai_* engine tags — the server existence-gates
tags rather than keeping a GTD-only allow-list, so item 2.5 needed no code change.

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


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
