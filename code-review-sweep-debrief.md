---
report_type: handback-debrief
scope: code-review-sweep — whole-codebase review + fix batch (bugs, robustness, dead code)
implemented_by: Claude Code session (Fable 5), directed by Paul
derived_at: 2026-07-04
target_repo: rtm-mcp
artifact: v1.18.1 (uncommitted at time of writing — see Open items)
relates_to: in-session four-agent code review (core infra / parsers / GTD pure modules / tool layer)
status: needs-restart (MCP server restart on v1.18.1 to pick up behaviour fixes)
---

# What shipped

A whole-codebase review (four parallel reviewers, findings adversarially spot-verified against
source and tests) followed by a fix sweep: **3 confirmed bugs, 8 likely bugs, ~10 quality issues,
and the safe nits**, each with a regression test. 647 → **694 tests**, `make lint` + `make test`
green. No new tool, no new tag, no envelope shape change — everything is a fix or an additive
field, so this is a **patch** bump (1.18.0 → 1.18.1).

The headline fixes a consumer could notice:

- **`RTM_AUTH_TOKEN` env var now actually works.** `alias="token"` made pydantic-settings expect a
  bare `token` env var (aliases bypass the `RTM_` prefix), so env-only configuration silently fell
  through to the config file — while startup text and README told users to set `RTM_AUTH_TOKEN`.
  Now `validation_alias=AliasChoices("RTM_AUTH_TOKEN", "token")` + `populate_by_name=True` (all
  three spellings — env var, `token=`, `auth_token=` — are accepted).
- **`add_task` / `list_tasks` no longer swallow a bad `list_name`.** A typo'd list used to
  silently create the task in the Inbox / return every task in the account as if filtered. Both
  now return the standard actionable `{"error": ...}` with **nothing written** (same contract as
  `move_task`).
- **`gtd_chat_post` no longer stamps the drain signal when the chat-note write fails.** A failed
  note write now returns a top-level `error` and skips the tag ops entirely (a `me` turn no longer
  summons the worker to an empty thread; an `ai` turn no longer marks an unanswered turn answered).
- **`gtd_create_project` rejects colliding in-draft ids** (new `duplicate_id` + `self_dep`
  rejection reasons from `validate_create`). Previously `{"id": "1"}, {}` gave both items id "1",
  validation passed, and the apply loop silently dropped one item and mis-wired its dependants.
- **`gtd_chat_inflight` attributes to the *nearest* `#project` ancestor** (was topmost — latent
  until projects nest, which RTM's 3-level cap permits).
- **Client robustness:** connect-phase timeouts (`ConnectTimeout`/`PoolTimeout`) are now retried
  for writes too (the request never left the client); mid-flight transport errors (`ReadError`
  etc.) and non-JSON 200 bodies are wrapped in `RTMNetworkError` instead of escaping raw; a failed
  settings fetch is no longer cached for the session (one blip used to disable tz localisation —
  re-introducing the BST off-by-one — until restart); timeline creation is lock-guarded so
  concurrent first writes can't split across two timelines and break undo; RTM error 102 is now
  `RTMNetworkError` (transient), not a validation error.
- **Smaller:** `undo` validates against the session log up-front (parity with `batch_undo`);
  `set_default_list` records its transaction (undoable at the RTM level, visible in
  `get_timeline_info`); `get_task_notes` by name reaches completed tasks (the by-IDs path always
  did); `companion.py` survives non-UTF-8 companions (`UnicodeDecodeError` is a `ValueError`, not
  an `OSError` — the "never raises" contract had a hole); day-scale estimates parse (`P1D`,
  "2 days"); `get_rate_limit_status` gains `reads_session`/`writes_session`; startup
  "not configured" text goes to stderr (stdout carries JSON-RPC under stdio);
  `project_index` counts guard `completed` uniformly; credentials file saved 0600;
  `safety_margin` bounded to [0, 1); user filters parenthesized in `list_tasks`; dead code removed
  (`types.py`, `lookup._format_candidates`, `response_builder.get_transaction_id`).

# Design decisions & deviations

- **Validate-then-fail-loud over silent fallback** for name resolution (`add_task`, `list_tasks`):
  consistency with every other list-name consumer won over backward-compatibility with the silent
  path — an agent acting on "0 results in list X" that is actually "whole account" is worse than
  an error.
- **`gtd_chat_post` returns a top-level `error` on note failure** (not just a populated `errors`
  list). This is a deliberate response-shape change on the *failure* path only; the success shape
  is untouched. The board treats missing `note.id` + `error` as a failed post.
- **`populate_by_name=True`** was needed because switching `alias` → `validation_alias` changes
  the synthesized constructor signature (pyright rejected the internal `token=` call sites, which
  were switched to `auth_token=`; the JSON file format keeps its `token` key).
- **Byte-compat ports untouched.** All reference-inherited oddities in `project_plan`,
  `plan_graph`, `canvas_seed`, `canvas_overlay` were verified against the gtd plugin's scripts and
  left alone. Known upstream-parity follow-ups (unchanged): `frame.focus` always `""` on the
  read path (the reference never emits it; the gtd draft path does).
- **Deliberately deferred:** tag-normalization convention split (`gtd_chat` normalizes before
  membership tests, `project_index`/`project_plan` compare raw — harmless while RTM lowercases
  tags; unifying touches many gates); hardening redaction to null names server-side (documented
  out-of-scope in the redaction feature docs).
- **Test-count inventory re-measured.** The old inventory had pre-existing drift (e.g.
  response_builder said 40, actual 42; list_tools said 16, actual 17; config said 12, actual 13);
  all counts in CLAUDE.md are now the *measured* per-file collect counts, and
  `test_plan_graph_parity.py` (1 test) is now listed.

# Membrane / activation

- **Restart the MCP server on v1.18.1** to pick up the behaviour fixes. No new tag, no strict-tag
  gate interaction, no activation-ordering hazard.
- **Backward-compatible** except the deliberate failure-path changes above (silent-fallback
  callers of `add_task`/`list_tasks` with bad list names now get errors; `gtd_chat_post` note
  failure now errors; `undo` with an unknown/already-undone id now errors without calling RTM).
  Additive: `reads_session`/`writes_session` in `get_rate_limit_status`; `duplicate_id`/`self_dep`
  rejection reasons.
- Anyone setting a bare `token` env var (the accidental workaround for the broken alias) still
  works — `AliasChoices` kept it.

# Verification done

- `make test`: **694 passed** (was 647; +47 regression tests covering every fix).
- `make lint`: ruff check + format-check + pyright all clean.
- The `RTM_AUTH_TOKEN` fix was verified empirically against the installed pydantic-settings
  (env-only load now populates `auth_token`; test `TestEnvVarCredentials` pins it).
- **Not run:** a live smoke against the real RTM API (no server restart in this session), and no
  live exercise of the board (`project-plan-artifact.html`) against the changed `gtd_chat_post`
  failure shape — both validated in-suite via the FakeMCP/respx patterns instead.

# Conventions

§ 6 (removal never gated — unchanged), § 7 (docstrings updated where behaviour changed), § 8
(FakeMCP/respx patterns, read-only call-surface assertions preserved), § 9 (CLAUDE.md tree +
transport/strict-tag sections + re-measured test inventory; README/server-instructions needed no
change — the fixes make the existing docs true), § 10 (patch → 1.18.1), § 13 (ports untouched).

# Open items / handback

- **Paul:** restart the rtm MCP server on v1.18.1 (bundles the pending 1.17.1/1.18.0 restarts).
- **Paul / this session:** commit + PR — the sweep is uncommitted at time of writing.
- **gtd side — no action required.** The board degrades cleanly; the `gtd_chat_post` failure
  shape is only stricter (top-level `error` instead of a fake success).
- **Upstream parity follow-ups (unchanged backlog):** tz localisation in `rtm_fetch.py`,
  `header.project.files`/`prog`/`redacted` additive fields, `frame.focus` emission.
- **Deferred candidates** (see decisions): tag-normalization unification; redaction plaintext
  hardening; `decision_count` (blocked on the gtd tag question from the v1.18.0 debrief).

# Durable lesson / gotcha

`alias=` on a pydantic-settings field consumes the alias **verbatim as the env var name** — the
`env_prefix` is not applied, and field-name kwargs stop working unless `populate_by_name=True`.
If a settings field must keep a legacy alias, use `validation_alias=AliasChoices(...)` listing the
real env name explicitly, and add an env-loading test: the entire test suite passed for 18 minor
versions while the documented env var was broken, because every test constructed the config via
kwargs or file. Similarly: `UnicodeDecodeError` is a `ValueError` — an `except OSError` around
file reads does not deliver a "never raises" contract.

---
Source of truth: `CLAUDE.md` §§ "HTTP Transport", "Rate Limiting and Connection Retry",
"Strict-Tag Mode", the GTD feature sections, and the per-tool docstrings. Provenance: in-session
four-agent review (core infra / parsers / GTD pure / tool layer) + spot verification, 2026-07-04.
