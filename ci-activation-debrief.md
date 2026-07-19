---
report_type: handback-debrief
scope: CI activation + Dockerfile README fix
implemented_by: Claude Opus 4.8 (Claude Code session)
derived_at: 2026-07-19
target_repo: rtm-mcp
artifact:
  prs: "#35 (merge 140fb7d), #36 (merge 04b31e4)"
  feature_commits: "65554fe, a59920a, f3abaf0"
  branch: main
  version: 1.32.3 (unchanged — no source change)
relates_to:
  - "tool-fingerprints-emitter-debrief.md — its freshness guard is the main beneficiary"
  - "credential-redaction-reject-reason-consts-debrief.md — first recorded the dormant-CI caveat"
  - "tool-fingerprints-emitter-noop-debrief.md — same session; carried the caveat until corrected"
status: DONE — main green, no follow-up required
---

# CI activation + Dockerfile fix — handback debrief

## What shipped

**rtm-mcp's CI now runs.** It never had, in the repo's entire history — zero workflow runs, and PRs
#25–#34 all reported no checks. Every debrief since v1.32.2 therefore carried a caveat that local
`make test` was the only real enforcement. That caveat is now retired: CI fires on push and PR to
`main`, and `main` is green across all five jobs.

Activating it immediately surfaced a real latent defect — the `docker` job had **never once run**, and
failed on first execution. That is fixed too.

No source, test, tool-behaviour, or version change. Version stays **1.32.3**.

## Design decisions & deviations

- **The cause was `disabled_manually`, not a broken config.** This is the single most valuable fact
  here. `.github/workflows/ci.yml` has been present and correct since the initial release (`f778b09`,
  never edited). Someone disabled the workflow in the GitHub UI. **The trap:** both `gh workflow list`
  and `gh run list` conceal this — the former omits disabled workflows entirely, the latter returns
  empty, which is indistinguishable from "never triggered". Only **`gh workflow list --all`** reveals
  it. Prior sessions diagnosed the symptom correctly (zero runs) and the cause wrongly (assumed
  trigger/config), because the obvious commands actively mislead. Fix was `gh workflow enable`.
- **Added `workflow_dispatch`** so CI can be exercised on demand without a dummy commit. Note it does
  **not** help the docker job (see the gap below) — `workflow_dispatch` is a third event name, so that
  job's `github.event_name == 'push'` condition still excludes it.
- **Dockerfile fix — one line, pre-existing bug.** `pyproject.toml` declares `readme = "README.md"`,
  but `Dockerfile:12` copied only `pyproject.toml`, `uv.lock*` and `src/`. hatchling then fails
  metadata validation during `uv build --wheel`. Invisible until now because (a) CI never ran the job,
  and (b) the separate `build` job builds from a full checkout where the README is present.
  `.dockerignore` already whitelists `README.md` (`*.md` then `!README.md`), so the omission was in the
  `COPY`, not deliberate. **The published image could never have been built from this Dockerfile** —
  worth knowing given CLAUDE.md's deployment section documents `docker push ghcr.io/…`.

## Membrane / activation

Nothing to activate — CI is live and `main` is green. No server restart, no tag, no ordering hazard.

**The consequence that matters:** the `tool-fingerprints.json` freshness guard is now a genuine merge
gate. Since v1.32.3 its "fails CI on drift" property was true of the *mechanism* only; a schema change
without `make fingerprints` will now actually block a PR. Same for every other test in the suite.

## Verification done

- **PR #35** (activation) — green: lint, test (3.11), test (3.12), build. `docker` skipped by design.
- **PR #36** (Dockerfile) — green: lint, test (3.11), test (3.12), build. `docker` skipped again.
- **Post-merge on `main` (`04b31e4`) — ALL FIVE GREEN including `docker`.** This is the run that
  actually proves the fix; the PR could not.
- **Locally, before pushing:** pytest **946 passed on both matrix versions (3.11 and 3.12)** — my
  first pass had used 3.14, which would not have proven the matrix; `ruff check` + `ruff format
  --check` clean; `pyright src` 0 errors.
- **Dockerfile fix proven twice locally before merge:** (1) replicated the builder stage's exact file
  set in a clean dir → identical `OSError: Readme file does not exist: README.md`; adding `README.md`
  → `Successfully built rtm_mcp-1.32.3-py3-none-any.whl`. (2) full `docker build` → exit 0, then
  `which rtm-mcp` → `/usr/local/bin/rtm-mcp` and `import rtm_mcp` → 1.32.3, confirming the wheel
  **installs**, not merely builds.
- **NOT done:** no source or test change was made, so nothing in the package was re-validated beyond
  the existing suite. The published ghcr.io image was **not** rebuilt or pushed — the CI docker job
  builds without pushing (`push: false`), so any previously published image is untouched and, by this
  finding, cannot have come from this Dockerfile.

## Conventions

§ 14 (this debrief). No § 9 doc lockstep (no tool/schema change), no § 10 version bump (no source
change), no § 6 tag discipline (no tag).

## Open items / handback

- **This change — no action.** CI live, `main` green.
- **Known gap, deliberately not closed: the `docker` job never runs on a PR.** It is gated
  `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`, so the container build is only
  ever tested *after* a change lands. That is precisely how this bug reached `main` and stayed there.
  Adding `pull_request` to that condition (still `push: false`) would gate it at review time. Raised
  with Paul and left as a follow-up — out of scope for "activate CI".
- **Superseded guidance:** any debrief or note saying "CI is dormant on rtm-mcp — verify locally" is
  wrong from 2026-07-19. Corrected in `tool-fingerprints-emitter-noop-debrief.md`; the older
  `credential-redaction-reject-reason-consts-debrief.md` still carries the stale claim in its own text
  (left as-is — it is a historical record, and this debrief supersedes it).
- **Observed, untouched, NOT an action item:** `mindmeister-mcp`'s latest CI run (2026-07-19,
  "six-surface tool-documentation standard + tool-fingerprints.json emitter (v0.2.0)") is **failing**.
  Same fingerprints rollout as this repo's v1.32.3; `meistertask-mcp` (same feature) and
  `agent-memory-mcp` are green. Paul explicitly chose to leave it. Recorded so it is not lost.
  All three siblings' workflows are `active` — rtm-mcp's disabled state was isolated, not a pattern.

## Durable lesson / gotcha

- **`gh workflow list --all` is the only command that reveals a manually-disabled workflow.** If a
  repo has an obviously-correct workflow file and zero runs, check this *first* — the default commands
  will send you looking for a config bug that isn't there.
- **A skipped job is not a passing job.** The docker job showed as `skipping` on both PRs, which reads
  as benign in the checks list but meant the fix was entirely unverified by CI until merge. Read
  skip-conditions before trusting an all-green PR.
- **`uv run` here defaults to Python 3.14; the CI matrix is 3.11/3.12.** Local green does not prove the
  matrix — use `uv run --python 3.11` / `--python 3.12`.

## Footer

Source of truth: `.github/workflows/ci.yml` + `Dockerfile`. Provenance: session 2026-07-19; PRs
[#35](https://github.com/PaulEastabrook/rtm-mcp/pull/35) and
[#36](https://github.com/PaulEastabrook/rtm-mcp/pull/36).
