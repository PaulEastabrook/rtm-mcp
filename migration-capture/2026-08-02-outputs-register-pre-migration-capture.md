# Pre-migration capture — the live OUTPUTS registers as at 2026-08-02

Read-only capture taken before v6.4.0 ships the derived register writer. **RTM note edits are
NOT undoable** (`transaction_undoable: false` on every note edit in this account), so this file
IS the rollback for any register rewrite. Nothing was written to RTM to produce it.

**No register was rewritten by the v6.4.0 change itself.** The derived writer regenerates each
register on that project's next `gtd_note_attach_output` call, and the finder accepts the legacy
`OUTPUTS: <name>` form for one release so nothing is orphaned in the meantime. A bulk rewrite is
a separate, explicitly-authorised operational step — see the debrief's Open items.

Every register below shows the two defects the census named: the header line stored **twice**
(RTM stores a note as `note_title\nnote_text`, and the old writer put `OUTPUTS: <name>` in both),
and the title cut mid-word at exactly 60 characters.

---

## 1. Claude Coworking Productivity Enhancements — task `1195789348` / ts `605561942` / list `49657585`

TWO registers on this project, created 99 minutes apart on 2026-04-06. This is the live proof of
the prefix-finder defect: `startswith("OUTPUTS:")` could not see the date-prefixed `116750518`,
so it created `116751124` beside it.

### note `116751124` — the LIVE one (last modified 2026-04-27), buggy legacy title

```
OUTPUTS: Claude Coworking Productivity Enhancements
OUTPUTS: Claude Coworking Productivity Enhancements

| Date | Action | Output | Type | Status | Path |
|------|--------|--------|------|--------|------|
| 2026-04-06 | Brainstorm file storage skill/plugin separation from agent-memory | File Storage Skill/Plugin Separation from Agent Memory — Brainstorm | brainstorm | exploratory | Agent Memory/personal/personal-productivity/claude-coworking-productivity-enhancements/output/file-storage-separation-brainstorm.docx |
| 2026-04-06 | Brainstorm file storage skill/plugin separation from agent-memory | Agent Memory File Store — System Documentation | report | draft | Agent Memory/personal/personal-productivity/claude-coworking-productivity-enhancements/output/agent-memory-file-store-system-documentation.docx |
| 2026-04-19 | Atlassian recon: Jira + Confluence usage sampling | Atlassian Knowledge Graph Reconnaissance 2026-04-19 | report | review-needed | Agent Memory/personal/personal-productivity/claude-coworking-productivity-enhancements/output/atlassian-knowledge-graph-recon-2026-04-19.md |
| 2026-04-27 | Apply Research Notes Pattern enhancement to gtd plugin | GTD Skill Enhancement Proposal — Research Notes & Inline Citations | specification | draft | Agent Memory/personal/personal-productivity/claude-coworking-productivity-enhancements/output/2026-04-27-gtd-research-notes-enhancement-proposal.md |

Last updated: 2026-04-27
```

created `2026-04-06T11:32:10Z`, modified `2026-04-27T19:32:12Z`

### note `116750518` — the ABANDONED first attempt, catalogue title, free-prose body

```
2026-04-06 — OUTPUTS — Project output register
This note is a cumulative register of all artefacts produced by actions within this project and filed to the Agent Memory store. Updated each time an output is filed.

REGISTER
Date       | Action                                                          | Artefact                              | Format | Status      | Companion
2026-04-06 | Brainstorm file storage skill/plugin separation from agent-memory | File Storage Separation Brainstorm    | docx   | Exploratory | .md (v1.0.0)

All artefacts filed to: personal/personal-productivity/claude-coworking-productivity-enhancements/output/

SCHEMA CONTROLS
Current schema version: 1.0.0
Controls file: AI Memory/_schema.md
Convention: Each artefact has a companion .md metadata file (same base name) following the seven-section archival-informed structure defined in the controls file.

SYSTEM FILES (not artefacts, but created during this project)
AI Memory/_schema.md — root schema controls file for companion metadata (v1.0.0, created 2026-04-06)

--- AI Context ---
This is a living note — update it each time an output is filed to the store from any action in this project.
To find all project outputs: Glob personal/personal-productivity/claude-coworking-productivity-enhancements/output/*
To understand an output without opening it: Read its companion .md file (same base name as the artefact)
To understand the metadata schema: Read AI Memory/_schema.md
To see the full details of a specific output: Read the OUTPUT note on the action that produced it
Convention: OUTPUT note (action-level, rich detail) + FILING note (action-level, accession record) + this register (project-level, cumulative index)
```

created `2026-04-06T09:53:39Z`, modified `2026-04-06T09:53:39Z`

> ⚠ **This pair is why `resolve_outputs_register` falls back to the note's `created` date.** The
> brief said the winner should be `116751124`. A first implementation keyed only on the TITLE
> date, which sorts the undated legacy form as `""` — handing the win to the *dead* register and
> rebuilding into it, losing four live rows. Pinned by
> `test_THE_LIVE_CLAUDE_COWORKING_PAIR_resolves_to_the_one_still_in_use`.

---

## 2. Re-baseline the Programme Thunder / TSA exit … — task `1220192347` / ts `617467014` / list `49657585`

### note `118608594`

```
OUTPUTS: Re-baseline the Programme Thunder / TSA exit servic
OUTPUTS: Re-baseline the Programme Thunder / TSA exit service delivery work plan

| Date | Action | Output | Type | Status | Path |
|------|--------|--------|------|--------|------|
| 2026-07-31 | Brainstorm the re-baseline with Claude — scope, known unknowns, estimation approach, talent-deployment options and the per-person asks | Framing brief for the Thunder re-baseline — the pre-read and | doc | filed | work/hive-delivery/thunder-rebaseline/output/2026-07-31-thunder-rebaseline-framing-brief.md |

Last updated: 2026-07-31
```

created/modified `2026-07-31T17:34:14Z`

Both truncations visible: the title cut at `…TSA exit servic` and the **Output cell** cut at
`…the pre-read and`.

---

## 3. [FIXTURE-B] completion-workflow — task `1218857702` / ts `616786838` / list `51526642`

An eval fixture, not real work — so there are **three real registers**, not four.

### note `118504878`

```
OUTPUTS: [FIXTURE-B] completion-workflow — staging rollout p
OUTPUTS: [FIXTURE-B] completion-workflow — staging rollout project

| Date | Action | Output | Type | Status | Path |
|------|--------|--------|------|--------|------|
| 2026-07-25 | [FIXTURE-B] write the rollback runbook | Rollback runbook (staging rollout) drafted and saved — not f | doc | filed | rerun-eval1/rollback-runbook.md |

Last updated: 2026-07-25
```

created/modified `2026-07-25T20:56:33Z`

---

## 4. Define the Engineering Manager role … — task `1220362716` / ts `617517410` / list `49657585`

### note `118616044`

```
OUTPUTS: Define the Engineering Manager role — Roles & Respo
OUTPUTS: Define the Engineering Manager role — Roles & Responsibilities (co-authored with Clayton)

| Date | Action | Output | Type | Status | Path |
|------|--------|--------|------|--------|------|
| 2026-08-01 | Draft v0.1 of the Engineering Manager R&R in the Lead Software Engineer house format | Engineering Manager R&R draft v0.1 in the Lead SWE house for | doc | filed | work/turner-and-townsend/tech-strategy-steering/engineering-roles/reference/engineering-manager-role-rr-draft-v0.1.md |

Last updated: 2026-08-01
```

created/modified `2026-08-01T09:44:50Z`

Both truncations visible again: the title cut at `…Roles & Respo` and the Output cell at
`…the Lead SWE house for`.

---

## Summary — what each register loses or keeps on its next rebuild

The derived writer re-derives a row **only** from a live OUTPUT note carrying a `FILING:` line
on the project or one of its descendants. Anything else is dropped, and the drop is reported in
the receipt's `not_applied[]` (`output:register-row-dropped`). Predicted, from the OUTPUT notes
visible in this capture:

| Register | Rows now | Re-derivable | Note |
|---|---|---|---|
| `116751124` Claude Coworking | 4 | likely 1–2 | the four rows predate the `FILING:` convention; only `118162038` and `118161843` carry FILING lines, and both are 2026-07-04 briefs absent from the table. Expect rows to CHANGE, not merely shrink — check the receipt. |
| `116750518` Claude Coworking (dead) | 1 (free prose) | n/a | reported as a duplicate, never touched |
| `118608594` Programme Thunder | 1 | 0 from this capture | no OUTPUT note with a FILING line is visible on the project task itself; the source is presumably on a child action not read here |
| `118504878` FIXTURE-B | 1 | 0 | eval fixture, soft-deleted at teardown — irrelevant |
| `118616044` EM role | 1 | 0 from this capture | same as Thunder: the OUTPUT note lives on the child action that drafted v0.1 |

**This is the honest caveat on Move 3.** For Thunder and the EM role the register row was written
by the attach call, but this capture only read the PROJECT task's notes — the descendant OUTPUT
notes that will re-derive them were not read. The rebuild walks the whole descendant tree, so
they are very likely re-derived; that is an expectation, not a measurement. The receipt is the
place to confirm it on the first real attach against each project.
