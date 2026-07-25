---
report_type: handback-debrief
scope: gtd-domain-tool-suite / Wave 3a — make the server's records emit
implemented_by: claude-code (rtm-mcp repo)
derived_at: 2026-07-25
target_repo: rtm-mcp
artifact: v3.0.1 — logging configured, 5 records raised to WARNING, warn-mode fixed, 1611 tests
relates_to:
  - brief: Wave 3a hand-off brief, 2026-07-25
  - predecessor: 2026-07-25-rtm-mcp-wave2-rename-debrief.md
  - unblocks: Wave 3b (drop the aliases, promote `make naming` to strict)
status: needs-restart
breaking: false
---

# Handback debrief — Wave 3a: make the records emit

**Confirmed, fixed, and verified against a real server process.** `configure_logging()` runs from
`main()`, the five silent records are now `WARNING`, `RTM_STRICT_NOTES=warn` observably warns, and
a real deprecated-alias invocation now writes to stderr:

```
2026-07-25 15:40:15,909 WARNING rtm_mcp.tools.gtd: deprecated tool alias invoked:
gtd_health_check -> gtd_health_report (removed in v3.1.0)
```

**Wave 3b's cycle clock starts from this release.** Everything logged before it is unmeasured, not
clean.

---

## 1. The diagnosis, re-verified rather than accepted

The brief's own method section argues for testing the instrument rather than trusting it, so I
re-ran the diagnosis rather than taking it on faith. **Worth recording: my first attempt to
confirm it produced a false "NONE — confirmed".** The `grep --include=*.py` glob was eaten by zsh,
the command errored, and my `|| echo "NONE"` fallback printed a clean result for a search that had
never run. Same failure shape as the bug, in the act of investigating the bug. Re-run properly
(and with a guard-the-guard search proving the pattern *can* match), it confirms:

- No `basicConfig` / `dictConfig` / `addHandler` / `StreamHandler` / `setLevel` anywhere.
- Nine log call sites: five `INFO`, three `WARNING`, one `DEBUG`.

**Then confirmed by execution, which is stronger than any grep.** Driving the three gates directly
with stderr captured:

| Gate | Outcome | stderr |
|---|---|---|
| `strict_notes=shape` | REJECTED | *(empty)* |
| `strict_notes=warn` | ALLOWED | *(empty)* |
| strict-tag gate | REJECTED | *(empty)* |

So `warn` mode did not block and its only other effect could not be observed — a complete no-op,
exactly as the brief said.

---

## 2. The level decision, and why

**All five records moved to `WARNING`. Configuration was added as well, not instead.**

The brief offered two positions and asked for reasoning. I took (a), on three grounds:

1. **Semantics.** All five are exceptional outcomes, not bookkeeping. Three are a **refused
   write** — something an operator may need to act on (provision a tag, fix a title). Two are a
   call to a name that **disappears next release**, which is what `DeprecationWarning` exists for.
2. **Self-defence, which is the whole subject of this brief.** `WARNING` emits through logging's
   `lastResort` with no configuration at all. These records were silent for the entire life of the
   gates *because the configuration did not exist and nobody noticed*. A level that survives the
   configuration being lost again is the one that matches the failure mode actually observed.
3. **The alias record gates a destructive decision** — dropping 26 compatibility surfaces. An
   instrument whose reliability depends on config that has already been lost once should not gate
   that.

**Volume is not an objection here.** Both classes should be rare and trending to zero: gate
rejections mean something is wrong, and alias hits decaying to zero *is* the Wave 3b gate.

**The configuration still earns its place** even with the records self-defending: `lastResort` has
no formatter (no timestamp, no level, no logger name — useless for a log you intend to *read*),
`DEBUG` needs a way to be switched on, and explicit configuration is the house standard going
forward.

**Consequence worth naming honestly:** because the five are now self-defending, their emission
tests pass even with `configure_logging` neutered. The test that discriminates the *configuration*
is the `INFO` probe. I verified this by neutering `configure_logging` and re-running — 6 tests
fail, and the 5 record tests correctly do not. That asymmetry is by design, not an oversight.

---

## 3. `RTM_STRICT_NOTES=warn`

The mode's documented behaviour — log and allow — was correct; the record just could not emit. Now
it does, and the message names the outcome explicitly so the two modes are distinguishable in a
log:

- `warn` → `… — ALLOWED (observe-before-enforce)`
- `shape` → `… — REJECTED`

Both halves are pinned by tests, because fixing one without the other still leaves the mode
useless.

---

## 4. The sweep the brief asked for — and one real find

**§ 8 asked: are there other controls whose only output is a record?** I swept every `except`
handler in `src/` with `ast`, looking for failures that neither log, re-raise, nor record into a
returned structure. 37 hits, of which the overwhelming majority are **documented fallbacks**, not
silent controls — tz→UTC, date-parse→raw truncation, companion-file IO→no `meta`. Those are
specified behaviour with tests.

**One is a genuine silent control, and it is worse than the ones the brief found.**
`client.get_account_tags()` caught a failed `rtm.tags.getList` and cached an **empty set** as the
strict-tag allow-list. The consequence: the gate then rejects **every** tag write, and the guided
error tells the caller its tags do not exist in the account — true of an empty set, and completely
misleading about the cause. No log, no distinguishing signal, and a transient RTM blip presents
identically to a genuine vocabulary error.

Now logged at `WARNING`, saying explicitly that this is a fetch failure and not a tag-vocabulary
problem. Pinned by a test.

**Answer to the brief's question, stated plainly:** the five records it names were the only
controls whose *only* output is a record. This one was worse — a control whose failure produced
**no output at all**.

---

## 5. Verification

**Run and passing:**

- `ruff check` + `ruff format --check` + `pyright src` — **0 errors, 0 warnings**.
- `pytest` — **1611 passed** (from 1594; +17, all in the new `tests/test_logging.py`).
- `make fingerprints` — regenerated at `source_version 3.0.1`. No schema changed.
- `make naming` — still clean.

**The discrimination check, which is the one that matters.** I neutered `configure_logging` and
re-ran: **6 tests fail**. The suite genuinely detects the absence of configuration rather than
merely passing alongside it.

**Empirical confirmation, per § 5's last bullet** — not the suite, a real process using the real
entry-point configuration:
- a real deprecated alias invocation wrote the record quoted at the top of this debrief;
- five log calls at every level wrote **0 bytes to stdout**, so the JSON-RPC protocol stream is
  untouched.

**Test design.** Assertions are on emitted records, never on source. Two details worth carrying
forward:
- **`caplog` is used WITHOUT `set_level`/`at_level`.** Setting the level would configure the very
  thing under test, so such a test passes against the broken code. Relying on the level
  `configure_logging()` sets is what makes the `INFO` probe discriminating.
- **The one end-to-end stderr test builds its handler inline**, because `logging.StreamHandler()`
  binds `sys.stderr` at construction and pytest swaps that stream. My first version put it in a
  fixture and got empty captures — which reads exactly like the bug, and cost a debugging round.

**NOT done:**

- **Not exercised through a restarted MCP server.** The empirical confirmation drove
  `configure_logging()` + a real alias in-process. A restart is still required before the running
  server emits anything.
- **No live RTM write** — nothing in this release touches a write path's behaviour.

---

## 6. Conventions

| § | Applied |
|---|---|
| **§ 7a (new)** | A logging convention now exists: scoped to `rtm_mcp`, stderr-only with the stdout hazard stated, level chosen by asking *what happens if the configuration is lost*, and "test emission, never existence" |
| § 9 | Lockstep: `CHANGELOG.md`, `CONTRIBUTING.md` § 7a, `CLAUDE.md` test inventory (reconciled to 1611 exactly); fingerprints regenerated |
| § 10 | Patch bump 3.0.0 → **3.0.1** — no interface change, no schema change |
| § 11 | Quality gate passed |

The repo's guidance forced no deviation — there was no logging convention to deviate from, which
is why one is now written down.

---

## 7. Open items

**This unblocks Wave 3b.** Restart the server on v3.0.1, then start the cycle clock. The gate
remains *zero alias hits across a full scheduled-task cycle* — but it is now an instrument that
can record one.

Still open from earlier waves, none touched here: `CONTRIBUTING.md` § 7's stale `from __future__`
rule; `gtd_reads.parse_note_type`'s hyphenated-type split; the never-exercised live write path.

---

## 8. Durable lesson

**A control's level is a claim about what happens when its configuration is lost.** `INFO` says
*I am willing to be silent if someone forgets to configure me*. For a record that is a control's
only output, that is not a logging-style preference — it decides whether the control exists.

And the sharper one, which this session demonstrated on itself: **a verification step can fail the
same way the thing it verifies fails.** My first check for logging configuration was a shell glob
that zsh rejected; the command errored, my fallback printed "NONE — confirmed", and I nearly
recorded a *correct conclusion reached by an instrument that never ran*. The fix is the same one
this whole programme keeps arriving at — prove the check can find something before believing it
found nothing.

---

*Source of truth: `CONTRIBUTING.md` § 7a (the convention), `server.configure_logging()` (the
implementation and its rationale), `tests/test_logging.py` (the emission contract), `CHANGELOG.md`
v3.0.1. Provenance: Wave 3a hand-off brief 2026-07-25; independent re-verification by source
search, direct execution of the three gates with stderr captured, a neuter-and-rerun discrimination
check, and a real-process confirmation of both the alias record and stdout cleanliness, all
2026-07-25.*
