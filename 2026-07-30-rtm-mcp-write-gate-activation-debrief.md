---
report_type: handback-debrief
scope: write-gate activation — v5.1.0 restarted, gates verified live, merged and pushed; plus the environment fault that was masking it
implemented_by: Claude Code (rtm-mcp session, 2026-07-30)
derived_at: 2026-07-30
target_repo: rtm-mcp
artifact: merge `ffbd00a` on `main` (feature commit `1d7ec65`), v5.1.0 — no PR, merged locally
relates_to: >-
  predecessor 2026-07-26-rtm-mcp-write-gate-observability-debrief.md (the implementation, status needs-restart);
  designed change general/plugin-marketplace-architect/designed-changes/2026-07-26-write-boundary-gate-observability.md;
  2026-07-19-rtm-mcp-write-boundary-gates-debrief.md (v2.2.0, where both gates shipped off)
status: DONE
---

# Handback debrief — write-gate activation (v5.1.0)

**Ten-second version.** v5.1.0 is live, merged to `main` (`ffbd00a`) and pushed; CI green. Both
previously-dormant write gates were **probed against the running server** and both reject; both
rejections reached the new file log sink on the instance whose fd 2 is `/dev/null` — the exact loss
the change existed to close, now observed rather than argued. Branch hygiene done (24 local, 12
remote, all merged). **Two things remain open and neither is mine:** the board artifacts still need
re-rendering, and Paul needs to decide what to do about iCloud (below), which is a genuine
infrastructure problem this session uncovered.

## What shipped

Nothing new was written. This session **activated** what v5.1.0 had already built and left at
`needs-restart`, then verified it.

| | Before | Now |
|---|---|---|
| `RTM_STRICT_NOTES` | `shape` in code, never exercised live | **rejecting live** (`note_shape_rejected`) |
| `RTM_STRICT_LIST_TARGETS` | on in code, never exercised live | **rejecting live** (`smart_list_target`) |
| Gate WARNINGs on the Desktop-spawned server | destroyed (fd 2 is `/dev/null`) | **landing in `~/.config/rtm-mcp/logs/rtm-mcp.log`** |
| v5.1.0 | unmerged branch | merged `ffbd00a`, pushed, CI green |

## Design decisions & deviations

**The probes were built to be side-effect-free by construction, not by luck.** Verifying a *write*
gate means attempting a write, so the probes were designed so that a gate which is *off* still writes
nothing:

- **Note gate** — `add_note` with a malformed title and deliberately fake ids (`000000`). The gate
  runs **before** the task lookup ([`src/rtm_mcp/tools/notes.py:104`](src/rtm_mcp/tools/notes.py)), so
  a live gate rejects on shape and a dead gate fails resolution. Either way nothing is written. That
  ordering is load-bearing for the probe; it exists so a rejection costs no API call, and it happens
  to make the gate safely testable against a live account.
- **List gate** — `add_task` at the smart list `Single Actions`. RTM rejects smart-list adds anyway,
  so the worst case was a downstream error rather than a write.

**The rejection prose was checked, not just the code.** Flipping a default silently invalidates any
guidance that told the caller to *enable* the thing now on. Both messages name the shipped default
correctly (`set RTM_STRICT_NOTES=warn` / `RTM_STRICT_LIST_TARGETS=0` to relax). This was a real risk:
pre-v5.1.0 the note-gate text told a caller to *unset* the variable, which after the flip would be
advice to leave the gate on.

**Gate 1 (strict tags) was not re-probed.** It has been on by default since long before this change
and nothing in v5.1.0 touched it. Its liveness is asserted in-suite, not in this session.

**Remote branch deletion was not bundled into "sweep".** Local deletion is a clone-level change;
deleting on origin mutates the shared repo. I confirmed all 12 were merged into `origin/main` with no
open PRs, then asked before pushing the deletions. SHAs were captured first so any ref can be
recreated (`git branch <name> <sha>`).

## Membrane / activation

**Nothing further to activate.** The server is running v5.1.0 (the launch config is `uv run --project
<clone>`, so the working tree *is* production — `main` at `ffbd00a` is what serves the next request).
Vault-free, no new tag, no new `ErrorCode`, no schema change.

**Rollback stays one env var per gate**, each asserted by test: `RTM_STRICT_NOTES=off`,
`RTM_STRICT_LIST_TARGETS=0`.

## Verification done — and what was not

**Run and green:**

- `PYTHONPATH=src make test` → **1741 passed**.
- `make lint` → naming `--strict` clean, `ruff check` clean, `ruff format --check` clean (100 files),
  `pyright` 0 errors.
- **Live probes** against the running MCP server: `note_shape_rejected` and `smart_list_target`, both
  with zero writes, both records confirmed in the rotating file sink.
- **CI green on the merge** (run `30584676614`, 3m06s) — an independent check on a clean checkout.

**Not run, stated plainly:**

- The strict-**tag** gate was not probed live (see above).
- The board artifacts were **not** re-rendered or retested; no consumer-side check was performed.
- No live probe of `edit_note`'s title-changing path, `move_task`, or the `warn` mode — all in-suite
  only.
- **`make test` without `PYTHONPATH=src` fails 2 tests on this machine.** That is environmental, not a
  defect — see below. CI, which has no iCloud, passes the same tests unmodified, which is what makes
  the environmental attribution defensible rather than convenient.

## The environment fault — the durable lesson

**Symptom.** `make test` reported `1739 passed, 2 failed`, the two failures being exactly
`test_logging.py::TestTheSinkThatSurvivesDevNull` — the load-bearing sink tests. They spawn a child
`sys.executable`, and the child died with `ModuleNotFoundError: No module named 'rtm_mcp'`. Because
those probes deliberately redirect the child's stderr to `/dev/null`, all the failure showed was
`returncode == 1` and empty stdout. **Re-running the child's `-c` payload by hand, with stderr
visible, was what turned an apparent code defect into an environment diagnosis in one step.**

**Cause.** The editable-install `.pth` in `.venv` carries the macOS `UF_HIDDEN` flag, and Python
silently skips a hidden `.pth`, so the package never enters `sys.path`. The prior recorded cure was
`chflags nohidden` — which works for about two seconds. Something re-applies the flag.

**Culprit, identified by probe rather than inference: iCloud Drive's "Desktop & Documents Folders"
sync, via `fileproviderd`.**

| Probe | Result |
|---|---|
| dot-prefixed dir under `~/Documents` or `~/Desktop` | **hidden within ~2s**, recursively |
| same under `~/Downloads`, `~/Movies`, `$HOME`, `/tmp` | never hidden |
| `notdotvenv/` (no leading dot) in the repo | never hidden |

That boundary *is* the iCloud Desktop & Documents scope, and `~/Documents` carries
`com.apple.icloud.desktop` + `com.apple.file-provider-domain-id` to match. The rule is the **leading
dot**, not the name — a fresh `.dotprobe/` is hidden as fast as `.venv`. Ruled out by measurement:
`uv` (`uv run python`, `uv run pytest --version`, `uv sync --all-extras` each left the flag clear),
Syncthing (syncs only `~/Documents/AI Memory`), and the repo itself (no `chflags`/`UF_HIDDEN` in
`src`, `tests`, `scripts`). The `com.dropbox.attrs` xattr on the repo is residue from before the
2026-07-13 move.

**Why this matters more than the flag.** The repos were moved out of Dropbox *because* a cloud
provider kept corrupting their venvs. `~/Documents/Code` is cloud-managed too — **the hazard was
swapped, not escaped.** Live evidence inside `.venv`: `bin 2`, `lib 2`, `pyvenv 2.cfg`,
`CACHEDIR 2.TAG` (conflict copies) and files flagged `dataless` (contents evicted to the cloud). A
dataless `.pth` is exactly the `ModuleNotFoundError` recorded on 2026-07-17.

**It also explains a maddening pattern**: a long suite passes, and the *very next* run fails at
`conftest`. The flag flips mid-suite, after the conftest import that made the run possible.

## Open items / handback

| # | Item | Owner |
|---|---|---|
| 1 | **Decide on iCloud.** Options, best first: (a) move the clones out of `~/Documents` (e.g. `~/Code`) — ends the class of problem, but the Desktop launch config hardcodes `$HOME/Documents/Code/<repo>`, so repo + config move together; (b) keep the repos, move the venvs: `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/<repo>` (`$HOME` is outside the scope — verified); (c) per-run `PYTHONPATH=src` only. **Nothing applied — this is Paul's call**, and it affects all four MCP-server repos, not just this one. | Paul |
| 2 | **Re-render the board artifacts.** Carried over unresolved from the receipts trial. A rendered artifact freezes its tool names and its `mcpTools` allowlist, so it is a live caller no repo grep can see. | Cowork |
| 3 | **gtd notes-audit must adopt the free-text rule** — *no date prefix → Paul's own note, informational, never a finding.* Carried over from the v5.1.0 debrief; the server is safe by construction (it never sees the RTM app), but the audit is not. | gtd |
| 4 | Note-vocabulary promotion (13 of 27 catalogue types already server-owned) — its own designed change, deliberately sequenced after the shape gate proved live. It now has. | architect |

**Consumer — no action** for items 1 and 4 in the immediate term; item 2 is the only one blocking
anything consumer-facing.

## Conventions

§ 6 (tag discipline — untouched, no new tag), § 9 (lockstep — none triggered), § 10 (version — v5.1.0
already bumped by the predecessor), § 14 (this debrief).

## Durable gotchas

1. **A write gate can be probed safely if it runs before resolution.** Check the ordering before
   assuming a live-account probe is destructive.
2. **When a child-process test fails opaquely, re-run its payload with stderr visible before touching
   any code.** These probes redirect to `/dev/null` by design; the honest failure was one command away.
3. **`chflags nohidden` is not a cure on this machine, it is a two-second reprieve.** Prior guidance
   said otherwise; it has been corrected in memory.
4. **Flipping a default silently invalidates prose that told callers to enable it.** Grep the
   guidance strings whenever a default flips.
5. **Green CI plus red local is a signal about the machine, not permission to ignore the red.** Here
   it was the discriminator that made the environmental attribution honest.

---

**Source of truth:** `CLAUDE.md` § "Write-gate observability", § "Note-shape mode + list-target mode",
and the `add_note` / `add_task` docstrings. **Predecessor:**
`2026-07-26-rtm-mcp-write-gate-observability-debrief.md` (implementation; this is activation).
**Provenance:** Claude Code session, 2026-07-30, rtm-mcp on `main` @ `ffbd00a`.
