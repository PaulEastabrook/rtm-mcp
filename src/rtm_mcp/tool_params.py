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
