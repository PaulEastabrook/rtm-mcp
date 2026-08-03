---
report_type: handback-debrief
scope: a name-length advisory on the two governed item-creation writes, and the advisory-key collision it exposed
implemented_by: Claude Code (rtm-mcp session, 2026-08-02 → 2026-08-03)
derived_at: 2026-08-03
target_repo: rtm-mcp
artifact: v6.5.2 → v6.7.0, merged to `main` (`5b4dd12` merge; `cd0559a` v6.6.0, `bfd9aca` v6.7.0)
relates_to:
  - hand-off brief "name-length advisory (rtm-mcp)", filed by `plugin-marketplace-architect` 2026-08-02
  - designed change `general/plugin-marketplace-architect/designed-changes/2026-08-02-vault-naming-mirrors-rtm.md`
    §§ 1a.1, 1a.3, Moves 7 and 8 (approved 2026-08-02)
  - `2026-07-26-rtm-mcp-teaching-receipts-debrief.md` (v4.0.0) — the receipt this extends,
    and the release the v6.7.0 defect dates from
  - `2026-08-01-rtm-mcp-silent-parameter-loss-debrief.md` (v6.1.0) — the second advisory producer
  - agent-memory-mcp's own brief from the same designed change — it owns the slug, the cap and
    the truncation report; **nothing in this change belongs to it and vice versa**
status: needs-restart
---

# A name length is a GTD signal, not a filesystem one

## What shipped

**v6.6.0 — the advisory.** `gtd_item_create` and `gtd_project_create` now emit a receipt
`advisory` when the raw item/project name exceeds **60 characters**:

> Name is 84 characters. Long names usually mean something belongs in another field — an outcome
> statement, an acceptance criterion, or a date that belongs on the due date. Consider shortening.

**The message is the deliverable, and what it does *not* say is deliberate.** It names a length,
never a path, folder or slug. Vault folder names are now derived from the RTM item name, but
"your folder will be truncated" is not the value here. Measured over the live estate on
2026-08-02: live project names run **45% longer** than archived ones (median slug 46.5 vs 32.0);
of the 31 live projects over budget, 18 come under by cutting at the first `—` or `(`, and **13
are defects the length merely exposed** — nine outcome statements sitting in the title field,
four single actions mis-tagged as projects, two carrying a date that belongs on the due date. So
the useful claim is *"something is in the wrong field"*. That is a judgement only the caller can
make, which is why this is an advisory and can never become a gate.

**v6.7.0 — the collision the first change walked into.** Implementing v6.6.0 meant reading what
already wrote to `data["advisory"]`, and `gtd_item_create` already did: the Definition-of-Ready
`relational` axis, a `list[str]`, on all three return paths. `receipt.attach` — applied centrally
by `tools/gtd.py::_tool` — then assigned that same key unconditionally with the receipt's
`str | None`. **The axis its own docstring promised was "REPORTED in `advisory`" reached a caller
zero times between v4.0.0 and v6.6.0.** The axes are `advisory_axes` now, and the durable half is
the guard rather than the rename (below).

Consumer-facing summary: `gtd_item_create`'s payload gains `advisory_axes: list[str]` and its
`advisory` is now honestly typed `string | null`; both creation tools may return a longer
`advisory`. Nothing else changes shape.

## Design decisions & deviations

### The membrane — the constraint the brief was emphatic about, and it was right to be

rtm-mcp marks tool after tool "vault-free", and the single place it touches the vault
(`companion.py`) is read-only and documented as never to widen. An earlier draft of the designed
change gave this repo the slug function, the path template and the length budget; that was
corrected *before* implementation (§ 1a.1).

**What this repo owns is one integer and a comparison.** It imports no naming rule, knows nothing
of folders, and its message names no path. Three tests enforce that, and the third is the one
worth keeping:

| Guard | What it catches |
|---|---|
| `ast` sweep for an import of `vault_naming` | the rule being imported |
| scan for a vault path template in any module but `companion.py` | the rule being **copied** — the half an import check misses |
| `test_it_never_names_a_path_or_a_folder`, asserted on the OUTPUT | the claim escaping in prose even with the code clean |

The third exists because the message is where an unfounded filesystem claim would actually reach
a user, and — being a one-sided proxy — it would sometimes be false.

### ⚠ The threshold is a one-sided proxy, and lowering the number does not make it sound

The advisory measures the **raw name**; truncation is decided by the **slug**, computed
vault-side. They are different quantities:

- Measured: **6** live items truncate without tripping a 60-character advisory (a 56-character
  name losing its last word). **Zero** trip it without truncating. The error is strictly
  one-sided — under-warns, never over-warns, which is the safe direction for an advisory.
- It is unsound **in principle**, not merely imprecise: slugging *expands* as well as contracts
  (`&` → `and`), so `R&D & QA & Ops & Sec review` is 27 characters and slugs to 37. **No raw-name
  threshold is sound**, so reaching for a "better" number is wasted work — and reaching for a
  sound one would mean importing the slug rule, i.e. breaching the membrane.

The band is closed at the other end by `agent-memory-mcp`, which reports *actual* truncation at
filing time where `folder_name()` can compute it. Both docstrings state the caveat.

### Appended, not ranked

`attach` concatenates the name advisory onto whichever loss advisory fired (markup, else
bare-call). The existing two are mutually exclusive because one *explains* the other; name length
explains neither and is explained by neither — it is an observation about data that **did** land,
where the other two are about data that may not have. Ranking would silently drop a true signal.

### Silent by construction, not by exemption

`_tool` accepts `name_of`, an extractor supplied at the two registration sites (`name`;
`frame["name"]`, coerced because `frame` may still arrive as a JSON string). Every other tool
passes nothing, so `item_name` is `None` and the producer cannot fire. A **callable** rather than
a dotted-path string: the two sources are genuinely different shapes, and two small lambdas beat
a path mini-language nothing else would use.

### v6.7.0 — a separate key, not a merged advisory

Three grounds, in order of weight:

1. The receipt's `advisory` must be **one type across all 25 governed writes**. The collision *is*
   the defect; making one tool's field differ in type would preserve it under a new name.
2. `ADVISORY_AXES` is a constant lookup by kind, so merging would append a fixed sentence to
   **100% of action creates** — precisely the noise `receipt.is_facet` already exists to prevent,
   having been measured at two tools firing on every legitimate call.
3. `advisory_axes` reads as `missing`'s sibling — same `list[str]`, opposite gate — so a consumer
   iterates a list instead of searching a substring.

**The durable deliverable is the guard, not the rename.** `_write_envelope_schema` now raises
`TypeError` at import when a success model declares any `RECEIPT_FIELDS` name. That is the v6.0.0
posture — make the defect *unrepresentable* rather than merely rejected — and it is what stops the
next author reintroducing this in a different tool.

## Membrane / activation

Vault-free, **no new tag**, **no new `ErrorCode`**, no strict-tag interaction, no gate, no
`not_applied[]` entry (nothing was withheld). No activation-ordering hazard.

**To go live: restart the MCP server on v6.7.0.** Rollback is a revert.

Backward compatibility: v6.6.0 is purely additive. v6.7.0 is a **minor**, not a major, and the
reason is specific — the *runtime* value of `data["advisory"]` on `gtd_item_create` is unchanged
(it was already the receipt's string), so no consumer can have been reading the axes from it. The
advertised schema changes to match what was always written; `advisory_axes` is new.

**Three fingerprints churn** across the two releases (`gtd_item_create` twice, `gtd_project_create`
once) — description and output-schema only.

## Verification done

`make test` — **2,021 passed**. `make lint` — ruff, format and pyright all clean. Fingerprints
regenerated (`make fingerprints`, 102 tools, source_version 6.7.0). Both **re-run on the merge
commit `5b4dd12` itself**, not merely on the feature branch, and green there. **CI on the merge
push completed green** (run `30786030145`, 3m29s) across the supported Python matrix — which is
the one check a local run cannot stand in for, since the v4.0.1 docstring-dedent bug was
3.11/3.12-only and passed locally.

**Every guard was watched to FAIL under a deliberate mutation** — this is the part worth trusting,
because the brief flagged that sibling work on this pack had shipped five green tests guarding
nothing:

| Mutation | Result |
|---|---|
| threshold comparison never fires | 6 failed, including all four "fires" tests |
| `name_of` never reaches `attach` | **3 failed — only the end-to-end ones**; every pure test passed |
| naming-rule import + path template added | both membrane guards failed, naming file and line |
| v6.7.0: the collision guard removed, nothing else | exactly the 2 guard tests failed |
| v6.7.0: full revert to the v6.6.0 shape (guard removed, field renamed back, all three return paths reverted) | 8 of the 9 new tests failed, plus the fingerprint freshness guard |

**The ninth test passing there is the point, not a gap.** `test_a_clean_model_still_builds` is the
counterfactual: a guard that refused *everything* would satisfy the two tests above it, so one
test in the class must keep passing under the revert or the class proves less than it looks.

**What was NOT run.** No live RTM call and no live vault check — the server is still on v6.5.2
until it is restarted, so everything above is in-suite. Specifically unverified against
production: that the advisory renders as intended in a real client's tool result, and the
population estimate of how often it will fire (the 31-projects figure comes from the brief's own
scan, not from a re-scan here).

## Conventions

§ 3 tool pattern · § 6 write-gate discipline (**not** engaged — this is advisory, never a gate) ·
§ 7 enriched docstring · § 9 documentation lockstep (`CLAUDE.md` architecture section + test
inventory, `CHANGELOG.md`, `README.md`) · § 10 versioning (minor ×2) · § 12 add-a-tool checklist ·
§ 14 this debrief.

## Open items / handback

- **Consumer (gtd / board artifacts) — no action.** Both changes are additive at runtime. A caller
  that ignores `advisory` and `advisory_axes` is unaffected.
- **Paul — one action:** restart the MCP server on v6.7.0.
- **Open, minor, not a contract gap:** `tool_help.RECEIPT_FIELD_DOC["advisory"]` documents the
  bare-call and leaked-markup causes but not the name-length producer. Tier-2 documentation only —
  the tier-1 descriptions and the docstrings are correct.
- **Out of scope by design, and stays there:** the slug, the length cap, the path budget and the
  folder shape are all agent-memory's. If a future change here appears to need any of them, the
  scope is wrong.

## Durable lesson / gotcha

**When two mechanisms can both write one key, assert them together on one payload — otherwise a
green suite is compatible with them disagreeing.**

The v6.7.0 defect is the cleanest example this repo has produced. `_write_envelope_schema` mixes
`Receipt` in *behind* the result model, so on a shared field name the tool won the **advertised
schema** while `receipt.attach`, which assigns unconditionally, won at **runtime**. Both halves
worked perfectly. The schema tests read the schema and passed; the tool tests read the runtime and
passed; nothing compared them, so the DoR axis reached a caller zero times for three releases and
the output schema advertised an array where a string was written.

It was not found by a test or a review. It was found because implementing a *new* writer to that
key required reading the *existing* one — which is a reason to prefer changes that touch a shared
mechanism over changes that route around it.

Two smaller traps for the next author:

- **A docstring cannot interpolate a constant.** `60` is hard-coded in two docstrings, and the
  only thing keeping them in step with `NAME_ADVISORY_LIMIT` is a test asserting the advertised
  descriptions name it. Do not delete that test as redundant.
- **Only ever `make test`.** A system pytest at `/opt/anaconda3` silently **skips every async
  test** and still reports green — hit again during this work while filtering a single test class.

---

*Source of truth:* `CLAUDE.md` § "Name length as a GTD hygiene signal (v6.6.0) — and the membrane
it must not cross"; the docstrings on `receipt.build_name_advisory`, `receipt.attach`,
`models._write_envelope_schema` and `tools/gtd.py::_with_receipt`.
*Provenance:* hand-off brief 2026-08-02 (`plugin-marketplace-architect`) → designed change
`2026-08-02-vault-naming-mirrors-rtm` §§ 1a.1, 1a.3, Moves 7–8 → v6.6.0 (`cd0559a`) → v6.7.0
(`bfd9aca`, found in passing) → merge `5b4dd12`.
