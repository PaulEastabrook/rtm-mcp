---
report_type: feature-debrief
scope: rtm-mcp — gtd_project_index waiting_count (engage-filter roll-up); decision_count open for research; focus-redaction already shipped
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-07-04
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #27 (feature commit 793de65), rtm-mcp v1.17.1 → v1.18.0
relates_to: gtd build briefing 2026-07-04 (gtd v0.119.3); the (on-disk-absent) briefs
            rtm-mcp-brief-engage-item-flags.md / rtm-mcp-brief-focus-redaction.md — content sourced from
            plugins/gtd/specs/gtd.md + references/gtd-glossary.md ("engage filter (Focus pill)"); the
            per-project count pattern (chat_count v1.16.0, ai-counts v1.13.0); redaction surface (PR #26, v1.17.x)
status: waiting_count DONE (needs server restart on v1.18.0); focus-redaction ALREADY DONE (v1.17.1);
        decision_count BLOCKED — open question for the gtd/cowork side (see § Open questions)
---

# Debrief — engage item-flags: `waiting_count` shipped, `decision_count` open, focus-redaction already done

The board's 04/07 briefing flagged two additive rtm-mcp changes as "in the rtm-mcp court". On
verifying `main`, the picture is: one was **already shipped**, one **half-buildable now**, one half
**blocked on a taxonomy question**. This debrief records all three states and hands the open question
back for research.

## What shipped (this change, v1.18.0)

`gtd_project_index` project rows now carry **`waiting_count`** — incomplete `#waiting_for` items in
the project, using the canvas's own `r.k` `"waiting_for"` classification (`canvas_seed.map_kind`) so
it matches the board glyph. It unlocks the navigator **Focus pill's** reserved *waiting-for* segment.
Tallied in `build_index` off the rows it already reconstructs (same row set + completed-guard as
`chat_count`/`ai_quick`) — no extra read, read-only, vault-free, no new tag. Always present (`0` when
none). Backward-compatible: the board reserves the slot and lights it up on restart, no board change.

## Already shipped — focus-redaction (item 1 of the briefing)

The briefing's item 1 ("emit `redacted` on `gtd_project_index` `foci[]`") is **already live**:
`build_foci` emits `redacted` from the area's `#redacted` tag in **v1.17.1** (PR #26, `3fc3759` —
landed before this session). The briefing itself hedged "if already shipped and restarted, this is
done." **It is done server-side** — the only remaining step is the operational server restart. No code
was needed here; flagging it so the board side can close the item.

## Design decisions & deviations

- **`waiting_count` scope = the project's incomplete children** (the same `rows` set every other index
  count uses), not a deep-descendant walk. `build_envelope` reconstructs a project's **direct
  children** as its plan items; `open_count`/`blocked_count`/`chat_count`/`ai_*` all count over that
  set. The briefing said "incomplete descendant items" — if plan items are ever nested deeper than one
  level under a project, that deeper nesting is a **cross-cutting** concern affecting *every* index
  count, not something to special-case for `waiting_count`. Kept consistent; flagged here.
- **Reused `map_kind` for canvas parity** rather than a raw `#waiting_for` membership test — so
  `waiting_count` and the action rows' `type` field and the board glyph are one classification.
- **Did not invent a decision tag** for `decision_count` — see below.

## Open questions — `decision_count` (for the gtd / cowork side to research)

`decision_count` (the Focus pill's reserved *decisions* segment) is **not built**. I could not derive
it without inventing a marker, and inventing taxonomy server-side violates the membrane (the server
holds no canonical taxonomy — CONTRIBUTING § 6). What I found and what I need:

1. **Is there a per-item "needs-you decision" tag at plan-item granularity?** My search of
   `plugins/gtd/skills/gtd/references/tag-taxonomy.md` (and siblings) found **none**. "Decisions" in
   the GTD system appear to live in the separate **`AI_Questions`** list (paired "AI_Questions
   decision" items), not as a `#decision`-style tag on a project's plan items. If a tag exists (e.g.
   `#decision` / `#needs_decision` / `#awaiting_decision`), **name it** and I'll roll it up exactly
   like `waiting_count`.
2. **If decisions are NOT plan-item tags but live in `AI_Questions`,** then a per-*project*
   `decision_count` on `gtd_project_index` may be the wrong home — the index reads a project's own
   descendant items, and an `AI_Questions` decision is a separate task not under the project. Options
   to research on the gtd side:
   - (a) introduce a per-item decision tag on the plan item the decision blocks (then it's a clean
     roll-up here); or
   - (b) surface decisions from a different read (an `AI_Questions`-scoped tool), not the project
     index; or
   - (c) drop the per-project decision segment as not-index-shaped and keep only the reply/overdue/
     due/talking/waiting segments.
3. **Definition, once the marker is known:** confirm it's *incomplete* items only (like every other
   index count), and whether the project task itself can carry it (as `chat_count` does).

Until this is answered, the board's *decisions* slot stays reserved and dark — exactly as designed.
`decision_count` lands additively (another minor bump, no board change) the moment the marker/rule is
defined.

## Membrane / activation

Additive, read-only, vault-free; reads the existing `#waiting_for` tag — no tag write, no new tag, no
strict-tag interaction, no activation-ordering hazard. **Operational step: restart the MCP server on
v1.18.0** so the waiting-for segment lights up (board degrades gracefully until then).

## Verification done

`make lint` + `make test` green on the branch (**644 → 647**). New coverage
(`tests/test_project_index.py::TestEngageCounts`): `waiting_count` counts incomplete `#waiting_for`
items; canvas-kind parity (a `#calendar_entry` is not a waiting-for); completed items excluded;
present-and-`0` when none. Field-set assertions (pure + tool via FakeMCP) updated to the new row shape.

A **live** read against the account was **not** run — the session's MCP server is still on v1.17.1, so
live calls would exercise the old code; the fix is verified in-suite. After the restart, a project with
`#waiting_for` children should report a matching `waiting_count`.

## Conventions (CONTRIBUTING.md)

§1/§3 logic in the pure `build_index`, tool stays thin. §6 reads a tag only — no write, no gate, **no
new tag**, and (crucially) **no server-side taxonomy invention** for decisions. §8 pure + tool tests,
inventory kept accurate. §9 lockstep (README, server instructions, CLAUDE.md feature section + module
table + inventory). §10 additive → **minor** bump 1.17.1 → 1.18.0. §14 this debrief (with the open
questions, as requested).

## Open items / handback

1. **Restart the RTM MCP server on v1.18.0** (lights up the waiting-for segment) — and confirm the
   already-shipped **focus-redaction** (v1.17.1) is live after the restart, closing briefing item 1.
2. **gtd / cowork: research the `decision_count` marker** (§ Open questions) and reply with the
   tag/rule, or decide the decisions segment isn't index-shaped.
3. **Consumer — no board change** for `waiting_count`; the reserved segment absorbs it.

## Durable lesson

When a brief asks for a count "where feasible" and the marker isn't in the taxonomy, **do not invent
the tag server-side** — the server holds no canonical taxonomy by design (CONTRIBUTING § 6). Ship the
clean half, and hand the taxonomy question back to the side that owns the taxonomy (gtd), with concrete
options rather than a bare "what tag?".

---
*Handback from the rtm-mcp implementation session (2026-07-04). As-built source of truth: `CLAUDE.md`
§ Portfolio index (`gtd_project_index`) + the `build_index` docstring. Briefing source: gtd
`plugins/gtd/specs/gtd.md` + `references/gtd-glossary.md` ("engage filter (Focus pill)"). Consumer:
claude-plugins `project-plan-artifact.html` navigator Focus pill.*
