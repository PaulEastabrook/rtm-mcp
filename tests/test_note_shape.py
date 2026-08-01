"""Note-shape gate — the title-grammar and vocabulary write boundary.

Mirrors test_strict_tags.py in shape: pure-policy unit tests for the grammar plus the
four-mode enforcement escalation (off / warn / shape / vocabulary).
"""

from types import SimpleNamespace
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

    def test_how_to_proceed_points_at_the_catalogue_for_a_vocabulary_rejection(self):
        """The server now ENFORCES the vocabulary but still does not OWN it.

        Through v5.1.x this assertion sat on the shape rejection, where it meant "we check shape,
        they own types". Since v5.2.0 the server checks types too — so the pointer moves to the
        vocabulary rejection, where it now means something sharper: a new type is added to the
        catalogue FIRST, never minted at the call site. Codification before validation.
        """
        how = guided_error("x", "y", kind="vocabulary")["error"]["details"]["how_to_proceed"]
        assert "note-shape-catalogue" in how
        assert "first" in how.lower()

    def test_the_two_rejection_kinds_are_distinguishable_without_a_new_error_code(self):
        for kind in ("shape", "vocabulary"):
            err = guided_error("x", "y", kind=kind)["error"]
            assert err["code"] == "note_shape_rejected"
            assert err["details"]["rejected_by"] == kind

    def test_recovery_guidance_matches_the_shipped_default(self):
        """The guidance is caller-facing recovery, so a stale default makes it actively wrong.
        Before v5.1.0 it said "unset RTM_STRICT_NOTES (default: off)" — advice that, once the
        gate ships on, tells a caller to do the exact thing that leaves it enabled."""
        how = guided_error("garbage", "malformed")["error"]["details"]["how_to_proceed"]
        assert "unset" not in how.lower()
        assert "RTM_STRICT_NOTES=off" in how


def test_mode_vocabulary_is_the_config_contract():
    """An escalation, in order. `vocabulary` was appended in v5.2.0; `shape` stays as the
    byte-for-byte rollback step, which is why it is not simply replaced."""
    assert VALID_STRICT_NOTES_MODES == ("off", "warn", "shape", "vocabulary")


class TestTheShippedDefaultIsLive:
    """v5.1.0: the gate is ON by default, and that is a different claim from "the gate works".

    Every other test in this file forces a mode onto a `MagicMock` config, so they all passed
    for the two releases in which the gate shipped inert. These drive a REAL `RTMConfig`, which
    is the only way to assert what an operator who sets nothing actually gets.
    """

    @staticmethod
    def _real_client(monkeypatch, mode: str | None = None) -> MagicMock:
        from rtm_mcp.config import RTMConfig

        monkeypatch.delenv("RTM_STRICT_NOTES", raising=False)
        if mode is not None:
            monkeypatch.setenv("RTM_STRICT_NOTES", mode)
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

    def test_an_off_vocabulary_TYPE_is_now_REJECTED__the_boundary_moved(self, monkeypatch):
        """**This assertion was inverted in v5.2.0, and the inversion is the change.**

        Through v5.1.x it read "an off-vocabulary TYPE passes — the ownership boundary": the
        server checked shape, gtd owned the vocabulary, and promoting the gate was called out as
        a separate, deliberately-sequenced change. That change is this one. The sequencing held —
        it landed only after the vocabulary was measured (~40 tokens / 114 notes, 2026-07-31) and
        the corpus scheduled for remediation.

        What did NOT move is who OWNS the vocabulary: `note-shape-catalogue.md` § 2 is still the
        authority and the server codifies it. Enforcement moved; authorship did not.
        """
        client = self._real_client(monkeypatch)
        assert (
            enforce_note_shape(client, "2026-07-26 — WIDGET — invented type", "", tool="x")
            is not None
        )

    def test_shape_mode_restores_the_old_boundary_exactly(self, monkeypatch):
        """The rollback is one env var, and it must land on the PREVIOUS behaviour, not near it."""
        client = self._real_client(monkeypatch, mode="shape")
        assert (
            enforce_note_shape(client, "2026-07-26 — WIDGET — invented type", "", tool="x") is None
        )

    def test_every_legacy_ACTIVITY_spelling_is_now_unwritable(self, monkeypatch):
        """Also inverted in v5.2.0 — and this is the inversion the gate exists FOR.

        In `shape` mode all three legacy spellings passed, because a space is legal in a TYPE
        token. That is exactly how four spellings of one concept accumulated. They now fail on
        different grounds, and the distinction is worth keeping: `ACTIVITY` and `AR` are
        well-SHAPED but unregistered; `ACTIVITY_REPORT` never parsed at all, the TYPE token
        admitting no underscore.

        They remain READABLE throughout — see test_note_types.py. Unwritable is not unreadable,
        and conflating the two would mis-classify every legacy note on the surface lists.
        """
        client = self._real_client(monkeypatch)
        for legacy in ("ACTIVITY", "AR", "ACTIVITY REPORT"):
            err = enforce_note_shape(client, f"2026-07-05 — {legacy} — scan report", "", tool="x")
            assert err is not None, legacy
            assert err["error"]["details"]["rejected_by"] == "vocabulary", legacy
        underscore = enforce_note_shape(client, "2026-07-05 — ACTIVITY_REPORT — x", "", tool="x")
        assert underscore["error"]["details"]["rejected_by"] == "shape"

    def test_the_canonical_replacement_for_each_legacy_spelling_writes(self, monkeypatch):
        """A gate that refuses the old spelling without accepting the new one is just an outage."""
        client = self._real_client(monkeypatch)
        assert (
            enforce_note_shape(client, "2026-07-05 — ACTIVITY-REPORT — scan report", "", tool="x")
            is None
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


class TestVocabularyTier:
    """`vocabulary` mode — the v5.2.0 default. Grammar AND a registered TYPE.

    The reversal these tests pin: through v5.1.x a well-shaped title with an off-vocabulary TYPE
    passed here by design (the CONTRIBUTING § 6 membrane), and the plugin validator caught it —
    when a caller remembered to run it. A 2026-07-31 census measured what that cost: ~40 tokens
    across 114 notes over five months. A gate that can be forgotten is not a gate.
    """

    def _gate(self, mode, title):
        client = SimpleNamespace(config=SimpleNamespace(strict_notes=mode))
        return enforce_note_shape(client, title, "", tool="add_note")

    def test_registered_type_passes(self):
        assert self._gate("vocabulary", "2026-08-01 — CONTEXT — fine") is None

    def test_unregistered_type_is_rejected(self):
        err = self._gate("vocabulary", "2026-08-01 — EXECUTOR — skipped")
        assert err is not None
        assert err["error"]["code"] == "note_shape_rejected"

    def test_shape_mode_still_lets_an_unregistered_type_through(self):
        """The rollback step must reproduce v5.1.0 byte-for-byte, or it is not a rollback."""
        assert self._gate("shape", "2026-08-01 — EXECUTOR — skipped") is None

    def test_off_mode_lets_everything_through(self):
        assert self._gate("off", "not a title at all") is None

    def test_a_malformed_title_is_a_SHAPE_finding_not_a_vocabulary_one(self):
        """Ordering matters: an unparseable title has no TYPE to judge, so shape reports first."""
        err = self._gate("vocabulary", "no date prefix here")
        assert err["error"]["details"]["rejected_by"] == "shape"

    def test_a_well_shaped_unregistered_type_is_a_VOCABULARY_finding(self):
        err = self._gate("vocabulary", "2026-08-01 — EXECUTOR — skipped")
        assert err["error"]["details"]["rejected_by"] == "vocabulary"

    def test_no_new_error_code_was_minted(self):
        """A `note_vocabulary_rejected` synonym would churn all 100 fingerprints for a
        distinction `error.details` already carries — the drift the unified registry removed."""
        for title in ("no date prefix", "2026-08-01 — EXECUTOR — x"):
            assert self._gate("vocabulary", title)["error"]["code"] == "note_shape_rejected"

    def test_the_vocabulary_rejection_teaches_codification_before_validation(self):
        how = self._gate("vocabulary", "2026-08-01 — EXECUTOR — x")["error"]["details"][
            "how_to_proceed"
        ]
        assert "note-shape-catalogue.md" in how  # where a NEW type is added
        assert "first" in how.lower()  # ...and that it goes there FIRST
        assert "gtd_note_add" in how  # the governed path that avoids this entirely
        assert "RTM_STRICT_NOTES=shape" in how  # the precise rollback, not just "off"

    def test_warn_mode_logs_a_vocabulary_finding_but_allows_it(self):
        assert self._gate("warn", "2026-08-01 — EXECUTOR — x") is None


class TestTheShippedVocabularyDefaultIsLive:
    """Drives a REAL RTMConfig, not a mode-forced double.

    Every test in `TestVocabularyTier` passes against a server where the default is still
    `shape` — the exact vacuity that let the note-shape gate ship inert for two releases while
    its own suite stayed green.
    """

    def _real(self):
        from rtm_mcp.config import RTMConfig

        cfg = RTMConfig(api_key="k", shared_secret="s", auth_token="t")
        return SimpleNamespace(config=cfg)

    def test_the_default_mode_is_vocabulary(self):
        assert self._real().config.strict_notes == "vocabulary"

    def test_an_unregistered_type_is_rejected_with_no_env_set(self):
        err = enforce_note_shape(
            self._real(), "2026-08-01 — EXECUTOR — skipped", "", tool="add_note"
        )
        assert err is not None
        assert err["error"]["details"]["rejected_by"] == "vocabulary"

    def test_a_legacy_surface_spelling_is_rejected_with_no_env_set(self):
        err = enforce_note_shape(self._real(), "2026-08-01 — Q — legacy", "", tool="add_note")
        assert err is not None
        assert "LEGACY" in err["error"]["details"]["reason"]

    def test_a_registered_type_still_writes(self):
        assert (
            enforce_note_shape(self._real(), "2026-08-01 — SCOPE — refocused", "", tool="add_note")
            is None
        )
