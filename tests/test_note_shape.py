"""Note-shape gate — the mechanical title-grammar write boundary.

Mirrors test_strict_tags.py in shape: pure-policy unit tests for the grammar plus the
three-mode enforcement flow (off / warn / shape).
"""

from unittest.mock import MagicMock

import pytest

from rtm_mcp.error_codes import ErrorCode
from rtm_mcp.note_shape import (
    VALID_STRICT_NOTES_MODES,
    check_title,
    effective_title,
    enforce_note_shape,
    guided_error,
)


def _client(mode: str) -> MagicMock:
    client = MagicMock()
    client.config = MagicMock(strict_notes=mode)
    return client


class TestCheckTitle:
    """The grammar itself: mechanical shape, never vocabulary."""

    @pytest.mark.parametrize(
        "title",
        [
            "2026-07-19 — OUTPUT — brief drafted",
            "2026-07-19 14:30 — CHAT — me — project",  # extra dashes ride in the summary
            "2026-07-19 — DEPENDS-ON — upstream task",  # hyphenated TYPE
            "2026-07-19 — AI LINK — surface item",  # spaced TYPE
            "2026-07-19T09:05 — ORDER — 4 items",  # T separator
            "2026-07-19 — OUTPUT — brief drafted – with an en-dash inside",  # noqa: RUF001
            "  2026-07-19 — OUTPUT — leading whitespace tolerated",
        ],
    )
    def test_accepts_well_formed_titles(self, title):
        assert check_title(title) is None

    @pytest.mark.parametrize(
        "title",
        [
            "",
            "   ",
            "OUTPUT — no date prefix",
            "2026-07-19 — OUTPUT",  # only one separator
            "2026-07-19 - OUTPUT - hyphen separators",  # not a dash
            "19-07-2026 — OUTPUT — wrong date order",
            "2026-07-19 — output — lowercase type",  # TYPE must be an uppercase token
            "2026-07-19 —  — empty type",
            "2026-07-19 — OUTPUT —   ",  # empty summary
        ],
    )
    def test_rejects_malformed_titles(self, title):
        assert check_title(title) is not None

    def test_en_dash_is_tolerated_like_the_gtd_validator(self):
        """The plugin validator WARNS on an en-dash rather than erroring, so this
        mechanical gate must not be stricter than the grammar it mirrors."""
        assert check_title("2026-07-19 – OUTPUT – brief drafted") is None  # noqa: RUF001

    def test_impossible_calendar_date_is_rejected(self):
        """The regex admits 2026-13-45; 'parseable date prefix' means a REAL date."""
        assert "not a real calendar date" in check_title("2026-13-45 — OUTPUT — x")
        assert "not a real calendar date" in check_title("2026-02-30 — OUTPUT — x")

    def test_impossible_wall_clock_time_is_rejected(self):
        assert "not a real wall-clock time" in check_title("2026-07-19 25:00 — OUTPUT — x")

    def test_unknown_type_passes_the_server_gate(self):
        """THE ownership boundary: the server checks that a TYPE token is well-formed,
        never that it is canonical. An off-vocabulary TYPE is the gtd validator's job —
        importing a vocabulary here would be exactly the drift the split prevents."""
        assert check_title("2026-07-19 — NOTATYPE — invented on the spot") is None


class TestEffectiveTitle:
    """RTM has no note-title field: the body is stored as `title\\ntext`."""

    def test_explicit_title_wins(self):
        assert effective_title("2026-07-19 — OUTPUT — x", "body line") == "2026-07-19 — OUTPUT — x"

    def test_falls_back_to_the_first_line_of_the_body(self):
        body = "2026-07-19 — OUTPUT — x\nthe body\nmore body"
        assert effective_title("", body) == "2026-07-19 — OUTPUT — x"

    def test_whitespace_only_title_falls_back(self):
        assert effective_title("   ", "first\nsecond") == "first"

    def test_single_line_body(self):
        assert effective_title("", "just one line") == "just one line"


class TestEnforceNoteShape:
    """The three modes. `off` must be byte-identical to pre-gate behaviour."""

    def test_off_is_inert_even_for_a_malformed_title(self):
        assert enforce_note_shape(_client("off"), "garbage", "body", tool="add_note") is None

    def test_absent_config_attribute_is_inert(self):
        """Defensive: a client whose config predates the field must not start rejecting."""
        client = MagicMock()
        client.config = MagicMock(spec=[])  # no strict_notes attribute at all
        assert enforce_note_shape(client, "garbage", "body", tool="add_note") is None

    def test_warn_logs_but_allows(self, caplog):
        with caplog.at_level("INFO"):
            result = enforce_note_shape(_client("warn"), "garbage", "body", tool="add_note")
        assert result is None
        assert "strict_notes(warn)" in caplog.text

    def test_shape_rejects_a_malformed_title(self):
        err = enforce_note_shape(_client("shape"), "garbage", "body", tool="add_note")
        assert err is not None
        assert err["error"]["code"] == ErrorCode.NOTE_SHAPE_REJECTED

    def test_shape_allows_a_well_formed_title(self):
        assert (
            enforce_note_shape(_client("shape"), "2026-07-19 — OUTPUT — x", "body", tool="add_note")
            is None
        )

    def test_shape_judges_the_body_first_line_when_no_title_given(self):
        """The inline-grammar path: callers that author `title\\ntext` are still gated."""
        assert (
            enforce_note_shape(
                _client("shape"), "", "2026-07-19 — OUTPUT — x\nbody", tool="add_note"
            )
            is None
        )
        assert (
            enforce_note_shape(_client("shape"), "", "no title here\nbody", tool="add_note")
            is not None
        )


class TestGuidedError:
    """The rejection must be deterministic, typed, and recoverable — never prose alone."""

    def test_carries_the_code_and_recovery_material(self):
        err = guided_error("garbage", "note title is empty")
        body = err["error"]
        assert body["code"] == ErrorCode.NOTE_SHAPE_REJECTED
        details = body["details"]
        assert details["rejected_title"] == "garbage"
        assert details["strict_notes_mode"] is True
        assert "YYYY-MM-DD" in details["expected_shape"]
        assert "RTM_STRICT_NOTES" in details["how_to_proceed"]

    def test_how_to_proceed_points_at_the_plugin_for_vocabulary(self):
        """Recovery guidance must not imply the server owns the TYPE vocabulary."""
        assert (
            "note-shape-catalogue" in guided_error("x", "y")["error"]["details"]["how_to_proceed"]
        )

    def test_recovery_guidance_matches_the_shipped_default(self):
        """The guidance is caller-facing recovery, so a stale default makes it actively wrong.
        Before v5.1.0 it said "unset RTM_STRICT_NOTES (default: off)" — advice that, once the
        gate ships on, tells a caller to do the exact thing that leaves it enabled."""
        how = guided_error("garbage", "malformed")["error"]["details"]["how_to_proceed"]
        assert "unset" not in how.lower()
        assert "RTM_STRICT_NOTES=off" in how


def test_mode_vocabulary_is_the_config_contract():
    assert VALID_STRICT_NOTES_MODES == ("off", "warn", "shape")


class TestTheShippedDefaultIsLive:
    """v5.1.0: the gate is ON by default, and that is a different claim from "the gate works".

    Every other test in this file forces a mode onto a `MagicMock` config, so they all passed
    for the two releases in which the gate shipped inert. These drive a REAL `RTMConfig`, which
    is the only way to assert what an operator who sets nothing actually gets.
    """

    @staticmethod
    def _real_client(monkeypatch) -> MagicMock:
        from rtm_mcp.config import RTMConfig

        monkeypatch.delenv("RTM_STRICT_NOTES", raising=False)
        client = MagicMock()
        client.config = RTMConfig()
        return client

    def test_a_malformed_title_is_rejected_with_no_env_set(self, monkeypatch):
        err = enforce_note_shape(self._real_client(monkeypatch), "garbage", "", tool="add_note")
        assert err is not None
        assert err["error"]["code"] == ErrorCode.NOTE_SHAPE_REJECTED

    def test_a_well_formed_title_still_passes(self, monkeypatch):
        client = self._real_client(monkeypatch)
        assert (
            enforce_note_shape(client, "2026-07-26 — OUTPUT — brief drafted", "", tool="x") is None
        )

    def test_an_off_vocabulary_TYPE_passes__the_ownership_boundary(self, monkeypatch):
        """The membrane, now that the gate is live: the server checks SHAPE, gtd owns the TYPE
        vocabulary (`note-shape-catalogue.md` § 2). Switching the gate on must not quietly
        promote it into a vocabulary gate — that is a separate, deliberately-sequenced change."""
        client = self._real_client(monkeypatch)
        assert (
            enforce_note_shape(client, "2026-07-26 — WIDGET — invented type", "", tool="x") is None
        )

    def test_the_legacy_ACTIVITY_spellings_pass_but_the_underscore_does_not(self, monkeypatch):
        """The measured live sample. `ACTIVITY`, `AR` and `ACTIVITY REPORT` are legacy spellings
        that still parse — a space is legal in a TYPE token — so switching the gate on does not
        invalidate history. `ACTIVITY_REPORT` is the v3.3.0 defect and is the one that fails:
        the TYPE token admits no underscore. Verified absent from live data before the flip."""
        client = self._real_client(monkeypatch)
        for legacy in ("ACTIVITY", "AR", "ACTIVITY REPORT"):
            assert (
                enforce_note_shape(client, f"2026-07-05 — {legacy} — scan report", "", tool="x")
                is None
            )
        assert (
            enforce_note_shape(client, "2026-07-05 — ACTIVITY_REPORT — x", "", tool="x") is not None
        )

    def test_pauls_free_text_note_is_rejected_only_because_it_is_an_MCP_WRITE(self, monkeypatch):
        """The free-text rule, pinned at the boundary where it actually holds.

        A note with no date prefix is Paul's own, typed into the RTM app, and is never a
        violation — but the app does not come through here. Through the MCP an undated title IS
        malformed, and rejecting it is right. The rule binds the gtd-side notes-audit, which
        scans EXISTING notes and would otherwise report Paul's prose as drift.
        """
        client = self._real_client(monkeypatch)
        assert enforce_note_shape(client, "make this a general slack message to all", "", tool="x")

    def test_off_restores_pre_gate_behaviour_byte_for_byte(self, monkeypatch):
        from rtm_mcp.config import RTMConfig

        monkeypatch.setenv("RTM_STRICT_NOTES", "off")
        client = MagicMock()
        client.config = RTMConfig()
        assert enforce_note_shape(client, "garbage", "", tool="add_note") is None
