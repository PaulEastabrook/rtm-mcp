"""Tool-schema contract: the model-facing MCP surface (the six-surface standard).

Introspects the REAL server (`rtm_mcp.server.mcp` — every tool registered at import) via
`mcp.get_tools()` → `to_mcp_tool()`, so these assertions pin what an MCP client actually sees:
every tool + parameter is described, behaviour annotations are correct per class, closed-vocabulary
params expose their enums (asserted EQUAL to the canonical constants, so they can never drift from
the handler), structured params are exposed, and every tool advertises an `outputSchema` whose
`data` is a `success | error` union. See CONTRIBUTING § 3 + § 8 and the family standard
(mcp-tool-documentation-standard.md § 4/§ 5).
"""

import importlib.util
import json
from pathlib import Path
from typing import ClassVar

from rtm_mcp.canvas_commit import COMMIT_REJECT_REASONS, VALID_EXECUTE_COMMIT, VALID_SCOPES
from rtm_mcp.canvas_create import CREATE_REJECT_REASONS
from rtm_mcp.engage_commit import ENGAGE_REJECT_REASONS, VERDICT_FAMILY
from rtm_mcp.gtd_chat import VALID_MODES, VALID_ROLES
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

    # The ONE legitimate remaining union, pinned so it stays a deliberate decision rather than an
    # oversight. `set_task_priority.priority` is REQUIRED and genuinely accepts `str | int` —
    # `parsers.priority_to_code` does `str(priority).lower()`, so `1` and `"1"` and `"high"` all
    # work. That is a value-type union, not an optionality artefact, so no `optional_*` builder
    # applies: flattening it to `type: string` would misdescribe what the handler accepts.
    #
    # KNOWN CONSEQUENCE (deliberately not "fixed" here): because the client flattens `anyOf`, this
    # param currently reaches the model as `{}`. There is also a latent inconsistency predating
    # this change — the advertised `enum` is string-only while the type admits `integer`, so a
    # strictly-validating client would reject `priority=1`. Resolving that means either widening
    # the enum to include the int forms or narrowing the annotation to `str` (a runtime-behaviour
    # change on a central tool with downstream consumers). It needs a decision, not a guess.
    KNOWN_VALUE_TYPE_UNIONS: ClassVar[set[str]] = {"set_task_priority.priority"}

    async def test_no_optional_param_advertises_a_union(self):
        tools = await _tools()
        offenders = [
            f"{name}.{param}"
            for name, tool in tools.items()
            for param, spec in (
                (tool.to_mcp_tool().inputSchema or {}).get("properties") or {}
            ).items()
            if param != "ctx"
            and ("anyOf" in spec or "oneOf" in spec)
            and f"{name}.{param}" not in self.KNOWN_VALUE_TYPE_UNIONS
        ]
        assert not offenders, (
            "these params advertise a union and will be flattened to `{}` by simplifying "
            "clients — use a tool_params.optional_* builder instead of Field(...) on the "
            f"`T | None` annotation: {offenders}"
        )

    async def test_the_known_union_is_still_the_only_one(self):
        """If this fails because the exception is gone, delete it from the allowlist — the point
        is that the set never grows silently."""
        tools = await _tools()
        actual = {
            f"{name}.{param}"
            for name, tool in tools.items()
            for param, spec in (
                (tool.to_mcp_tool().inputSchema or {}).get("properties") or {}
            ).items()
            if param != "ctx" and "anyOf" in spec
        }
        assert actual == self.KNOWN_VALUE_TYPE_UNIONS, (
            f"the value-type-union allowlist is stale: advertised={sorted(actual)}, "
            f"allowlisted={sorted(self.KNOWN_VALUE_TYPE_UNIONS)}"
        )

    async def test_every_other_param_declares_a_type(self):
        """The payoff: a model can always see what to send."""
        tools = await _tools()
        offenders = [
            f"{name}.{param}"
            for name, tool in tools.items()
            for param, spec in (
                (tool.to_mcp_tool().inputSchema or {}).get("properties") or {}
            ).items()
            if param != "ctx"
            and "type" not in spec
            and f"{name}.{param}" not in self.KNOWN_VALUE_TYPE_UNIONS
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

    async def test_rejection_reason_enums_match_canonical_constants(self):
        """Each commit tool's advertised `rejected[].reason` enum EQUALS the handler's canonical
        constant — so the schema can never drift from what the handler emits (drift-proof, like the
        input enums)."""
        tools = await _tools()

        def reason_enum(tool: str, model: str) -> list:
            defs = tools[tool].to_mcp_tool().outputSchema.get("$defs", {})
            return defs[model]["properties"]["reason"]["enum"]

        assert reason_enum("gtd_apply_canvas_commit", "CommitRejection") == sorted(
            COMMIT_REJECT_REASONS
        )
        assert reason_enum("gtd_create_project", "CreateRejection") == sorted(CREATE_REJECT_REASONS)
        assert reason_enum("gtd_apply_engage_commit", "EngageRejection") == sorted(
            ENGAGE_REJECT_REASONS
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
