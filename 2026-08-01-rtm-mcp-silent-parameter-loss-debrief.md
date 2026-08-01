---
report_type: handoff-debrief
title: Silent parameter loss — the mechanism is caller-side leaked tool-call markup, not a host strip
target_repo: rtm-mcp
handoff_brief: general/plugin-marketplace-architect/handoff-briefs/2026-08-01-silent-parameter-loss-brief.md
version_shipped: v6.1.0 (the advisory-prose fix was developed as v6.0.5 and released inside it — never separately tagged)
status: DONE — mechanism established, estate repaired, detector shipped
filed: 2026-08-01
---

# Debrief — silent parameter loss (rtm-mcp v6.1.0)

**Verdict: H1 — caller-side, but not the caller-side fault the brief imagined, and not bounded.**
The parameter was never emitted as a JSON key. No client stripped anything. **H2 is dead by
measurement**: on this host a declared optional either passes through or throws — it is never
silently dropped. But the defect class that *did* bite is real, five months old, spans four MCP
servers and four model generations, and has already destroyed one parameter's worth of content in
Paul's system of record. Unlike the client strip, **it is server-detectable**, because the value
arrives in the wrong parameter instead of being destroyed upstream.

The brief's own framing is the thing to correct first: it treated "the advisory fired" as evidence
of a strip. It was not. The advisory's *prose* said so, and the advisory's prose was wrong.

---

## 1. The mechanism

The 2026-08-01 call is on record in the Claude Desktop local-agent audit log
(`local_b551979e-…/audit.jsonl`, lines 4738/4739; the rejected sibling at 4728/4729). The tool_use
`input` object carries exactly four keys — `task_ref`, `note_type`, `summary`, `narrative`. There is
no `sources` key. The array sits at **character 1,730 of the 2,010-character `narrative` string**,
as literal text:

```
…how a defect outlives its own fix.</narrative>
<parameter name="sources">["AI Memory general/…", "gtd v0.206.0 …", "RTM 1218844852 — …"]
```

The model emitted XML-style tool-call delimiters mid-argument and the serialiser folded them into
the preceding string rather than splitting them into sibling JSON keys.

**Why this is conclusive and not merely plausible.** Three independent legs:

1. The record is an `assistant` message carrying `request_id` and `usage` — the raw API response,
   logged **before** dispatch.
2. The sibling call in the same pair was **rejected by the host** (`-32602`, on an unrelated
   `note_type` enum), so it never produced a parsed argument object at all — yet its input is logged
   in full, with the identical leak. The log is therefore pre-strip, not post-strip.
3. No strip mechanism can relocate a sibling key into the middle of another key's string value.

**Three states, and collapsing any pair is the error.** The brief conflated (1) and (2) and went
hunting a host strip. A first analysis pass in this investigation conflated (2) and (3) and declared
the write clean. Two adversarial verifiers caught the second error; it is why the verify phase
existed.

| | model raw output | post-host arguments | durable RTM note |
|---|---|---|---|
| `sources` | intended, emitted as malformed markup | **absent** — no key, no strip | **present**, verbatim, as literal markup inside the prose |

So for `gtd_note_add` this is data **corruption**, not data **loss** — the intent is recoverable from
the artefact, and remediation is a body edit rather than a re-send. That distinction does not hold
for every case (see § 2).

### H2 is dead, and that is the load-bearing negative

Re-measured against the shipped converter (`/Applications/Claude.app` 1.24012.9,
`.vite/build/index.chunk-6k1UHY_-.js`) by instrumenting it with a recursive Proxy and replaying the
real advertised `gtd_note_add` schema through a line-by-line transcription on zod 4.4.3:

| Input | Result |
|---|---|
| `sources` as a proper `list[str]` | passes through unchanged |
| `sources` as the JSON **string** `'["a","b"]'` | **throws** (`invalid_type`, path `['sources']`) — not stripped |
| `sources` as a bare string | throws, same |
| `note_type` off-enum | throws (`invalid_value`) — this is the live ~2 ms rejection observed |
| undeclared key `sorces` | **stripped silently** |

**Only undeclared keys strip.** A correctly-named declared optional cannot silently vanish on this
path. Any future investigation should stop looking for that failure mode.

Incidental but material: `anyOf` / `oneOf` converts to `z.unknown().optional()` — a union-typed
parameter degrades to *fully untyped* at the host. That is a measured mechanism for the
single-typed-parameter policy in `tool_params.py`, which until now was justified only by "clients
flatten it to a bare `{}`".

---

## 2. Blast radius

Swept 20.8 k transcript files / ~104 k distinct tool_use calls across both transcript roots, then
adversarially re-verified. Every figure below survived a refutation pass; figures that did **not**
survive are named in § 3.

- **13 genuine leak events**, 2026-03-31 → 2026-08-01. **8 succeeded.** Spread across
  `mcp__rtm__` (6), Claude Code built-ins (4), `mcp__cowork__` (3), `mcp__Claude_in_Chrome__` (1),
  and four model generations. **Not rtm-specific, not `gtd_*`-specific, not one model.**
- **A longstanding low background rate plus a recent cluster** — 8 of 13 in the last 14 days.
- **It clusters within a session**: once it happens it recurs (3× inside one 92-second window).
- **Always at the tail of the longest free-prose parameter** (affected values 1,624–11,034 chars).
- **No gate anywhere caught the markup.** Every rejection among the 13 fired on something else.

### Durable damage in RTM — 5 corrupted notes, 3 tools, 2 dates

| Task | Note | Tool | Date | Shape |
|---|---|---|---|---|
| 1218845399 | 118619351 | `gtd_note_add` | 08-01 | `</narrative>` + `<parameter name="sources">[…]` |
| 1220192114 | 118619367 | `gtd_item_complete` | 08-01 | `</completion>\n</invoke>` (markup only) |
| 1218949038 | 118508560 | `gtd_inbox_item_annotate` | 07-26 | `</analysis_body>` + `<questions>[…]</questions>` |
| 1218949100 | 118508561 | `gtd_inbox_item_annotate` | 07-26 | `</analysis_body>\n</invoke>` |
| 1218949104 | 118508567 | `gtd_inbox_item_annotate` | 07-26 | `</analysis_body>\n</invoke>` |

Exact within the reachable search space, not a floor. Ruled out, not assumed: two further
`noteContains:"</"` hits are legitimate prose about HTML and JS bugs.

### Two genuine parameter losses — and the worse one is not the reported one

- **`gtd_note_add.sources`** (08-01) — recoverable; the text landed as garbage.
- **`gtd_inbox_item_annotate.questions`** (07-26) — **semantic loss.** Two clarifying questions were
  folded into `analysis_body`. The tool returned `questions_count: 0` and emitted no
  `CLARIFYING QUESTIONS` block, so the only trace is garbage in the body. **This one is six days
  older than the incident the brief was written about, and nobody noticed** — because the loss
  surfaced as a zero, and nobody reads a zero.

**The transcript sweep is not a superset of the RTM damage.** Three of the five corruptions came
from a scheduled autonomous run with no `local-agent-mode-sessions` record. Any future census must
query RTM, not the transcripts.

---

## 3. Deviations, and where the brief or my own agents were wrong

**The brief's H1/H2/H3 trichotomy did not contain the answer.** It is H1, but the brief glossed H1
as "the caller malformed the argument encoding (a harness-level serialisation fault)" and paired it
with "bounded, affects one caller shape". It is a serialisation fault, and it is **not bounded** —
four servers, five months, three rtm tools.

**The brief said the in-memory transaction log would almost certainly be gone.** It was not — the
rtm-mcp server session that made the 08-01 writes was still live (timeline 1945457989). It does not
help: RTM reports both transactions `undoable: false`, so undo is closed off regardless.

**CONTRIBUTING § 14 vs the brief's output path.** § 14 puts debriefs at the repo root; the brief
asked for this vault path. Both are live conventions — 56 debriefs sit at the repo root, and the
immediately preceding release (v6.0.0) filed vault-only. I have written **both**, identical content.

**Agent findings I had to discard.** The verify phase refuted 14 of 20 claims, several decisively:

- An agent identified the app.asar converter as the code path that served the incident. **Wrong** —
  local agent mode runs a separate Claude Code sidecar (2.1.219) whose 257 MB binary contains zero
  occurrences of `jsonSchemaToZodShape`. The converter table in § 1 is measured on Desktop chat's
  converter and is *consistent with* the observed rejection shape; the sidecar's own validation stack
  was **not** extracted. This does not weaken any conclusion — the loss happened before any
  converter ran — but the boundary is recorded in `CLAUDE.md` rather than papered over.
- An agent claimed `CLAUDE.md` was wrong that the converter "reads only `properties` and
  `required`". A verifier showed that function genuinely touches only those two and delegates the
  rest, so the original text is literally correct and the "refutation" attacked a strawman. What
  survived is an *extension*, not a correction — and separately, three real corrections did survive.
- The detector-feasibility agent reported "0/10 false positives" while its own script printed 4/4
  false positives on a second corpus it excluded from the denominator. A verifier caught it. But a
  different verifier then measured the tool-scoped predicate over **13,435 real RTM calls** and found
  **7 firings, all true positives, zero false positives**. The honest reading: the synthetic corpus
  was adversarial in the wrong direction; real traffic is far cleaner than it modelled.
- Two agents' file-sweep totals were unreproducible because **the corpus mutates under measurement** —
  this investigation's own tool calls contain the search needles. One sweep silently skipped 56% of
  the corpus (Python's `glob` does not descend into dot-directories). Counts in § 2 are the
  re-verified ones.

---

## 4. What shipped (v6.1.0)

**No gate, no schema, no signature, no tool behaviour changed. All 100 fingerprints byte-identical**
(verified: regenerating `tool-fingerprints.json` moved only `generated_at` and `source_version`).

**The advisory stops asserting a cause it has never been right about.** `receipt.build_advisory` told
every caller, as fact, that *"a misspelt optional is dropped by some MCP clients before the server
sees it, so the write lands without it"*. Measured across the whole transcript population, the
advisory has fired **twice** and that was the cause **neither time** — once a legitimately bare call,
once this leak, where nothing was misspelt, nothing was dropped, and the write landed *with* the
value. That wrong cause was not inert: it is what sent this brief hunting a host strip.

It now states the **observation** and offers both recorded causes without committing to either,
naming the markup cause first because it is the one a caller can check for itself. **The firing rule
is untouched** — `is_facet` and the all-absent condition are exactly as they were, per the brief's
§ 3 "out of scope". Corrected on all three surfaces that carried it: `receipt.build_advisory`, the
`receipt.py` module docstring, and `tool_help.RECEIPT_CONTRACT["advisory"]`.

**`CLAUDE.md`** gains the converter extension (§ 1) and a new section recording leaked tool-call
markup as a distinct mechanism — including the explicit correction that "No server-side change can
detect that" is true of the strip and **false of this**.

**v6.1.0 — the detector, built.** Initially left as a recommendation; Paul asked for it in the same
session. `receipt.detect_leaked_markup` is the whole rule, tool-scoped: a closing tag is a finding
only when its name is a parameter *the tool being called declares*. One predicate, two consumers —
the receipt `advisory` on the 25 governed writes (caller-visible) and a **log-only, never-raising**
middleware check on all 100 (the file sink), because `add_note` alone carries 78x the traffic of
`gtd_note_add` and is the escape hatch where drift enters.

It is **advisory, never a gate** — the anchor cannot separate a genuine leak from a note
*documenting* one, and this repo journals its own defects through exactly the tools being watched.
It also **closes the partial-loss blind spot for this cause**: `build_advisory` is silent whenever
one facet is supplied and another lost (15 of 25 governed writes), whereas this fires on the
evidence. Where both would fire, markup outranks, because it explains the absence and names the
lost parameter.

**A failing test improved the design.** The bare-tag dialect has no `<parameter name=…>` opener and
looked information-poor. It is not — `</analysis_body>\n<questions>[…]</questions>` closes
`questions`, itself a declared parameter of that tool. So a closing tag naming a declared parameter
*other than the carrier* is the lost-parameter signal, and both dialects reduce to one field. The
test asserted `[]`; the code was right.

---

## 5. Verification — and its boundary

| Check | prose fix | + detector |
|---|---|---|
| `make test` — Python **3.14** (production) | 1799 passed | **1817 passed** |
| `make test` — Python **3.11** | 1799 passed | **1817 passed** |
| `make test` — Python **3.12** | 1799 passed | **1817 passed** |
| `make lint` | clean | clean |
| `tool-fingerprints.json` | 100/100 unchanged | **25 changed** — the governed writes, from rewording the shared `RECEIPT_DOC`, not from 25 tools changing behaviour |

**Tests: two replace one.** `test_offers_both_recorded_causes_and_asserts_neither` and
`test_does_not_assert_a_single_cause_as_fact` supersede
`test_explains_that_a_misspelt_optional_is_dropped_client_side`. **The old test is the cautionary
one**: it asserted only that the word `"drop"` appeared in the message, so it passed happily for four
releases while the message told every caller something measured wrong. The inverted test carries its
previous claim in its docstring, per the `note_shape` precedent.

**Are the new tests vacuous?** The prose ones partly are, and I would rather say so: they pin
*prose*, proving the string says what we decided, not that the advisory is correct. **The detector ones are not**, and that is deliberate — `TestTheDetectorRunsOnTheRealServer` drives the in-memory
protocol end-to-end, because every pure-function test would pass against a server that never calls
the detector, which is the exact vacuity this whole investigation was about. Both new suites carry a
guard-the-guard proving a clean call stays silent; without it, a detector that fired on everything
would pass and be worse than none.

**Live verification of the repairs, done.** The estate-wide search that found the five corruptions
(`noteContains:"</analysis_body>" OR "</completion>" OR "</narrative>" OR "<parameter" OR
"</invoke>" OR "<questions>"`) now returns **0 tasks**, and the two restored blocks were confirmed
present by a positive control.

**Not run:** the detector has not been exercised against the live server — it needs a restart onto
v6.1.0, so it was validated in-suite over the real in-memory protocol instead.

**§ 9 lockstep:** `CLAUDE.md`'s test inventory was stale before I started — documented 1796 against
an actual 1798. Fixed to 1799, with the three drifting per-file counts corrected
(`test_note_types` 12→13 and `test_tool_help` 26→27 were pre-existing; `test_receipt` 44→45 is mine).

---

## 6. Recommendation — and what was then done

**Not "do nothing".** The brief invited that answer and it would have been wrong: this defect had
already destroyed content, the older loss went unnoticed for six days, and unlike the client strip
**the server can see this one**. Paul authorised all of it in-session, so items 1 and 2 are **done**
rather than recommended.

1. **DONE — the 5 corrupted notes are repaired** (§ 2 table). Not via `edit_note`, which replaces the
   whole body and would have meant retyping 2,000-character notes by hand — a transcription hazard
   on live data. Used `gtd_note_edit`'s bounded `replace_substring` op instead, which mutates in
   place and is a no-op (`changed: false`, nothing written) if the substring is absent. Three notes
   were markup-only truncations; two had content restored in the server's own grammar — the three
   sources as a `--- Sources ---` block, the two clarifying questions as a `CLARIFYING QUESTIONS`
   block. **A `title`-carrying edit would have been rejected**: `AI ANALYSIS` is not a registered
   note TYPE, so only the body-only path (which the note-shape gate never judges) was viable.
   Verified: the estate-wide markup search now returns zero.
2. **DONE — the detector shipped as v6.1.0** (see § 4). The design below is what was built:

   - **Predicate**: a closing tag whose name equals a **declared parameter of the tool being
     called**. Tool-scoped is what makes it precise — a full HTML document passed to `add_note`
     (`</head>`, `</body>`, `</script>`) does not fire, because none is an `add_note` parameter.
     Must match bare tags (`</analysis_body>`, `</completion>`) as well as `<parameter name=`; the
     bare dialect is the majority and a `<parameter name=`-only detector would miss it.
   - **Measured**: 7 firings across 13,435 real RTM calls, all true positives, 0 false positives.
   - **Cost**: **zero fingerprint churn** as a `not_applied[]` entry reusing `ErrorCode.NO_CHANGE`.
     (Ladder: a new `ErrorCode` churns all 100 tools; adding an existing code to `RECEIPT_REASONS`
     churns exactly the 25 governed writes; reusing a member already in both changes nothing.)
   - **Must be ADVISORY, never a gate.** The one class it cannot separate is a note *documenting*
     this defect — and this repo journals its own findings into RTM through exactly that tool. Also,
     `instructions` sits at **2,046 of its asserted 2,048-byte budget**: there is no room to document
     a gate on the selection surface.
   - **Scope decision to make**: the receipt covers only the 25 governed writes, and `add_note` alone
     carries **78× more traffic** than `gtd_note_add`. Middleware would cover all 100 tools but can
     only raise `ToolError` — i.e. it is a gate by construction. That tension is the designed
     change's central question.

3. **Widen the partial-loss blind spot advice.** `build_advisory` fires only when *every* facet is
   absent, so **15 of 25 governed writes** have a blind spot, and **90.8%** of live governed-write
   traffic sits in the silent zone. Two losses would *invert* an operation rather than omit a
   property: `gtd_chat_post.role` defaults to `me`, so a lost `role` posts an AI reply as Paul's turn
   **and adds** `#ai_chat_requested` instead of removing it (the board then polls forever);
   `gtd_dependency_link.mode` defaults to `create`, so a lost `mode` writes a **new** dependency
   instead of resolving one. Neither is currently detectable. This is the strongest argument for the
   detector, because the detector *would* catch both.

**Explicitly not recommended:** any attempt to parse the leaked array back out and apply it. The
server would be reconstructing intent from malformed output — precisely the "parse the model's prose"
posture v6.0.0 was built to eliminate.

---

## 7. Open items / handback

| Item | Owner | State |
|---|---|---|
| Repair the 5 corrupted RTM notes | — | **DONE**, verified zero remaining |
| Leaked-markup detector | — | **DONE**, shipped v6.1.0 |
| gtd skill: "check `not_applied[]` before reporting success" should widen to `advisory` — it now carries a second, more specific trigger | **gtd** | open |
| Extract the Claude Code 2.1.219 sidecar's own validation stack | — | open, low priority; no conclusion depends on it |
| Server restart onto **v6.1.0** (also picks up v6.0.4's SCOPE fix, still not live) | **Paul** | open — the detector does nothing until then |
| Sibling MCP servers (agent-memory, mindmeister, meistertask) carry the same receipt and the same exposure; 3 of the 13 measured events were on `mcp__cowork__` | **architect** | open — the detector is ~60 lines and portable |

**Consumer impact — no action.** Nothing a consumer calls changed shape, name, or behaviour.

---

## 8. Durable lesson

**A confidently wrong explanation is worse than no explanation.** The advisory correctly detected an
anomaly and then told the caller why — and the why was a guess, hard-coded as fact, that had never
once been right. It propagated into a hand-off brief, which spent its whole framing on a host-strip
hypothesis that measurement killed in one command. The detector fired; the diagnosis was invented.

The structural version: **the receipt reasons about absence, so it can only ever report absence.**
The moment it also asserts a *cause*, it is claiming knowledge it does not have, because the causes
of absence are not distinguishable from inside the server. State the observation; enumerate the
causes; commit to none.

And the investigative one: **three states — model output, post-host arguments, durable artefact.**
The brief collapsed the first two; my own first pass collapsed the last two. Both readings were
internally coherent and both were wrong. Whenever a parameter "goes missing", read all three before
concluding anything, and read the durable artefact **last and always** — it is the only one that
records what actually happened.

---

*Source of truth: `CLAUDE.md` §§ "Unknown-parameter rejection" (⚠ EXTENDED 2026-08-01) and "Leaked
tool-call markup"; `src/rtm_mcp/receipt.py::build_advisory`. Provenance: audit reproduction plus a
25-agent evidence/adversarial-verify workflow, 2026-08-01.*
