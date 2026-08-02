---
report_type: handback-debrief
scope: the sync-tool artefact survey, and the companion-counted-as-artefact defect it led to
implemented_by: Claude Code (rtm-mcp session, 2026-08-02)
derived_at: 2026-08-02
target_repo: rtm-mcp
artifact: v6.5.1 → v6.5.2, merged to `main` (`548aec7` survey comment, `8eac94d` fix)
relates_to:
  - `2026-08-02-filing-gaps-noise-debrief.md` (v6.5.1) — whose lesson this tested
  - v6.4.1, v6.5.0, v6.5.1 — the three prior fixes to the same report
  - NO hand-off brief: this arc came from Paul asking whether the sync conventions had
    actually been looked up, and then whether the lesson generalised
status: needs-restart
---

# The companion that was also an artefact

## What shipped

Two commits, one arc, no brief — both came from Paul asking the right question after v6.5.1.

**`548aec7` (comment only).** v6.5.1 replaced a hand-maintained `_SKIP_DIRS` with a derived
dot/underscore-prefix rule, and I described that rule as "derived" when it was derived from two
data points — `.stversions` (because the brief named it) and one `" 2"` duplicate (because I
happened to see it in `git status`). Paul asked whether I had actually looked up iCloud and
Syncthing conventions. I had not. The survey is now recorded in `companion.py`, including a rule
**not** to add.

**`8eac94d` (v6.5.2).** Paul then asked whether the lesson generalised. It did: the same module
held a second pair of lists that must agree and did not, and **49 companion files were being
enumerated as artefacts in their own right**.

## Design decisions & deviations

### The survey — why no further exclusion was added

The finding is that the dot-prefix rule is sufficient, and for a structural reason rather than
luck:

- **Directory-level versioning copies the tree verbatim**, so `X.md` and `X.meta.md` stay paired,
  the copy resolves a companion, and it is **tracked** — passing v6.4.1's filter and reading as an
  orphan that can never be journalled. That is `.stversions`, and it is the dangerous shape. Every
  such convention is dot-prefixed and already pruned.
- **File-level conflict copies mangle the stem.** iCloud writes `X.md` → `X 2.md` and `X.meta.md`
  → `X.meta 2.md`; the duplicate then looks for `X 2.meta.md`, which does not exist. Syncthing's
  `X.sync-conflict-<date>-<time>-<id>.md` behaves the same. **Untracked by construction**, so
  already out of `filed_unlinked` and counted only in `untracked_unlinked_count`.

Census: 6 `.sync-conflict-` files (all inside `.auto-memory` / `.obsidian` / `system`, already
pruned); 1 iCloud ` 2` duplicate (untracked); 0 `~syncthing~` temps, 0 `.icloud` placeholders, 0
Dropbox `(conflicted copy)`. Dot-directories present: `.companion`, `.obsidian`, `.claude-plugin`,
`.trash`, `.stversions`, `.stfolder`, `.auto-memory` — **`.claude-plugin` was not in the old
hand-maintained list either**, so the derived rule earned its keep twice.

**A rule was deliberately NOT added, and the comment says why.** A ` <n>.<ext>` exclusion reads as
the obvious iCloud-duplicate rule and is wrong: it matches three *real tracked artefacts* on this
vault — `AI Daily Briefing - 4 April 2026.md` and two siblings, where the year before the
extension looks exactly like a copy suffix. I only found that because I ran the pattern as a
measurement probe before considering it as a rule.

### The defect — a list that was the wrong shape for the fact

`companion_candidates` knows **five** companion forms; `_COMPANION_SUFFIXES`, which
`walk_artefacts` uses to keep companions out of the census, knows **three**. The gap is form 2:
for a non-`.md` artefact `X.pdf`, the companion may be `X.md`.

**That form cannot be expressed as a suffix at all** — it depends on a *sibling's* existence
rather than on the filename. So it was not forgotten; the list was structurally incapable of
holding it. Third occurrence in this sequence of the same conclusion, after `is_legacy_unfiled`
and `is_bare_path`: **when a list keeps failing, check whether the fact is list-shaped.**

`resolve_companion_path` returns the file acting as an artefact's companion; `walk_artefacts`
skips paths claimed that way, deriving the claimed set from the same candidate list the resolver
uses. Both public resolvers now delegate to one private core, so *which file is the companion* and
*what does it say* cannot disagree — **they previously could not disagree only because one of them
did not exist**, which is not the same thing.

Candidate order is honoured: `X.meta.md` outranks `X.md`, so where both exist the `.md` is not the
companion and keeps being enumerated. Asserted, because getting it wrong would delete real
artefacts from the census.

### The judgement call I nearly escalated, and why I did not

One of the 49 looked like genuine vault semantics rather than a defect:
`general/reference/library/books/book-getting-things-done.md` could plausibly be a library
*record* that merely happens to sit beside the PDF, and CONTRIBUTING § 6 is explicit that the
server must not decide vault semantics. I had the question drafted. Then I opened the file:

```yaml
schema_version: "1.0.0"
format: "pdf (application/pdf)"
library_entry: "[[book-getting-things-done]]"
```

It describes its sibling and points at the real Reference entity elsewhere. All 49 carry
`schema_version: "1.0.0"`; none is a standalone artefact. **Reading one file turned a question
for Paul into a plain defect.** The § 6 test is "would the server be DECIDING, or codifying a
decision already made?" — and the decision was already made, in the same module, by
`companion_candidates`.

## Membrane / activation

Vault-free in the write direction (the companion seam stays read-only), no new tag, no new
`ErrorCode`, no schema change, **no fingerprint churn** (only `generated_at` / `source_version`
move). Patch bump. **To go live: restart on v6.5.2.** Rollback is a revert.

## Verification done

**Ran and green:** `make test` — **1994 passed** (from 1989; +5). `make lint` — naming `--strict`,
ruff, pyright, all clean. `make fingerprints` regenerated.

**Guard verified by removal:** neutering the claimed-path skip fails
`test_the_sibling_md_companion_is_not_enumerated`. Restored and re-run green. The class also
carries its own anti-vacuity guard — a rule that excluded *too much* would pass that test
trivially, so `test_the_artefact_it_belongs_to_still_is_and_is_tracked` and
`test_an_md_beside_a_pdf_that_has_its_OWN_meta_is_still_an_artefact` sit beside it.

**Measured against the live vault** (read-only, no writes):

```
enumerated              1273 → 1224
untracked_unlinked      1113 → 1064
tracked                  160 →  160   (unchanged — the companions were untracked,
                                        so filed_unlinked does not move)
```

**NOT run, explicitly:**
- **No live run of `gtd_note_filing_gaps` or `gtd_note_report`.** The server has not been
  restarted; it is now behind v6.4.1, v6.5.0, v6.5.1 and v6.5.2. The vault-side numbers above are
  real, taken by calling `walk_artefacts` directly against `~/Documents/AI Memory`; the resulting
  *report* numbers still need the restart.
- No RTM calls of any kind. No notes repaired.

## Conventions

§ 6 membrane (the deciding-vs-codifying test, applied and resolved by reading the data) · § 8
testing (guard verified by removal; anti-vacuity guards beside it) · § 9 lockstep (`CLAUDE.md`
module row + test inventory, `CHANGELOG.md`; README unaffected — no user-facing surface changed) ·
§ 10 patch bump · § 14 this debrief.

## Open items / handback

1. **Restart on v6.5.2** — one restart covers v6.4.1 → v6.5.2.
2. **Re-run `gtd_note_filing_gaps` afterwards and record the numbers.** Four consecutive releases
   have each found a defect the previous one's noise was hiding; assume nothing until the run
   is clean twice.
3. **Consumer — no action.** No advertised shape changed.
4. **Considered and deliberately not changed:** `_NON_ARTEFACT` is
   `{context.md, _schema.md, _reference-index.md, _index.md}`, and three of the four start with
   `_` — which both consumers already skip. Only `context.md` does any work. Harmless redundancy
   rather than drift, and the explicit names document intent, so it was left. Recorded here so the
   next reader knows it was examined rather than missed.

## Durable lesson / gotcha

**"Derived" means derived from the space, not from the examples you happened to hit.** I replaced
a hand-maintained list with a rule inferred from two data points and called the result derived.
It was — accidentally. The survey that should have preceded it took twenty minutes and found a
seventh dot-directory the old list had also missed, which is the evidence that the rule was right
for reasons I had not established when I shipped it.

**When a list keeps being wrong, ask whether the fact is list-shaped.** Three times in this
sequence the answer was no: a legacy `(unfiled)` marker needed a predicate, a path-vs-sentence
test needed a predicate, and "this `.md` is my sibling's companion" needed a sibling lookup. A
list can only hold facts about a thing in isolation; all three facts were relational.

**Run the candidate rule as a measurement before adopting it as a rule.** The ` <n>.<ext>` iCloud
pattern flagged three real briefings. That took one command and would have been a silent
data-loss defect otherwise — the second time in two releases that the "obvious" pattern (`no
spaces in paths`, `a number before the extension`) would have rejected real artefacts.

**And the trap I documented one release ago, re-hit.** A `str.replace()` that matches nothing is a
silent no-op. Patching the test import failed because `ruff` had reordered the block between my
reading it and patching it; the script printed "ok". I had asserted the *other* anchors in the
same script — **some asserted anchors is the same as none**, because the unasserted one is exactly
where it will bite.

---

*Source of truth: `CLAUDE.md` § "Output-filing integrity …" (the companion.py module row) and the
comment block above `_COMPANION_SUFFIXES` in `companion.py`, which carries the survey census and
the do-not-add rule. Provenance: Paul's two questions after the v6.5.1 handback, 2026-08-02.*
