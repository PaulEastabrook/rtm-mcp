"""Pure-builder tests for `contribution` — the CONTRIB state machine.

The state machine is canonical in `journaling-lifecycle.md` § "The contribution state machine";
these tests pin the codified copy against it. The judged/invalidated split gets the most attention
because it is the difference between a real acceptance rate and a misleading one — and because
nothing has ever transitioned a contribution, so there is no live behaviour to fall back on.
"""

from typing import ClassVar

import pytest

from rtm_mcp.contribution import (
    CONTRIB_STATES,
    INVALIDATED_STATES,
    JUDGED_STATES,
    OPEN_STATE,
    RETIRED_STATES,
    STATE_KIND,
    TERMINAL_STATES,
    artefact_path,
    category,
    current_state,
    find_state_note,
    make_update_note,
    note_type,
    rewrite_state,
    state_remainder,
    validate_transition,
)
from rtm_mcp.note_shape import check_title

CONTRIB_BODY = (
    "Drafted: work/research/options.md\n"
    "Category: research\n"
    "Confidence: high\n"
    "Trigger: research-and-synthesise (scheduled)\n"
    "State: drafted\n"
)


def _note(note_id, title, body, created="2026-07-20T09:00:00Z"):
    return {"id": note_id, "$t": f"{title}\n{body}", "created": created}


def _contrib_note(state="drafted", created="2026-07-20T09:00:00Z"):
    return _note(
        "n1",
        "2026-07-20 — CONTRIB — research — Synthesis of the options",
        CONTRIB_BODY.replace("State: drafted", f"State: {state}"),
        created,
    )


class TestTheStateMachine:
    def test_six_states_one_open_three_judged_two_invalidated(self):
        assert {
            "drafted",
            "accepted",
            "edited",
            "discarded",
            "superseded",
            "stale",
        } == CONTRIB_STATES
        assert OPEN_STATE == "drafted"
        assert {"accepted", "edited", "discarded"} == JUDGED_STATES
        assert {"superseded", "stale"} == INVALIDATED_STATES
        assert TERMINAL_STATES == JUDGED_STATES | INVALIDATED_STATES
        assert OPEN_STATE not in TERMINAL_STATES

    def test_the_judged_invalidated_split_is_carried_on_every_state(self):
        """Load-bearing: the acceptance rate denominator is the judged set alone."""
        assert {STATE_KIND[s] for s in JUDGED_STATES} == {"judged"}
        assert {STATE_KIND[s] for s in INVALIDATED_STATES} == {"invalidated"}
        assert STATE_KIND[OPEN_STATE] == "open"

    def test_retired_values_are_not_states(self):
        assert {"offered", "archived", "surfaced"} == RETIRED_STATES
        assert not (RETIRED_STATES & CONTRIB_STATES)


class TestValidation:
    @pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
    def test_every_terminal_is_reachable_from_drafted(self, state):
        assert validate_transition(state=state, note_found=True, from_state="drafted") == []

    @pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
    def test_terminal_to_terminal_is_always_rejected(self, state):
        for current in sorted(TERMINAL_STATES):
            out = validate_transition(state=state, note_found=True, from_state=current)
            assert out and out[0]["reason"] == "invalid_input", (current, state)

    def test_a_note_with_no_state_line_still_transitions(self):
        """6 of 39 live notes carry no `State:` line — the old wiring's fault, not the caller's.
        Refusing would leave exactly those permanently stuck."""
        assert validate_transition(state="accepted", note_found=True, from_state="") == []

    def test_the_open_state_is_not_a_transition_target(self):
        out = validate_transition(state="drafted", note_found=True, from_state="drafted")
        assert out[0]["reason"] == "off_enum"
        assert "OPEN state" in out[0]["detail"]

    @pytest.mark.parametrize("state", sorted(RETIRED_STATES))
    def test_a_retired_state_is_rejected_and_says_so(self, state):
        out = validate_transition(state=state, note_found=True, from_state="drafted")
        assert out[0]["reason"] == "off_enum"
        assert "RETIRED" in out[0]["detail"]

    def test_an_unknown_state_is_off_enum(self):
        out = validate_transition(state="nonsense", note_found=True, from_state="drafted")
        assert out[0]["reason"] == "off_enum"

    def test_no_contribution_note_is_its_own_reason(self):
        out = validate_transition(state="accepted", note_found=False, from_state="")
        assert out[0]["reason"] == "no_contribution_note"

    def test_off_enum_is_checked_before_the_missing_note(self):
        """A bad state and a missing note both apply; the caller should hear the input error."""
        out = validate_transition(state="nonsense", note_found=False, from_state="")
        assert [r["reason"] for r in out] == ["off_enum"]


class TestNoteLocation:
    def test_finds_the_contrib_note(self):
        task = {"notes": [_contrib_note()]}
        assert find_state_note(task)["id"] == "n1"

    def test_finds_a_prep_note_too(self):
        task = {"notes": [_note("p1", "2026-07-20 — PREP — agenda", "State: drafted")]}
        assert find_state_note(task)["id"] == "p1"

    def test_a_contrib_update_is_NOT_the_state_bearer(self):
        """The catalogue says the ORIGINAL CONTRIB note's State is updated; an UPDATE records a
        transition rather than holding the state. A prefix match would wrongly pick it."""
        task = {
            "notes": [
                _contrib_note(created="2026-07-20T09:00:00Z"),
                _note(
                    "n2", "2026-07-24 — CONTRIB-UPDATE — research — x", "", "2026-07-24T09:00:00Z"
                ),
            ]
        }
        assert find_state_note(task)["id"] == "n1"

    def test_latest_state_bearing_note_wins(self):
        task = {
            "notes": [
                _contrib_note(created="2026-07-20T09:00:00Z"),
                _note(
                    "n3",
                    "2026-07-24 — CONTRIB — research — later",
                    "State: drafted",
                    "2026-07-24T09:00:00Z",
                ),
            ]
        }
        assert find_state_note(task)["id"] == "n3"

    def test_no_contrib_note_returns_none(self):
        assert find_state_note({"notes": [_note("x", "2026-07-20 — CONTEXT — x", "")]}) is None
        assert find_state_note({"notes": []}) is None

    def test_hyphenated_types_are_not_split_at_their_own_hyphen(self):
        assert note_type("2026-07-20 — CONTRIB-UPDATE — x — y") == "CONTRIB-UPDATE"
        assert note_type("2026-07-20 — DEPENDS-ON — x") == "DEPENDS-ON"


class TestBodyFields:
    def test_reads_state_category_and_artefact(self):
        assert current_state(CONTRIB_BODY) == "drafted"
        assert category(CONTRIB_BODY, "") == "research"
        assert artefact_path(CONTRIB_BODY) == "work/research/options.md"

    def test_missing_state_line_reads_as_empty_not_a_guess(self):
        assert current_state("Drafted: a.md\nCategory: draft") == ""

    def test_prep_defaults_to_its_brief_alias(self):
        assert category("Confidence: high", "2026-07-20 — PREP — agenda") == "brief"

    def test_rewrite_replaces_the_existing_state_line(self):
        out = rewrite_state(CONTRIB_BODY, "accepted")
        assert current_state(out) == "accepted"
        assert "State: drafted" not in out
        # every other line survives untouched
        assert "Drafted: work/research/options.md" in out and "Confidence: high" in out

    def test_rewrite_appends_when_there_is_no_state_line(self):
        out = rewrite_state("Drafted: a.md\nCategory: draft", "edited")
        assert current_state(out) == "edited"

    def test_rewrite_preserves_indentation(self):
        assert "  State: stale" in rewrite_state("x\n  State: drafted\ny", "stale")

    def test_only_the_first_state_line_is_rewritten(self):
        out = rewrite_state("State: drafted\nnarrative mentioning State: drafted", "accepted")
        assert out.startswith("State: accepted")


class TestUpdateNote:
    def test_title_passes_the_note_shape_gate(self):
        """The server writing a title its own validator rejects is exactly the ACTIVITY_REPORT
        defect; this pins that it cannot recur here."""
        for state in sorted(TERMINAL_STATES):
            title, _ = make_update_note(
                state=state,
                previous_state="drafted",
                note="x",
                category_name="research",
                original_note_id="n1",
                artefact="work/x.md",
                date="2026-07-25",
            )
            assert check_title(title) is None, (state, title)

    def test_body_records_the_transition_and_its_kind(self):
        _, text = make_update_note(
            state="accepted",
            previous_state="drafted",
            note="Used as-is.",
            category_name="research",
            original_note_id="n1",
            artefact="work/x.md",
            date="2026-07-25",
        )
        assert "Transition: drafted → accepted" in text
        assert "State: accepted" in text
        assert "Kind: judged" in text
        assert "Original CONTRIB: n1" in text
        assert "Artefact: work/x.md" in text
        assert "Used as-is." in text
        assert "#ai_conversation" in text

    def test_update_mode_appears_only_for_the_invalidated_pair(self):
        """The catalogue's `Update mode:` vocabulary (addendum|delta|revision|stale) describes a
        REASSESSMENT, and maps onto exactly the two invalidated states. A judged transition has
        no meaningful value there, so the line is omitted rather than forced."""
        for state, mode in (("superseded", "revision"), ("stale", "stale")):
            _, text = make_update_note(
                state=state,
                previous_state="drafted",
                note="",
                category_name="draft",
                original_note_id="n1",
                artefact="",
                date="2026-07-25",
            )
            assert f"Update mode: {mode}" in text
        for state in sorted(JUDGED_STATES):
            _, text = make_update_note(
                state=state,
                previous_state="drafted",
                note="",
                category_name="draft",
                original_note_id="n1",
                artefact="",
                date="2026-07-25",
            )
            assert "Update mode:" not in text

    def test_an_unset_previous_state_is_named_not_blank(self):
        title, text = make_update_note(
            state="accepted",
            previous_state="",
            note="",
            category_name="draft",
            original_note_id="n1",
            artefact="",
            date="2026-07-25",
        )
        assert "unset → accepted" in title and "unset → accepted" in text


class TestLiveStateLineContamination:
    """3 of 39 live notes carry prose after the state word on the `State:` line. Reading the whole
    line would make each an unrecognised state; dropping the prose on rewrite would be a quiet
    deletion. Both are pinned here against the exact live shapes."""

    LIVE_LINES: ClassVar[list[tuple[str, str]]] = [
        (
            "State: drafted (production happened in the interactive session — see the two output "
            "notes of 2026-07-04; this scan pass adds the #ai_contrib_drafted state tag)",
            "(production happened",
        ),
        ("State: drafted — pending paul's review (#ai_output_review_needed)", "— pending"),
        ("State: drafted → offered", "→ offered"),
    ]

    @pytest.mark.parametrize(("line", "remainder_prefix"), LIVE_LINES)
    def test_state_is_the_first_token_only(self, line, remainder_prefix):
        assert current_state(line) == "drafted"
        assert state_remainder(line).startswith(remainder_prefix)

    @pytest.mark.parametrize(("line", "_r"), LIVE_LINES)
    def test_such_a_note_is_still_transitionable(self, line, _r):
        assert (
            validate_transition(state="accepted", note_found=True, from_state=current_state(line))
            == []
        )

    @pytest.mark.parametrize(("line", "_r"), LIVE_LINES)
    def test_rewrite_produces_a_clean_machine_field(self, line, _r):
        out = rewrite_state(line, "accepted")
        assert out == "State: accepted", "prose must not survive into the new state value"

    def test_the_discarded_prose_is_carried_into_the_update_note(self):
        line, _ = self.LIVE_LINES[1]
        _, text = make_update_note(
            state="accepted",
            previous_state=current_state(line),
            note="",
            category_name="draft",
            original_note_id="n1",
            artefact="",
            date="2026-07-25",
            superseded_text=state_remainder(line),
        )
        assert "Superseded State: annotation:" in text
        assert "pending paul's review" in text

    def test_a_clean_line_adds_no_annotation(self):
        _, text = make_update_note(
            state="accepted",
            previous_state="drafted",
            note="",
            category_name="draft",
            original_note_id="n1",
            artefact="",
            date="2026-07-25",
            superseded_text=state_remainder("State: drafted"),
        )
        assert "Superseded State:" not in text

    def test_agreement_with_engine_report(self):
        """The two must never disagree about what state a note is in."""
        from rtm_mcp.engine_report import contribution_facets

        for line, _ in self.LIVE_LINES:
            body = f"Drafted: x.md\nCategory: draft\n{line}\n"
            note = {"id": "n", "$t": f"2026-07-20 — CONTRIB — draft — x\n{body}"}
            assert contribution_facets(note)[1] == current_state(body) == "drafted"
