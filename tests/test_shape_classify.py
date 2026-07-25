"""Tests for `detectors.classify_shape` — single-item shape classification.

`shape-patterns.md` is the authority. The most valuable assertions here are the exhaustive ones:
**every pattern in the vocabulary must classify to its own shape, and every anti-pattern must
knock out what it claims to** — a spot-check would pass while a mis-transcribed regex sat unused.
The lockstep is structural (the classifier uses the same compiled objects as the detectors), so
`TestLockstep` pins the identity rather than re-listing the patterns.
"""

import pytest

from rtm_mcp.detectors import (
    DECISION_ANTI,
    DECISION_PATTERNS,
    DELIVERABLE_ANTI,
    DELIVERABLE_PATTERNS,
    RESEARCH_ANTI,
    RESEARCH_PATTERNS,
    SHAPE_ORDER,
    SHAPE_VERDICTS,
    classify_shape,
)

#: One name per pattern, in vocabulary order, chosen to trip exactly that pattern and survive its
#: own shape's anti-patterns. `shape-patterns.md` §§ research / draft / decide.
RESEARCH_NAMES = [
    "Find out what the licence covers",
    "Look into the vendor's uptime record",
    "Understand the new billing model",
    "Research the competitor landscape",
    "Investigate the latency spike",
    "Explore the partnership space",
    "Learn about the new framework",
    "Synthesise the interview notes",
    "Review the literature on team topologies",
    "Compare Postgres vs MySQL for this",
    "Compare Postgres versus MySQL for this",
    "Assess the feasibility of the migration",
    "Evaluate the options for the CRM",
]
DELIVERABLE_NAMES = [
    "Draft the onboarding spec",
    "Email Nektarios about the rota",
    "Send the quarterly pack",
    "Create the position paper",
    "Update the template for reviews",
    "Write up the retro",
    "Positioning statement for Hive",
    "Weekly status update for Digital",
    "RFD for the platform split",
    "One-pager on the AI policy",
    "Business case for the tooling spend",
    "Job spec for the EM role",
    "Offer letter for the new starter",
    "Appointment letter for Suares",
    "ALR for the permanent hire",
]
DECISION_NAMES = [
    "Decide the rollout window",
    "Decide between Vercel and Fly",
    "Choose between the two vendors",
    "Pick the approach for auth",
    "Evaluate the trade-offs for storage",
    "Review the trade-offs on hosting",
    "Make a decision on the rota",
    "Should we adopt the new framework",
    "What's the right approach for onboarding",
    "Pros and cons of the two vendors",
    "Weigh up the two proposals",
    "Approve the proposal for Q4",
    "Go/no-go decision on the pilot",
    "Sign-off on the design",
]


class TestEveryPatternClassifiesToItsOwnShape:
    """Exhaustive, so a mis-transcribed or shadowed pattern cannot hide."""

    @pytest.mark.parametrize("name", RESEARCH_NAMES)
    def test_research(self, name):
        assert classify_shape(name)["shape"] == "research", name

    @pytest.mark.parametrize("name", DELIVERABLE_NAMES)
    def test_draft(self, name):
        assert classify_shape(name)["shape"] == "draft", name

    @pytest.mark.parametrize("name", DECISION_NAMES)
    def test_decide(self, name):
        assert classify_shape(name)["shape"] == "decide", name

    def test_the_sample_set_covers_every_pattern_in_the_vocabulary(self):
        """Guard-the-guard: if a pattern is added to `shape-patterns.md` and mirrored into the
        constants, this fails until a name exercising it is added above."""
        for patterns, names, shape in (
            (RESEARCH_PATTERNS, RESEARCH_NAMES, "research"),
            (DELIVERABLE_PATTERNS, DELIVERABLE_NAMES, "draft"),
            (DECISION_PATTERNS, DECISION_NAMES, "decide"),
        ):
            for p in patterns:
                assert any(p.search(n) for n in names), f"{shape}: no sample trips {p.pattern}"


class TestAntiPatternsKnockOut:
    @pytest.mark.parametrize(
        ("name", "shape"),
        [
            ("Email about the research", "research"),
            ("Draft the research summary", "research"),
            ("Send the research findings", "research"),
            ("Decide what to research", "research"),
            ("Book a meeting about the research", "research"),
        ],
    )
    def test_research_anti_patterns(self, name, shape):
        out = classify_shape(name)
        assert shape in [k["shape"] for k in out["knocked_out"]], out

    @pytest.mark.parametrize(
        "name",
        [
            "Draft a decision on the vendor",
            "Draft the spec, then decide between A and B",
            "Draft the research brief",
            "Write the investigate-first plan",
            "Draft the note once we find out more",
            "Draft the plan, look into options first",
            "Draft the agenda and book meeting",
            "Draft the note and meet with Alex",
        ],
    )
    def test_deliverable_anti_patterns_knock_draft_out(self, name):
        out = classify_shape(name)
        assert "draft" in [k["shape"] for k in out["knocked_out"]], out

    @pytest.mark.parametrize(
        "name",
        [
            "Decide between vendors — email Alex first",
            "Draft the decision record for the split",
            "Decide the rota and send it out",
            "Decide after the research lands",
            "Decide once we investigate further",
            "Decide after we find out the cost",
            "Decide the venue, book meeting first",
            "Decide the plan and meet with Luke",
            "Write up the decision on hosting",
        ],
    )
    def test_decision_anti_patterns_knock_decide_out(self, name):
        out = classify_shape(name)
        assert "decide" not in [out["shape"]], out

    def test_the_sample_set_covers_every_anti_pattern(self):
        """Guard-the-guard for the knock-out side."""
        cases = {
            "research": (
                RESEARCH_ANTI,
                [
                    "Email about the research",
                    "Draft the research summary",
                    "Send the research findings",
                    "Decide what to research",
                    "Book a meeting about the research",
                    "Meet to research the options",
                ],
            ),
            "draft": (
                DELIVERABLE_ANTI,
                [
                    "Draft a decision on the vendor",
                    "Draft the spec, then decide between A and B",
                    "Draft the research brief",
                    "Write the investigate-first plan",
                    "Draft the note once we find out more",
                    "Draft the plan, look into options first",
                    "Draft the agenda and book meeting",
                    "Draft the note and meet with Alex",
                ],
            ),
            "decide": (
                DECISION_ANTI,
                [
                    "Decide between vendors — email Alex first",
                    "Draft the decision record for the split",
                    "Decide the rota and send it out",
                    "Decide after the research lands",
                    "Decide once we investigate further",
                    "Decide after we find out the cost",
                    "Decide the venue, book meeting first",
                    "Decide the plan and meet with Luke",
                    "Write up the decision on hosting",
                ],
            ),
        }
        for shape, (antis, names) in cases.items():
            for a in antis:
                assert any(a.search(n) for n in names), f"{shape}: no sample trips {a.pattern}"


class TestTheKnownAmbiguity:
    """`evaluate (the) options|alternatives|approaches` is in BOTH pattern sets. Deliberate."""

    @pytest.mark.parametrize(
        "name",
        [
            "Evaluate the options for the CRM",
            "Evaluate the alternatives for hosting",
            "Evaluate the approaches to onboarding",
        ],
    )
    def test_resolves_to_research_and_reports_decide_as_also_matched(self, name):
        out = classify_shape(name)
        assert out["shape"] == "research"
        assert out["also_matched"] == ["decide"], (
            "the runner-up must be SURFACED, not silently discarded"
        )


class TestNoMatchIsNeverAGuess:
    @pytest.mark.parametrize("name", ["Buy milk", "Call the dentist", "", "   ", "Tidy the garage"])
    def test_unclassifiable_returns_none(self, name):
        out = classify_shape(name)
        assert out["shape"] == "none"
        assert out["matched_pattern"] == ""
        assert out["also_matched"] == [] and out["knocked_out"] == []

    def test_a_calendar_entry_name_returns_none_because_brief_is_not_lexical(self):
        """`brief` is the #calendar_entry tag, which a name-only classifier cannot see. The
        caller applies the tag check; the classifier must not guess."""
        out = classify_shape("Book meeting with the platform team")
        assert out["shape"] == "none"

    def test_a_knocked_out_shape_explains_the_none(self):
        out = classify_shape("Email about the research")
        assert out["shape"] == "none"
        assert {k["shape"] for k in out["knocked_out"]} == {"research", "draft"}
        assert all(k["anti_pattern"] for k in out["knocked_out"])


class TestLockstep:
    def test_priority_order_is_research_draft_decide(self):
        assert SHAPE_ORDER == ("research", "draft", "decide")

    def test_the_verdict_vocabulary_adds_only_none(self):
        assert {"research", "draft", "decide", "none"} == SHAPE_VERDICTS

    def test_matching_is_case_insensitive(self):
        assert classify_shape("RESEARCH THE MARKET")["shape"] == "research"
        assert classify_shape("research the market")["shape"] == "research"

    def test_the_winning_pattern_is_reported(self):
        out = classify_shape("Research the competitor landscape")
        assert out["matched_pattern"] and "research" in out["matched_pattern"]

    def test_the_classifier_and_the_detectors_share_the_same_objects(self):
        """The lockstep contract — *an action the fan-out classifies as `draft` is one the
        deliverable detector would have found* — holds by CONSTRUCTION, not by two lists being
        kept in step. This asserts the identity, so a future copy-paste fails here."""
        from rtm_mcp.detectors import _SHAPE_RULES

        assert _SHAPE_RULES["research"][0] is RESEARCH_PATTERNS
        assert _SHAPE_RULES["research"][1] is RESEARCH_ANTI
        assert _SHAPE_RULES["draft"][0] is DELIVERABLE_PATTERNS
        assert _SHAPE_RULES["draft"][1] is DELIVERABLE_ANTI
        assert _SHAPE_RULES["decide"][0] is DECISION_PATTERNS
        assert _SHAPE_RULES["decide"][1] is DECISION_ANTI
