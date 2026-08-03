---
report_type: handback-debrief
scope: surface the RTM recurrence KIND (every vs after) that the parser was discarding
implemented_by: rtm-mcp (Claude Code session)
derived_at: 2026-08-03
target_repo: rtm-mcp
artifact:
  version: v6.8.0
  branch: feat/recurrence-kind
relates_to:
  - brief 2026-08-03 "Brief — surface the recurrence kind (rtm-mcp)"
  - designed change general/plugin-marketplace-architect/designed-changes/2026-08-02-vault-naming-mirrors-rtm.md
  - handback 2026-08-03 rtm-mcp v6.7.0 (name-length advisory) — this is the follow-on
status: needs-restart
---

# Handback — the recurrence kind is now readable (`repeat_kind`, v6.8.0)

**Consumer headline: every task rtm-mcp returns now says WHICH kind of repeat it is, so a
consumer can tell whether `taskseries_id` is a durable key or an id that re-keys every
occurrence.** Read `repeat_kind` **together with** `is_repeating` — see the trap below, it is the
one thing likely to be got wrong.

## What shipped

`parsers.repeat_kind(rrule)` → `"every"` | `"after"` | `None`, surfaced on:

| Surface | Fields added |
|---|---|
| parsed task (`parse_tasks_response`) | `repeat_kind` |
| `list_tasks` (`format_task`) | `is_repeating` **and** `repeat_kind` — it carried neither before |
| `gtd_project_plan` (`project-plan-seed/3.1`) | `repeat_kind` on `header.project` and every row |
| `gtd_item_stamp_tokens` | `repeat_kind` per project |

Additive throughout. Nothing changes shape for a non-repeating item beyond gaining two fields that
read `False` / `None`.

## Why it was worth doing — the fact was discarded, not unobtainable

`parsers.py` did `is_repeating = bool(ts.get("rrule"))`. RTM sends `<rrule every="0|1">` and
**that attribute is exactly the discriminator**, so the whole element was being collapsed to a
boolean one line into the parser.

This nearly went down as "unobtainable", which would have been costly and wrong. It is
unobtainable *everywhere else* — MilkScript exposes only a bare `isRecurring()`,
`rtm.Recurrence` is a **write-only builder** (no `getRecurrence` on `TaskSeries` or `Task`), and
RTM search syntax has `isRepeating:true` but **no repeat-type operator**. That one parser line is
the only place the fact exists in this system.

The stakes, for the vault folder rule:

| Kind | Structure | Identity across occurrences |
|---|---|---|
| `every` | ONE taskseries, MANY tasks | `taskseries_id` **stable** — a sound folder key |
| `after` | a NEW taskseries per occurrence | **nothing survives**; both ids re-key — unsolvable, so *detect and refuse* |

## Design decisions

### Three-valued, with `None` deliberately overloaded

`None` means **either** *not repeating* **or** *a rule I could not classify*. `is_repeating`
beside it separates them: `None` + `is_repeating False` = no rule; `None` + `is_repeating True` =
a rule that could not be read. This is the brief's fourth case, implemented as specified.

### ⚠ Never default an unreadable rule to `"every"` — the trap for the next author

It looks like a harmless convenience (99% of live rules are `every`). It is the exact
silent-wrong-identity failure the field exists to prevent: a consumer keying durable state on
`taskseries_id` would key it on an id that re-keys, and **nothing would say so**. Unreadable must
read as unreadable. `test_a_rule_with_no_readable_every_is_unclassified_never_guessed` pins it and
was verified to fail under a mutant that guesses.

### `list_tasks` got BOTH fields, not just the one asked for

`repeat_kind` alone is undecodable on a surface that lacks `is_repeating` — its `None` covers two
different facts with nothing to separate them. `format_task` carried neither, so it gains the pair
or nothing. This is a small widening of the brief's literal scope and it is what makes the brief's
own three-valued contract usable there.

### `gtd_project_index` deliberately untouched

See the corrections below — it carries neither `is_repeating` nor `taskseries_id`, so there is
nothing for a kind to qualify. **If the vault needs recurrence in the cockpit index, say so and it
is a small follow-on** — it would mean adding `taskseries_id` there too, which is a real decision
rather than a mechanical extension.

## Deviations from the brief — three, all from measurement

1. **"`list_tasks` … already carr[ies] `is_repeating`" — false.** `format_task` never carried it.
   Handled by adding the pair (above).
2. **"`gtd_project_index` … already carr[ies] `is_repeating`" — false.** It carries neither that
   nor `taskseries_id`. Left alone, flagged above.
3. **"there is no confirmed live `after` in the account any more" — false. There are 27.** So the
   `after` branch is verified against **live data**, not only a fixture. The brief's suggested
   fixture-only route would have been sound but weaker.

The brief's core technical claims were all correct: the parser line, the `every` attribute as
discriminator, the three-valued design, and the ≥2-tasks cross-check.

## Verification — what was actually run

- **`make test` — 2033 passed, 0 failed, 0 skipped.** (Was 2021 before; +12.)
- **`make lint`** — ruff check, ruff format --check, pyright: all clean.
- **`make naming`** — no findings. **`make fingerprints`** — regenerated at `source_version 6.8.0`.
- **Every new guard verified by removal** (the brief's explicit ask), with `__pycache__` cleared and
  `PYTHONDONTWRITEBYTECODE=1` so stale bytecode could not answer. **Six mutants, six killed:**
  parser discards the attribute; unclassifiable defaults to `"every"`; `list_tasks` drops
  `repeat_kind`; `list_tasks` drops `is_repeating`; plan rows drop it; plan header drops it.
- **Live end-to-end against the real account** (not just the raw shape): `237677328` *Weekly GTD
  review* → `"every"`, `606337000` *z4 car insurance* → `"after"`, a one-off control →
  `False`/`None` with both keys present.

### Live measurements (2026-08-03, whole account)

- 118 repeating series: **91 `every`, 27 `after`** → 124 / 27 tasks post-parse.
- **Zero** unclassified rules — the fourth case does not occur in live data today (it is still
  implemented, because "does not occur today" is not a contract).
- **Deductive cross-check holds**: of **31** series holding ≥2 tasks, **31** classified `every`,
  **0** violations. (A series with ≥2 tasks is provably `every` — an `after` repeat cannot make
  one. Free from the same read; cannot confirm a never-yet-recurred series.)
- The attribute's wire shape: the **string** `"1"`/`"0"` on a dict also carrying `$t`, e.g.
  `{"every": "1", "$t": "FREQ=WEEKLY;INTERVAL=1;WKST=MO"}`.

### NOT verified

- **No live MCP call through a restarted server.** The tools still advertise v6.7.0 schemas until
  restart; live validation was done by driving the real client and the real parser in-process.
- **Not pushed, no PR, not merged** — committed on `feat/recurrence-kind` only.
- **No `after`-kind write path was exercised** (nothing writes recurrence here; `set_task_recurrence`
  was untouched).

## Membrane / activation

Pure RTM data — **vault-free, no new tag, no new `ErrorCode`, no gate, no strict-tag
interaction**, therefore **no activation-ordering hazard**. rtm-mcp still owns nothing of the
vault: it reports a fact about RTM and the vault decides what to do with it.

**To go live: restart the MCP server on v6.8.0.** Rollback is a revert.

**Fingerprint churn is 20 of 102, and it is structural.** `list_tasks`, `gtd_project_plan` and
`gtd_item_stamp_tokens` genuinely changed shape; the other **17** are task-write tools that share
the `Task` output model, which gained two fields. Not 20 tools changing behaviour.

## Gotchas for the next author

- **`make test` runs `/opt/anaconda3/bin/pytest`, not the project venv.** `uv sync --all-extras`
  does not install pytest into `.venv`, so `uv run pytest` falls through to PATH. It happens to
  work correctly here — anaconda has `pytest-asyncio` 1.3.0, `asyncio_mode=auto` is active, 0
  tests skipped, and an editable `_rtm_mcp.pth` in anaconda's site-packages points at this repo's
  `src`, so the working tree really is what is under test (confirmed: the description-budget test
  tracked byte-level edits across three runs). **But it is fragile** — this is the documented trap
  where a system pytest silently skips every async test and still reports green. Worth fixing
  separately; do not assume it is safe on another machine.
- **`.venv` holds a `_editable_impl_rtm_mcp 2.pth`** — a Dropbox-style " 2" duplicate, matching a
  known class of pollution in these repos. Untouched here; flagged.
- **The description budget is real and it bit this change.** The first `gtd_project_plan` docstring
  addition pushed it to 2,211 bytes against a 2,048 cap, and a second attempt still missed at
  2,073. It was trimmed to fit rather than added to `OVER_BUDGET_EXEMPTIONS` — the full contract
  lives in `rtm_tool_help`, and the exemption list exists for tools that cannot fit, not for
  regrowth.
- **Ruff will reject `{"1", 1, True}`.** `bool` subclasses `int`, so `True` is a literal duplicate
  of `1` and the set collapses anyway — `True`/`False` are covered by the int members. A comment in
  `parsers.py` says so, to stop someone "fixing" it back.
- **`gtd_project_canvas` correctly did not churn.** The canvas seed never carried `is_repeating`,
  so there was nothing to qualify. If the board ever needs the kind, that is a `canvas_seed` change.

## Open / consumer action

- **Consumer (agent-memory / vault): no action needed to keep working** — every field is additive.
  To *use* it: after the server restart, read `repeat_kind` beside `is_repeating` and refuse the
  `after` case rather than keying a folder on a `taskseries_id` that re-keys.
- **Open question back to the requester:** should `gtd_project_index` gain `taskseries_id` +
  `repeat_kind`? Not done here because the brief's premise for it was wrong and adding an identity
  field to the cockpit index is a decision, not a mechanical extension.
- **Out of scope, as briefed:** the vault-side folder shape, the `after` refusal, and the
  `PROJECT_FIELDS` change are agent-memory's.
