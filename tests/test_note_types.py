"""The note-type vocabularies — the tests that keep four sets from collapsing into one.

Every assertion here exists because a specific conflation already happened. The sets are NOT
subsets of one another by accident, and the load-bearing property is the **asymmetry**: a legacy
spelling must stay readable while ceasing to be writable. A single merged vocabulary cannot say
that, which is why merging them is the defect this module prevents.
"""

import ast
import pathlib

from rtm_mcp import note_types as nt
from rtm_mcp.gtd_writes import JOURNAL_NOTE_TYPES, SURFACE_BODY_NOTE_TYPE
from rtm_mcp.note_shape import check_title, check_type


class TestTheWriteSetIsDerivedNotHandListed:
    """The rule that keeps this from becoming the fifth vocabulary to maintain by hand."""

    def test_write_set_is_exactly_the_documented_composition(self):
        assert nt.WRITE_AUTHORISED_NOTE_TYPES == (
            nt.CATALOGUE_NOTE_TYPES | nt.RESPONSE_NOTE_TYPES | nt.BARE_MARKER_NOTE_TYPES
        )

    def test_write_set_is_built_by_union_in_source_not_typed_out(self):
        """A literal `frozenset({...})` here would silently become a fifth hand-kept list.

        Asserted against the SOURCE, because the value-equality test above passes just as happily
        against a hand-typed duplicate that happens to match today.
        """
        src = (pathlib.Path(nt.__file__)).read_text()
        assign = next(
            node
            for node in ast.parse(src).body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "WRITE_AUTHORISED_NOTE_TYPES" for t in node.targets)
        )
        assert isinstance(assign.value, ast.BinOp), (
            "WRITE_AUTHORISED_NOTE_TYPES must be composed from the other sets, not typed out"
        )


class TestTheAsymmetryThatMakesTheGateWorthHaving:
    """Legacy spellings stay READABLE and stop being WRITABLE. Both halves, or it is pointless."""

    def test_no_legacy_surface_spelling_is_writable(self):
        assert not (nt.SURFACE_NOTE_TYPES & nt.WRITE_AUTHORISED_NOTE_TYPES)

    def test_every_legacy_spelling_is_still_recognised_on_the_read_path(self):
        # The half that a careless "tidy the vocabularies" pass would delete. Losing it does not
        # raise — it silently mis-classifies live notes, which is a wrong answer, not an error.
        assert nt.SURFACE_NOTE_TYPES <= nt.SYSTEM_NOTE_TYPES

    def test_the_underscore_spelling_is_readable_and_unwritable(self):
        assert "ACTIVITY_REPORT" in nt.SYSTEM_NOTE_TYPES
        assert "ACTIVITY_REPORT" not in nt.WRITE_AUTHORISED_NOTE_TYPES
        # …and it is unwritable by CONSTRUCTION too: the TYPE token forbids an underscore.
        assert check_title("2026-08-01 — ACTIVITY_REPORT — x") is not None

    def test_a_legacy_rejection_says_legacy_not_unknown(self):
        # A caller reaching for `Q` is copying what is already on the list, not guessing.
        assert "LEGACY" in (check_type("2026-08-01 — Q — x") or "")
        assert "not in the registered vocabulary" in (check_type("2026-08-01 — EXECUTOR — x") or "")


class TestTheServerCanWriteWhatTheServerWrites:
    """The v5.1.1 defect class, now asserted against the WRITE gate as well as the read path."""

    def test_every_emitted_surface_body_type_is_writable(self):
        for item_type, token in SURFACE_BODY_NOTE_TYPE.items():
            title = f"2026-08-01 — {token} — a summary"
            assert check_title(title) is None, item_type
            assert check_type(title) is None, f"{item_type} emits {token!r}, which is unwritable"

    def test_every_journalling_catalogue_type_is_authorable_by_gtd_note_add(self):
        """Registering a journalling type is a TWO-set change, and only one has a prompt.

        v5.1.2 registered `SCOPE` in `CATALOGUE_NOTE_TYPES` — making it writable through the
        generic `add_note` escape hatch — and did not add it to `JOURNAL_NOTE_TYPES`, so the
        GOVERNED tool rejected the type the server had just declared canonical. Found when a real
        `gtd_note_add(note_type="SCOPE")` was refused, not by any test.

        The asymmetry that makes this easy to miss: side-effect types are excluded from the journal
        set BY DESIGN (each rides with its owning tool), so "canonical but not journal" is a
        legitimate state and cannot simply be banned. This asserts the narrower thing that is
        actually true — every type the catalogue files under the JOURNALLING lifecycle must be
        authorable by the journalling tool.
        """
        journalling = {
            "INCEPTION",
            "CONTEXT",
            "DECISION",
            "PROGRESS",
            "COMPLETION",
            "CASCADE",
            "SCOPE",
            "STATE",
            "SESSION",
            "BLOCKER",
        }
        assert journalling <= nt.CATALOGUE_NOTE_TYPES, "the fixture has drifted from the catalogue"
        # COMPLETION is the one deliberate exclusion: it rides with gtd_item_complete.
        assert journalling - {"COMPLETION"} <= JOURNAL_NOTE_TYPES, (
            "a journalling type is canonical but not authorable by gtd_note_add"
        )

    def test_every_journal_type_gtd_note_add_accepts_is_writable(self):
        # gtd_note_add's closed enum must be a SUBSET of what the escape hatch permits, else the
        # governed path could write something the generic path refuses — an incoherent estate.
        assert JOURNAL_NOTE_TYPES <= nt.WRITE_AUTHORISED_NOTE_TYPES

    def test_every_bare_marker_is_writable_when_properly_date_prefixed(self):
        # The four markers bypass the gate as bare titles (load-bearing —
        # project_plan._extract_deps_and_files round-trips on them). This asserts the other
        # direction: a caller who DOES date-prefix one is not refused.
        for marker in nt.BARE_MARKER_NOTE_TYPES:
            title = f"2026-08-01 — {marker} — a summary"
            assert check_title(title) is None, marker
            assert check_type(title) is None, marker


class TestCatalogueTracksTheMarkdown:
    def test_the_five_surface_body_types_are_catalogue_members(self):
        """Registered in note-shape-catalogue.md § 2 on 2026-07-25; the server lagged a week."""
        for token in ("QUESTION", "ALERT", "NOTIFICATION", "SURFACE", "ACTIVITY-REPORT"):
            assert token in nt.CATALOGUE_NOTE_TYPES, token
            assert token not in nt.SURFACE_NOTE_TYPES, f"{token} is registered, not legacy"

    def test_scope_is_registered(self):
        """§ 2a — the one legacy token promoted rather than rewritten (2026-08-01)."""
        assert "SCOPE" in nt.CATALOGUE_NOTE_TYPES
        assert check_type("2026-05-10 — SCOPE — DCI evolves into a departmental CI system") is None

    def test_the_rewritten_legacy_tokens_are_NOT_registered(self):
        """The remediation pass rewrites these; registering any would make it pointless."""
        for token in ("EXECUTOR", "FILING", "DRAFT", "OUTPUT-UPDATE", "ADDITION", "HANDOFF"):
            assert token not in nt.WRITE_AUTHORISED_NOTE_TYPES, token
