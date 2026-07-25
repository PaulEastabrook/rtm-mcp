"""Tests for the D9 tool-naming conformance check (`scripts/check-tool-naming.py`).

**The most important assertions here are that the check FIRES**, not that the suite is clean. A
conformance check reporting zero findings because it silently skipped everything is worse than no
check at all — it converts "not tested" into "clean bill of health", which is the exact failure
shape this programme has now found five times over. So every rule is exercised against a known-bad
fixture, and the unclassifiable path is asserted rather than assumed.
"""

from importlib import util
from pathlib import Path

import pytest

_SPEC = util.spec_from_file_location(
    "check_tool_naming", Path(__file__).resolve().parents[1] / "scripts" / "check-tool-naming.py"
)
assert _SPEC and _SPEC.loader
check = util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check)


class TestTheCheckFires:
    """Known-bad fixtures. If any of these stops being a finding, the check has gone blind."""

    @pytest.mark.parametrize(
        ("name", "read_only"),
        [
            ("gtd_item_classify", True),  # the real Wave 1b drift
            ("gtd_health_check", True),  # ⚠ a read named imperatively
            ("gtd_thing_create", True),  # a create that claims to be read-only
            ("gtd_note_edit", True),  # an edit that claims to be read-only
        ],
    )
    def test_imperative_on_a_read_is_a_finding(self, name, read_only):
        verdict, detail = check.classify(name, read_only)
        assert verdict == "finding", (name, detail)
        assert "READ-ONLY" in detail

    @pytest.mark.parametrize("name", ["gtd_item_report", "gtd_thing_index", "gtd_thing_queue"])
    def test_result_noun_on_a_write_is_a_finding(self, name):
        verdict, detail = check.classify(name, read_only=False)
        assert verdict == "finding", (name, detail)
        assert "WRITING" in detail

    def test_the_check_would_have_caught_the_drift_it_exists_for(self):
        """`gtd_item_classify` shipped four days after the standard was frozen, in a wave whose
        own brief claimed conformance. This is the assertion that it cannot recur silently."""
        assert check.classify("gtd_item_classify", True)[0] == "finding"
        assert check.classify("gtd_item_shape", True)[0] == "ok"


class TestUnclassifiableNeverPasses:
    """The rule that matters most: a name the lexicons do not recognise must SURFACE."""

    @pytest.mark.parametrize(
        ("name", "read_only"),
        [
            ("gtd_frobnicate_widget", True),  # a novel verb — the escape route
            ("gtd_frobnicate_widget", False),
            ("gtd_inbox_zero", False),  # a write named as a noun phrase (the GTD end-state)
            ("gtd_wibble", True),
        ],
    )
    def test_unrecognised_names_are_reported_not_passed(self, name, read_only):
        verdict, detail = check.classify(name, read_only)
        assert verdict == "unclassifiable", (name, verdict)
        assert "must not pass by silence" in detail

    def test_zero_is_not_an_imperative(self):
        """`zero` was briefly in the imperative lexicon, which made the check BLESS
        `gtd_inbox_zero` — the very name Wave 2 renames for being misleading."""
        assert "zero" not in check.IMPERATIVE_SEGMENTS


class TestConformantNamesPass:
    @pytest.mark.parametrize(
        ("name", "read_only"),
        [
            ("gtd_canvas_commit", False),
            ("gtd_item_create", False),
            ("gtd_inbox_drain", False),
            ("gtd_waiting_for_sweep", False),
            ("gtd_health_report", True),
            ("gtd_surface_queue", True),
            ("gtd_focus_index", True),
            ("gtd_item_shape", True),
            ("gtd_item_today", True),
        ],
    )
    def test_ok(self, name, read_only):
        assert check.classify(name, read_only)[0] == "ok", check.classify(name, read_only)

    def test_the_suffix_beats_an_imperative_looking_noun_adjunct(self):
        """`capture` in `gtd_capture_candidates` is the contribution SHAPE, not a verb. This was
        the check's own first false positive, on its first run."""
        assert check.classify("gtd_capture_candidates", True)[0] == "ok"
        for shape in ("decision", "deliverable", "research", "reassessment", "unblock"):
            assert check.classify(f"gtd_{shape}_candidates", True)[0] == "ok"

    def test_gtd_item_stale_resolves_via_the_documented_adjective_filter(self):
        """The brief predicted this would be the first unclassifiable. The query lexicon was
        extended with a documented adjective-filter form rather than renaming a Wave 1 tool."""
        assert "stale" in check.ADJECTIVE_FILTERS
        assert "stale" not in check.RESULT_NOUNS, "in both, the adjective-filter branch is dead"
        verdict, detail = check.classify("gtd_item_stale", True)
        assert verdict == "ok" and "adjective-filter" in detail


class TestExemptions:
    def test_nothing_is_exempt_by_silence(self):
        """Every exemption carries a stated reason."""
        assert check.EXEMPT
        for name, reason in check.EXEMPT.items():
            assert reason.strip(), name

    def test_next_actions_is_the_documented_ubiquitous_language_exception(self):
        verdict, detail = check.classify("gtd_next_actions", True)
        assert verdict == "exempt" and "ubiquitous-language" in detail


class TestAgainstTheLiveServer:
    async def test_no_findings_and_nothing_unclassifiable(self):
        rows = await check.collect()
        bad = [r for r in rows if r["verdict"] in ("finding", "unclassifiable")]
        assert bad == [], f"non-conformant tool names: {bad}"

    async def test_deprecated_aliases_are_bucketed_not_judged(self):
        """The aliases ARE the non-conformant names — judging them would fire on all 26 by
        construction, which is why the check is report-only until they are removed."""
        from rtm_mcp.tools.gtd import DEPRECATED_ALIASES

        rows = {r["tool"]: r for r in await check.collect()}
        for old in (*DEPRECATED_ALIASES, "gtd_query"):
            assert rows[old]["verdict"] == "deprecated", old

    async def test_every_live_tool_reaches_a_verdict(self):
        """No tool may be absent from the report — silence is the failure mode."""
        rows = await check.collect()
        assert all(r["verdict"] for r in rows)
        assert len(rows) >= 55
