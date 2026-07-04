---
report_type: docs-debrief
scope: rtm-mcp — CONTRIBUTING §14 makes a handback debrief a required contributor practice
implemented_by: Claude Code (rtm-mcp host session)
derived_at: 2026-06-30
target_repo: rtm-mcp (custom RTM-MCP server) — github.com/PaulEastabrook/rtm-mcp
artifact: PR #24 (merged to main, merge commit ef4a9f0; feature commit 2586e79) — docs-only, no version change
relates_to: the seven *-debrief.md handbacks written this session (their shape became the standard);
            CONTRIBUTING §7 (the enriched-docstring "shape" pattern this mirrors); the marketplace
            conventions-doc marker on CONTRIBUTING line 1
status: DONE on main — a process/convention change; no server restart or consumer wiring involved
---

# Debrief — a handback debrief is now required (CONTRIBUTING §14)

Merged: PR [#24](https://github.com/PaulEastabrook/rtm-mcp/pull/24) → `main` (merge `ef4a9f0`, feature
`2586e79`). Docs-only; no code, no version bump. Written to the very §14 shape it introduces (the
debrief-for-the-debrief-rule).

## What shipped

`CONTRIBUTING.md` now **requires** a handback debrief for consumer-facing changes, and defines what a
good one is:
- **New §14 "Handback debrief (required)"** — when it's required (a change shipping behaviour a
  downstream consumer or a future session depends on) and when it isn't (pure-internal refactors /
  formatting / no external consumer); the **four properties of a good debrief**; and the
  frontmatter + sections **shape**.
- **§12 add-a-tool checklist** gains item 12 (write the debrief).
- **Pull request process** gains a step to keep the debrief with the change and reference it in the PR.

The four properties: (1) honest about its **verification boundary** — state what was run *and* what
was not, never imply a check that didn't happen; (2) readable cold; (3) about **decisions and gotchas,
not the diff**; (4) actionable at the seams — activation + open items, "consumer — no action" when true.

## Design decisions & deviations

- **Appended as §14, not inserted.** Inserting near the thematically-related §9 (docs lockstep) / §11
  (quality gate) would have renumbered §10–§13 and broken every existing `§ N` cross-reference in
  CONTRIBUTING.md *and* CLAUDE.md. Appending keeps all numbering and references valid — verified by
  grepping the `§ 12` / `§ 9` cross-refs after the edit.
- **Embedded the shape inline** rather than adding a separate `DEBRIEF_TEMPLATE.md`, matching how §7
  embeds the enriched-docstring shape — one canonical doc, no second file to drift.
- **Scoped the requirement** (consumer-facing only) so it doesn't become bureaucratic overhead on
  trivial internal changes.
- **Dogfooded it in the same PR:** retro-filed the previously-missing v1.16.0 chat-counts debrief, so
  the repo *conforms* to §14 rather than introducing the rule in violation.
- **No CLAUDE.md change** — CLAUDE.md already delegates all conventions to CONTRIBUTING.md ("Conventions
  & standards live in CONTRIBUTING.md"), so the debrief rule belongs there and only there.

## Verification done

- Structure checked by grep: section headers §1–§14 present and in order (no renumbering); §12 item 12
  and the new PR step present; §14 cross-references resolve.
- **Not run:** `make test` / `make lint` — deliberately. The change touches only `CONTRIBUTING.md`
  (markdown, outside `src`/`tests`) plus a new root `*-debrief.md`; ruff/pyright/pytest don't cover
  either, so the gate is genuinely unaffected. `git diff --stat` confirms no code paths changed.

## Conventions

Docs-only: §10 (versioning) does **not** apply — no `pyproject`/code change, so no bump; the
`conventions-doc: marketplace/v1` marker on line 1 is untouched. The change *is* itself an addition to
the conventions doc that §9-style lockstep points at.

## Open items / handback

- **None blocking.** The rule is live for all future contributions.
- Going forward, every consumer-facing rtm-mcp change carries its debrief (checklist §12.12 + PR step).
  Recorded as a persistent memory (`handback-debrief-required`) so it's applied across sessions.

## Durable lesson

When adding a section to a **numbered** conventions doc that other files cross-reference by number,
**append** rather than insert — renumbering silently invalidates every `§ N` pointer elsewhere. And
when you introduce a discipline, **apply it to itself in the same change** (here: this debrief, and the
retro-filed v1.16.0 one) so the repo is never in a state that violates its own freshly-added rule.

---
*Handback from the rtm-mcp implementation session (2026-06-30). Source of truth for the rule:
`CONTRIBUTING.md` § 14 (+ the § 12 checklist and the PR-process step). This file is itself an instance
of the § 14 shape.*
