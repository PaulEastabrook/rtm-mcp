---
report_type: handback-debrief
scope: give `gtd_inbox_item_close` a `narrative`
implemented_by: rtm-mcp (Claude Code session)
derived_at: 2026-08-02
target_repo: rtm-mcp
artifact: v6.3.0 — branch `feat/inbox-close-narrative` (PR pending)
relates_to:
  - hand-off brief "gtd_inbox_item_close cannot carry handler content, so a handler writes two
    notes where one was meant" (raised 2026-08-01 by plugin-marketplace-architect)
  - sibling brief `2026-08-01-outputs-register-and-inbox-close-brief.md` § Gap A (NOT in scope here)
  - predecessor: `note-body-construction` (v6.0.0) — the precedent this reuses wholesale
status: needs-restart
---

## What shipped

`gtd_inbox_item_close` takes an optional `narrative`. Prose you pass lands **above** the
derived-items list in the one COMPLETION note that closes the loop:

```
Routed to pmgo. Reflect 1w/4w.

DERIVED ITEMS CREATED:
1. [action] "Draft the pmgo hand-off" — RTM URL: https://…

SOURCE: Inbox_Stuff item "raw capture" — RTM URL: https://…
```

The consumer-visible effect: a handler that wants the routing reasoning, a reflection schedule or a
hand-off pointer recorded at closure **no longer needs a second note**. The
`plugin-marketplace-architect` `improvement_candidate` executor handler currently writes a preceding
CONTEXT note (claude-plugins `7f94464f1`) whose link to the closure is positional — and since the
note-reading protocol orders notes STATE-first, "the note above" was never a stable pointer. It can
now collapse back to one note.

Everything else is unchanged. `derived_refs` is still required and still non-empty.

## Design decisions & deviations

**No deviations from the brief.** Every constraint in § 4 was implementable as written; the notes
below are the reasoning, plus one consequence the brief did not name.

- **Above the list, not below.** The derived items and the `SOURCE:` back-pointer are what close the
  audit loop and are read mechanically; prose appended after them would put unstructured text
  between a reader and the structured tail. Same order `assemble_note_body` emits: prose first,
  structure last.
- **A facet, not a payload.** Deliberately NOT added to the eight v5.0.0 required-and-non-empty
  payload parameters (`check_payload`). Absence is legitimate — most closes have nothing to add — so
  the receipt covers it, not a rejection. `receipt.is_facet` classifies it correctly by construction
  (it is not a boolean); a test asserts that against the real signature rather than assuming it.
- **A blank narrative writes no block and no bare blank line**, and reports `no_change` in
  `not_applied[]`. That is the v6.0.0 `sources` / `ai_context` precedent reused verbatim — same
  `ErrorCode.NO_CHANGE`, same shape — not a new rule. The close itself still lands: a blank facet is
  reported, never a rejection.
- **`gtd_note_add`'s parameter set was NOT reused.** No `sources`, no `ai_context`. A COMPLETION
  note's structure *is* the derived list; blurring the two grammars is exactly what the brief warned
  against.
- **No `note_shape` wiring, and none wanted.** This tool calls `rtm.tasks.notes.add` directly (as all
  37 `gtd_*` note writes do), and its title is `format_note_title`'s fixed canonical string, so it
  already conforms.

### The one consequence the brief did not name — the advisory now fires on a bare close

`gtd_inbox_item_close` previously declared **no optional parameters at all**, so
`receipt.build_advisory` was silent on it by construction. `narrative` is now its only optional, and
the advisory fires when *every* declared optional is absent — so a close that passes no narrative
(the modal call) now returns `advisory: "…none of: narrative…"`.

This is accepted, not a regression, and it is precisely the v6.0.0 `gtd_note_add` situation
(`sources` / `ai_context` made the advisory live on the modal narrative-only journal note). The
reasoning transfers unchanged: a caller who types `narative=` has it stripped client-side and reads
*"none of: narrative"* instead of a confident success. Measured in-suite: silent on every close that
supplies one, fires on every close that does not — pinned by
`test_close_inbox_narrative_is_a_receipt_facet`.

If the noise proves unwanted in practice, the fix is a receipt-level policy decision (not a
parameter change) and should be taken with the other 24 governed writes in view, not for this one.

## Membrane / activation

- **Additive and backward-compatible.** A close without `narrative` writes a **byte-identical** body.
- **No new tag, no new `ErrorCode`, no strict-tag interaction, vault-free.** No activation-ordering
  hazard of any kind.
- **Fingerprint churn: exactly one tool** (`gtd_inbox_item_close`) — confined as the brief predicted,
  because nothing shared changed. `tool-fingerprints.json` regenerated (`make fingerprints`,
  `source_version 6.3.0`).
- **To go live: restart the MCP server on v6.3.0.** Until then the parameter is undeclared, and the
  Desktop host will silently strip it from any call that sends it (the documented client-side strip)
  — so the gtd-side handler edit must land *after* the restart, not before.
- **Rollback** is a signature revert. No data migration, no live-state change.

## Verification done

- `make test` — **1875 passed** (was 1868; +7: 3 pure-grammar, 4 tool-level).
- `make lint` — naming (`--strict`, no findings), ruff check, ruff format, pyright `0 errors`.
- `make fingerprints` regenerated and the freshness guard passes.
- The description-budget guard passes **without an exemption**: the tool sits at 2,016 of 2,048
  bytes. It briefly went 10 bytes over during the build and the docstring was tightened rather than
  exempted — an exemption there would have been a licence to regrow.

**Not run, explicitly:** no live RTM call. The server was not restarted and no note was written to
the real account, so the rendered body is verified in-suite (byte-equality against the exact string,
at both the pure-grammar and the tool level) and **not** against a live COMPLETION note. First live
close after the restart is the remaining confirmation.

## Conventions

§ 3 tool pattern + the six surfaces · § 3a affordance obligations (tier-1 front-loading, the 2 KB
budget) · § 4.1 the teaching receipt (`not_applied[]` / `NO_CHANGE`) · § 7 enriched docstring · § 9
documentation lockstep (CLAUDE.md tree row + feature section + test inventory; README's GTD list is a
curated subset and has never carried this tool, so it is unchanged) · § 10 minor bump, additive
feature.

## Open items / handback

- **claude-plugins — one edit, after the restart.** Collapse the `improvement_candidate` executor
  handler back to a single note: drop the preceding CONTEXT note and pass its content as
  `gtd_inbox_item_close(narrative=…)`. Lands in its own lockstep bump.
- **rtm-mcp — nothing.** No follow-up owned here.
- **Out of scope, unchanged:** the sibling brief's Gap A (outputs register) — larger, has a migration
  trap, and its decisions were still pending with Paul.

## Durable lesson / gotcha

**Adding the first optional to a governed write turns its bare-call advisory on.** The receipt's
advisory fires only when *every* declared optional facet is absent, so a tool with zero optionals is
silent by construction and a tool with exactly one becomes noisy on its modal call. That is a
property of the tool's *parameter count*, not of the parameter you added — worth predicting before
you add one, and worth stating in the change rather than letting a consumer discover it.

Second, smaller: this repo's in-tree `.venv` was a corrupted iCloud conflict artefact (`lib 2/`, no
`bin/`) and `uv run` refuses it. Every `make` target already pins
`UV_PROJECT_ENVIRONMENT=~/.venvs/rtm-mcp` for exactly that reason — **use `make`, never a bare
`uv run`**, and the Makefile header explains why at length.

---

Source of truth: `CLAUDE.md` § "The same rule applied to the close note —
`gtd_inbox_item_close.narrative` (v6.3.0, additive)", plus the docstrings on
`gtd_writes.inbox_close_body` and `tools/gtd.py::gtd_inbox_item_close`. Provenance: hand-off brief
raised 2026-08-01 by `plugin-marketplace-architect` from a marketplace-wide note-type sweep across
10 plugins.
