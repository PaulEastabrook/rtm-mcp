---
report_type: handback-debrief
scope: the pre-v6.4.0 `FILING: <path> (unfiled)` marker — one predicate, two consumers
implemented_by: Claude Code (rtm-mcp session, 2026-08-02)
derived_at: 2026-08-02
target_repo: rtm-mcp
artifact: v6.4.1 → v6.5.0, merged to `main`
relates_to:
  - hand-off brief "The pre-v6.4.0`(unfiled)` marker is read as a broken link" (2026-08-02)
  - candidate RTM 1220547491
  - v6.4.0 (`2026-08-02-output-filing-integrity-debrief.md`) — the release that introduced
    `UNFILED:` and whose reasoning this applies backwards
  - v6.4.1 (`filed_unlinked` scoping) — the sibling first-live-run fix
status: needs-restart
---

# The legacy `(unfiled)` marker

## What shipped

A pre-v6.4.0 OUTPUT note declares "nothing was filed" as `FILING: <path> (unfiled)` — on a real
FILING line, because `unfiled=True` did not exist yet. Two things now treat it correctly:
`gtd_chat_thread` no longer renders an attachment for it, and `gtd_note_filing_gaps` reports it
under its own `legacy_unfiled` class instead of miscounting it as a broken link.

**The reported symptom was the cosmetic half.** The half that mattered is that
`_clean_filing_path` strips only the companion marker, so `work/…/x.md (unfiled)` was non-empty,
relative and backslash-free — it passed every check and `parse_filings` returned it as a real
path. Since `parse_filings` backs `gtd_chat_thread`, **the board was rendering a file attachment
for an artefact that was never filed**, with a path whose `(unfiled)` suffix resolves to nothing.
That is exactly what v6.4.0's `UNFILED:`-on-its-own-line design prevents; the reasoning was right
and simply had not been applied backwards to the notes already in RTM.

## Design decisions & deviations

**None from the brief.** Option (a) — a new `legacy_unfiled` class — was taken as recommended,
and is RTM-only, so it stays out of `VAULT_DEPENDENT` and keeps answering on a vault-less run.

**A predicate, not a change to `_clean_filing_path`'s return**, because the two consumers want
opposite things: `parse_filings` must skip it (no phantom attachment) while the audit must keep it
(silently dropping a legacy form makes a migration backlog invisible — the failure mode this whole
programme keeps finding).

**One line-walker, two typed views.** `_filing_payloads` was extracted so `parse_filings` and the
new `legacy_unfiled_paths` consume the same walk. Without that, the two-line labelled-continuation
form could work in one and not the other; there is a test asserting it works in both, because that
is the entire reason for sharing.

**The marker is stripped in the audit view and not in `parse_filings`** — deliberately asymmetric.
The verbatim-path rule exists so a filed path compares equal to the board's `FILED:` echo, which
is how the board suppresses its duplicate parse; a legacy-unfiled path never reaches the board, so
the row names the artefact plainly instead.

**One extra branch the brief did not call out.** A note carrying *only* a legacy-unfiled line has
no valid FILING path, so it falls through to the `prose_path` fallback — and its body trips every
prose hint. Without a guard it would be double-reported. There is a test for that specifically.

## Membrane / activation

- Vault-free, read-only path, **no new tag, no new `ErrorCode`**, no strict-tag interaction, no
  activation-ordering hazard.
- **Exactly one fingerprint churns** — `mcp__rtm__gtd_note_filing_gaps`, because its description
  enumerates its classes. Verified from the diff: `generated_at`, `source_version`, and that one
  tool. Nothing else moved.
- **Minor, not patch.** It is mostly a fix, but it adds an advertised output field
  (`findings.legacy_unfiled`) that a consumer can read, and CONTRIBUTING § 10 puts new features at
  minor. A board iterating `findings` by key sees a new key.
- **Version drift fixed in passing:** `src/rtm_mcp/__init__.py` was left at `6.4.0` by the v6.4.1
  bump while `pyproject.toml` and `uv.lock` went to `6.4.1`. All three are now `6.5.0`.
- **To go live: restart the server on v6.5.0.** Rollback is a revert.

## Verification done

**Ran and green:** `make test` — **1974 passed** (from 1960; +14). `make lint` — naming `--strict`,
ruff check, ruff format, pyright, all clean. `make fingerprints` regenerated.

**The guards were verified by removal**, per CONTRIBUTING § 8 and the brief's § 6 — the same
discipline that caught the v6.4.1 fixture gap. With `is_legacy_unfiled` neutered to `return False`,
**12 of the new tests fail** plus two pre-existing ones that depend on the behaviour
(`test_a_mounted_but_empty_vault_is_CLEAN_not_unknown` starts counting a fourth `linked_missing`).
The predicate was then restored and the suite re-run green. Every guard is load-bearing; none
passes vacuously.

Coverage against the brief's § 6 list, all present:
- a legacy line yields no `parse_filings` entry and no `parse_output_note` record;
- it appears under `legacy_unfiled` and **not** under `linked_missing` — nor, separately, under
  `prose_path`;
- **a genuine `FILING: <path> (+ .meta.md)` is byte-unchanged through both views** (the
  load-bearing regression, since this touches the shared parser);
- a path *containing* the word — `work/notes/unfiled-drafts/x.md`, and `work/(unfiled)/x.md` — is
  unaffected;
- one note carrying both forms reconciles the real one and reports the legacy one.

**NOT run, explicitly:**
- **No live smoke test.** The server has not been restarted on v6.5.0 (and is still behind v6.4.1
  as well). The three live instances named in the brief have not been re-read post-change.
- No RTM writes of any kind.
- The three live notes were **not** rewritten — out of scope per the brief's § 8: they are eval
  fixtures, fixtures are regenerated rather than edited, and RTM note edits are not undoable.

## Conventions

§ 8 testing (guards verified by removal) · § 9 documentation lockstep (README, `CLAUDE.md` module
table + feature section + test inventory; `server.py` instructions unaffected — no tool count
change) · § 10 minor bump · § 14 this debrief.

## Open items / handback

1. **Restart on v6.5.0** — now three releases overdue (v6.4.1 was never activated either).
2. **Nothing else.** No consumer action: `gtd_chat_thread.files[]` keeps its shape and only loses
   phantom entries; `gtd_note_filing_gaps` gains a key. **Consumer — no action.**
3. Standing from v6.4.0, unchanged: drop `LEGACY_OUTPUTS_PREFIX` at the next minor, and the open
   question about hand-filed artefacts polluting `filed_unlinked`.

## Durable lesson / gotcha

**When a release introduces a better form, ask what the OLD form now does in the new code.**
v6.4.0 reasoned correctly that a placeholder path on a `FILING:` line would be scraped as a real
artefact — and then shipped a parser that did exactly that to every note already carrying one. The
design note and the defect were written the same day, in the same file. The check to run is
mechanical: for each legacy spelling the new grammar replaces, trace it through every existing
consumer, not just the one that motivated the change.

**Two environment traps, both hit this session and both worth knowing:**

- **`uv run --no-sync pytest` silently runs the ANACONDA pytest**, which has no `pytest-asyncio` —
  so every async test is skipped and the suite reports green having run a fraction of itself. The
  tell is `PytestConfigWarning: Unknown config option: asyncio_mode`. Use `make test`.
- **A bare `uv run ruff …` re-syncs without the dev extra** and then cannot find `ruff` at all
  (the documented `uv sync` drops-dev-extra hazard, in a new costume). Use `make format` /
  `make lint`, which are the same commands via the Makefile and work.

**And one process note:** a `str.replace()` in a docs-patching script that matches nothing is a
silent no-op. Patching `CLAUDE.md`'s test-count line for `1958` did nothing, because v6.4.1 had
already moved it to `1960` — and the script still printed "ok". Assert every anchor.

---

*Source of truth: `CLAUDE.md` § "Output-filing integrity …" (the ⚠ v6.5.0 subsection) and the
docstrings of `gtd_chat.is_legacy_unfiled` / `legacy_unfiled_paths` / `_filing_payloads` and
`filing_gaps.FINDING_CLASSES`. Provenance: hand-off brief 2026-08-02; the second consequence was
found by the brief's author reading `_clean_filing_path` against its consumer rather than from the
symptom.*
