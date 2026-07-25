---
report_type: handback-debrief
scope: gtd-domain-tool-suite / Wave 3 — drop the aliases, promote the naming check to blocking
implemented_by: claude-code (rtm-mcp repo)
derived_at: 2026-07-25
target_repo: rtm-mcp
artifact: v3.1.0 — 26 deprecated surfaces removed, `make naming` blocking, 55 tools, 1601 tests
relates_to:
  - brief: Wave 3 hand-off brief, 2026-07-25
  - predecessor: 2026-07-25-rtm-mcp-wave3a-logging-debrief.md
  - closes: designed change 2026-07-25-gtd-milkscript-retirement
status: needs-restart
breaking: true
---

# Handback debrief — Wave 3: dropping the aliases

**26 deprecated surfaces → 0. `make naming` is `--strict` and part of `make lint`. 55 tools,
unchanged.** Verified through a **genuinely restarted server** — the thing Wave 2 could not do:

```
tools advertised : 99  (gtd: 55)
removed names still advertised: NONE
gtd_item_today   : 33 rows      gtd_health_report: 222 issues
gtd_health_check : Unknown tool: 'gtd_health_check'   (isError: true)
```

**This closes the programme.** § 7 lists what should outlive it.

---

## 1. A version-sequencing note

The brief was drafted at 15:00 with `current_version: 3.0.0`; **Wave 3a shipped at 15:30 and took
the repo to 3.0.1**, which the brief could not have known. So this is 3.0.1 → **3.1.0**, and both
entries are in `CHANGELOG.md`. Wave 3a is still on the same branch, uncommitted — two commits are
ready when you want them.

Wave 3a's stated purpose was to make the alias log a usable gate. **This brief then dropped that
gate as disproportionate.** The logging fix stands on its own regardless — three write-boundary
gates were silent and `RTM_STRICT_NOTES=warn` was a complete no-op — but it is worth recording
that the work was justified by a requirement that was retired half an hour later.

---

## 2. What was removed

- The 25 aliases, the `gtd_query` dispatcher, the `_make_alias` helper and the registration loop.
- `DEPRECATED_ALIASES` itself — a leftover map is how one gets re-registered by accident.
- Dead scaffolding: `GTD_QUERY_OUTPUT` (`models.py`), `VALID_PERSPECTIVES` (`gtd_reads.py`), and
  `_PERSPECTIVE_ENUM`. The three perspectives are three tools now, so a vocabulary naming them has
  nothing left to validate.
- `CONTRIBUTING.md` § 2.8 reduced from a live policy to **policy-for-the-next-rename plus the
  history** — a live section describing a mechanism that no longer exists is exactly the drift
  this programme keeps finding.

---

## 3. The test that mattered most, and what it caught

**The removal list is owned by the test file, not imported.** The brief was explicit about why,
and it is worth restating: had the test iterated `DEPRECATED_ALIASES`, deleting the constant would
have broken the import, and *leaving it behind as an empty dict would have made every removal
assertion pass without checking a single name*. The list is a literal tuple of 26, and
`len(...) == 26` is asserted **before** anything iterates it — twice, once in its own test and
once inside the loop.

**A new stray-reference test found four stale user-facing strings.** This was not in scope and is
the most valuable thing in the wave:

| Where | What it still said |
|---|---|
| `server.py` instructions | advertised **`gtd_query`** as a live tool to every client |
| `server.py` instructions | *"All 25 old names remain callable as deprecated aliases"* — now false |
| `project_plan.py` | a runtime `focus_not_found` message telling the caller to use `gtd_query` |
| `tools/gtd.py` | a runtime `task_not_found` message: *"find it with gtd_query / list_tasks"* |

**Nothing had ever asserted on those**, so they would have survived indefinitely — a rename that
updates every call site and leaves the *advice* pointing at removed tools. All four fixed.

The test flags a removed name only **outside backticks**: a backticked mention is documentation
explaining history (*"not a `gtd_query` perspective"*) and is correct to keep. That is the same
live-call-site-vs-prose distinction the caller enumeration drew, applied to source.

**And the strict promotion is tested by its exit code**, not its output: `--strict` returns 1 on a
known-bad fixture and on an unclassifiable one, 0 on the real suite, while report-only returns 0
on the same bad fixture. A `--strict` that always exits 0 would be the same silent control in a
new costume.

---

## 4. Verification

**Run and passing:**

- `ruff check` + `ruff format --check` + `pyright src` — **0 errors, 0 warnings**.
- `pytest` — **1601 passed**.
- `make naming` (now `--strict`, and inside `make lint`) — **52 ok, 3 exempt, 0 findings, 0
  unclassifiable.** The `deprecated` bucket is gone; every gtd tool now faces the same judgement,
  which is precisely what made promotion possible.
- `make fingerprints` — 99 surfaces at `source_version 3.1.0`, down from 125.

**Through a restarted server** — spawned as a client spawns it, JSON-RPC over stdio:

- 99 tools advertised, **55 gtd**, **zero removed names**;
- live reads under the new names: `gtd_item_today` 33 rows, `gtd_health_report` 222 issues;
- every removed name returns `Unknown tool: '<name>'` with `isError: true`.

*Small self-correction worth recording:* my first probe labelled the removed-tool call **"STILL
WORKS (bad)"**. The server was right; my check was misreading it — FastMCP returns unknown-tool as
a *result* with `isError: true`, not a JSON-RPC `error`, and I had only tested for the latter. A
verification step reporting the wrong verdict about a correct system is the same class of defect
as the ones this programme has been chasing, in the mirror.

**NOT done:**

- **No live WRITE.** Third wave running. It has never been authorised — I offered a `#test`-scoped
  scratch write after Wave 1b and the answer each time has been to commit and move on. Per the
  brief's § 6, saying so explicitly rather than leaving it ambiguous. **The offer stands.**
- The **running** MCP server has not been restarted; my verification span its own subprocess.

---

## 5. Conventions

| § | Applied |
|---|---|
| § 2 | Updated: the suite conforms, the aliases are history, § 2.7 records the check as blocking |
| § 2.8 | Reduced to policy + history, and now carries the **rendered-vs-source** rule |
| § 9 | Lockstep: `CHANGELOG.md` (with v3.0.0 and v3.0.1 corrected in place, since both made claims that v3.1.0 falsifies), `README.md`, `server.py` instructions, `CLAUDE.md` + inventory (1601, reconciled exactly) |
| § 10 | Minor bump 3.0.1 → **3.1.0** (breaking removal, but the suite is 0.x-style pre-1.0 in spirit; SemVer-major was spent on v3.0.0's rename) |
| § 11 | Quality gate passed |

No deviation was forced. One judgement call: the brief said `--strict` "in CI", and this repo's CI
runs `make lint`, so I put it there rather than editing the workflow — the check now blocks
without a separate CI change.

---

## 6. The reasoning error, recorded

The brief's § 3 is the most important thing in it, and it belongs in the permanent record rather
than only in a debrief: **the designed change (§ 2a, D8) argued for no alias window because
`plugin-marketplace-ui-patterns` slots the tool name.** True of the base scaffold; false of gtd's
own profile, which hardcodes them — and once *rendered*, freezes them. The sweep checked the
template layer and concluded about the rendered layer.

Wave 2 shipped aliases anyway, for an unrelated reason (cross-repo doc sequencing). **So the
compatibility layer that saved the live board was justified by an argument that had nothing to do
with the risk it actually covered.** It is now written into `CONTRIBUTING.md` § 2.8 as a rule:
*ask "rendered or source?" before concluding a rename has no callers.*

---

## 7. Standing items that outlive the programme

**In this repo:**

1. **The live write path has never been exercised** — across Waves 1b, 2 and 3. Every write tool
   is covered by mocks and by schema/parity assertions, and no governed write has been run against
   the real account by me. This is the single largest untested surface.
2. **`CONTRIBUTING.md` § 7's `from __future__ import annotations` rule is stale** — flagged in
   Wave 1, untouched in three waves since. Six pure modules use it; injecting it into a schema
   surface produced byte-identical schemas. Narrow it or drop it.
3. **`gtd_reads.parse_note_type` splits hyphenated types at their own hyphen** (`AI-LINK` → `AI`).
   Two modules route around it with their own regex. Fixing it changes `gtd_item_context` output,
   so it wants its own change.
4. **The editable install is unreliable.** `uv sync` / `uv run` repeatedly dropped `rtm_mcp` from
   the venv mid-session, producing `ModuleNotFoundError` in subprocesses and test runs. Both the
   naming-check subprocess test and the live verifier now pass `PYTHONPATH` explicitly rather than
   trusting it. Worth a proper fix — a conformance check that fails because the venv is unhealthy
   is indistinguishable from one that fails because the code is wrong.
5. **`2026-07-20-rtm-mcp-enable-gates-debrief.md` is still untracked** — predates this session,
   flagged four times, wants a commit or a delete.

**Gtd-side, from earlier waves:** the `shape-patterns.md` self-contradiction on *"Email about X"*
(the inline comment says `draft`, the rules produce `none`); the CONTRIB-UPDATE body grammar
having no judged-transition shape; `RESOLVED`/`RESOLUTION` missing from `surface_queue`'s
response-note vocabulary.

**Practice, not code:** the rendered-vs-source rule in § 6, and the one below.

---

## 8. Durable lesson

**A removal test is the easiest kind of test to write so that it cannot fail.** Iterate the
constant you just deleted and it passes vacuously; import a list that has silently emptied and it
passes vacuously; assert "the tool is gone" against a registry you forgot to rebuild and it passes
vacuously. Every one of those reads as a green suite. The defences are cheap and unglamorous —
own the list, assert its length before iterating it, and check the exit code rather than the
output — but they are the entire difference between proving a removal and performing one.

That is the same lesson as the guard idiom, the `Phase:`/`State:` regex, the `"N days ago"`
filter, the byte-threshold audit, the unconfigured logger and my own false `grep`. **Six
instances, one shape: a control that stops testing reports success.** If this programme leaves one
thing behind, it should be the reflex of asking a passing check to fail on purpose before
believing it.

---

*Source of truth: `CHANGELOG.md` v3.1.0 (the migration table — with the aliases gone it is the
only map from an old name to its replacement), `CONTRIBUTING.md` §§ 2.7–2.8,
`scripts/check-tool-naming.py`, `tests/test_tool_schemas.py` (`REMOVED_AT_V3_1_0`),
`tests/test_tool_naming.py`. Provenance: Wave 3 hand-off brief 2026-07-25 with its caller
attestation and live-artifact inspection; verification through a freshly-spawned MCP server
subprocess, 2026-07-25.*
