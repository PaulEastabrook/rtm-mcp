"""Pure-builder tests for `engine_report` — proactive-contribution engine telemetry.

`TestRegressionAgainstTheRetiredScript` is the point of this file. `engine-telemetry-aggregator.ms`
reported structural zeros for every window-scoped figure for its whole life, across four
independent faults, and two live scheduled tasks have been raising adaptation proposals from those
zeros every week. Each fixture below is built so that **the old logic scores 0 and the correct
logic scores non-zero** — a test that merely exercised the happy path would have passed against
the broken script too, which is exactly how this went unnoticed. The arithmetic has never been
tested before now.
"""

from datetime import UTC, datetime, timedelta

from rtm_mcp.engine_report import (
    ACTIVITY_BLOAT_THRESHOLD,
    CONTRIB_STATES,
    QUESTIONS_BLOAT_THRESHOLD,
    build_contributions,
    build_engine_report,
    build_speculation,
    build_surface_side,
    contribution_facets,
    contribution_note,
)

NOW = "2026-07-25T09:00:00Z"
WINDOW_START = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)


def _iso(days_ago):
    return (datetime(2026, 7, 25, 9, 0, tzinfo=UTC) - timedelta(days=days_ago)).isoformat()


def _contrib_note(state="accepted", category="research", note_type="CONTRIB", created=None):
    body = (
        f"{'2026-07-20'} — {note_type} — Synthesis of the options\n"
        "Drafted: work/research/options.md\n"
        f"Category: {category}\n"
        "Confidence: high\n"
        f"State: {state}\n"
    )
    return {"id": "n1", "$t": body, "created": created or _iso(3)}


def _task(task_id="1", created=None, modified=None, notes=None, tags=None, completed=None):
    return {
        "id": task_id,
        "name": f"task {task_id}",
        "tags": tags if tags is not None else ["ai_contrib_drafted"],
        "notes": notes if notes is not None else [_contrib_note()],
        "created": created,
        "modified": modified,
        "completed": completed,
    }


def _report(**over):
    kwargs = {
        "contributions": [],
        "questions": [],
        "activity": [],
        "speculative": [],
        "deferred": [],
        "now": NOW,
        "window_days": 7,
        "today": "2026-07-25",
    }
    kwargs.update(over)
    return build_engine_report(**kwargs)


class TestRegressionAgainstTheRetiredScript:
    """Each fixture FAILS under the old script's logic and passes under the corrected logic."""

    def test_fault_1_a_task_in_window_is_counted_not_skipped(self):
        """Old: `getCreated()`/`getModified()` don't exist, the guard returned null, `inWindow(null)`
        was false, EVERY task was skipped. Old score: 0. Correct score: 1."""
        out = build_contributions(
            [_task(created=_iso(3), modified=_iso(1))], window_start=WINDOW_START
        )
        assert out["drafted_in_window"] == 1
        assert out["acceptance_rate_pct"] == 100

    def test_fault_2_created_outside_but_modified_inside_is_the_canonical_case(self):
        """The brief's canonical case. Old (and naive) logic keys the window on MODIFIED and
        counts this in the cohort; the window is a CREATION cohort, so it must not be — but it
        must still appear under `touched_in_window`, not vanish."""
        task = _task(created=_iso(40), modified=_iso(2))
        out = build_contributions([task], window_start=WINDOW_START)
        assert out["drafted_in_window"] == 0, "modified-in-window must not enter the cohort"
        assert out["touched_in_window"] == 1, "and must not be silently dropped either"

    def test_fault_2_the_two_figures_genuinely_diverge(self):
        """Live 30-day window at the time of the fix: 12 created vs 37 modified. Conflating them
        is not a rounding difference."""
        tasks = [
            _task("a", created=_iso(2), modified=_iso(1)),
            _task("b", created=_iso(40), modified=_iso(1)),
            _task("c", created=_iso(40), modified=_iso(40)),
        ]
        out = build_contributions(tasks, window_start=WINDOW_START)
        assert (out["drafted_in_window"], out["touched_in_window"]) == (1, 2)

    def test_fault_3_note_facets_resolve_instead_of_unknown(self):
        """Old: `note.getTitle()`/`.getBody()` don't exist either, so category and state were
        `"unknown"` for every contribution — a SECOND independent path to a 0% acceptance rate,
        which survived the 2026-07-24 correctness pass untouched."""
        category, state = contribution_facets(_contrib_note(state="accepted", category="research"))
        assert (category, state) == ("research", "accepted")

    def test_fault_4_state_is_read_from_State_not_Phase(self):
        """Old: matched `/Phase:\\s*(\\w+)/`. The canonical body field is `State:`; live, `State:`
        appears on 33 of 39 contribution notes and `Phase:` on ZERO."""
        note = {"id": "n", "$t": "2026-07-20 — CONTRIB — x\nPhase: accepted\n", "created": _iso(2)}
        assert contribution_facets(note)[1] == "unknown", "a Phase: line is not the contract"
        note = {"id": "n", "$t": "2026-07-20 — CONTRIB — x\nState: accepted\n", "created": _iso(2)}
        assert contribution_facets(note)[1] == "accepted"

    def test_all_four_faults_together_on_one_realistic_cohort(self):
        """The end-to-end assertion: the old pipeline scores 0% acceptance here on four separate
        grounds; the corrected pipeline scores 50%."""
        tasks = [
            _task("a", created=_iso(2), modified=_iso(1), notes=[_contrib_note("accepted")]),
            _task("b", created=_iso(3), modified=_iso(1), notes=[_contrib_note("discarded")]),
            _task("c", created=_iso(40), modified=_iso(1), notes=[_contrib_note("accepted")]),
        ]
        out = build_contributions(tasks, window_start=WINDOW_START)
        assert out["drafted_in_window"] == 2
        assert out["acceptance_rate_pct"] == 50
        assert out["discard_rate_pct"] == 50
        assert out["by_state"] == {"accepted": 1, "discarded": 1}


class TestContributionFacets:
    def test_category_comes_from_the_body_not_the_title(self):
        """Live: 35 of 39 CONTRIB titles carry no category segment, and the 4 that parse yield
        summary prose. The body `Category:` line is the canonical carrier."""
        note = {
            "id": "n",
            "$t": "2026-07-20 — CONTRIB — Chase queue largely cleared\nCategory: monitor\nState: drafted\n",
            "created": _iso(2),
        }
        assert contribution_facets(note)[0] == "monitor"

    def test_title_segment_is_a_fallback_only_when_it_is_a_real_category(self):
        note = {
            "id": "n",
            "$t": "2026-07-20 — CONTRIB — Research — options\nState: drafted\n",
            "created": _iso(2),
        }
        assert contribution_facets(note)[0] == "research"

    def test_a_title_summary_masquerading_as_a_category_is_rejected(self):
        note = {
            "id": "n",
            "$t": "2026-07-20 — CONTRIB — draft slack-message: conor chase — x\nState: drafted\n",
            "created": _iso(2),
        }
        assert contribution_facets(note)[0] == "unknown"

    def test_prep_defaults_to_its_permanent_brief_alias(self):
        note = {"id": "n", "$t": "2026-07-20 — PREP — agenda\nState: drafted\n", "created": _iso(2)}
        assert contribution_facets(note) == ("brief", "drafted")

    def test_latest_note_wins_so_a_contrib_update_supersedes(self):
        task = _task(
            notes=[
                _contrib_note("drafted", note_type="CONTRIB", created=_iso(5)),
                _contrib_note("accepted", note_type="CONTRIB-UPDATE", created=_iso(1)),
            ]
        )
        assert contribution_facets(contribution_note(task))[1] == "accepted"

    def test_no_contribution_note_is_unknown_not_a_crash(self):
        assert contribution_facets(contribution_note(_task(notes=[]))) == ("unknown", "unknown")

    def test_an_observed_state_outside_both_vocabularies_is_still_counted(self):
        """Live estate carries `surfaced`, which is in neither published vocabulary. The report
        describes what is there rather than dropping it."""
        assert "surfaced" not in CONTRIB_STATES
        out = build_contributions(
            [_task(created=_iso(2), notes=[_contrib_note("surfaced")])], window_start=WINDOW_START
        )
        assert out["by_state"] == {"surfaced": 1}

    def test_undated_creation_is_counted_not_assumed_in_window(self):
        out = build_contributions(
            [_task(created=None, modified=_iso(1))], window_start=WINDOW_START
        )
        assert out["undated_creation"] == 1 and out["drafted_in_window"] == 0


class TestSurfaceSide:
    def test_closure_keys_off_modified_because_it_is_an_event(self):
        """The ONE deliberate exception to the creation-cohort rule: a task completed this week
        was necessarily modified this week, whenever it was created."""
        task = _task(created=_iso(40), modified=_iso(1), completed=_iso(1), tags=["q_question"])
        out = build_surface_side([task], window_start=WINDOW_START, bloat_threshold=20)
        assert out["created_in_window"] == 0
        assert out["closed_in_window"] == 1

    def test_engagement_and_per_item_type_breakdown(self):
        tasks = [
            _task("a", created=_iso(2), modified=_iso(1), tags=["q_question", "q_answered"]),
            _task("b", created=_iso(2), modified=_iso(1), tags=["q_alert"]),
        ]
        out = build_surface_side(tasks, window_start=WINDOW_START, bloat_threshold=20)
        assert out["paul_engaged_in_window"] == 1
        assert out["per_item_type"]["question"] == {"created": 1, "engaged": 1, "auto_closed": 0}
        assert out["per_item_type"]["alert"]["engaged"] == 0

    def test_open_depth_and_queue_bloat_flag(self):
        tasks = [_task(str(i), created=_iso(2), modified=_iso(1)) for i in range(25)]
        out = build_surface_side(tasks, window_start=WINDOW_START, bloat_threshold=20)
        assert out["open_depth"] == 25 and out["queue_bloat"] is True

    def test_latency_is_reported_as_approximate_or_null(self):
        out = build_surface_side([], window_start=WINDOW_START, bloat_threshold=20)
        assert out["avg_latency_to_engagement_hours"] is None
        assert "approximate" in out["latency_basis"]

    def test_thresholds_match_the_cost_discipline(self):
        assert (QUESTIONS_BLOAT_THRESHOLD, ACTIVITY_BLOAT_THRESHOLD) == (20, 50)


class TestSpeculationStaysWithdrawn:
    def test_open_population_is_reported(self):
        tasks = [_task("a", created=_iso(2), modified=_iso(1)), _task("b", created=_iso(40))]
        out = build_speculation(tasks, window_start=WINDOW_START)
        assert out["open_total"] == 2 and out["opened_in_window"] == 1
        assert out["oldest_open"] == "2026-06-15"

    def test_no_upgrade_rate_is_emitted_at_all(self):
        out = build_speculation([], window_start=WINDOW_START)
        assert out["upgrade_rate_reported"] is False
        assert not any("upgrade_rate" in k and k != "upgrade_rate_reported" for k in out)

    def test_the_gap_is_named_in_the_report(self):
        gaps = {g["metric"] for g in _report()["gaps"]}
        assert "speculation_upgrade_rate" in gaps


class TestReportShape:
    def test_window_bounds_and_semantics_are_explicit(self):
        out = _report(window_days=30)
        assert out["window_days"] == 30
        assert out["window_start"] == "2026-06-25T09:00:00Z"
        assert out["window_end"] == "2026-07-25T09:00:00Z"
        assert "creation cohort" in out["window_semantics"]

    def test_underivable_metrics_are_named_never_zeroed(self):
        """monitor-outcomes.md § 4c asks for these; none is derivable from RTM state. A zero
        that means 'not measured' is the failure this tool exists to end."""
        gaps = {g["metric"] for g in _report()["gaps"]}
        assert {
            "unblock_walk_outcomes",
            "cluster_synthesis_yield",
            "scheduled_task_run_health",
        } <= gaps
        for gap in _report()["gaps"]:
            assert gap["reason"].strip(), gap["metric"]

    def test_deferred_count_is_a_current_snapshot_not_windowed(self):
        out = _report(deferred=[_task(str(i), created=_iso(400)) for i in range(15)])
        assert out["engine_state"]["deferred_pending_unblock"] == 15

    def test_empty_account_produces_a_complete_report(self):
        out = _report()
        assert out["contributions"]["drafted_in_window"] == 0
        assert out["ai_surface"]["questions"]["open_depth"] == 0
        assert out["speculation"]["open_total"] == 0
