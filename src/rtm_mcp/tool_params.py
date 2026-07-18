"""Shared MCP tool-parameter helpers for complex (array/object) arguments.

Some MCP clients (notably the Cowork tool-call channel) serialise a **union-typed** complex
parameter — one whose JSON schema is an `anyOf`, e.g. the `array | null` that pydantic emits for
an optional `list[...] | None` — as a JSON **string** rather than as structured JSON. pydantic
then rejects it (`Input should be a valid list … input_type=str`) *before* the tool body runs.

These helpers close that class of defect for any tool with complex params:

- `coerce_json` — a `BeforeValidator` that `json.loads` a string argument back into structured
  JSON (and is a no-op for already-structured values). It is also safe to call directly at the
  top of a tool body as belt-and-braces for any caller that bypasses pydantic validation
  (e.g. the `FakeMCP` test harness, which invokes the raw function).
- `JsonStrArray` / `JsonObjArray` / `JsonObject` — `Annotated` *optional* parameter types that
  (a) coerce a stringified value via `coerce_json` and (b) advertise a **clean single-typed**
  JSON schema (via `WithJsonSchema`, with no `anyOf`/null branch) so conformant clients pass
  structured JSON in the first place. Use as `param: JsonObjArray = None`.
- `JsonStrArrayRequired` — the same, for a *required* array parameter (no default).
"""

import json
from typing import Annotated, Any

from pydantic import BeforeValidator, WithJsonSchema


def coerce_json(value: Any) -> Any:
    """Parse a JSON string into structured data; pass non-strings through unchanged.

    A blank string becomes ``None`` (an omitted optional). A string that is not valid JSON is
    returned unchanged so pydantic raises a clear, typed validation error rather than a confusing
    JSON-decode error.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return value
    return value


# Optional complex params — coerce a stringified value, and present a clean single-typed schema
# (no `anyOf`/null) so clients that choke on union schemas still pass structured JSON.
JsonStrArray = Annotated[
    list[str] | None,
    BeforeValidator(coerce_json),
    WithJsonSchema({"type": "array", "items": {"type": "string"}, "default": None}),
]
JsonObjArray = Annotated[
    list[dict[str, Any]] | None,
    BeforeValidator(coerce_json),
    WithJsonSchema({"type": "array", "items": {"type": "object"}, "default": None}),
]
JsonObject = Annotated[
    dict[str, Any] | None,
    BeforeValidator(coerce_json),
    WithJsonSchema({"type": "object", "default": None}),
]

# Required array param (no default) — same coercion, clean schema.
JsonStrArrayRequired = Annotated[
    list[str],
    BeforeValidator(coerce_json),
    WithJsonSchema({"type": "array", "items": {"type": "string"}}),
]


# --------------------------------------------------------------------------- #
# Schema-dict builders for the tool-documentation standard (surface 2 + 4).
#
# The `Annotated` aliases above present a clean schema but carry NO per-parameter
# `description` (and `WithJsonSchema` REPLACES the generated schema, so a sibling
# `Field(description=...)` is silently dropped). These helpers return the schema
# *dict* to hand to `WithJsonSchema` with the description (and, for structured
# params, an item/value schema carrying enums) baked in — used inline as
# `Annotated[T, BeforeValidator(coerce_json), WithJsonSchema(coerced_*_schema(...))]`
# so the coercion machinery is preserved AND the description reaches the client.
# They return `dict[str, Any]` (not an `Annotated` type) because a call expression
# is not permitted inside a type annotation (pyright reportInvalidTypeForm).
# --------------------------------------------------------------------------- #


def coerced_str_array_schema(description: str, *, required: bool = False) -> dict[str, Any]:
    """WithJsonSchema dict for a `list[str]` coercion param (clean single-typed array)."""
    schema: dict[str, Any] = {
        "type": "array",
        "items": {"type": "string"},
        "description": description,
    }
    if not required:
        schema["default"] = None
    return schema


def coerced_obj_array_schema(
    description: str, *, item_schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    """WithJsonSchema dict for a `list[dict]` coercion param. `item_schema` (optional) types the
    element object — e.g. an object with a closed `verdict`/`type` enum — for a richer contract."""
    return {
        "type": "array",
        "items": item_schema or {"type": "object"},
        "default": None,
        "description": description,
    }


def coerced_object_schema(
    description: str, *, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """WithJsonSchema dict for a `dict` coercion param. `extra` merges additional schema keys
    (e.g. `additionalProperties` typing the value space with an enum)."""
    schema: dict[str, Any] = {"type": "object", "default": None, "description": description}
    if extra:
        schema.update(extra)
    return schema
