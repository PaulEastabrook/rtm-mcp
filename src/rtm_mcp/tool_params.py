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


# --------------------------------------------------------------------------- #
# Single-typed presentation for OPTIONAL SCALAR params.
#
# The builders above solved the union problem for *complex* params. The same
# problem applies to a plain optional scalar: `Annotated[str | None, Field(...)]`
# serialises to `{"anyOf": [{"type": "string"}, {"type": "null"}], …}`, and MCP
# clients that simplify schemas before showing them to the model flatten that to a
# bare `{}` — losing the type, the description AND any enum. Measured 2026-07-19
# against a live Claude Code session: this server had 110 such params across 32
# tools, including the closed vocabularies on `set_task_priority.priority` and
# `gtd_chat_post.mode`.
#
# These builders present the same clean single-typed schema for scalars. The Python
# annotation stays `T | None` with its `None` default, so runtime behaviour — an
# omitted arg, an explicit null, a real value — is unchanged; optionality is carried
# (correctly) by absence from `required`.
#
# `enum=` / `pattern=` / `format=` and friends pass through as keyword arguments, so
# a vocabulary stays sourced from its canonical constant, e.g.
#     Annotated[str | None, optional_string("…", enum=sorted(PRIORITY_INPUT_CODES))]
#
# NOTE the residual client-side loss this cannot fix: that same client strips
# `description` / `minimum` / `maximum` / `pattern` from every non-required param
# regardless of typing. They are kept regardless — a conformant client gets them, and
# `tests/test_tool_schemas.py` requires them. (This server is on fastmcp 2.x, so its
# full docstring — `Args:` prose included — already reaches the model and carries the
# same information; the 3.x siblings needed a registration shim for that.)
# --------------------------------------------------------------------------- #


def _optional(json_type: str, description: str, **extra: Any) -> WithJsonSchema:
    """Present an optional scalar as a single-typed schema instead of a `T | None` union."""
    schema: dict[str, Any] = {"type": json_type, "description": description}
    schema.update(extra)
    return WithJsonSchema(schema)


def optional_string(description: str, **extra: Any) -> WithJsonSchema:
    """For `str | None`. Pass `enum=[...]` / `pattern=...` to advertise a constraint."""
    return _optional("string", description, **extra)


def required_string(description: str, **extra: Any) -> WithJsonSchema:
    """Single-typed schema for a REQUIRED string param (no `default: null`).

    Used where the Python annotation is a genuine value-type union but the *advertised*
    contract should be the string form — `set_task_priority.priority` is annotated
    `str | int` because `parsers.priority_to_code` does `str(priority).lower()`, so
    `1` and `"1"` both work. Advertising `anyOf: [string, integer]` there had two
    costs: simplifying clients flattened it to `{}` (so the enum, and the param itself,
    were invisible), and the enum was string-only anyway — meaning a strictly-validating
    client would have rejected `priority=1` despite the server accepting it.

    Advertising the string form is NARROWER than what the handler accepts, never wider:
    every schema-conformant call still works, and the integer aliases keep working for
    existing callers. The docstring documents the alias.
    """
    schema: dict[str, Any] = {"type": "string", "description": description}
    schema.update(extra)
    return WithJsonSchema(schema)


def optional_integer(description: str, **extra: Any) -> WithJsonSchema:
    """For `int | None`."""
    return _optional("integer", description, **extra)


def optional_number(description: str, **extra: Any) -> WithJsonSchema:
    """For `float | None`."""
    return _optional("number", description, **extra)


def optional_boolean(description: str, **extra: Any) -> WithJsonSchema:
    """For `bool | None`."""
    return _optional("boolean", description, **extra)
