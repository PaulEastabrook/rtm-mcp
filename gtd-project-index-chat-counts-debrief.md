---
report_type: feature-debrief
scope: rtm-mcp — gtd_project_index per-project conversation counts (chat_count / chat_review_count) — SHIPPED
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-30
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #23 (merged to main, merge commit 4dee795; feature commit e40d17f), rtm-mcp v1.15.0 → v1.16.0
relates_to: brief "gtd_project_index — per-project conversation counts"; sibling gtd_chat_inflight (v1.15.0,
            the real-time cross-project band); predecessor project-row enrichments (foci/actions v1.10.0,
            action rows v1.11–1.12, ai-counts v1.13.0)
status: server half DONE on main; consumer (project-plan-artifact.html navigator chip + Conversations
        sort) already forward-compatible — only needs the MCP server restarted on v1.16.0 to light up
---

# Debrief — `gtd_project_index` per-project conversation counts (v1.16.0)

Built, tested, merged: rtm-mcp **v1.16.0**, PR [#23](https://github.com/PaulEastabrook/rtm-mcp/pull/23)
→ `main` (merge `4dee795`, feature `e40d17f`). Merged `main` is green: **628 tests**, `make lint`
(ruff check + format + pyright) clean. Additive, read-only, vault-free.

## What shipped

Each `projects[]` row of `gtd_project_index` now carries two integer conversation counts, so the
navigator's conversation chip + "Conversations" sort lens work for **every** project — not just the
one currently open on the board. The item-level chat glyph already worked live off the loaded plan's
tags; the project level only worked for the open project (the only one whose item rows are loaded), so
every other project showed no chip and sorted as zero.

- `chat_count` = incomplete items tagged `#ai_chat` (a conversation is underway).
- `chat_review_count` = incomplete items tagged `#ai_output_review_needed` (AI replied — Paul's turn).

## Design decisions & deviations

- **No deviation from the brief's shape.** Both fields as specified, always present (`0`, not absent).
- **`chat_review_count` is a subset signal, counted independently** — an item awaiting review is still
  an item with a conversation. The server returns the two counts; the artifact composes the display
  (chip shows `chat_count`, tints amber when `chat_review_count > 0`).
- **The project task itself counts** when it carries the tag (a project-scoped conversation is one
  more subject).
- **One judgement call worth surfacing:** I guard the count on the row's `completed` flag even though
  the tool's `getList` is already `status:incomplete`. `build_index` reuses `build_envelope`, which
  carries completed children too, so the guard makes the incomplete-only rule hold at the count level
  and satisfies acceptance case #1 (a completed `#ai_chat` item excluded) directly rather than relying
  on the upstream filter. Documented in the code comment + `CLAUDE.md`.

## Membrane / activation

Tallied in `build_index` off the rows it already reconstructs — **no extra read**, still one
`rtm.tasks.getList`, read-only, no timeline. Reads the existing `#ai_chat` / `#ai_output_review_needed`
tags (account-provisioned) — **writes nothing, introduces no new tag, no strict-tag-gate interaction,
no activation-ordering hazard**. Additive and backward-compatible: the artifact's `projChatCounts(p)`
already reads `p.chat_count` / `p.chat_review_count` with a `0` fallback, so non-open chips light up
and the full-fleet sort becomes correct **with no artifact change**. Complementary to `gtd_chat_inflight`
(the real-time F3 band); this is the standing per-project count in the index.

## Verification done

`make lint` + `make test` green on merged `main` (**622 → 628**). New coverage:
- **Pure** (`tests/test_project_index.py::TestConversationCounts`, 5): both acceptance cases (incl.
  the completed-`#ai_chat`-excluded case), review-is-subset-not-additive, project-scoped counts the
  project, zero-not-absent. Plus the `TestShape` field-set updated to the 15-field row.
- **Tool** (`tests/test_tools/test_gtd_tools.py::TestGtdProjectIndex::test_project_chat_counts`):
  non-zero counts across the index via FakeMCP.

A live read against the account was **not** run — the session's MCP server is still on the old build,
so live calls would exercise old code. The pure + tool tests reproduce the counting behaviour in-suite.

## Conventions (CONTRIBUTING.md)

§1/§3 logic in the pure `project_index.build_index`, tool stays thin. §6 reads tags only — no write,
no gate, no new tag. §8 pure + tool tests, inventory kept accurate. §9 lockstep (README, server
instructions, CLAUDE.md feature section + module table + inventory). §10 additive → minor bump
1.15.0 → 1.16.0 (`pyproject` / `uv.lock` / `__init__` aligned).

## Open items / handback

1. **Restart the RTM MCP server on v1.16.0** — the one operational step; the navigator chips +
   Conversations sort then light up across the full fleet.
2. **Consumer — no action.** claude-plugins is already forward-compatible (`projChatCounts` reads the
   fields with a `0` fallback).

## Durable lesson

`build_envelope` carries **completed** children (it is not itself filtered to incomplete — the tool's
`getList` filter is what excludes them in production). Any per-item count added to `build_index` that
must be incomplete-only should **guard on the row's `completed`** rather than assume the read already
filtered — and any pure test can then inject a completed row to prove the exclusion.

---
*Handback from the rtm-mcp implementation session (2026-06-30). As-built source of truth: `CLAUDE.md`
§ Portfolio index (`gtd_project_index`) + the `build_index` docstring. Sibling: gtd_chat_inflight
(v1.15.0). Consumer: claude-plugins `project-plan-artifact.html` navigator conversation chip +
"Conversations" sort lens.*
