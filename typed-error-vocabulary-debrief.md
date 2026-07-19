---
report_type: handback-debrief
scope: rtm-mcp-typed-error-vocabulary
implemented_by: Claude Opus 4.8 (Claude Code)
derived_at: 2026-07-19
target_repo: rtm-mcp
artifact:
  branch: feat/typed-error-vocabulary
  feature_commit: 592ef74
  version: v2.0.0 (MAJOR — breaking)
  pr: not yet raised (atomic release — see Open items)
relates_to:
  - Claude Code implementation brief — rtm-mcp typed error vocabulary (Option B)
  - designed-change candidate RTM 1217273391 (this IS that candidate landing)
  - write-boundary gates RTM 1217340684 (unblocked by this)
status: needs-atomic-release  # BOTH halves committed + verified; unpushed pending Paul's coordinated release
---

# Handback debrief — rtm-mcp typed error vocabulary (v2.0.0)

## What shipped

`data.error` is no longer a free-text prose string. It is a **structured object** carrying a
stable, machine-branchable `code`:

```json
{"error": {"code": "task_not_found",
           "message": "Task not found: 'Buy milk'. Use list_tasks to search by filter or check spelling.",
           "rtm_code": null,
           "details": {"query": "Buy milk"}}}
```

A wrapper, scheduled engine, or eval grader recovering from a failure now branches on `code`
instead of pattern-matching English. **The prose is carried verbatim** — the exact string that was
`data.error` through v1.35.0 is now `error.message`; only its location moved. Nothing is lost, so a
human reading a failure sees precisely what they saw before.

This completes **surface 6** of the family standard (deterministic server-surface uplift) and
unblocks the write-boundary gates, which reject recoverably on these codes.

Scale: a new 45-member registry, ~40 envelope call sites converted, 3 reject vocabularies unified,
975 tests green (25 new), all 56 tool fingerprints regenerated.

## Design decisions & deviations

**§7 open decisions (Paul, 2026-07-19).** The brief left four open. Decided:

| § | Decision | Note |
|---|---|---|
| 7.1 | Nested `details{}` + `extra="forbid"` on `ErrorBody` | Closed four-field top level; optional keys confined to `details` |
| 7.2/7.3 | Hard-cut, atomic release | No prose-parsing fallback, no version guard |
| 7.4 | Retain `rtm_code` | Transport fact preserved without leaking into the semantic name |
| reject scope | **IN scope**, full normalisation + gtd lockstep | Overrode the drafter's *and* my recommendation — see below |

**The consumer audit changed the risk calculus, and is why hard-cut is safe.** Before writing any
code I enumerated the migration surface (brief § 6.1). It is far smaller than the brief assumed:
**two** genuinely executable breaks, both in `project-plan-artifact.html` (lines 1244 and 2710,
where `d.error` is concatenated into user-visible chrome and would render `[object Object]`).
Everything else is agent-facing markdown or documentation. Decisively, **line 4914 of that same
file already does `rd.error.code === 'ambiguous_name'`** against agent-memory-mcp — the target
shape is already in-house and already consumed in the exact file needing migration. A
version-guarded fallback would have added dual-path code to a two-line surface.

**Unification exposed real drift — which is the argument for having done it.** Paul chose to bring
`rejected[].reason` into scope (I had recommended deferring). Folding three independently-grown
vocabularies into one registry surfaced genuine inconsistency that would otherwise have persisted:

```
off-enum                     -> off_enum                  (hyphen, LOCKSTEP)
unknown-kind                 -> unknown_kind              (hyphen, LOCKSTEP)
type-illegal                 -> type_illegal              (hyphen, LOCKSTEP)
confirm_destructive_required -> destructive_unconfirmed   (ONE concept with TWO names)
non_canonical_tag            -> strict_tag_rejected       (names the gate, not the tag)
not_found (engage)           -> task_not_found            (it is a task id miss)
```

`destructive_unconfirmed` vs `confirm_destructive_required` is the standout: the commit and engage
engines had two spellings for a single fact. A registry makes that impossible by construction.

**The lockstep seam is real and was nearly missed.** The three hyphenated values are not arbitrary
— they mirror gtd's `validate-engage-verdict.py` under the **ratified** `engage-verdict-grammar.md`,
which both sides conform to independently. Renaming them in rtm-mcp alone would have silently broken
twin-conformance. They are therefore normalised **with** matching changes to the gtd validator, its
tests, and the grammar document, and the constraint is now documented at all three sites
(`engage_commit.py`, `CLAUDE.md`, `CONTRIBUTING.md` § 5) so a future author cannot re-hit it.

**Deliberate scope boundary — two error shapes, one changed.** The brief did not distinguish them;
the codebase has both:

| Shape | Where | Status |
|---|---|---|
| Envelope error | `data.error` | **Restructured** — the union discriminator |
| Per-op batch failure | `data.errors[]` inside a *successful* envelope | **Unchanged** — flat `{"op", "id", "error": str(exc)}` |

The second reports partial failure in a batch that otherwise applied — a different contract, with
no consumer branching on it per the audit. Converting it would have been invisible scope creep.
Documented as a boundary, not silently widened. The commit engines' `rejected[].reason` is a third,
*flat* surface: its vocabulary comes from the registry, but an entry is `{reason, detail, …}` and is
**never** a nested envelope error.

**`ErrorData` keeps `extra="allow"`, only `ErrorBody` forbids.** `test_connection` / `check_auth` /
the undo paths legitimately set `status` and `transaction_id` *alongside* `error`. The tight
contract Paul asked for belongs on the error object itself, not on the payload that carries it.

## Membrane / activation

Vault-free, pure RTM. **No new tag, so no strict-tag activation-ordering hazard.**

**This is NOT additive and NOT backward-compatible** — that is the point of the major bump. The
release must be atomic:

1. Merge `feat/typed-error-vocabulary` (rtm-mcp v2.0.0).
2. Merge the marketplace lockstep **in the same push window** (gtd validator + tests + grammar doc,
   the two artifact lines, the agent-facing recovery references, the family standard).
3. Restart the MCP server so the connector serves v2.0.0.
4. Re-run the stale gtd proofs and confirm the fingerprint scan sees 56 schema-changed captures
   (expected — the `outputSchema` genuinely changed for every tool).

Ordering hazard: releasing the repo before the consumers leaves recovery paths degraded (the
artifact renders `[object Object]` in loader chrome). Not corrupting, but visible. Land together.

## Verification done

**Ran and passing:**
- `uv run pytest` — **975 passed** (was 946; +25 new registry tests, +4 from split assertions).
- `uv run ruff check` + `ruff format --check` — clean across `src/` and `tests/`.
- `uv run pyright src/` — **0 errors, 0 warnings**.
- Fingerprints regenerated (`scripts/dump-tool-fingerprints.py`, 56 tools, source_version 2.0.0);
  the committed-freshness guard passes.
- Advertised schema inspected directly off the live server object: `ErrorData.error` resolves to
  `ErrorBody` with `additionalProperties: false` and the code enum inlined.

**NOT run, and why:**
- **No live RTM call.** Every error path was exercised against the suite's mocks/respx, not the real
  API. The `rtm_code` round-trip is proven by unit test (`RTMNotFoundError(…, 341)` →
  `code: task_not_found`, `rtm_code: 341`), not by provoking a real RTM 341.
- **No stdio spot-check through a running connector** — that needs the server restarted on v2.0.0,
  which is an activation step (see Membrane). Validated in-suite instead.
- **No behavioural eval tier.** Brief § 8 recommends the gtd project-plan suite (~3 sub-agents)
  *after* the consumer pass lands. Not run here; it belongs to the post-migration checkpoint and is
  more valuable there.
**Marketplace lockstep — done, and independently re-verified (not taken on trust):**
- `claude-plugins` branch `feat/rtm-mcp-v2-typed-errors`, commit `c3ef8b021`. gtd 0.177.0 → 0.178.0,
  git-ops 0.12.2 → 0.12.3, ui-patterns 0.38.1 → 0.38.2; `marketplace.json` synced.
- gtd's `validate-engage-verdict.py` suite: **16/16 green**, re-run by me.
- **Twin conformance asserted directly across the two repos**: the values the gtd validator emits
  are set-equal to rtm-mcp's `VERDICT_REJECT_REASONS` → `True`. This is the invariant the whole
  lockstep exists to protect, so it is checked mechanically rather than by inspection.
- Artifact loader re-read by hand: `m` is provably always a string (code check → `.message` →
  `d.message` → literal), so no object can reach `esc()`.

## Conventions

| § | Applied |
|---|---|
| CONTRIBUTING § 5 | Rewritten — now the typed-vocabulary contract (construction rules, additive-only, the two-shapes boundary) |
| CONTRIBUTING § 3, surface 6 | Updated — "document what exists, don't invent codes" became "reuse a code, add only for a new failure, never rename" |
| CONTRIBUTING § 9 | Documentation lockstep — `CLAUDE.md` architecture tree, module table, Error Handling narrative, strict-tag components, engage lockstep note, test inventory (946 → 975) |
| CONTRIBUTING § 10 | MAJOR bump v1.35.0 → v2.0.0 across `pyproject.toml` + `__init__.py` + `uv.lock` |
| CONTRIBUTING § 6 | Untouched — no tag discipline change; the gate's *response shape* moved, its policy did not |

## Open items / handback

- **Atomic release is the open action** (see Membrane). BOTH branches are committed and
  **deliberately unpushed**, so neither half can land ahead of the other:
  - rtm-mcp — `feat/typed-error-vocabulary` (`592ef74` + `bf28eb5`)
  - claude-plugins — `feat/rtm-mcp-v2-typed-errors` (`c3ef8b021`)
- **Latent pre-existing bug flagged, not fixed** (out of scope, predates this change): the artifact
  does `res.rejected.join('; ')` at ~3007/3036/3070, but `rejected[]` entries are objects — so that
  fallback already renders `[object Object]`. Raised as a separate task.
- **`ci-activation-debrief.md`** was untracked before this work and was left untracked — unrelated.
- **Stale memory corrected:** my note claimed PR #33 (reject-reason constants) was unmerged. It is
  merged, in `main` at `923d8f8`.
- **Consumer — action required** (not "no action"): every enumerated consumer in the audit must be
  re-tested post-migration. That list is the regression checklist.
- Not attempted: unifying `data.errors[]` batch entries into the registry. A clean, separate change
  if it is ever wanted.

## Durable lesson / gotcha

**Do not brace-count Python source to find dict literals.** I twice wrote a scripted rewriter that
walked `{`/`}` to locate `{"error": …}` blocks. It corrupted six files both times, because
f-strings — `f"List '{list_name}' not found"` — contain braces for *interpolation* that are
indistinguishable from dict delimiters to a naive counter. The failure was loud (SyntaxError), but a
subtler transform could have silently mangled strings. **Use `ast`**: `ast.walk` for `ast.Dict`
nodes plus `ast.get_source_segment` gives exact spans and is immune to the problem. The third
attempt, AST-based, converted 31 sites with zero unmapped and zero breakage.

Two smaller traps for the next author:

- **`guided_error` has its own `reason` detail key** (explanatory prose). `as_rejection` therefore
  spreads `details` **first** and sets the canonical `reason` **after** — spread the other way and
  the prose silently clobbers the machine-branchable code. Pre-v2.0.0 `{**gate, "reason": <code>}`
  had the same ordering for the same reason.
- **Reason producers are not all dict literals.** `engage_commit.validate` uses *assignment*
  (`res["reason"] = "off-enum"`), so a regex keyed on `"reason": "…"` misses them entirely — and the
  miss surfaced only as a failing test, not a compile error. Grep for both forms.

Also: `uv sync` alone does **not** install the dev extras — `pytest` silently resolves from an
ephemeral env without `rtm_mcp` on the path, producing a confusing `ModuleNotFoundError` in
`conftest.py`. The cure is `uv sync --extra dev`. (Related to, but distinct from, the known stale-venv
`rm -rf .venv && uv sync` fix.)

---

*Source of truth: `CLAUDE.md` § "Error Handling" + `src/rtm_mcp/error_codes.py` module docstring
(the registry discipline) + `CONTRIBUTING.md` § 5 (construction rules).
Implemented by Claude Opus 4.8 from the Option B implementation brief, 2026-07-19.*
