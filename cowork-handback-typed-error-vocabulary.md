---
report_type: cowork-handback
scope: rtm-mcp-typed-error-vocabulary (Option B)
audience: the Cowork session that issued the implementation brief
implemented_by: Claude Opus 4.8 (Claude Code), 2026-07-19
status: DELIVERED — released, live-verified, consumers migrated
derived_from: "Claude Code implementation brief — rtm-mcp typed error vocabulary (Option B)"
closes: designed-change candidate RTM 1217273391
unblocks: write-boundary gates RTM 1217340684
---

# Handback to Cowork — rtm-mcp typed error vocabulary (Option B)

**Everything in the brief is delivered.** Repo and consumers released atomically, server restarted,
contract verified against the live RTM API. Two follow-up releases closed a gap the brief anticipated
but that the first pass under-delivered. Nothing is left half-landed.

---

## 1. Status at a glance

| Artefact | Version | Merge | State |
|---|---|---|---|
| rtm-mcp — typed error vocabulary | **v2.0.0** | `7afa57f` (PR #40) | released, live-verified |
| claude-plugins — lockstep migration | gtd 0.178.0 / git-ops 0.12.3 / ui-patterns 0.38.2 | `04de1cc58` (PR #21) | merged same window |
| rtm-mcp — error contract advertised | **v2.1.0** | `f3d2aa4` (PR #41) | merged |
| rtm-mcp — structural guard | **v2.1.1** | `c3dd0c8` (PR #42) | merged |

`main` = **v2.1.1**, 1003 tests green, CI green, server running this content.

---

## 2. Your §7 open decisions — as answered by Paul (2026-07-19)

| § | Question | Decision |
|---|---|---|
| 7.1 | Envelope detail shape | **Nested `error.details{}`** + `extra="forbid"` on `ErrorBody` |
| 7.2 | Fallback policy | **Hard-cut** — no prose-parsing fallback, no version guard |
| 7.3 | Release atomicity | **Atomic** — repo + consumers in one push window |
| 7.4 | `rtm_code` retention | **Retained** as `error.rtm_code` |
| — | `rejected[].reason` scope | **IN scope, full normalisation + gtd lockstep** (overrode the drafter's *and* the implementer's recommendation) |

The final wire shape:

```json
{"error": {"code": "task_not_found",
           "message": "Task not found: 'Buy milk'. Use list_tasks to search by filter…",
           "rtm_code": null,
           "details": {"query": "Buy milk"}}}
```

Prose is carried **verbatim** from the pre-v2.0.0 `data.error` string. Only its location moved.

---

## 3. Wrapper delta list (brief § 10)

The enumerated consumer surface from the §6.1 pre-implementation audit, with final migration state.
**Every row verified against the merged tree**, not from recollection.

### Executable — would have broken

| File | Site | State |
|---|---|---|
| `project-plan-artifact.html` | ~1244 seed-load failure (concatenated `d.error` into chrome) | **MIGRATED** — branches on `error.code === 'ambiguous_name'`, renders `error.message`; no object can reach `esc()` |
| `project-plan-artifact.html` | ~2710 redaction write-verification | **MIGRATED** — throws `error.message` |
| `project-plan-artifact.html` | ~2879 truthiness guard | **NO CHANGE NEEDED** — was already correct; deliberately untouched |
| `project-plan-artifact.html` | ~4914 `rd.error.code === 'ambiguous_name'` | **NOT IN SCOPE** — agent-memory-mcp, already object-typed. Served as the in-file precedent |
| `build-canvas-seed.py` | ~286 `obj.get("error")` | **FALSE ALARM** — reads gtd-side `rtm_fetch.py` output; `build_envelope` never emits a header `error`. No change |

### Executable prose — agent-read calling instructions

| File | State |
|---|---|
| `references/rtm-patterns.md` | **MIGRATED** — discriminator is now `data.error.code`; message explicitly must-not-parse |
| `references/tag-write-recovery.md` | **MIGRATED** — trigger keys on `error.code === "strict_tag_rejected"`; recovery material under `error.details`. *(Consumed by six plugins — written self-containedly)* |
| `skills/gtd/SKILL.md` | **MIGRATED** — inline restatement matched |
| `agents/inbox-stuff-executor.md` | **NO CHANGE NEEDED** — verified: a prose condition row, no wire-shape reference |

### Grammar lockstep — the seam that mattered

| File | State |
|---|---|
| `scripts/validate-engage-verdict.py` | **MIGRATED** — emits `off_enum` / `unknown_kind` / `type_illegal` |
| `scripts/test_validate_engage_verdict.py` | **MIGRATED** — **16/16 green** (re-run independently) |
| `references/engage-verdict-grammar.md` | **MIGRATED** — ratified grammar updated; now records that renaming a reason is a lockstep change to both repos |

**Twin conformance asserted mechanically across repos**: the values gtd's validator emits are
set-equal to rtm-mcp's `VERDICT_REJECT_REASONS`. Verified `True` post-merge.

### Documentation

| File | State |
|---|---|
| `mcp-tool-documentation-standard.md` § 3 | **MIGRATED** — rtm-mcp error shape = the structured object |
| `mcp-tool-documentation-standard.md` § 4.6 | **MIGRATED** — candidate RTM 1217273391 recorded as **landed**; rtm-mcp reclassified as full typed vocabulary alongside agent-memory-mcp |
| `mcp-tool-documentation-standard.md` § 7 | **MIGRATED** — rollout row → v2.0.0 |
| `gtd/specs/gtd.md` | **MIGRATED** — changelog entries updated, marked superseded rather than rewriting history |
| `project-plan-canvas-integration.md` | **MIGRATED** — names `ambiguous_name` / `project_not_found` |
| `engaging.md`, `engage-sweep-integration.md`, `day-to-day.md`, `return-grammar.md` | **MIGRATED** — reason spelling normalised so one spelling holds everywhere |
| `gtd-glossary.md`, `marketplace-standards.md` | **NO CHANGE NEEDED** — verified: describe the gate/standard, not the wire shape |

### Confirmed unaffected (searched, clean)

Eval graders (`plugins/*/evals/*/evals.json`), scheduled-task specs (`plugins/*/scheduled-tasks/*.json`),
and the other live artifacts (`project-plan-canvas.html`, `engage-sweep-canvas.html`,
`base-live-artifact.html`, `story-backlog-canvas.html` — zero occurrences of "error").

**Migration surface: fully closed. No known consumer remains on the old shape.**

---

## 4. Gate RTM 1217340684 — unblocked

The dependency is satisfied: a stable, additive-only `ErrorCode` registry exists, every failure
carries a `code`, and — since v2.1.0 — every tool that can fail **advertises** the codes it produces,
so a gate can branch on them and an agent knows they exist.

**Honest scope:** the gates themselves are neither implemented nor tested here. "Unblocked" means the
blocking dependency is removed, not that the gates work.

---

## 5. Deviations from the brief

**Two error shapes, only one changed — a boundary the brief did not draw.** The codebase has both an
*envelope* error (`data.error`, the union discriminator) and a *per-op batch failure* list
(`data.errors[]` inside a **successful** envelope: `{"op", "id", "error": str(exc)}`). Only the first
was restructured. The second reports partial failure in a batch that otherwise applied — a different
contract with no consumer branching on it. Converting it would have been invisible scope creep; it is
documented as a boundary instead. A third surface, the commit engines' `rejected[].reason`, stays
**flat** `{reason, detail}` — its vocabulary comes from the registry, but an entry is never a nested
envelope error.

**Unification exposed real drift, and normalising it went beyond a rename.** Folding three
independently-grown reject vocabularies into one registry surfaced genuine inconsistency:

```
off-enum                     -> off_enum                  (LOCKSTEP — grammar-bound)
unknown-kind                 -> unknown_kind              (LOCKSTEP — grammar-bound)
type-illegal                 -> type_illegal              (LOCKSTEP — grammar-bound)
confirm_destructive_required -> destructive_unconfirmed   (ONE concept, TWO names)
non_canonical_tag            -> strict_tag_rejected       (names the gate, not the tag)
not_found (engage)           -> task_not_found            (it is a task id miss)
```

The first three are bound to the ratified `engage-verdict-grammar.md`; renaming them required
changing gtd's validator, its tests, and the grammar document in the same release. This was flagged
to Paul before proceeding, because it widened the release into a second repo's executable validator
and a ratified document.

**`ErrorData` keeps `extra="allow"`; only `ErrorBody` forbids.** `test_connection` / `check_auth` /
the undo paths legitimately set `status` and `transaction_id` alongside `error`. §7.1's tight contract
belongs on the error object, not on the payload carrying it.

---

## 6. What the brief anticipated that the first pass under-delivered

Brief item 7 asked for docstring updates. v2.0.0 did the narrative docs (`CLAUDE.md`,
`CONTRIBUTING.md`) but **under-covered the tool docstrings** — and FastMCP advertises the docstring as
the tool description, so five tools were actively telling callers to expect a prose string while the
server returned an object.

Found by a **live tool call after the server restart**, not by the suite: 975 tests were green
throughout, because they assert the *runtime dict* and never the *advertised description*.

Auditing all 56 descriptions then exposed a larger, **pre-existing** gap — 34 tools could return an
envelope error and documented none, including every high-traffic tool and all three governed commit
surfaces. Closed in v2.1.0. v2.1.1 then added a structural guard so it cannot recur, which immediately
found **5 further gaps the manual audit missed** — one of them a case where the audit's own bulk edit
had made a docstring *actively wrong*.

Recorded because it is the load-bearing lesson: **a manual audit is not a guard, and can itself
introduce defects.**

---

## 7. Open items — what Cowork now owns

1. **Marketplace CI does not exist.** `claude-plugins` has no `.github/workflows`. Its gtd validator
   tests (and `test_order_note.py`, `test_plan_graph_refresh.py`, the hiring/communication script
   tests) run **only when a human remembers**. The rtm-mcp↔gtd lockstep seam this release documented
   so carefully is therefore enforced by **prose in three files and nothing executable** — rename a
   code in one repo and both stay green while silently diverging. **Recommended as the next designed
   change**, and as a prerequisite: until it exists, any guard added to that repo is decorative.
2. **Cross-repo conformance test** — assert rtm-mcp's `VERDICT_REJECT_REASONS` set-equals what gtd's
   validator emits. Depends on (1) to be a real gate: hosted in rtm-mcp it would *skip* in GitHub CI
   (the runner has no `claude-plugins` checkout), making it a developer-machine guard only. The
   alternative is vendoring the three values into a shared file both sides read.
3. **Behavioural eval tier** — brief § 8 recommended the gtd project-plan suite (~3 sub-agents) *after*
   the consumer pass. Not run. Now is when it is most informative, since the recovery paths genuinely
   changed.
4. **Changelog** — brief § 10 asks for the multi-repo cascade logged in `memory/_changelog.md`. Not
   done here (vault write); the four merge SHAs in § 1 are what it needs.

---

## 8. Verification boundary — what was and was not proven

**Proven:** 1003 tests; ruff + pyright clean; 56 fingerprints regenerated; CI green on both merge
commits; gtd validator 16/16 re-run independently; twin conformance asserted mechanically across
repos; the structural guard **mutation-tested** (two induced failures caught, clean restore); and the
envelope verified **live against the real RTM API** post-restart — `list_not_found`,
`project_not_found`, `missing_parameter` returning correct codes, success paths unaffected.

**Not proven:** no live RTM *transport* error was provoked (the `rtm_code` round-trip is unit-tested,
not exercised against a real RTM 4xx); no behavioural eval tier; no cross-repo conformance check runs
in any CI; the write-boundary gates are unimplemented. The `[object Object]` artifact fix
(`89983a833`) was made in a **separate session** — its content was verified here, but it was not
written or tested by this one.

---

*Repo-side detail: `typed-error-vocabulary-debrief.md` (v2.0.0) and `error-contract-guard-debrief.md`
(v2.1.0/v2.1.1), both on rtm-mcp `main`. Cross-ref SHA for Cowork: **`c3dd0c8`** (rtm-mcp v2.1.1) and
**`04de1cc58`** (claude-plugins lockstep).*
