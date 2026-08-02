---
report_type: handback-debrief
scope: the last two noise sources in `gtd_note_filing_gaps` — `.stversions` ghosts, and a
  sentence accepted as a filing path
implemented_by: Claude Code (rtm-mcp session, 2026-08-02)
derived_at: 2026-08-02
target_repo: rtm-mcp
artifact: v6.5.0 → v6.5.1
relates_to:
  - hand-off brief "Two residual defects making `gtd_note_filing_gaps` nearly-trustworthy" (2026-08-02)
  - v6.4.1 (`filed_unlinked` scoping) and v6.5.0 (`legacy_unfiled`) — partial fixes of the same report
status: needs-restart
---

# The last two noise sources in `gtd_note_filing_gaps`

## What shipped

Two unrelated fixes in the same module, both found on the first live run after v6.5.0, both
masked until then by the `filed_unlinked` noise v6.4.1 removed.

**A.** `walk_artefacts` was enumerating Syncthing's `.stversions/` version history — including a
versioned *copy* of a real, already-journalled artefact which, because the whole folder is
versioned, carried a companion and so passed v6.4.1's tracked-ness filter. It would have been
reported as an orphan forever. Directory pruning is now **derived** rather than a hand-maintained
list.

**B.** A whole sentence on a `FILING:` line was accepted as a path, so the reconciliation reported
a present artefact as **missing**. `gtd_chat.is_bare_path` now says *"that isn't a path"*, and
`gtd_note_report.filing_path` — a class that existed, was correctly scoped, and reported `0` live
— reports it.

## Design decisions & deviations

**None from the brief.** Both fixes are as specified.

**One simplification worth naming.** The brief offered three signals for Defect B in order of
reliability: a trailing extension, a prose trailer, an unrecognised parenthetical. Signal 1 alone
covers every observed malformation — a trailing clause ends in prose, an unsanctioned parenthetical
ends in `)`, a sentence ends in `.` with nothing after it — so signals 2 and 3 would be two more
things to keep correct for no additional catch. The brief's own caveat about signal 3 (it must not
reject `…(signed).docx`) is precisely the kind of interaction that disappears when the rule is one
test instead of three.

**The whitespace trap was the important constraint, and it is asserted with real filenames.** The
predicate tests for a trailing extension and never for spaces. `Job Spec - Delivery Leader -
24-Mar-2026.pdf` and `Simon Meek - Flexible working application form (signed).docx` are live paths;
a space rule would reject them, and a rule that rejects real paths is worse than the defect.

**`system` is pruned at any depth, not just the vault root.** Checked against live data before
deciding: `general/system/` holds three `dci-link-audit-*.json` files — the same machine output as
the root `system/`, not filed artefacts. Root-only pruning would have left them.

**Where Defect B's row lands in `gtd_note_filing_gaps` is a decision, not a leftover.** It drops
out of `linked_missing` and appears in `prose_path`. That is now the *honest* classification: after
the fix the note genuinely carries no machine-readable FILING line, which is exactly what
`prose_path` means. The shape defect is reported separately by `gtd_note_report.filing_path`. Two
tools, two honest views, neither guessing — and `prose_path` still does not extract the real path,
even though it is obviously the leading token, because detect-don't-parse is the standing posture.

**`note_report._filing_findings` was rewritten to consume `gtd_chat._filing_payloads`** rather than
walking the lines itself. It had its own walk, which meant the two-line labelled-continuation form
was handled twice and could drift. A third parser is what this programme keeps refusing to write.

**One fingerprint churns** — `gtd_note_report`, because its description now states what its
`filing_path` class actually catches. The brief anticipated this. Defect A churns none.

**Patch, not minor.** Two bug fixes; no new class, no new field, no new tool.

## Membrane / activation

Vault-free in the write direction (the companion seam stays read-only), no new tag, no new
`ErrorCode`, no strict-tag interaction, no activation-ordering hazard. **To go live: restart on
v6.5.1.** Rollback is a revert.

## Verification done

**Ran and green:** `make test` — **1989 passed** (from 1974; +15). `make lint` — naming `--strict`,
ruff, pyright, all clean. `make fingerprints` regenerated (one tool).

**Both predicates were verified by removal**, per CONTRIBUTING § 8 and the brief:

| Neutered | Failing tests |
|---|---|
| `_is_artefact_dir` → `return True` | 4 (the fifth, "a real artefact is still found", correctly still passes — it is the anti-vacuity guard) |
| `is_bare_path` → `return True` | 6, across `test_gtd_chat`, `test_note_report` and `test_filing_gaps` |

Both were then restored and the suite re-run green.

**Measured against the live vault** (read-only walk, no writes):

```
files enumerated   2731 → 1273
tracked artefacts   184 →  160
pruned by dir:  system 1251 · _dev 83 · _archive 68 · .stversions 47
                .auto-memory 7 · _master 1 · .stfolder 1
```

**Zero real artefacts lost** — every pruned path was enumerated and checked to sit under a
`system/`, `_archive/`, `_master/` or dot-prefixed segment. The reported `.stversions` ghost is
gone. `filed_unlinked`'s universe shrinks by the 24 tracked entries that left.

**NOT run, explicitly:**
- **No live run of `gtd_note_filing_gaps` or `gtd_note_report` itself.** The server has not been
  restarted on v6.5.1 (and is now behind v6.4.1, v6.5.0 and v6.5.1). The vault-side numbers above
  are real, measured by calling `walk_artefacts` directly against `~/Documents/AI Memory`; the
  resulting *report* numbers are not, because they need RTM too.
- **The new `filed_unlinked` and `linked_missing` counts are therefore unknown.** The brief asked
  for them in the debrief; I can give the artefact-side input honestly and not the output. Getting
  them needs the restart.
- No RTM calls of any kind. The malformed notes are **not** repaired — out of scope per the brief.

## Conventions

§ 8 testing (both guards verified by removal; anti-vacuity guard on the pruning rule) · § 9
documentation lockstep (README unaffected — no user-facing surface changed; `CLAUDE.md` module
table + feature section + test inventory; `CHANGELOG.md`) · § 10 patch bump · § 14 this debrief.

## Open items / handback

1. **Restart on v6.5.1** — one restart now covers v6.4.1, v6.5.0 and v6.5.1.
2. **Re-run `gtd_note_filing_gaps` afterwards and record the numbers.** That is the step this
   debrief cannot do, and it is also the step that has found a defect three times running.
3. **Consumer — no action.** No advertised shape changed; `gtd_note_report` gains findings it
   should always have had, and `files[]` keeps its shape.
4. Remediating the malformed notes remains a separate Paul-approved pass.

## Durable lesson / gotcha

**Re-run the report after every fix to the report.** Three consecutive releases each fixed the
last defect anyone could see, and each time the fix revealed another that its own noise had been
hiding: v6.4.1's 2,704-row `filed_unlinked` hid the `.stversions` ghost, which hid the
sentence-as-path. A signal-to-noise fix does not just improve a report — it changes what the report
is capable of showing you, which means the next run is new evidence rather than a confirmation.

**A hand-maintained exclusion list is a defect waiting for its trigger.** `_SKIP_DIRS` named six
directories and was wrong about a seventh that had existed all along. This is the fourth time this
programme has fixed that shape. The rule to reach for: can membership be *derived* from a property
(a dot prefix, an underscore prefix) rather than enumerated? Here it could, and the derived rule
happened to fix an unrelated inconsistency for free — `_`-prefixed files were skipped while
`_`-prefixed directories were walked.

**A predicate that "detects malformation" is really deciding what a valid input looks like, so
check it against the ugliest real inputs first.** The obvious rule for Defect B is "a path has no
spaces". It is also wrong, and would have broken hiring paperwork filings that have been working
for months. Two real filenames were worth more than any amount of reasoning about path grammar.

---

*Source of truth: `CLAUDE.md` § "Output-filing integrity …" (the ⚠ v6.5.1 subsection) and the
docstrings of `companion._is_artefact_dir` and `gtd_chat.is_bare_path`. Provenance: hand-off brief
2026-08-02, from the first live run after the v6.5.0 restart.*
