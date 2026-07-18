"""Tool-schema contract: the model-facing MCP surface (the six-surface standard).

Introspects the REAL server (`rtm_mcp.server.mcp` — every tool registered at import) via
`mcp.get_tools()` → `to_mcp_tool()`, so these assertions pin what an MCP client actually sees:
every tool + parameter is described, behaviour annotations are correct per class, closed-vocabulary
params expose their enums (asserted EQUAL to the canonical constants, so they can never drift from
the handler), structured params are exposed, and every tool advertises an `outputSchema` whose
`data` is a `success | error` union. See CONTRIBUTING § 3 + § 8 and the family standard
(mcp-tool-documentation-standard.md § 4/§ 5).
"""

from rtm_mcp.canvas_commit import VALID_EXECUTE_COMMIT, VALID_SCOPES
from rtm_mcp.engage_commit import VERDICT_FAMILY
from rtm_mcp.gtd_chat import VALID_MODES, VALID_ROLES
from rtm_mcp.parsers import PRIORITY_INPUT_CODES
from rtm_mcp.server import mcp
from rtm_mcp.tools.tasks import MOVE_DIRECTIONS

# Behaviour-class expectations (the source of truth for the annotation assertions).
READ_ONLY_TOOLS = {
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
}
DESTRUCTIVE_TOOLS = {
    "delete_task",
    "delete_list",
    "delete_note",
    "gtd_apply_canvas_commit",
    "gtd_apply_engage_commit",
}


async def _tools() -> dict:
    return await mcp.get_tools()


async def _schema(name: str) -> dict:
    return (await _tools())[name].to_mcp_tool().inputSchema or {}


async def _props(name: str) -> dict:
    return (await _schema(name)).get("properties") or {}


async def _annotations(name: str) -> dict:
    ann = (await _tools())[name].to_mcp_tool().annotations
    return {} if ann is None else {k: v for k, v in ann.model_dump().items() if v is not None}


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
    """Closed-set params expose their legal values, sourced from the canonical constants so the
    advertised enum can never drift from what the handler validates."""

    async def test_set_task_priority_enum(self):
        assert (await _props("set_task_priority"))["priority"]["enum"] == sorted(
            PRIORITY_INPUT_CODES
        )

    async def test_move_task_priority_direction_enum(self):
        assert (await _props("move_task_priority"))["direction"]["enum"] == list(MOVE_DIRECTIONS)

    async def test_commit_scope_enum(self):
        assert (await _props("gtd_apply_canvas_commit"))["scope"]["enum"] == sorted(VALID_SCOPES)

    async def test_commit_execute_value_enum(self):
        execute = (await _props("gtd_apply_canvas_commit"))["execute"]
        assert execute["additionalProperties"]["enum"] == sorted(VALID_EXECUTE_COMMIT)

    async def test_chat_post_role_and_mode_enums(self):
        props = await _props("gtd_chat_post")
        assert props["role"]["enum"] == sorted(VALID_ROLES)
        assert props["mode"]["enum"] == sorted(VALID_MODES)

    async def test_engage_commit_items_verdict_enum(self):
        items = (await _props("gtd_apply_engage_commit"))["items"]
        assert items["items"]["properties"]["verdict"]["enum"] == sorted(VERDICT_FAMILY)


class TestStructuredParams:
    """Complex coercion params still advertise a clean single-typed schema (no anyOf/null) AND a
    description — the tool_params coercion machinery is composed, not replaced."""

    async def test_commit_complex_params_are_clean_typed_arrays_objects(self):
        props = await _props("gtd_apply_canvas_commit")
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

        def defs(name):
            return tools[name].to_mcp_tool().outputSchema.get("$defs", {})

        # gtd_project_plan advertises the project-plan-seed header a caller reads.
        assert "project" in defs("gtd_project_plan")["PlanHeader"]["properties"]
        # the commit tool advertises its rejection-reason vocabulary as an enum.
        reason = defs("gtd_apply_canvas_commit")["CommitRejection"]["properties"]["reason"]
        assert "invalid_scope" in reason["enum"]
        # a task write advertises the Task object a caller chains on.
        assert "id" in defs("add_task")["Task"]["properties"]
