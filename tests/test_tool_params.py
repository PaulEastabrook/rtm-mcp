"""Tests for shared MCP tool-parameter coercion (tool_params).

Covers the Cowork-interop fix: complex params must (a) advertise a clean single-typed JSON
schema (no `anyOf`/null union, which some clients serialise as a JSON string) and (b) still
coerce a stringified value back into structured JSON before validation.
"""

from pydantic import TypeAdapter

from rtm_mcp.tool_params import (
    JsonObjArray,
    JsonObject,
    JsonStrArray,
    JsonStrArrayRequired,
    coerce_json,
)


class TestCoerceJson:
    def test_parses_json_array_string(self):
        assert coerce_json('[{"a": 1}]') == [{"a": 1}]

    def test_parses_json_object_string(self):
        assert coerce_json('{"a": 1}') == {"a": 1}

    def test_passes_structured_through(self):
        assert coerce_json([{"a": 1}]) == [{"a": 1}]
        assert coerce_json({"a": 1}) == {"a": 1}

    def test_none_passes_through(self):
        assert coerce_json(None) is None

    def test_blank_string_becomes_none(self):
        assert coerce_json("   ") is None

    def test_invalid_json_returned_unchanged(self):
        # returned as-is so pydantic raises a clear, typed error downstream
        assert coerce_json("not json") == "not json"


class TestAnnotatedParams:
    def test_obj_array_coerces_string(self):
        ta = TypeAdapter(JsonObjArray)
        assert ta.validate_python('[{"type": "action"}]') == [{"type": "action"}]
        assert ta.validate_python([{"type": "action"}]) == [{"type": "action"}]
        assert ta.validate_python(None) is None

    def test_str_array_coerces_string(self):
        assert TypeAdapter(JsonStrArray).validate_python('["a", "b"]') == ["a", "b"]

    def test_object_coerces_string(self):
        ta = TypeAdapter(JsonObject)
        assert ta.validate_python('{"c1": {"priority": "1"}}') == {"c1": {"priority": "1"}}

    def test_required_array_coerces_string(self):
        assert TypeAdapter(JsonStrArrayRequired).validate_python('["tx1", "tx2"]') == ["tx1", "tx2"]

    def test_schema_is_clean_single_type_no_anyof(self):
        cases = [
            (JsonObjArray, "array"),
            (JsonStrArray, "array"),
            (JsonObject, "object"),
            (JsonStrArrayRequired, "array"),
        ]
        for alias, jtype in cases:
            schema = TypeAdapter(alias).json_schema()
            assert schema.get("type") == jtype
            assert "anyOf" not in schema
