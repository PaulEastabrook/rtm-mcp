---
report_type: handback-debrief
scope: rtm-mcp-advertised-error-contract
implemented_by: Claude Opus 4.8 (Claude Code)
derived_at: 2026-07-19
target_repo: rtm-mcp
artifact:
  versions: v2.1.0 (docstring contract) + v2.1.1 (structural guard)
  prs: "#41 (merged, f3d2aa4) + #42 (this change)"
  branch: test/error-contract-guard
relates_to:
  - typed-error-vocabulary-debrief.md (the v2.0.0 parent change)
  - designed-change candidate RTM 1217273391
status: DONE  # repo side complete; see Open items for the marketplace CI gap (NOT fixed)
---

# Handback debrief — the advertised error contract (v2.1.0 / v2.1.1)

## What shipped

v2.0.0 made every failure carry a typed `code`. This pair makes that contract **visible to the
callers who must branch on it**, and then makes it **impossible to silently lose again**.

- **v2.1.0** — every tool that can return an envelope error now names, in its docstring, the codes
  it can actually produce. 34 tools gained an `Errors:` clause; 5 more had one that was stale.
- **v2.1.1** — `TestAdvertisedErrorContract` enforces that property structurally, so a new failure
  path fails the suite until it is documented.

Consumer-visible effect: a model calling `gtd_apply_canvas_commit` is now told it can receive
`commit_rejected` / `strict_tag_rejected` / `cross_project` and that per-item `rejected[]` entries
are flat — rather than being told nothing and having to discover it by failing.

## Why this was needed — the honest version

**v2.0.0 shipped with 975 tests green and a wrong advertised contract.** Five tools still described
the pre-v2.0.0 prose shape (`{"error": "..."}`), and 34 more documented no error at all.

Nothing caught it because **the suite asserts the runtime dict and never the advertised
description**. Those are different surfaces. A single live tool call after the server restart found
it in seconds.

The sequence is the whole lesson, and it is not flattering:

| Pass | Method | Found |
|---|---|---|
| 1 | grep one literal (`{"error": "..."}`) | 12 stale sites |
| 2 | audit all 56 advertised descriptions | **34** tools documenting nothing |
| 3 | automated guard | **5 more** the audit missed — one *actively wrong* |

Pass 3 found that `gtd_chat_thread` advertised `project_not_found | missing_parameter` when it can
only produce `task_not_found`. That was **introduced by my own pass-2 bulk edit**, which pasted a
generic gtd clause onto it. A manual audit did not just miss a gap; it created one. That is the
argument for the guard existing.

## Design decisions

**Codes are derived from source, never hand-written.** `_reachable_codes` collects a tool's direct
`ErrorCode` references plus what the shared helpers it calls surface on its behalf
(`resolve_task_ids` → `task_not_found` + `missing_parameter`; `resolve_list_id` → `list_not_found`;
`enforce_strict_tags` → `strict_tag_rejected`; `error_from_exception` → the transport codes). Hand-
maintained lists rot; a derivation tracks the code by construction.

**Parsed with `ast`, never regex or brace-counting.** Tool bodies are full of f-strings whose
interpolation braces are indistinguishable from dict delimiters to a naive counter — the exact trap
that corrupted six files during the v2.0.0 sweep. `ast.walk` + `get_source_segment` gives exact
spans and cannot be fooled.

**Three tests, because two would be a trap.** The third — `test_tools_that_cannot_fail_are_not_
forced_to_document_errors` — asserts that *some* tools remain classified non-failable. Without it,
a derivation bug that marked everything failable (or nothing) would let the other two pass
vacuously while guarding nothing. A guard needs a guard.

**Verified by mutation, not by passing.** A test that has never failed is not evidence. Both failure
modes were induced and confirmed:

- dropping one code from a docstring → `{'complete_task': ['task_not_found']}`
- deleting an entire `Errors:` clause → `['list_tasks'] advertise no error shape`

Each fails with a message naming the tool and what to add. Restored cleanly afterwards.

**Version choice.** v2.1.0 was MINOR, not patch — consistent with the family precedent for
restoring dropped tool documentation (mindmeister v0.3.0, meistertask v0.4.0). v2.1.1 is a patch:
docstring corrections plus tests, no behaviour change.

## Verification done

**Ran and passing:**
- `uv run pytest` — **1003 passed** (975 → 1000 at v2.1.0, → 1003 with the three guard tests).
- `ruff check` + `format --check` clean; `pyright src/` 0 errors.
- Fingerprints regenerated (56 tools, source_version 2.1.1); freshness guard passes.
- **Live, post-restart, against the real RTM API** — the check the suite structurally cannot do:
  `list_not_found`, `project_not_found`, `missing_parameter` all returned correct codes; success
  paths unaffected; the v2.1.0 `Errors:` clauses confirmed present in the descriptions the running
  connector actually serves.
- Guard mutation-tested (above).

**NOT run, and why:**
- **No cross-repo conformance check in CI.** The twin-conformance assertion between rtm-mcp's
  `VERDICT_REJECT_REASONS` and gtd's `validate-engage-verdict.py` was run **once, by hand**, as a
  shell command. It proved conformance at that moment and left nothing behind. See Open items.
- **No behavioural eval tier.** Still deferred; unchanged from the v2.0.0 debrief.
- The `[object Object]` artifact fix was done in a **separate session** (claude-plugins `89983a833`,
  merged `f8d5fa3f3`). I verified its content but did not write it and claim no credit for its
  testing.

## Open items / handback — the marketplace CI gap

Investigating whether the guard should extend to the plugin side surfaced a larger, **unfixed**
problem. Stated plainly so it is not mistaken for solved:

1. **`claude-plugins` has no CI at all** — no `.github/workflows`. Every test in that repo
   (gtd's 16 validator tests, `test_order_note.py`, `test_plan_graph_refresh.py`, the hiring and
   communication script tests) runs **only when a human remembers to run it**.
2. **gtd's validator tests are standalone.** They assert literals like `"type_illegal"` against the
   validator itself. If rtm-mcp renamed a code tomorrow, those 16 tests would still pass — both
   repos green, silently diverged.
3. **The lockstep seam is protected by prose in three files and nothing executable.** This release
   spent considerable effort documenting that renaming `off_enum` / `unknown_kind` / `type_illegal`
   in one repo silently breaks the other. That documentation is the entire enforcement.

**Two options, in dependency order:**

- **(a) Marketplace CI — the foundation.** A minimal `.github/workflows` running the existing Python
  test scripts on push/PR. Until this exists, *any* guard added to that repo is decorative.
  **Recommended first**, because it makes every subsequent check real rather than aspirational.
- **(b) Cross-repo conformance test.** Assert rtm-mcp's `VERDICT_REJECT_REASONS` set-equals the
  values gtd's validator emits. Honest caveat: hosted in rtm-mcp it would **skip in GitHub CI**
  (the runner has no `claude-plugins` checkout), making it a developer-machine guard, not a gate.
  A true gate needs (a), or the three values vendored into a shared file both sides read.

Neither is started. Owner: whoever picks up the thread — this is a fresh-brief-sized piece, not a
tail of this change.

Also still open, unchanged: the behavioural eval tier for the gtd project-plan suite.

## Conventions

| § | Applied |
|---|---|
| CONTRIBUTING § 3, surface 6 | The advertised half of the typed-error contract is now enforced, not just described |
| CONTRIBUTING § 5 | Error-construction rules unchanged; the `Errors:` docstring clause is the advertised counterpart |
| CONTRIBUTING § 9 | Lockstep — `CLAUDE.md` test inventory updated (975 → 1003) with the new class described |
| CONTRIBUTING § 10 | v2.1.0 MINOR (documentation restored), v2.1.1 PATCH (corrections + tests) |
| CONTRIBUTING § 14 | This debrief; parent change's debrief cross-linked |

## Durable lesson / gotcha

**A passing suite is not a correct contract — verify the surface consumers actually read.** For an
MCP server that is the advertised schema and description, not the return value. 975 green tests
coexisted with five tools advertising the wrong error shape.

**A manual audit is not a substitute for a guard, and can itself introduce defects.** The audit
found 34 gaps; the automated guard then found 5 more, one of which the audit had *created*.

**Environment gotcha (recurs, cost ~10 minutes twice).** `uv sync` can report
`Checked N packages` and change nothing while the editable install is inert — the `.pth` file
present but the package absent from `sys.path`, producing a confusing `ModuleNotFoundError` in
`conftest.py`. Neither `uv sync` nor `uv sync --extra dev` detects or repairs it. Only
`rm -rf .venv && uv sync --extra dev` does. Note the `--extra dev`: a bare `uv sync` drops pytest,
which then resolves from an ephemeral environment that has no `rtm_mcp` on its path at all — the
same symptom from a different cause.

---

*Source of truth: `tests/test_tool_schemas.py::TestAdvertisedErrorContract` (the enforcement) +
`CONTRIBUTING.md` § 5 (the construction rules) + `error_codes.py` (the registry).
Parent change: `typed-error-vocabulary-debrief.md`.
Implemented by Claude Opus 4.8, 2026-07-19.*
