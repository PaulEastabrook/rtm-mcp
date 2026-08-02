"""The output-filing reconciliation builder (v6.4.0, `gtd_note_filing_gaps`).

Every finding class is driven by a fixture built to trip it, AND a guard-the-guard asserts the
fixture set actually trips every one — a report that finds nothing because it skipped everything
is worse than no report, and that failure mode is invisible in a green suite.

The load-bearing test is the last class: with no vault, the vault-dependent classes must be
NAMED in `gaps[]` and their counts must be **null, never 0**.
"""

import pytest

from rtm_mcp.companion import walk_artefacts
from rtm_mcp.filing_gaps import FINDING_CLASSES, VAULT_DEPENDENT, build_filing_gaps

PROJECT_ID = "9000"


def _note(nid, title, body=""):
    """A note as getList returns it: RTM stores `title\\ntext` and returns an EMPTY title."""
    return {
        "id": nid,
        "title": "",
        "$t": title if not body else f"{title}\n{body}",
        "created": "2026-07-20T00:00:00Z",
    }


def _task(tid, name, notes=None, parent="", tags=("work", "action")):
    return {
        "id": tid,
        "taskseries_id": f"ts{tid}",
        "list_id": "1",
        "name": name,
        "parent_task_id": parent,
        "tags": list(tags),
        "notes": notes or [],
        "completed": "",
    }


def _artefact(path, meta=None):
    return {"path": path, "meta": meta}


@pytest.fixture
def estate():
    """One fixture that trips ALL SEVEN classes at once — the guard-the-guard depends on it."""
    return [
        # linked_missing: the FILING path resolves to nothing.
        _task(
            "1",
            "Broken pointer",
            [_note("n1", "2026-07-20 — OUTPUT — moved", "x\n\nFILING: work/gone.md")],
        ),
        # companion_missing: resolves, untracked.
        _task(
            "2",
            "Untracked",
            [_note("n2", "2026-07-20 — OUTPUT — bare", "x\n\nFILING: work/bare.md")],
        ),
        # join_unpopulated: tracked, but the companion carries no source_action.
        _task(
            "3",
            "No join",
            [_note("n3", "2026-07-20 — OUTPUT — joined?", "x\n\nFILING: work/tracked.md")],
        ),
        # prose_path: an OUTPUT note describing a path instead of carrying a FILING line.
        _task(
            "4",
            "Prose",
            [_note("n4", "2026-07-20 — OUTPUT — prose", "I filed it under output/notes.md")],
        ),
        # legacy_unfiled: the pre-v6.4.0 declaration of absence, on a real FILING line.
        _task(
            "5",
            "Never filed",
            [
                _note(
                    "n5",
                    "2026-07-20 — OUTPUT — runbook",
                    "x\n\nFILING: work/gtd-eval/output/staging-rollback-runbook.md (unfiled)",
                )
            ],
        ),
        # register_defect: two registers on one project (the live Claude Coworking shape).
        _task(
            PROJECT_ID,
            "Proj",
            [
                _note("r1", "2026-04-06 — OUTPUTS — Project output register"),
                _note("r2", "OUTPUTS: Proj"),
            ],
            tags=("work", "project"),
        ),
    ]


@pytest.fixture
def artefacts():
    return [
        _artefact("work/bare.md", None),
        _artefact("work/tracked.md", {"title": "T"}),
        # filed_unlinked: tracked and referenced by nothing.
        _artefact("work/orphan.md", {"title": "O"}),
        # UNtracked AND unreferenced. Absent until 2026-08-02, and its absence is why the
        # v6.4.0 defect passed a green suite: every other fixture artefact is either tracked
        # or referenced, so the one case where the two classes could overlap never ran.
        _artefact("work/junk.cache", None),
    ]


class TestEveryClassFires:
    def test_each_class_has_at_least_one_row(self, estate, artefacts):
        """Guard-the-guard: if the fixture stops tripping a class, THIS fails rather than the
        class silently going dead and every per-class assertion passing vacuously."""
        out = build_filing_gaps(estate, artefacts=artefacts)
        empty = [c for c in FINDING_CLASSES if out["findings"][c]["count"] == 0]
        assert empty == [], f"fixture no longer trips: {empty}"

    def test_linked_missing_names_the_path(self, estate, artefacts):
        rows = build_filing_gaps(estate, artefacts=artefacts)["findings"]["linked_missing"]["rows"]
        assert [r["path"] for r in rows] == ["work/gone.md"]

    def test_filed_unlinked_is_the_artefact_no_note_references(self, estate, artefacts):
        rows = build_filing_gaps(estate, artefacts=artefacts)["findings"]["filed_unlinked"]["rows"]
        assert [r["path"] for r in rows] == ["work/orphan.md"]

    def test_filed_unlinked_counts_TRACKED_artefacts_only(self, estate, artefacts):
        """The class means "the file store says this is filed, and nothing journalled it".

        An untracked file is a different finding and belongs to `untracked_unlinked_count`.
        Measured on the first live run of v6.4.0: without this filter the class reported
        **2,704** rows against a baseline of **97**, because `walk_artefacts` enumerates every
        file in the vault — `.auto-memory/` caches, `.bak` files, Syncthing sync-conflict
        artefacts. A class whose whole value is that its findings are real was ~96% noise.
        """
        out = build_filing_gaps(estate, artefacts=artefacts)
        paths = [r["path"] for r in out["findings"]["filed_unlinked"]["rows"]]
        assert "work/junk.cache" not in paths, "an untracked file is not a filed artefact"
        assert all(r["companion"] for r in out["findings"]["filed_unlinked"]["rows"])

    def test_the_two_unlinked_classes_are_disjoint(self, estate, artefacts):
        """The module comment asserts disjointness; until 2026-08-02 it was false —
        `filed_unlinked` CONTAINED every row `untracked_unlinked_count` counted, so a total
        across the classes double-counted every untracked orphan."""
        out = build_filing_gaps(estate, artefacts=artefacts)
        assert out["untracked_unlinked_count"] == 1
        filed = {r["path"] for r in out["findings"]["filed_unlinked"]["rows"]}
        assert "work/junk.cache" not in filed
        assert out["findings"]["filed_unlinked"]["count"] + out["untracked_unlinked_count"] == 2

    def test_companion_missing_is_reported_against_the_note(self, estate, artefacts):
        rows = build_filing_gaps(estate, artefacts=artefacts)["findings"]["companion_missing"][
            "rows"
        ]
        assert rows[0]["path"] == "work/bare.md" and rows[0]["note_id"] == "n2"

    def test_join_unpopulated_fires_on_an_absent_source_action(self, estate, artefacts):
        rows = build_filing_gaps(estate, artefacts=artefacts)["findings"]["join_unpopulated"][
            "rows"
        ]
        assert "source_action" in rows[0]["detail"]

    def test_a_matching_source_action_is_not_a_finding(self, estate):
        arte = [_artefact("work/tracked.md", {"source_action": "rtm:3"})]
        task = [t for t in estate if t["id"] == "3"]
        out = build_filing_gaps(task, artefacts=arte)
        assert out["findings"]["join_unpopulated"]["count"] == 0

    def test_prose_path_reports_the_note_and_does_not_parse_it(self, estate, artefacts):
        rows = build_filing_gaps(estate, artefacts=artefacts)["findings"]["prose_path"]["rows"]
        # Reported, never interpreted — ten mutually incompatible dialects were counted live.
        assert rows[0]["note_id"] == "n4" and "path" not in rows[0]

    def test_register_defect_reports_both_duplicates(self, estate, artefacts):
        rows = build_filing_gaps(estate, artefacts=artefacts)["findings"]["register_defect"]["rows"]
        assert {r["note_id"] for r in rows} >= {"r1", "r2"}


class TestTheLegacyUnfiledClass:
    """v6.5.0. A pre-v6.4.0 `FILING: <path> (unfiled)` is a DECLARATION OF ABSENCE, not a broken
    link — nothing is missing, because nothing was ever filed. It is also not `prose_path`: the
    note does carry a FILING line. Its own class, because it is a migration backlog with a
    natural end state, and because filing it under a description that does not fit is how
    vocabularies rot."""

    def test_it_is_reported_in_its_own_class(self, estate, artefacts):
        rows = build_filing_gaps(estate, artefacts=artefacts)["findings"]["legacy_unfiled"]["rows"]
        assert [r["note_id"] for r in rows] == ["n5"]
        assert rows[0]["path"] == "work/gtd-eval/output/staging-rollback-runbook.md"
        assert "(unfiled)" in rows[0]["detail"]

    def test_it_is_NOT_reported_as_a_broken_link(self, estate, artefacts):
        """The reported symptom. Counting it `linked_missing` sends a reader hunting a file
        that was never meant to exist."""
        out = build_filing_gaps(estate, artefacts=artefacts)
        assert [r["path"] for r in out["findings"]["linked_missing"]["rows"]] == ["work/gone.md"]

    def test_it_is_NOT_double_reported_as_prose(self, estate, artefacts):
        """A note carrying ONLY a legacy-unfiled line has no valid FILING path, so it would fall
        through to the prose fallback — and its body trips every prose hint."""
        out = build_filing_gaps(estate, artefacts=artefacts)
        assert [r["note_id"] for r in out["findings"]["prose_path"]["rows"]] == ["n4"]

    def test_it_is_RTM_ONLY_so_it_survives_a_vault_less_run(self, estate):
        """No vault is needed to spot the marker, so unlike the four vault-dependent classes it
        keeps answering — and must NOT appear in gaps[]."""
        out = build_filing_gaps(estate, artefacts=None)
        assert out["findings"]["legacy_unfiled"]["count"] == 1
        assert "legacy_unfiled" not in out["gaps"]
        assert "legacy_unfiled" not in VAULT_DEPENDENT

    def test_a_genuine_filing_alongside_it_is_still_reconciled(self):
        """The load-bearing regression: one note may carry both forms, and the real one must
        still be joined against the vault."""
        task = _task(
            "7",
            "Both",
            [
                _note(
                    "n7",
                    "2026-07-20 — OUTPUT — both",
                    "x\n\nFILING: work/real.md (+ .meta.md)\nFILING: work/never.md (unfiled)",
                )
            ],
        )
        out = build_filing_gaps([task], artefacts=[_artefact("work/real.md", {"title": "R"})])
        assert out["findings"]["legacy_unfiled"]["count"] == 1
        assert out["findings"]["linked_missing"]["count"] == 0
        # `work/real.md` resolved and is tracked, so it is referenced — not an orphan.
        assert out["findings"]["filed_unlinked"]["count"] == 0


class TestAnAbsentVaultIsPartialNeverClean:
    """The load-bearing test for the whole tool. A reconciliation reporting zero drift because
    nothing was mounted is the silent-control failure this programme keeps finding."""

    def test_vault_dependent_classes_are_named_in_gaps(self, estate):
        out = build_filing_gaps(estate, artefacts=None)
        assert out["vault_present"] is False
        assert set(out["gaps"]) == set(VAULT_DEPENDENT)

    def test_no_vault_dependent_class_is_emitted_as_zero(self, estate):
        out = build_filing_gaps(estate, artefacts=None)
        for name in VAULT_DEPENDENT:
            assert out["findings"][name]["count"] is None, name

    def test_the_rtm_only_classes_still_answer(self, estate):
        """`prose_path` and `register_defect` need no vault, so a vault-less run is degraded,
        not useless."""
        out = build_filing_gaps(estate, artefacts=None)
        assert out["findings"]["prose_path"]["count"] == 1
        assert out["findings"]["register_defect"]["count"] >= 2
        assert out["gaps"] and "prose_path" not in out["gaps"]

    def test_a_mounted_but_empty_vault_is_CLEAN_not_unknown(self, estate):
        """The other half of the distinction: `[]` means "walked it, found nothing", which is a
        real answer. Collapsing it with None would make an empty vault indistinguishable from
        an absent one."""
        out = build_filing_gaps(estate, artefacts=[])
        assert out["vault_present"] is True and out["gaps"] == []
        assert out["findings"]["filed_unlinked"]["count"] == 0
        assert out["findings"]["linked_missing"]["count"] == 3  # all three paths resolve nowhere


class TestTruncationIsAnnounced:
    def test_rows_are_capped_but_the_count_stays_true(self, estate, artefacts):
        out = build_filing_gaps(estate, artefacts=artefacts, max_rows=1)
        reg = out["findings"]["register_defect"]
        assert reg["count"] >= 2 and len(reg["rows"]) == 1 and reg["truncated"] is True


class TestTheVaultWalker:
    def test_no_vault_returns_none_not_empty(self):
        """None means "could not look"; [] means "looked, found nothing". Collapsing them is
        what would let a vault-less run read as clean."""
        assert walk_artefacts(None) is None

    def test_it_finds_artefacts_and_resolves_their_companions(self, tmp_path):
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "_index.md").write_text("# index")
        out = tmp_path / "work"
        out.mkdir()
        (out / "a.md").write_text("artefact")
        (out / "a.meta.md").write_text("---\ntitle: A\n---\n")
        (out / "b.md").write_text("untracked")
        found = {a["path"]: a for a in walk_artefacts(str(tmp_path))}
        assert found["work/a.md"]["meta"] == {"title": "A"}
        assert found["work/b.md"]["meta"] is None
        # A companion is metadata, not an artefact in its own right.
        assert "work/a.meta.md" not in found
        # …and the vault marker is not an artefact either.
        assert "memory/_index.md" not in found

    def test_the_limit_is_a_runaway_guard(self, tmp_path):
        (tmp_path / "memory").mkdir()
        (tmp_path / "memory" / "_index.md").write_text("# index")
        for i in range(5):
            (tmp_path / f"f{i}.md").write_text("x")
        assert len(walk_artefacts(str(tmp_path), limit=3)) == 3
