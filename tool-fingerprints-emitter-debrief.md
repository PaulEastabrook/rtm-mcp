---
report_type: handback-debrief
scope: tool-fingerprints-emitter
implemented_by: Claude Opus 4.8 (Claude Code session)
derived_at: 2026-07-18
target_repo: rtm-mcp
artifact:
  feature_commit: 842fc80
  branch: feat/tool-fingerprints-emitter
  version: 1.32.3
  pr: (open on push)
relates_to:
  - "Session brief: tool-fingerprints emitter (Cowork, 2026-07-18)"
  - "Family standard § 5 Schema fingerprints (mcp-tool-documentation-standard.md)"
  - "Designed change 2026-07-18-tool-detection-schema-fingerprints.md (marketplace 3e9775c24)"
  - "Consumer: architect tool-detection v2 (RTM 1217273388; interface-proof currency RTM 1217273393)"
status: needs-restart (push + PR + merge; no server restart needed for the consumer)
---

# Tool-fingerprints emitter — handback debrief

## What shipped

`rtm-mcp` now commits a **`tool-fingerprints.json`** at its repo root: a per-tool `sha256`
fingerprint of each tool's advertised schema, so the architect's weekly tool-detection scan can diff
per-tool fingerprints (schema-changed events) instead of re-introspecting, and downstream
interface-proof currency can key on them (RTM 1217273393). The file covers all **56** tools, names
them fully qualified (`mcp__rtm__list_tasks` style), and carries `schema_version` / `server` /
`generated_at` / `source_version` per the standard § 5 shape.

Freshness is enforced **by this repo, not the consumer**: a new test in `tests/test_tool_schemas.py`
recomputes the fingerprint map from the live server and asserts equality with the committed file, so
any schema change (docstring, param, annotation, or output schema) that isn't accompanied by a
regenerated file fails CI. Regeneration is one command: `make fingerprints`.

This is **tooling + a generated artefact only** — no tool behaviour, return value, or schema changed.
Version bumped **patch → 1.32.3** (pyproject + `__init__` + uv.lock together).

## Design decisions & deviations

- **`server: "rtm"`, not `"rtm-mcp"`.** The FastMCP server's internal `name` is `"rtm-mcp"`, but the
  architect composes qualified names as `mcp__<connector-slug>__<tool>` and the connector slug is
  `rtm` (matches the standard's example `"server": "rtm"` and the live `mcp__rtm__*` tool ids). So the
  script hard-codes `SERVER = "rtm"` with a comment; do **not** switch it to `mcp.name`.
- **One-truth fingerprint computation.** The freshness test loads the generator script by path
  (`importlib.util.spec_from_file_location` — the filename has a hyphen and isn't import-safe) and
  calls its `compute_fingerprints()`, rather than re-implementing the hash. Generator and guard can't
  drift because there's exactly one implementation. No new `src/` module was added (the brief scoped
  it to script + test + generated file; a path-load keeps the shipped package unchanged).
- **The freshness test compares only the `tools` map** (plus `schema_version`/`server` sanity), NOT
  `generated_at` (changes every run) or `source_version`. Deliberate: the guarantee is "schema change
  → regenerate", so a plain version bump does **not** force a regen. `make fingerprints` still stamps
  a current `source_version`/`generated_at` when you do run it.
- **Annotations serialized with `model_dump(mode="json", exclude_none=True)`** — mirrors how the
  existing schema tests read annotations (the client-visible set), and keeps the hash stable.
- **`--check` mode** added beyond the brief: a no-write CI-parity verifier (`make fingerprints` writes;
  `--check` only asserts and exits non-zero on drift). Cheap, and lets a CI job assert freshness
  without a working-tree write if preferred over the pytest guard.
- **Inventory total corrected, not just incremented.** `CLAUDE.md` said "938 tests total / 17 in the
  schema file"; the live suite is **946 / 20** (the v1.32.2 credential-redaction PR added tests
  without updating the inventory). I set both to the live count rather than propagating 938+2.

## Membrane / activation

- Additive and backward-compatible. **No server restart needed for the consumer** — the architect
  reads the committed file from git; it does not call the server for this. An **absent** file simply
  degrades that server to names-only detection (standard § 5), so nothing breaks before merge.
- **Operational:** the branch is committed but not pushed. Push `feat/tool-fingerprints-emitter`, open
  the PR, merge. The architect **picks the file up automatically on its next Sunday scan** — no
  marketplace change required.
- **No new tag, no strict-tag interaction, no ordering hazard.** Pure read-side tooling.

## Verification done

- **Ran:** `uv run pytest` → **946 passed** (excluding one stray Dropbox conflict-copy file, see
  gotcha). `ruff check` + `ruff format --check` (src, tests, scripts) clean; `pyright src` → 0 errors.
- **Freshness guard demonstrated red→green** as the brief's acceptance requires: mutated a real tool
  docstring (`gtd_project_plan`) → `TestToolFingerprints` FAILED with the exact per-tool hash diff →
  reverted + `make fingerprints` → PASSED. `--check` prints "current (56 tools)".
- **Not run:** no live RTM API call or stdio JSON-RPC smoke — unnecessary here (the emitter introspects
  the in-process server at import, exactly like the existing schema suite; no network, no auth). The
  architect-side consumption was not exercised from this repo (out of scope; consumer landed
  marketplace-side as 3e9775c24).
- **CI caveat (integrity note):** GitHub Actions is nominally enabled and `.github/workflows/ci.yml`
  runs `uv run pytest` on push/PR, but **this repo's CI is dormant** — no workflow runs are recorded
  and PR #34 reports no checks (consistent with the v1.32.2 credential-redaction debrief's finding).
  So the "fails CI" guarantee describes the *mechanism* (the freshness test exists and fails on drift);
  the **live enforcement today is a local `make test`**. The stray Dropbox dup does not affect CI even
  if it wakes up — it's untracked, so it's absent from a fresh checkout (CI would see the true 946).

## Conventions

§ 9 lockstep (CONTRIBUTING gains the regenerate-on-schema-change one-liner; CLAUDE.md inventory
updated) · § 10 version (patch; three version sources together) · standard § 5 (fingerprint
definition, file shape, qualified names, repo-enforced freshness).

## Open items / handback

- **Push + PR + merge** the branch (only outstanding step for this change).
- **Remaining family repos** (per the brief's rollout order): `agent-memory-mcp` next, then
  `mindmeister-mcp` / `meistertask-mcp` once they reach the six-surface standard. This script is the
  reusable pattern — the only per-repo variables are `SERVER` (connector slug) and the test's import
  path. **Consumer — no action** (auto-picked on the next Sunday scan).
- **Not touched:** the interface-proof-currency consumer (RTM 1217273393) — explicitly out of scope.

## Durable lesson / gotcha

- **Stray Dropbox conflict-copy files pollute this repo's test collection.** Four untracked
  space-`2` files exist (`tests/test_tool_schemas 2.py`, `src/rtm_mcp/models 2.py`,
  `engage-commit-steer-note-debrief 2.md`, `tool-documentation-uplift-debrief 2.md`) — the exact
  partial-sync corruption that got the repo moved out of Dropbox. `tests/test_tool_schemas 2.py`
  **matches `test_*.py` and is collected by pytest**, inflating the run to 963 and executing stale
  copies of these tests. The real count is **946** (run with
  `--ignore="tests/test_tool_schemas 2.py"`). I left them untracked and unstaged (didn't create them,
  so didn't delete them) — **recommend `git clean`-ing these four files**; they can only cause
  confusion.
- **Server slug ≠ FastMCP name.** `mcp.name` is `"rtm-mcp"`; the qualified-name/`server` slug is
  `"rtm"`. Anyone regenerating for another repo must set `SERVER` to that repo's connector slug, not
  its FastMCP name.
- **The generator is the single source of the hash** — never re-implement the fingerprint in the test.
  If you change the fingerprint definition, change it in `scripts/dump-tool-fingerprints.py` only and
  regenerate; the test follows automatically.

## Footer

Source of truth: `scripts/dump-tool-fingerprints.py` (docstring) + `tests/test_tool_schemas.py`
`TestToolFingerprints` + CONTRIBUTING § 9 + CLAUDE.md § Testing inventory. Contract: family standard
§ 5 "Schema fingerprints". Provenance: session brief (Cowork, 2026-07-18); designed change
2026-07-18-tool-detection-schema-fingerprints.md (marketplace 3e9775c24); consumer architect v0.92.0
(RTM 1217273388).
