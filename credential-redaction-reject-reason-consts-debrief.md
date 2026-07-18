---
report_type: implementation-handoff-debrief
scope: rtm-mcp — two small fixes — redact credentials from test_connection echo (v1.32.1) + canonicalise reject-reason vocabularies (v1.32.2)
implemented_by: Claude Code (Opus 4.8) session on the rtm-mcp repo
derived_at: 2026-07-18
target_repo: rtm-mcp — ~/Documents/Code/rtm-mcp
artifact:
  version: 1.32.2
  pr: https://github.com/PaulEastabrook/rtm-mcp/pull/33
  branch: fix/credential-redaction-reject-reason-consts
  commits:
    - 290527f — fix: redact credentials from test_connection echo (v1.32.1)
    - 1b806bc — refactor: promote reject-reason vocabularies to canonical constants (v1.32.2)
relates_to:
  - brief: rtm-mcp small-fixes (credential redaction + reject-reason constants) — this session
  - source note: RTM 1217340361 (credential echo, observed live 2026-07-18)
  - source note: RTM 1217333831 (reject-reason single-source)
  - predecessor: tool-documentation-uplift-debrief.md (IC #2 — the documentary Literals this replaces)
status: needs-restart
---

## What shipped

Two independent, behaviour-scoped fixes, one patch commit each, on top of the v1.32.0 uplift.

**1 — `test_connection` no longer leaks credentials.** `rtm.test.echo` reflects every request
parameter back verbatim, so `test_connection`'s `api_response` was placing **`api_key`,
`auth_token`, and `api_sig`** into the calling model's conversation context — and any transcript
derived from it — on **every** call (observed live 2026-07-18). The echoed payload now passes through
`response_builder.redact_secrets(...)`, which masks secret-bearing keys as `"***redacted***"` before
the response is built. `stat` and the response-time measurement survive, so the tool still diagnoses
connectivity.

**2 — reject-reason vocabularies are now single-sourced.** The canvas/create/engage rejection
`reason` sets were duplicated between the handlers (inline literals) and the output-schema models
(documentary `Literal`s / an untyped dict), free to drift. Each handler module now owns its complete
emitted vocabulary as a frozenset, and `models.py` sources each `rejected[].reason` schema enum from
that constant; `test_tool_schemas` asserts schema == `sorted(constant)`, so drift is now impossible
(same guarantee the input enums already have).

## Design decisions & deviations

- **`redact_secrets` masks (not strips) and recurses.** Masking keeps the key present so a diagnostic
  reader sees the shape without the value; recursion is defensive (RTM's echo is flat today, but a
  future reflected payload could nest). Secret-key set is broad and case-insensitive:
  `api_key/auth_token/api_sig` + `frob/token/secret/shared_secret`. Non-mutating (returns a copy).
- **Audit result: `test_connection` was the only leak.** `check_auth` already builds a clean
  `user`/`permissions` dict from the raw response (no reflection); the other two `build_response(data=result)`
  sites in `utilities.py` carry internal URL/list-resolution dicts, not API credentials. No shared
  changes were needed beyond the one helper.
- **The reason constants are the COMPLETE emitted set, including the tool-layer reasons.** Five commit
  reasons come from `validate_commit`, but `invalid_scope` and `non_canonical_tag` are emitted in the
  tool wrapper (`tools/gtd.py`) — they are included in `COMMIT_REJECT_REASONS` with `# tool:` comments,
  because the schema advertises the *whole* vocabulary a caller can see. Same for `CREATE_REJECT_REASONS`
  (`+ non_canonical_tag`) and `ENGAGE_REJECT_REASONS` (`VERDICT_REJECT_REASONS + not_found /
  confirm_destructive_required / bad_date / non_canonical_tag`).
- **This made the schema HONEST, not just tidy.** The old `CommitRejection` / `CreateRejection`
  `Literal`s were **missing `non_canonical_tag`** — the strict-tag gate's reason, emittable by both
  tools. The emitted runtime strings are byte-identical (behaviour-preserving, as the brief required);
  the *schema* gained the previously-absent value. Called out in the commit body and PR.
- **Engage was genuinely closed, so it was modelled** (the brief left the door open to "record it's
  free-text instead"). New `EngageRejection` model gives `gtd_apply_engage_commit.rejected[]` a typed
  reason enum where it previously had `list[dict[str, Any]]`.
- **`json_schema_extra` via a typed `_enum_extra()` helper.** A bare `{"enum": sorted(...)}` literal
  trips pyright (dict value-invariance vs pydantic's `JsonValue`); a helper returning `dict[str, Any]`
  is clean. If you add another enum-sourced field, reuse it.

## Membrane / activation

- **Additive + backward-compatible; no new tag, no strict-tag interaction, no activation-ordering
  hazard.** Change 1 only redacts an existing field's contents; Change 2 only relocates constants and
  makes the advertised schema honest (no runtime behaviour change).
- **To go live: restart the MCP server on v1.32.2** so `test_connection` stops leaking and the tools
  advertise the sourced enums. Until then the running (pre-restart) server still echoes credentials.
- **⚠️ Rotate the RTM auth token.** It has already appeared in prior transcripts through this echo path.
  Re-run `rtm-setup` (RTM tokens don't expire but can be revoked/replaced). This is a Paul action, not
  a code change.

## Verification done

- **Full suite: 961 passed** (was 938 in the inventory + 23 net-new: 4 `redact_secrets` unit tests,
  1 `test_connection` redaction tool test, the schema-equality test, and the pre-existing count).
- **ruff check + ruff format --check: clean** across `src/` + `tests/`.
- **pyright: 0 errors** on all of `src/`.
- **Live introspection spot-check** (real `rtm_mcp.server.mcp`): `redact_secrets` masks all three
  secrets on a realistic echo while keeping `stat`; all three `rejected[].reason` enums are present in
  the built output schemas and equal their constants.
- **NOT run: GitHub Actions CI.** `ci.yml` exists on main and Actions is enabled, but the repo has
  **never** run a workflow (`actions/runs` total_count = 0 across its whole history — prior PRs #25–#32
  never triggered it either). The workflow is not firing on push/PR for a repo-level reason I can't fix
  from here. Local verification runs exactly what `ci.yml` runs (uv + pytest + ruff + pyright), so it
  stands in — but "CI green" could not be literally observed. Flag for Paul: CI appears dormant on this
  repo.
- **NOT run: a true stdio smoke of `test_connection`** — that would hit live RTM and dump Paul's real
  (now-redacted) token into this transcript, i.e. re-trigger the exact vulnerability. Verified through
  the registered tool with a mocked echo instead.

## Conventions

- § 10 versioning — two patch bumps (v1.32.0 → .1 → .2), `pyproject.toml` + `__init__.py` + `uv.lock`
  together, one per commit.
- § 6 tag discipline — untouched (no tag writes; the reason constants are not tags).
- § 9 documentation lockstep — `test_connection` `Returns` docstring updated to the masked shape;
  `engage_commit.validate` docstring now cites `VERDICT_REJECT_REASONS`.
- § 14 — this debrief (accumulate convention: a new dated file, not an edit to the uplift debrief).

## Open items / handback

- **Consumer (the claude.ai / Cowork board artifacts) — no action.** Both changes are transparent:
  redaction only removes secrets a consumer should never have read; the reason enums are additive
  schema metadata.
- **Paul — two actions:** (1) rotate the RTM auth token; (2) restart the MCP server on v1.32.2.
- **Both RTM candidates are now closed** by this PR — RTM 1217340361 (redaction) and RTM 1217333831
  (reject-reason constants). The Cowork session that tracked them can mark them done.
- **Out of scope (untouched):** the typed error-code vocabulary (RTM 1217273391 — a separate,
  design-first change).

## Durable lesson / gotcha

- **Any endpoint that echoes the request is a credential sink.** RTM signs requests by putting
  `api_key` + `auth_token` in the params and appending `api_sig`; `rtm.test.echo` reflects all of them.
  If a future tool ever surfaces a raw signed request/response, run it through `redact_secrets` — the
  helper is the reusable chokepoint.
- **The reason-enum tests only pin schema == constant, not handler ⊆ constant.** If someone adds a new
  inline `"reason": "..."` string in `tools/gtd.py` (or a `validate_*`) without adding it to the
  frozenset, the schema test won't catch the omission — same limitation as the input enums. Keep the
  frozenset in sync when you add a rejection path.
- **Stale-venv trap hit this session:** after `rm -rf .venv`, `uv sync` alone reinstalls the package
  but NOT the `dev` extra, so pytest vanished — `uv sync --extra dev` is required. (Matches the
  stale-venv memory.)

## Footer

Source of truth: `CLAUDE.md` (response envelope; the strict-tag / commit / create / engage sections
for the reason vocabularies) + the docstrings on `response_builder.redact_secrets`, `test_connection`,
and `engage_commit.validate`. Constants: `canvas_commit.COMMIT_REJECT_REASONS`,
`canvas_create.CREATE_REJECT_REASONS`, `engage_commit.{VERDICT,ENGAGE}_REJECT_REASONS`. Provenance:
this session (2026-07-18), brief "rtm-mcp small fixes", closing RTM 1217340361 + 1217333831.
