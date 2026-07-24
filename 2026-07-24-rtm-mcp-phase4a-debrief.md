report_type: handback-debrief
scope: gtd-domain-tool-suite / Phase-4a (note-family + note-edit + engine-tags)
target_repo: rtm-mcp
version_shipped: 2.7.0
branch: main
status: debriefed
derived_at: 2026-07-24

# Handback debrief — Phase 4a: the note-family, the note-edit verb, the engine-tag namespace

## 1. What landed

rtm-mcp **v2.7.0**, commit `257cf7c` on `main` (Phases 0–3 already merged/pushed; CI green). **85
tools** total. Four new note tools + two additive extensions.

| Item | Tool / change | Envelope | D8-gated? |
|---|---|---|---|
| 2.1 | `gtd_attach_output` | `AttachOutputEnvelope` | no |
| 2.2 | `gtd_attach_contribution` | `AttachContribEnvelope` | speculative variant only |
| 2.3 | `gtd_annotate_clarification` | `AnnotateEnvelope` | `#ai_review` (present) |
| 2.4 | `gtd_edit_note` | `GtdEditNoteEnvelope` | no |
| 2.5 | `gtd_transition_state` namespace widen | — | **no code needed** |
| 2.6 | `gtd_link_dependency` resolve/obsolete mode | (existing) | no |

## 2. Deviations — three, each forced by evidence

**a. `gtd_attach_output` emits ONE note, not the brief's "OUTPUT + FILING pair".** The research
found two contradictory authorities: the note-shape-catalogue + `validate-note.py` model FILING as
a *line inside* the OUTPUT note; the GMI convention + agents write two separate notes. The decision
is not a coin-flip — **this server's own `gtd_chat_thread` already parses FILING as a line inside an
OUTPUT-typed note** (the Phase-0 attachment feature). Emitting the GMI pair would produce artefacts
the server's own read side wouldn't attribute, and the GMI `OUTPUT: [title]` first line doesn't even
pass the em-dash title grammar. So the single-note shape is the only internally-consistent one. The
GMI two-note form is legacy. **This is a genuine gtd-side unreconciled tension** — flagged for
lockstep.

**b. Item 2.5 needed no code.** The brief (D3) frames it as widening `gtd_transition_state`'s
accepted tag namespace to the `#ai_*` families. But this server **never had a GTD-only allow-list** —
`validate_transition` enforces cardinality on the four structural vocabularies only and passes
everything else through the strict-tag existence gate. So an `#ai_*` tag already transitions today,
provided it exists in the account. Confirmed **live**: `gtd_transition_state(add_tags=
["ai_progress_requested"])` succeeded against the real account. Item 2.5 became a regression test +
this finding, not a change. (This is the additive-by-construction property paying off.)

**c. The DEPENDS-ON flip writes `Resolved at: <date>` and NO `Resolved-by:` line.** The brief said
"writing `Resolved-at`/`Resolved-by`" — both wrong per the engine (`progression-fanout.md:335`: space,
not hyphen; no by-line). Ported faithfully; a test pins the absence of `Resolved-by:`.

Minor: `gtd_edit_note`'s op-set is as the brief specified (`replace_substring` / `replace_line` /
`set_frontmatter_key` / `retitle`), but only `replace_substring` "surfaces" an existing interface —
`gtd:replace_in_note_body` is substring-only and is a 3-MCP-call protocol, not a script. The other
three are net-new bounded ops (still bounded — the op-set is the safety property, and there is no
free-form overwrite op).

## 3. D8 status — much lighter than assumed

The brief's Prerequisite P treats the 12 `#ai_*` engine tags as a hard gate needing codification +
provisioning. **Live check of the account: 10 of 12 are already provisioned.** Only **`ai_speculative`**
and **`ai_pending_creation_fanout`** are missing. Codification-wise the research confirms **all 12
are already in `tag-taxonomy.md`**. So:
- 2.3 (`#ai_review`) and 2.5 (10 present engine tags): work **today**.
- 2.2: contrib / contrib_update / prep work today; **speculative** is strict-gated on `ai_speculative`
  until Paul provisions it (a live test pins the rejection).
- `ai_pending_creation_fanout` isn't written by any 4a tool, so it doesn't block anything here.

D8 for 4a therefore reduces to: **provision `ai_speculative`** if the speculative contrib variant is
wanted before 4b.

## 4. Test results

- **Full suite green: 1265** (was 1236; **+29**). `make lint` clean (ruff + format + pyright).
- `test_gtd_writes.py` +18 — FILING-path shape, OUTPUTS-register append (one `Last updated:`),
  the four CONTRIB variants' TYPE+tag, AI-ANALYSIS question block, the edit op-set (incl. **no
  free-form overwrite op exists**, retitle grammar reject, first-occurrence-only), and the
  DEPENDS-ON flip (`Resolved at:`, no `Resolved-by:`).
- `test_gtd_tools.py` +15 — accept + reject-writes-nothing per tool; the register append-to-existing;
  the speculative strict-gate; **each bounded edit op**; retitle-grammar-reject writes nothing;
  no-match writes nothing; unknown-note-ref writes nothing; and the **two additive regression
  guards**: `#ai_*` transitions accepted (2.5), `mode='create'` unchanged + `mode='resolve'` flips
  (2.6).
- **Fingerprint churn: 4 added, 1 changed** (`gtd_link_dependency`, the `mode` param) — no new
  `ErrorCode`, so no all-schema churn.
- **Live coverage smoke-test** (`#test` throwaways, cleaned up): attach_output wrote the conforming
  `— OUTPUT —` note; attach_contribution wrote CONTRIB + `#ai_contrib_drafted`; edit_note's
  `replace_substring` changed the body; the `#ai_progress_requested` transition succeeded.

## 5. Coverage delta (the phase metric)

The note-family / note-edit / engine-tag rows flip **COVERED**:
- OUTPUT/FILING write → `gtd_attach_output` ✅
- CONTRIB / CONTRIB-UPDATE / PREP / SOURCE-DRAFT writes → `gtd_attach_contribution` ✅
- AI ANALYSIS + clarifying questions + inbox rename → `gtd_annotate_clarification` ✅
- mutate-in-place note edit → `gtd_edit_note` ✅ (bounded)
- `#ai_*` engine-tag transitions → `gtd_transition_state` ✅ (already, by existence-gate)
- DEPENDS-ON status flip → `gtd_link_dependency mode=resolve|obsolete` ✅

Remaining note-write gap after 4a: the **AI-surface subsystem** (AI_Questions / AI_Activity writes)
— explicitly deferred to **4b**.

## 6. Marketplace-side lockstep

New this phase:
1. **The OUTPUT/FILING single-vs-pair reconciliation** (§2a) — the catalogue/validator say one note;
   GMI + agents say two. The server (and its own reader) is committed to one. gtd should reconcile.
2. **Provision `ai_speculative`** in RTM if the speculative variant is wanted.
3. **Codification gaps the research surfaced**: `SOURCE-CONFIRMED` absent from note-shape § 2 (a
   retitle to it passes THIS server's shape gate — which polices shape not vocabulary — but would
   fail gtd's `validate-note.py`); DEPENDS-ON `Status: resolved` absent from the § 5 enum
   (`active|superseded`, stale).
4. **Route** the OUTPUT/FILING/CONTRIB/PREP/AI-ANALYSIS/note-edit/engine-tag/dependency-flip
   call-sites onto the new tools.

Standing carry-overs (unchanged): the DoR-catalogue note (Phase 1, still highest priority), the
completion fan-out decision (Phase 2), the DEPENDS-ON `Status`/`Upstream type` doc fixes (Phase 2).
**And the big one: 39 `gtd_*` tools now exist across five phases with ZERO consumers wired** — the
consumer migration remains the critical path.

## 7. Verification boundary (honest)

§4 is machine-verified and reproducible; the live smoke-test in §4 is a single real-account run
(cleaned up). The tools have **not** run inside the deployed MCP server (still v2.3.0 — Phases 1–4a,
sixteen write tools, all need a restart). Nothing about 4b was built. The `ai_speculative` gate is a
real live rejection, not a mock.
