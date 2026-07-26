"""Tool-schema contract: the model-facing MCP surface (the six-surface standard).

Introspects the REAL server (`rtm_mcp.server.mcp` — every tool registered at import) via
`list_tools()` → `to_mcp_tool()`, so these assertions pin what an MCP client actually sees:
every tool + parameter is described, behaviour annotations are correct per class, closed-vocabulary
params expose their enums (asserted EQUAL to the canonical constants, so they can never drift from
the handler), structured params are exposed, and every tool advertises an `outputSchema` whose
`data` is a `success | error` union. See CONTRIBUTING § 3 + § 8 and the family standard
(mcp-tool-documentation-standard.md § 4/§ 5).
"""

import importlib.util
import json
from pathlib import Path

from rtm_mcp.canvas_commit import COMMIT_REJECT_REASONS, VALID_EXECUTE_COMMIT, VALID_SCOPES
from rtm_mcp.canvas_create import CREATE_REJECT_REASONS
from rtm_mcp.engage_commit import ENGAGE_REJECT_REASONS, VERDICT_FAMILY
from rtm_mcp.gtd_chat import VALID_MODES, VALID_ROLES
from rtm_mcp.gtd_reads import VALID_DEPTHS
from rtm_mcp.gtd_writes import (
    ACTION_CONTEXTS,
    COMMS_MODES,
    ENERGY_LEVELS,
    GTD_WRITE_REJECT_REASONS,
    ITEM_KINDS,
    JOURNAL_NOTE_TYPES,
    LIFE_CONTEXTS,
    MOSCOW_BANDS,
)
from rtm_mcp.parsers import PRIORITY_INPUT_CODES
from rtm_mcp.server import mcp
from rtm_mcp.tools.tasks import MOVE_DIRECTIONS

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_fingerprint_script():
    """Load scripts/dump-tool-fingerprints.py by path (its name is not import-safe) so the freshness
    test shares the EXACT fingerprint computation with the generator — one truth, no drift."""
    path = _REPO_ROOT / "scripts" / "dump-tool-fingerprints.py"
    spec = importlib.util.spec_from_file_location("_dump_tool_fingerprints", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Behaviour-class expectations (the source of truth for the annotation assertions).
READ_ONLY_TOOLS = {
    # The affordance help surface (v3.3.0) — read-only AND offline: pure introspection of
    # the server's own advertised schema, so it reaches RTM not at all.
    "rtm_tool_help",
    "list_tasks",
    "get_lists",
    "get_tags",
    "get_locations",
    "get_settings",
    "parse_time",
    "get_timeline_info",
    "get_contacts",
    "get_groups",
    "get_rate_limit_status",
    "get_task_url",
    "get_list_url",
    "test_connection",
    "check_auth",
    "get_task_notes",
    "gtd_project_plan",
    "gtd_project_canvas",
    "gtd_project_index",
    "gtd_chat_thread",
    "gtd_chat_inflight",
    "gtd_engage_seed",
    "gtd_reassessment_candidates",
    "gtd_unblock_candidates",
    "gtd_decision_candidates",
    "gtd_deliverable_candidates",
    "gtd_research_candidates",
    "gtd_calendar_prep_candidates",
    "gtd_capture_candidates",
    "gtd_cluster_candidates",
    "gtd_health_report",
    "gtd_inbox_state",
    "gtd_waiting_for_queue",
    "gtd_item_context",
    # Wave 1 — the eight MilkScript-retirement reads (v2.9.0).
    "gtd_surface_queue",
    "gtd_engine_report",
    "gtd_dependency_gaps",
    "gtd_tag_report",
    "gtd_review_report",
    "gtd_item_stale",
    "gtd_workload_report",
    "gtd_focus_index",
    # Wave 1b (v2.10.0) — offline, pure string matching; no RTM call at all.
    "gtd_item_shape",
    # v3.0.0 — the three tools gtd_query split into (gtd_query itself removed at v3.1.0).
    "gtd_item_today",
    "gtd_next_actions",
    "gtd_focus_projects",
}
DESTRUCTIVE_TOOLS = {
    "delete_task",
    "delete_list",
    "delete_note",
    "gtd_canvas_commit",
    "gtd_engage_commit",
    "gtd_item_complete",
    "gtd_inbox_item_close",
    "gtd_item_transition_batch",
    "gtd_inbox_drain",
    "gtd_waiting_for_sweep",
    "gtd_cluster_consolidate",
    "gtd_surface_resolve",
}


async def _tools() -> dict:
    """Name -> FunctionTool. Tolerates both FastMCP majors: 3.x exposes `list_tools()`
    returning a list; 2.x exposed `get_tools()` returning a name-keyed dict."""
    if hasattr(mcp, "list_tools"):
        return {t.name: t for t in await mcp.list_tools()}
    return await mcp.get_tools()  # pragma: no cover — FastMCP 2.x fallback


async def _schema(name: str) -> dict:
    return (await _tools())[name].to_mcp_tool().inputSchema or {}


async def _props(name: str) -> dict:
    return (await _schema(name)).get("properties") or {}


async def _annotations(name: str) -> dict:
    ann = (await _tools())[name].to_mcp_tool().annotations
    return {} if ann is None else {k: v for k, v in ann.model_dump().items() if v is not None}


def _find_model(schema: dict, title: str) -> dict:
    """Locate a named model's `properties` anywhere in an outputSchema.

    FastMCP 2.x left pydantic's `$defs` intact, so a nested model was one dict lookup away.
    3.x DEREFERENCES them — the model is inlined wherever it is used (inside a union variant,
    an array's `items`, a nested property). Content is identical; placement moved. This walks
    the tree for an object carrying the model's `title`, so the assertions below track the
    CONTRACT rather than the serialisation, and work on either major.
    """
    defs = schema.get("$defs") or {}
    if title in defs:  # FastMCP 2.x shape
        return defs[title]["properties"]

    found: dict | None = None

    def walk(node):
        nonlocal found
        if found is not None:
            return
        if isinstance(node, dict):
            if node.get("title") == title and isinstance(node.get("properties"), dict):
                found = node["properties"]
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    assert found is not None, f"no `{title}` model found in the advertised outputSchema"
    return found


class TestToolDescriptions:
    async def test_every_tool_has_a_rich_description(self):
        tools = await _tools()
        assert tools, "no tools registered"
        for name, tool in tools.items():
            desc = tool.to_mcp_tool().description or ""
            assert len(desc) > 50, f"{name}: description too thin ({len(desc)} chars)"

    async def test_every_parameter_carries_a_schema_description(self):
        tools = await _tools()
        offenders: list[str] = []
        for name, tool in tools.items():
            schema = tool.to_mcp_tool().inputSchema or {}
            for param, spec in (schema.get("properties") or {}).items():
                if param == "ctx":  # FastMCP-injected Context — not a real arg
                    continue
                if not spec.get("description"):
                    offenders.append(f"{name}.{param}")
        assert not offenders, (
            "these tool parameters have no schema description — add "
            f"Annotated[T, Field(description=...)] (or a coerced_*_schema): {offenders}"
        )


class TestSingleTypedParameters:
    """Optional params must advertise a SINGLE-TYPED schema, never a `T | None` union.

    A union serialises to `anyOf`, and MCP clients that simplify schemas before showing them to
    the model simplify that shape worst: measured against a live Claude Code session
    (2026-07-19), every `anyOf` param collapsed to a bare `{}` — losing its type, its description
    AND its enum. Flat params keep `type` / `default` / `enum`. This server had 110 such params
    across 32 tools.

    The complex/coercion params were already immune (`tool_params`'s `JsonStrArray` /
    `coerced_*_schema` exist for the same reason); this extends the same treatment to optional
    scalars via `optional_string` / `_integer` / `_number` / `_boolean`. The trap is that the
    *obvious* way to write an optional param — `Annotated[T | None, Field(...)]` — is the wrong
    one, so this guard is what stops the fix eroding.
    """

    # There are now ZERO union-advertising params. `set_task_priority.priority` was the last
    # one: annotated `str | int` (genuine — `parsers.priority_to_code` does
    # `str(priority).lower()`, so 1 and "1" and "high" all work), it advertised
    # `anyOf: [string, integer]` and so flattened to `{}` in simplifying clients, taking its
    # enum with it. Since v1.34.0 it advertises the STRING form via `tool_params.required_string`
    # — narrower than what the handler accepts, never wider, so every schema-conformant call
    # still works and the integer aliases keep working for existing callers.

    async def test_no_optional_param_advertises_a_union(self):
        tools = await _tools()
        offenders = [
            f"{name}.{param}"
            for name, tool in tools.items()
            for param, spec in (
                (tool.to_mcp_tool().inputSchema or {}).get("properties") or {}
            ).items()
            if param != "ctx" and ("anyOf" in spec or "oneOf" in spec)
        ]
        assert not offenders, (
            "these params advertise a union and will be flattened to `{}` by simplifying "
            "clients — use a tool_params.optional_* builder instead of Field(...) on the "
            f"`T | None` annotation: {offenders}"
        )

    async def test_the_priority_param_advertises_its_enum(self):
        """The concrete payoff of retiring the last union: `set_task_priority`'s only required
        param used to reach the model as `{}`. It must now carry type + enum."""
        spec = (await _props("set_task_priority"))["priority"]
        assert spec["type"] == "string"
        assert spec["enum"] == sorted(PRIORITY_INPUT_CODES)

    async def test_every_param_declares_a_type(self):
        """The payoff: a model can always see what to send."""
        tools = await _tools()
        offenders = [
            f"{name}.{param}"
            for name, tool in tools.items()
            for param, spec in (
                (tool.to_mcp_tool().inputSchema or {}).get("properties") or {}
            ).items()
            if param != "ctx" and "type" not in spec
        ]
        assert not offenders, f"params with no advertised type: {offenders}"

    async def test_optional_params_are_still_optional(self):
        """Single-typed does NOT mean required — optionality is carried by absence from
        `required`, and the handlers still accept an explicit null at runtime."""
        schema = await _schema("list_tasks")
        required = set(schema.get("required") or [])
        for optional in ("filter", "list_name", "parent_task_id"):
            assert optional in (schema.get("properties") or {}), optional
            assert optional not in required, optional


class TestToolAnnotations:
    """MCP behaviour hints — read-only reads, additive writes, destructive deletes/removes."""

    async def test_reads_are_read_only_and_idempotent(self):
        for name in READ_ONLY_TOOLS:
            ann = await _annotations(name)
            assert ann.get("readOnlyHint") is True, f"{name}: not readOnlyHint"
            assert ann.get("idempotentHint") is True, f"{name}: not idempotentHint"

    async def test_destructive_tools_are_flagged(self):
        for name in DESTRUCTIVE_TOOLS:
            ann = await _annotations(name)
            assert ann.get("readOnlyHint") is False, f"{name}: read-only?"
            assert ann.get("destructiveHint") is True, f"{name}: not destructiveHint"

    async def test_additive_writes_are_non_readonly_non_destructive(self):
        tools = await _tools()
        additive = set(tools) - READ_ONLY_TOOLS - DESTRUCTIVE_TOOLS
        assert additive, "expected some additive-write tools"
        for name in additive:
            ann = await _annotations(name)
            assert ann.get("readOnlyHint") is False, f"{name}: read-only?"
            assert ann.get("destructiveHint") is not True, f"{name}: unexpectedly destructive"

    async def test_open_world_everywhere(self):
        # Every tool ultimately hits the RTM SaaS API — openWorldHint True across the board.
        for name in await _tools():
            assert (await _annotations(name)).get("openWorldHint") is True, f"{name}: not openWorld"


class TestClosedVocabularyEnums:
    async def test_contribution_state_enum_matches_the_terminal_set(self):
        """The five TERMINAL states — the open state `drafted` is deliberately NOT a transition
        target, so it must not appear in the advertised enum."""
        from rtm_mcp.contribution import OPEN_STATE, TERMINAL_STATES

        advertised = (await _props("gtd_contribution_transition"))["state"]["enum"]
        assert advertised == sorted(TERMINAL_STATES)
        assert OPEN_STATE not in advertised

    async def test_shape_verdict_vocabulary_is_sourced_from_the_detector_constants(self):
        from rtm_mcp.detectors import SHAPE_ORDER, SHAPE_VERDICTS

        assert {*SHAPE_ORDER, "none"} == SHAPE_VERDICTS

    """Closed-set params expose their legal values, sourced from the canonical constants so the
    advertised enum can never drift from what the handler validates."""

    async def test_set_task_priority_enum(self):
        assert (await _props("set_task_priority"))["priority"]["enum"] == sorted(
            PRIORITY_INPUT_CODES
        )

    async def test_move_task_priority_direction_enum(self):
        assert (await _props("move_task_priority"))["direction"]["enum"] == list(MOVE_DIRECTIONS)

    async def test_commit_scope_enum(self):
        assert (await _props("gtd_canvas_commit"))["scope"]["enum"] == sorted(VALID_SCOPES)

    async def test_commit_execute_value_enum(self):
        execute = (await _props("gtd_canvas_commit"))["execute"]
        assert execute["additionalProperties"]["enum"] == sorted(VALID_EXECUTE_COMMIT)

    async def test_chat_post_role_and_mode_enums(self):
        props = await _props("gtd_chat_post")
        assert props["role"]["enum"] == sorted(VALID_ROLES)
        assert props["mode"]["enum"] == sorted(VALID_MODES)

    async def test_engage_commit_items_verdict_enum(self):
        items = (await _props("gtd_engage_commit"))["items"]
        assert items["items"]["properties"]["verdict"]["enum"] == sorted(VERDICT_FAMILY)

    async def test_context_depth_enum(self):
        assert (await _props("gtd_item_context"))["depth"]["enum"] == sorted(VALID_DEPTHS)

    async def test_tier1_vocabulary_enums_match_canonical_constants(self):
        """The D1 shared-kernel promotion: all SEVEN structural GTD vocabularies are now
        server-owned, and every advertised enum EQUALS its canonical frozenset — so the schema
        can never drift from what the handler validates."""
        create = await _props("gtd_item_create")
        assert create["life_context"]["enum"] == sorted(LIFE_CONTEXTS)
        assert create["kind"]["enum"] == sorted(ITEM_KINDS)
        assert create["action_context"]["enum"] == sorted(ACTION_CONTEXTS)
        assert create["energy"]["enum"] == sorted(ENERGY_LEVELS)
        assert create["comms"]["enum"] == sorted(COMMS_MODES)
        assert create["priority"]["enum"] == sorted(MOSCOW_BANDS)
        assert (await _props("gtd_note_add"))["note_type"]["enum"] == sorted(JOURNAL_NOTE_TYPES)


class TestStructuredParams:
    """Complex coercion params still advertise a clean single-typed schema (no anyOf/null) AND a
    description — the tool_params coercion machinery is composed, not replaced."""

    async def test_commit_complex_params_are_clean_typed_arrays_objects(self):
        props = await _props("gtd_canvas_commit")
        assert props["adds"]["type"] == "array" and "anyOf" not in props["adds"]
        assert props["execute"]["type"] == "object" and "anyOf" not in props["execute"]
        assert props["order"]["type"] == "array"

    async def test_batch_undo_ids_is_clean_array(self):
        ids = (await _props("batch_undo"))["transaction_ids"]
        assert ids["type"] == "array" and ids["items"]["type"] == "string"


class TestOutputSchemas:
    """Every tool declares an outputSchema whose `data` is a success|error union — the
    machine-readable RESULT contract that closes the input+output loop for chaining."""

    async def test_every_tool_declares_an_output_schema(self):
        tools = await _tools()
        missing = [n for n, t in tools.items() if not t.to_mcp_tool().outputSchema]
        assert not missing, f"tools without an outputSchema: {missing}"

    async def test_output_data_is_success_or_error_union(self):
        for name, t in (await _tools()).items():
            data = t.to_mcp_tool().outputSchema["properties"]["data"]
            assert "anyOf" in data, f"{name}: output data is not a success|error union"

    async def test_spot_check_success_shapes(self):
        tools = await _tools()

        def model(name: str, title: str) -> dict:
            return _find_model(tools[name].to_mcp_tool().outputSchema or {}, title)

        # gtd_project_plan advertises the project-plan-seed header a caller reads.
        assert "project" in model("gtd_project_plan", "PlanHeader")
        # the commit tool advertises its rejection-reason vocabulary as an enum.
        assert "invalid_scope" in model("gtd_canvas_commit", "CommitRejection")["reason"]["enum"]
        # a task write advertises the Task object a caller chains on.
        assert "id" in model("add_task", "Task")

    async def test_rejection_reason_enums_match_canonical_constants(self):
        """Each commit tool's advertised `rejected[].reason` enum EQUALS the handler's canonical
        constant — so the schema can never drift from what the handler emits (drift-proof, like the
        input enums)."""
        tools = await _tools()

        def reason_enum(tool: str, model: str) -> list:
            schema = tools[tool].to_mcp_tool().outputSchema or {}
            return _find_model(schema, model)["reason"]["enum"]

        assert reason_enum("gtd_canvas_commit", "CommitRejection") == sorted(COMMIT_REJECT_REASONS)
        assert reason_enum("gtd_project_create", "CreateRejection") == sorted(CREATE_REJECT_REASONS)
        assert reason_enum("gtd_engage_commit", "EngageRejection") == sorted(ENGAGE_REJECT_REASONS)
        assert reason_enum("gtd_item_create", "GtdWriteRejection") == sorted(
            GTD_WRITE_REJECT_REASONS
        )


class TestToolFingerprints:
    """The committed tool-fingerprints.json is kept fresh by the repo, not the consumer (family
    standard § 5): a schema change without a regenerated file fails CI. The consumer is the
    architect's weekly tool-detection scan (per-tool `schema-changed` events)."""

    async def test_committed_fingerprints_match_the_live_server(self):
        module = _load_fingerprint_script()
        live = await module.compute_fingerprints()

        path = _REPO_ROOT / "tool-fingerprints.json"
        assert path.exists(), "tool-fingerprints.json missing — run: make fingerprints"
        committed = json.loads(path.read_text())

        assert committed["schema_version"] == module.SCHEMA_VERSION
        assert committed["server"] == module.SERVER
        assert committed["tools"] == live, (
            "tool-fingerprints.json is stale — tool schemas changed but the file was not "
            "regenerated. Run: make fingerprints"
        )

    async def test_fingerprints_are_qualified_sha256(self):
        tools = await _tools()
        live = await _load_fingerprint_script().compute_fingerprints()
        assert set(live) == {f"mcp__rtm__{name}" for name in tools}
        assert all(len(fp) == 64 and int(fp, 16) >= 0 for fp in live.values())


# --------------------------------------------------------------------------- #
# Surface 6 — the typed error contract must be ADVERTISED, not just returned
# --------------------------------------------------------------------------- #

# Error codes each shared helper can surface on behalf of its caller. A tool that calls
# the helper can return these, so its description must name them.
_HELPER_CODES: dict[str, set[str]] = {
    "resolve_task_ids": {"task_not_found", "missing_parameter"},
    "resolve_list_id": {"list_not_found"},
    "enforce_strict_tags": {"strict_tag_rejected"},
    "enforce_note_shape": {"note_shape_rejected"},
    "enforce_list_target": {"smart_list_target", "locked_system_list"},
    # error_from_exception maps whatever RTM raised; these are the codes worth advertising.
    "error_from_exception": {"auth_failed", "service_unavailable", "network_error"},
    # The Wave 1 reads' shared window/threshold guard rail.
    "_bounded_int": {"invalid_input"},
}


def _tool_sources() -> dict[str, str]:
    """Tool name -> its `async def` source block, from src/rtm_mcp/tools/*.py.

    Parsed with `ast` (never a brace/regex scan — tool bodies are full of f-strings whose
    interpolation braces are indistinguishable from dict delimiters to a naive counter).
    """
    import ast

    out: dict[str, str] = {}
    for path in sorted((_REPO_ROOT / "src" / "rtm_mcp" / "tools").glob("*.py")):
        src = path.read_text()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            decorated = any(
                isinstance(d.func if isinstance(d, ast.Call) else d, ast.Attribute)
                and (d.func if isinstance(d, ast.Call) else d).attr == "tool"
                for d in node.decorator_list
            )
            if decorated:
                out[node.name] = ast.get_source_segment(src, node) or ""
    return out


def _reachable_codes(body: str) -> set[str]:
    """Every ErrorCode a tool can actually surface — direct references plus what the shared
    resolvers/gates it calls can raise on its behalf."""
    import re

    codes = {m.lower() for m in re.findall(r"ErrorCode\.([A-Z_]+)", body)}
    for helper, implied in _HELPER_CODES.items():
        if re.search(rf"\b{helper}\(", body):
            codes |= implied
    return codes


class TestAdvertisedErrorContract:
    """v2.1.0 guard. Every tool advertises `data` as a `success | error` union (asserted in
    TestOutputSchemas), but the union alone tells a caller nothing about WHICH codes to branch
    on — and only some tools can fail at all. This pins the human/model-readable half: a tool
    that can return an envelope error must NAME the codes it can produce.

    Why it exists: v2.0.0 shipped with 975 tests green while five tools still advertised the
    pre-v2.0.0 prose shape and 34 more documented no error at all. The suite asserted the
    RUNTIME dict and never the ADVERTISED description, so nothing caught it — a live tool call
    did. This test closes that gap structurally."""

    async def test_failable_tools_document_an_error_shape(self):
        tools = await _tools()
        sources = _tool_sources()
        undocumented = []
        for name, tool in tools.items():
            if not _reachable_codes(sources.get(name, "")):
                continue  # genuinely cannot return an envelope error
            desc = tool.to_mcp_tool().description or ""
            if '"error"' not in desc and "error.details" not in desc:
                undocumented.append(name)
        assert undocumented == [], (
            "these tools can return an envelope error but advertise no error shape — add an "
            f"`Errors:` clause to the docstring (CONTRIBUTING § 5): {sorted(undocumented)}"
        )

    async def test_every_reachable_code_is_named_in_the_description(self):
        """The tight half: adding a new failure path to a tool fails this test until the
        docstring names its code. Prevents silent drift back into an under-advertised surface."""
        tools = await _tools()
        sources = _tool_sources()
        missing: dict[str, list[str]] = {}
        for name, tool in tools.items():
            codes = _reachable_codes(sources.get(name, ""))
            if not codes:
                continue
            desc = tool.to_mcp_tool().description or ""
            absent = sorted(c for c in codes if c not in desc)
            if absent:
                missing[name] = absent
        assert missing == {}, (
            "these tools can produce error codes their description never names — the advertised "
            f"contract is incomplete: {missing}"
        )

    async def test_tools_that_cannot_fail_are_not_forced_to_document_errors(self):
        """Guards the guard: the derivation must actually discriminate. If every tool were
        treated as failable the tests above would pass vacuously-strictly and stop meaning
        anything."""
        sources = _tool_sources()
        cannot_fail = [n for n in await _tools() if not _reachable_codes(sources.get(n, ""))]
        assert cannot_fail, "derivation marks every tool as failable — it is not discriminating"


# --------------------------------------------------------------------------- #
# v3.0.0 — deprecated aliases and the gtd_query split
# --------------------------------------------------------------------------- #


#: The 26 surfaces removed at v3.1.0, owned BY THIS FILE and not imported.
#:
#: This is the load-bearing detail. If the list came from `rtm_mcp.tools.gtd`, deleting the
#: constant would break the import — and worse, leaving it behind as an empty dict would make the
#: loop below iterate nothing and pass trivially. A test that silently stops testing is the exact
#: failure this programme has found five times over; here it would take the form of a removal test
#: that proves nothing. Hence the literal list, and the length assertion before any iteration.
REMOVED_AT_V3_1_0 = (
    "gtd_add_note",
    "gtd_annotate_clarification",
    "gtd_apply_canvas_commit",
    "gtd_apply_engage_commit",
    "gtd_attach_contribution",
    "gtd_attach_output",
    "gtd_batch_transition",
    "gtd_capture",
    "gtd_chase_sweep",
    "gtd_close_inbox_item",
    "gtd_complete_action",
    "gtd_consolidate_apply",
    "gtd_context",
    "gtd_create_item",
    "gtd_create_project",
    "gtd_edit_note",
    "gtd_health_check",
    "gtd_inbox_zero",
    "gtd_item_classify",
    "gtd_link_dependency",
    "gtd_query",
    "gtd_set_properties",
    "gtd_set_redaction",
    "gtd_stamp_tokens",
    "gtd_topic_clusters",
    "gtd_transition_state",
)


class TestDeprecatedSurfacesAreGone:
    """v3.1.0 removed the 25 aliases and the `gtd_query` dispatcher. 26 -> 0."""

    def test_the_removal_list_is_the_expected_size(self):
        """Asserted BEFORE anything iterates it — a list that had silently emptied would make
        every test below pass without checking a single name."""
        assert len(REMOVED_AT_V3_1_0) == 26
        assert len(set(REMOVED_AT_V3_1_0)) == 26, "duplicates would inflate the count"

    async def test_every_deprecated_name_is_unresolvable(self):
        tools = await _tools()
        assert len(REMOVED_AT_V3_1_0) == 26  # belt and braces: this loop must have 26 iterations
        still_present = [name for name in REMOVED_AT_V3_1_0 if name in tools]
        assert still_present == [], f"deprecated surfaces still advertised: {still_present}"

    async def test_the_alias_constant_itself_is_gone(self):
        """The mechanism, not just the surfaces — a leftover map is how one gets re-registered."""
        import rtm_mcp.tools.gtd as gtd_tools

        assert not hasattr(gtd_tools, "DEPRECATED_ALIASES")

    async def test_the_live_names_all_still_resolve(self):
        tools = await _tools()
        replacements = (
            "gtd_note_add",
            "gtd_inbox_item_annotate",
            "gtd_canvas_commit",
            "gtd_engage_commit",
            "gtd_contribution_attach",
            "gtd_note_attach_output",
            "gtd_item_transition_batch",
            "gtd_inbox_capture",
            "gtd_waiting_for_sweep",
            "gtd_inbox_item_close",
            "gtd_item_complete",
            "gtd_cluster_consolidate",
            "gtd_item_context",
            "gtd_item_create",
            "gtd_project_create",
            "gtd_note_edit",
            "gtd_health_report",
            "gtd_inbox_drain",
            "gtd_item_shape",
            "gtd_dependency_link",
            "gtd_item_set_properties",
            "gtd_item_set_redaction",
            "gtd_item_stamp_tokens",
            "gtd_cluster_candidates",
            "gtd_item_transition",
            "gtd_item_today",
            "gtd_next_actions",
            "gtd_focus_projects",
        )
        missing = [n for n in replacements if n not in tools]
        assert missing == [], f"replacements missing: {missing}"

    async def test_the_gtd_tool_count_is_pinned_at_55(self):
        tools = await _tools()
        gtd = {n for n in tools if n.startswith("gtd_")}
        assert len(gtd) == 55, sorted(gtd)

    async def test_no_fingerprint_records_a_deprecated_surface(self):
        import json

        committed = json.loads((_REPO_ROOT / "tool-fingerprints.json").read_text())["tools"]
        leftover = [n for n in REMOVED_AT_V3_1_0 if f"mcp__rtm__{n}" in committed]
        assert leftover == [], f"stale fingerprints: {leftover}"


class TestGtdQuerySplit:
    """D11: an invalid parameter combination should be UNREPRESENTABLE, not merely rejected."""

    async def test_each_tool_takes_only_its_own_parameters(self):
        assert set((await _props("gtd_item_today")) or {}) == set()
        assert set(await _props("gtd_next_actions")) == {"context"}
        assert set(await _props("gtd_focus_projects")) == {"focus"}

    async def test_no_split_tool_carries_perspective_forward(self):
        for name in ("gtd_item_today", "gtd_next_actions", "gtd_focus_projects"):
            assert "perspective" not in (await _props(name) or {}), name

    async def test_the_cross_perspective_parameters_are_gone(self):
        """`focus` belonged to one perspective and `context` to another; neither may appear on
        the other's tool."""
        assert "focus" not in (await _props("gtd_next_actions"))
        assert "context" not in (await _props("gtd_focus_projects"))

    async def test_all_three_are_read_only(self):
        for name in ("gtd_item_today", "gtd_next_actions", "gtd_focus_projects"):
            ann = await _annotations(name)
            assert ann.get("readOnlyHint") is True and ann.get("idempotentHint") is True, name


# ======================================================================================= #
# The Tool Affordance Standard — selection-surface budgets (v3.3.0)
# ======================================================================================= #

#: The client keeps roughly this much of a description and of `instructions`. A Claude Code /
#: Cowork implementation detail measured 2026-07-26, not an MCP guarantee — but the
#: front-loading discipline it forces is correct at any finite budget.
BUDGET_BYTES = 2048

#: Descriptions that deliberately exceed the budget, each with the reason it earns the cost.
#: The list is the POINT: it makes an over-budget description a conscious, recorded choice
#: rather than drift. Every one of these keeps its selection and write-safety payload inside
#: the surviving front block (asserted below) — the tail that gets cut is reference material
#: that `rtm_tool_help("<tool>")` serves in full.
#:
#: The governing constraint is local: CONTRIBUTING § 7 REQUIRES a multi-case `Returns` and an
#: `Args:` section in every tool docstring, and the `_FullDocstringMCP` shim advertises the
#: whole docstring as the description. So for a genuinely complex governed write, "get under
#: 2 KB" and "obey § 7" cannot both hold, and § 7 wins (it is the host repo's own standard).
OVER_BUDGET_EXEMPTIONS = {
    "gtd_canvas_commit": "The single governed write surface for a canvas commit: seven op maps, "
    "each with its own vocabulary, plus the destructive-confirm and strict-tag contracts.",
    "gtd_engage_commit": "The engage ACL: the full verdict->RTM-write grammar (13 verdicts) plus "
    "the two flag guards and the steer-note contract.",
    "gtd_project_index": "Three collections in one payload (projects / foci / actions), each with "
    "its own field set, plus the redaction-cascade rules.",
    "list_tasks": "Carries RTM's advanced-search operator table, which is the tool's entire "
    "usable surface — a caller cannot construct a filter without it.",
    "gtd_surface_queue": "Documents the three inclusion paths for response detection and the "
    "quarantine of unrecognised notes.",
    "gtd_chat_post": "Two roles x two modes with different tag side-effects, plus the "
    "clear_signal interim-note contract.",
    "gtd_chat_thread": "Documents the turn-attachment derivation (FILING correlation, LINK "
    "trailers) and the project-scope descendant scan.",
    "gtd_project_create": "Creates a whole project tree: frame + items + deps + notes, each with "
    "its own validation path.",
    "gtd_project_canvas": "Returns the rendered board seed; documents the overlay, lean profile "
    "and companion-metadata enrichment.",
    "gtd_contribution_transition": "Six states with a judged/invalidated split that changes the "
    "acceptance-rate denominator.",
    "gtd_surface_create": "Thirteen parameters across several item types.",
    "gtd_engine_report": "Reports telemetry whose predecessor was structurally zero; the "
    "description names each withdrawn metric and why.",
    "add_task": "Carries the Smart Add syntax table, which is the tool's primary interface.",
    "gtd_item_create": "The hard-gated per-kind Definition of Ready, which differs per kind.",
    "gtd_item_stamp_tokens": "Documents the token grammar and the idempotence/propagation model.",
    "gtd_engage_seed": "Documents six server-derived flags and the curtain-not-vault invariant.",
    "gtd_item_shape": "Documents the pattern vocabulary and the lockstep contract with the "
    "detectors.",
    "gtd_tag_report": "Documents the three-way classification and the people-tag caveat.",
    "gtd_item_complete": "Marginally over (17 bytes) once em-dashes are counted as UTF-8; "
    "trimming would cost a documented completion caveat.",
}

#: Cues that show a description's front block states the tool's posture. Presence of any one
#: is enough — the point is that a caller learns the safety/read-write stance from the part of
#: the description that always survives, never only from `annotations` (which this client does
#: not render to the model) or from a tail that gets cut.
_POSTURE_CUES = (
    "DESTRUCTIVE",
    "destructive",
    "confirm_destructive",
    "nothing written",
    "NOTHING",
    "soft-delete",
    "irreversible",
    "governed",
    "read-only",
    "Read-only",
    "no timeline",
    "transaction_id",
)


class TestSelectionSurfaceBudgets:
    """The two selection surfaces are the only channels a client puts in front of the model
    unprompted, and this client keeps ~2 KB of each. Before v3.3.0 nothing measured them:
    18 of 99 descriptions were over (the worst losing 58% — its governance contract) and
    `instructions` was 30,506 bytes, of which ~93% was discarded, leaving the legal
    disclaimer where the tool-family routing should be."""

    async def test_server_instructions_fit_the_budget(self):
        instructions = (mcp.instructions or "").encode()
        assert len(instructions) <= BUDGET_BYTES, (
            f"server instructions are {len(instructions)} bytes; the client keeps ~{BUDGET_BYTES} "
            "and discards the rest. Front-load: what-this-server-is, the tool-family split and "
            "routing keywords first; the legal disclaimer last."
        )

    async def test_instructions_lead_with_routing_not_boilerplate(self):
        """A disclaimer in the front block spends the whole budget saying nothing routable."""
        front = (mcp.instructions or "")[:400]
        assert "not endorsed" not in front, (
            "the legal disclaimer is in the front block of `instructions`, where the "
            "tool-family routing keywords should be. Move it to the end."
        )

    async def test_every_description_fits_the_budget_or_is_exempt(self):
        tools = await _tools()
        over = {
            name: len((tool.to_mcp_tool().description or "").encode())
            for name, tool in tools.items()
            if len((tool.to_mcp_tool().description or "").encode()) > BUDGET_BYTES
        }
        unexplained = {n: b for n, b in over.items() if n not in OVER_BUDGET_EXEMPTIONS}
        assert unexplained == {}, (
            "these descriptions exceed the client's budget with no recorded reason — either "
            "front-load them (move Returns / operator tables / caveats behind the selection "
            "block, and the reference detail into rtm_tool_help) or add a reasoned entry to "
            f"OVER_BUDGET_EXEMPTIONS: {unexplained}"
        )

    async def test_no_stale_exemptions(self):
        """Guards the guard. An exemption for a description that now fits would quietly license
        future growth back over the budget, and the list would stop meaning anything."""
        tools = await _tools()
        stale = [
            name
            for name in OVER_BUDGET_EXEMPTIONS
            if name in tools
            and len((tools[name].to_mcp_tool().description or "").encode()) <= BUDGET_BYTES
        ]
        assert stale == [], (
            f"these tools now fit the budget — remove their exemptions: {sorted(stale)}"
        )
        unknown = sorted(set(OVER_BUDGET_EXEMPTIONS) - set(tools))
        assert unknown == [], f"exemptions naming tools that no longer exist: {unknown}"

    async def test_every_exempt_description_states_its_posture_in_the_front_block(self):
        """The assertion that actually matters. A long description is tolerable ONLY if the
        part that survives truncation still tells a caller what the tool does to their data —
        so for every exempt tool, a posture cue must appear within the first BUDGET_BYTES."""
        tools = await _tools()
        silent = []
        for name in sorted(OVER_BUDGET_EXEMPTIONS):
            desc = (tools[name].to_mcp_tool().description or "").encode()
            front = desc[:BUDGET_BYTES].decode(errors="ignore")
            if not any(cue in front for cue in _POSTURE_CUES):
                silent.append(name)
        assert silent == [], (
            "these over-budget tools never state their read/write posture inside the front "
            "block a client actually keeps — a caller learns what they do to the account only "
            f"from a tail that gets discarded: {silent}"
        )

    async def test_every_description_front_block_parses_as_domain_and_purpose(self):
        """Tier 1 shape: `<Domain> — <purpose>`. The domain marker is also the model-readable
        half of the taxonomy — `_meta` is not rendered to the model on this client, so the
        marker in ordinary description text is what a skill can actually select on."""
        import re

        tools = await _tools()
        bad = {}
        for name, tool in tools.items():
            first = (tool.to_mcp_tool().description or "").strip().split("\n")[0].strip()
            if not re.match(r"^[A-Za-z][\w /&-]{1,24} — \S", first):
                bad[name] = first[:80]
        assert bad == {}, (
            "these descriptions do not open as `<Domain> — <purpose>`, so a caller cannot tell "
            f"which family the tool belongs to from the selection line: {bad}"
        )
