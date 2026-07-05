"""Tests for the template-child token stamping helpers (tmpl_child.py, write side)."""

import re

from rtm_mcp.tmpl_child import (
    add_token_line,
    depends_on_upstream_id,
    has_token_line,
    is_active_depends_on,
    make_tmpl_child_note,
    new_slug,
    note_child_token,
    plan_backfill,
)


def _counter_slugs(*slugs):
    """A deterministic slug generator for plan_backfill; cycles through the given slugs."""
    it = iter(slugs)
    return lambda: next(it)


def _depends_on(name, upstream_id, *, status="active", token_line=""):
    body = (
        f"2026-06-15 — DEPENDS-ON — {name} needs upstream\n"
        "Depends on: upstream\n"
        "Upstream RTM IDs:\n"
        f'  task_id: "{upstream_id}"\n'
        '  taskseries_id: "570000000"\n'
        '  list_id: "49657585"\n'
        f"Status: {status}\n"
        "Captured by: progression-fanout"
    )
    if token_line:
        body += f'\nTemplate-child-id: "{token_line}"'
    return body


def _tmpl_note(slug):
    title, text = make_tmpl_child_note(slug, "2026-07-05")
    return f"{title}\n{text}"  # RTM storage reality: body = title\ntext


# ── small helpers ──────────────────────────────────────────────────────────


class TestSmallHelpers:
    def test_new_slug_is_8_lowercase_hex(self):
        for _ in range(20):
            assert re.fullmatch(r"[0-9a-f]{8}", new_slug())

    def test_make_tmpl_child_note_shape(self):
        title, text = make_tmpl_child_note("1a2b3c4d", "2026-07-05")
        assert title == "2026-07-05 — TMPL-CHILD — 1a2b3c4d"
        assert text == '{"schema": "tmpl-child/1", "template_child_id": "1a2b3c4d"}'

    def test_note_child_token_from_stored_body(self):
        # The full stored body (title line + JSON) still yields the slug from the JSON key.
        assert note_child_token(_tmpl_note("deadbeef")) == "deadbeef"

    def test_note_child_token_requires_json_key(self):
        # A title-only line names the schema-less slug — not a valid token (no JSON key).
        assert note_child_token("2026-07-05 — TMPL-CHILD — deadbeef") == ""
        assert note_child_token("some other note") == ""

    def test_is_active_depends_on(self):
        assert is_active_depends_on(_depends_on("A", "101"))
        assert not is_active_depends_on(_depends_on("A", "101", status="resolved"))
        assert not is_active_depends_on(_depends_on("A", "101", status="obsolete"))
        assert not is_active_depends_on("just a normal note")

    def test_depends_on_upstream_id(self):
        assert depends_on_upstream_id(_depends_on("A", "101")) == "101"
        assert depends_on_upstream_id("no ids here") == ""

    def test_has_token_line(self):
        assert not has_token_line(_depends_on("A", "101"))
        assert has_token_line(_depends_on("A", "101", token_line="cafef00d"))

    def test_add_token_line_round_trip(self):
        body = _depends_on("A", "101")
        title, text = add_token_line(body, "cafef00d")
        # Title is the first line; text is the remainder + the new line.
        assert title == body.split("\n", 1)[0]
        assert text.endswith('Template-child-id: "cafef00d"')
        # Reconstructed stored body = title\ntext = original + the appended line.
        assert f"{title}\n{text}" == body + '\nTemplate-child-id: "cafef00d"'


# ── plan_backfill ───────────────────────────────────────────────────────────


class TestPlanBackfill:
    def test_assigns_slug_to_each_unstamped_child(self):
        children = [
            {"id": "101", "name": "A", "notes": []},
            {"id": "102", "name": "B", "notes": []},
        ]
        plan = plan_backfill(children, slug_gen=_counter_slugs("aaaaaaaa", "bbbbbbbb"))
        assert plan["assign"] == {"101": "aaaaaaaa", "102": "bbbbbbbb"}
        assert plan["tokens"] == {"101": "aaaaaaaa", "102": "bbbbbbbb"}
        assert plan["dep_edits"] == []

    def test_skips_already_stamped_child(self):
        children = [
            {"id": "101", "name": "A", "notes": [{"id": "n1", "body": _tmpl_note("existing0")}]},
            {"id": "102", "name": "B", "notes": []},
        ]
        plan = plan_backfill(children, slug_gen=_counter_slugs("bbbbbbbb"))
        assert "101" not in plan["assign"]  # not re-slugged
        assert plan["assign"] == {"102": "bbbbbbbb"}
        assert plan["tokens"]["101"] == "existing0"

    def test_authors_dep_line_in_token_space(self):
        # B depends on A; both get stamped; the dep line carries A's slug.
        children = [
            {"id": "101", "name": "A", "notes": []},
            {"id": "102", "name": "B", "notes": [{"id": "nDep", "body": _depends_on("B", "101")}]},
        ]
        plan = plan_backfill(children, slug_gen=_counter_slugs("aaaaaaaa", "bbbbbbbb"))
        assert len(plan["dep_edits"]) == 1
        edit = plan["dep_edits"][0]
        assert edit["child_id"] == "102"
        assert edit["note_id"] == "nDep"
        assert edit["upstream_id"] == "101"
        assert edit["upstream_slug"] == "aaaaaaaa"
        assert edit["note_text"].endswith('Template-child-id: "aaaaaaaa"')

    def test_idempotent_dep_line_not_reauthored(self):
        children = [
            {"id": "101", "name": "A", "notes": [{"id": "n1", "body": _tmpl_note("aaaaaaaa")}]},
            {
                "id": "102",
                "name": "B",
                "notes": [
                    {"id": "n2", "body": _tmpl_note("bbbbbbbb")},
                    {"id": "nDep", "body": _depends_on("B", "101", token_line="aaaaaaaa")},
                ],
            },
        ]
        plan = plan_backfill(children)
        assert plan["assign"] == {}  # both already stamped
        assert plan["dep_edits"] == []  # dep line already present

    def test_dep_upstream_not_a_sibling_keeps_raw(self):
        # The upstream task_id (999) is not among the children → no token line authored.
        children = [
            {"id": "102", "name": "B", "notes": [{"id": "nDep", "body": _depends_on("B", "999")}]},
        ]
        plan = plan_backfill(children, slug_gen=_counter_slugs("bbbbbbbb"))
        assert plan["dep_edits"] == []

    def test_new_slug_is_unique_within_plan(self):
        # An existing child already holds "aaaaaaaa"; the generator would collide once, then
        # the loop draws the next value.
        children = [
            {"id": "101", "name": "A", "notes": [{"id": "n1", "body": _tmpl_note("aaaaaaaa")}]},
            {"id": "102", "name": "B", "notes": []},
        ]
        plan = plan_backfill(children, slug_gen=_counter_slugs("aaaaaaaa", "bbbbbbbb"))
        assert plan["assign"] == {"102": "bbbbbbbb"}

    def test_next_occurrence_carries_same_slug(self):
        # Model RTM's note-copy propagation: stamp this occurrence, "recur" by copying the
        # TMPL-CHILD note (its slug) onto a fresh child id — the next run must NOT re-stamp.
        first = plan_backfill(
            [{"id": "101", "name": "A", "notes": []}], slug_gen=_counter_slugs("feedface")
        )
        slug = first["assign"]["101"]
        # New occurrence: fresh task id, same copied note body.
        recurred = [{"id": "201", "name": "A", "notes": [{"id": "n1", "body": _tmpl_note(slug)}]}]
        second = plan_backfill(recurred, slug_gen=_counter_slugs("ffffffff"))
        assert second["assign"] == {}  # identity preserved across the occurrence
        assert second["tokens"]["201"] == "feedface"

    def test_empty_children_is_noop(self):
        assert plan_backfill([]) == {"assign": {}, "tokens": {}, "dep_edits": []}
