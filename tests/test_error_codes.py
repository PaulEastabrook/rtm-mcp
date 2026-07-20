"""The canonical error-code registry and the v2.0.0 structured error envelope.

Guards the three properties the typed vocabulary rests on:

1. **Registry integrity** — codes are unique, lower_snake_case, and additive-only in
   spirit (a rename is a breaking change no test can catch after the fact, so the
   uniqueness + spelling checks are the mechanical part; the discipline is documented).
2. **Envelope shape** — `build_error` emits exactly `{code, message, rtm_code, details}`,
   omitting `details` when empty, and the prose is carried verbatim.
3. **One vocabulary, three scoped views** — the commit engines' `rejected[].reason` sets
   are drawn from the registry, so a reason can never be spelled two ways.
"""

import re

import pytest
from pydantic import ValidationError

from rtm_mcp.canvas_commit import COMMIT_REJECT_REASONS
from rtm_mcp.canvas_create import CREATE_REJECT_REASONS
from rtm_mcp.engage_commit import ENGAGE_REJECT_REASONS, VERDICT_REJECT_REASONS
from rtm_mcp.error_codes import RTM_CODE_MAP, ErrorCode, code_for_rtm
from rtm_mcp.exceptions import ERROR_CODE_MAP
from rtm_mcp.models import ErrorBody
from rtm_mcp.response_builder import build_error, error_from_exception


class TestRegistryIntegrity:
    def test_values_are_unique(self) -> None:
        values = [c.value for c in ErrorCode]
        assert len(values) == len(set(values))

    def test_values_are_lower_snake_case(self) -> None:
        """v2.0.0 normalised the three hyphenated engage reasons; nothing may reintroduce
        a hyphen, uppercase, or space — one spelling convention across the registry."""
        bad = [c.value for c in ErrorCode if not re.fullmatch(r"[a-z][a-z0-9_]*", c.value)]
        assert bad == [], f"non-canonical code spellings: {bad}"

    def test_str_mixin_compares_equal_to_wire_string(self) -> None:
        """Consumers branch on the raw string without importing the enum."""
        assert ErrorCode.TASK_NOT_FOUND == "task_not_found"
        assert ErrorCode.TASK_NOT_FOUND.value == "task_not_found"


class TestRtmCodeMapping:
    def test_covers_every_mapped_rtm_numeric(self) -> None:
        """The registry's RTM map must not fall behind the exception hierarchy's — every
        numeric that raises a typed exception also resolves to a semantic code."""
        assert set(RTM_CODE_MAP) == set(ERROR_CODE_MAP)

    @pytest.mark.parametrize(
        "numeric,expected",
        [
            (341, ErrorCode.TASK_NOT_FOUND),
            (340, ErrorCode.LIST_NOT_FOUND),
            (4080, ErrorCode.DUE_BEFORE_START),
            (98, ErrorCode.AUTH_FAILED),
            (102, ErrorCode.SERVICE_UNAVAILABLE),
        ],
    )
    def test_known_numerics_map_to_their_semantic_code(self, numeric, expected) -> None:
        assert code_for_rtm(numeric) is expected

    def test_unmapped_and_absent_numerics_fall_back_to_invalid_input(self) -> None:
        assert code_for_rtm(9999) is ErrorCode.INVALID_INPUT
        assert code_for_rtm(None) is ErrorCode.INVALID_INPUT


class TestBuildError:
    def test_minimal_shape(self) -> None:
        err = build_error(ErrorCode.TASK_NOT_FOUND, "Task not found: 'x'.")
        assert err == {
            "error": {
                "code": "task_not_found",
                "message": "Task not found: 'x'.",
                "rtm_code": None,
            }
        }

    def test_details_omitted_when_empty_not_null(self) -> None:
        """A simple failure stays a simple object — `details` is absent, not an empty dict."""
        assert "details" not in build_error(ErrorCode.INVALID_INPUT, "bad")["error"]

    def test_details_carried_and_rtm_code_preserved(self) -> None:
        err = build_error(ErrorCode.LIST_NOT_FOUND, "List 'x' not found.", rtm_code=340, query="x")[
            "error"
        ]
        assert err["rtm_code"] == 340
        assert err["details"] == {"query": "x"}

    def test_message_is_carried_verbatim(self) -> None:
        """The prose contract: byte-identical to what `data.error` held pre-v2.0.0."""
        prose = "Provide either task_name (for search) or all three: task_id, taskseries_id, and list_id."
        assert build_error(ErrorCode.MISSING_PARAMETER, prose)["error"]["message"] == prose

    def test_code_is_serialised_as_a_plain_string(self) -> None:
        """Not an `ErrorCode.X` repr — the wire carries the bare value."""
        assert type(build_error(ErrorCode.BAD_DATE, "m")["error"]["code"]) is str


class TestErrorFromException:
    def test_maps_rtm_error_code_and_preserves_numeric(self) -> None:
        from rtm_mcp.exceptions import RTMNotFoundError

        err = error_from_exception(RTMNotFoundError("Task not found", 341))["error"]
        assert err["code"] == "task_not_found"
        assert err["rtm_code"] == 341
        assert "Task not found" in err["message"]

    def test_non_rtm_exception_falls_back_with_null_rtm_code(self) -> None:
        err = error_from_exception(ValueError("boom"))["error"]
        assert err["code"] == "invalid_input"
        assert err["rtm_code"] is None
        assert err["message"] == "boom"


class TestRejectVocabularies:
    """One vocabulary, three scoped views — the v2.0.0 unification."""

    @pytest.mark.parametrize(
        "vocab",
        [COMMIT_REJECT_REASONS, CREATE_REJECT_REASONS, ENGAGE_REJECT_REASONS],
    )
    def test_every_reason_is_a_registry_member(self, vocab) -> None:
        assert all(isinstance(r, ErrorCode) for r in vocab)

    def test_shared_reasons_have_one_spelling_across_engines(self) -> None:
        """The drift v2.0.0 removed: `unknown_add_type` / `invalid_execute` appear in two
        engines and `strict_tag_rejected` in all three — each exactly once, by identity."""
        assert ErrorCode.UNKNOWN_ADD_TYPE in COMMIT_REJECT_REASONS & CREATE_REJECT_REASONS
        assert ErrorCode.INVALID_EXECUTE in COMMIT_REJECT_REASONS & CREATE_REJECT_REASONS
        assert ErrorCode.STRICT_TAG_REJECTED in (
            COMMIT_REJECT_REASONS & CREATE_REJECT_REASONS & ENGAGE_REJECT_REASONS
        )

    def test_destructive_unconfirmed_reconciled_to_one_name(self) -> None:
        """Was `destructive_unconfirmed` (commit) vs `confirm_destructive_required` (engage)."""
        assert ErrorCode.DESTRUCTIVE_UNCONFIRMED in COMMIT_REJECT_REASONS
        assert ErrorCode.DESTRUCTIVE_UNCONFIRMED in ENGAGE_REJECT_REASONS
        assert not any(r.value == "confirm_destructive_required" for r in ENGAGE_REJECT_REASONS)

    def test_verdict_reasons_are_the_lockstep_three(self) -> None:
        """Grammar-bound (engage-verdict-grammar.md §§ 1-4): re-spelling these requires a
        matching change to gtd's validate-engage-verdict.py. Underscored since v2.0.0."""
        assert {r.value for r in VERDICT_REJECT_REASONS} == {
            "off_enum",
            "unknown_kind",
            "type_illegal",
        }
        assert VERDICT_REJECT_REASONS <= ENGAGE_REJECT_REASONS


class TestErrorBodyModel:
    def test_forbids_extra_top_level_keys(self) -> None:
        """§7.1: optional keys belong under `details`, so the top level is closed."""
        with pytest.raises(ValidationError):
            ErrorBody(code=ErrorCode.INVALID_INPUT, message="m", how_to_proceed="nope")

    def test_accepts_the_canonical_shape(self) -> None:
        body = ErrorBody(
            code=ErrorCode.STRICT_TAG_REJECTED,
            message="rejected",
            rtm_code=None,
            details={"strict_tag_mode": True},
        )
        assert body.code is ErrorCode.STRICT_TAG_REJECTED
        assert body.details == {"strict_tag_mode": True}


class TestWriteBoundaryGateCodes:
    """The three write-boundary gates (tags / notes / list-targets) and their codes.

    The additive-only discipline in practice: the note-shape gate needed a NEW code, but
    the list-target gate reused two codes that already shipped. Re-spelling those (e.g. a
    `list_target_rejected`) would have created exactly the drift the unified registry
    exists to prevent — two names for one concept."""

    def test_note_shape_gate_has_its_own_code(self) -> None:
        assert ErrorCode.NOTE_SHAPE_REJECTED == "note_shape_rejected"

    def test_list_target_gate_reuses_existing_codes(self) -> None:
        """These predate the gate — smart_list_target from commit validation,
        locked_system_list from delete_list. The gate must not mint synonyms."""
        assert ErrorCode.SMART_LIST_TARGET == "smart_list_target"
        assert ErrorCode.LOCKED_SYSTEM_LIST == "locked_system_list"

    def test_no_synonym_codes_were_minted_for_the_gates(self) -> None:
        values = {c.value for c in ErrorCode}
        synonyms = {"list_target_rejected", "invalid_list_target", "note_title_rejected"}
        assert values & synonyms == set(), (
            "a gate minted a synonym for a concept the registry already names"
        )
