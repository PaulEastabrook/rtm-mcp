---
report_type: handback-debrief
scope: the Tool Affordance Standard — front-loaded selection, detail-on-demand (rtm_tool_help), teaching rejections
implemented_by: Claude Code session, rtm-mcp
derived_at: 2026-07-26
target_repo: rtm-mcp (~/Documents/Code/rtm-mcp)
artifact: v3.3.0 — 100 tools; committed on a feature branch, NOT yet merged or pushed (no PR raised)
relates_to:
  - handoff brief general/plugin-marketplace-architect/handoff-briefs/2026-07-26-rtm-mcp-tool-affordance-brief.md
  - designed change 2026-07-26-mcp-tool-affordance-standard.md (approved by Paul 2026-07-26)
  - design brief 2026-07-26-tool-affordance-and-codesign-brief.md (repo root — the OPEN input brief)
  - predecessor: reject-unknown-parameters-debrief.md (v3.2.0 — the trigger)
status: needs-restart (additive; live only after the connector restarts on v3.3.0)
---

# Handback debrief — rtm-mcp Tool Affordance Standard (v3.3.0)

## What shipped

Every tool is now **selectable from the part of its description the client actually keeps**,
**fully documented on demand**, and **teaches on rejection**. Three tiers, one authored fact per
surface:

- **Tier 1 (select).** Server `instructions` went **30,506 → 2,046 bytes**: the ~400-line per-tool
  catalogue is gone, replaced by what-the-server-is, the two-family split with routing keywords, and
  a pointer to `rtm_tool_help()`. The RTM legal disclaimer moved to the end. Every description now
  opens `<Domain> — <purpose>`.
- **Tier 2 (detail).** New tool **`rtm_tool_help(tool_name=None)`** — read-only and **offline**
  (zero RTM calls). No argument returns the whole-server index (one purpose line per tool, grouped
  by family); a name returns that tool's full contract: combination rules, worked examples, the full
  multi-case `Returns`, the read/write posture and undo path in prose, the typed-error catalogue
  with recovery, and chain edges.
- **Tier 3 (teach).** The v3.2.0 unknown-parameter rejection stopped merely refusing. It now names
  the tool's purpose, each valid parameter with type / required / enum, a nearest-name guess for a
  probable typo, the combination rules a JSON schema cannot express, and a pointer to the help
  payload. It still writes nothing.

No tool changed behaviour, capability, write safety, or return shape. **No new tag and no new
`ErrorCode`.**

## Design decisions & deviations

**The brief's measurements were accurate — verified first.** 18 of 99 descriptions over 2 KB,
`gtd_canvas_commit` at 4,893, `instructions` at 30,506 with ~93% discarded: all reproduced exactly
against v3.2.0 in this repo before any code was written.

**Deviation 1 — the 2 KB cap yields to CONTRIBUTING § 7, and 19 descriptions stay over budget.**
This is the most consequential departure. § 7 *requires* a multi-case `Returns` and an `Args:`
section in every tool docstring, and the `_FullDocstringMCP` shim advertises the **whole** docstring
as the description. For a genuinely complex governed write those two constraints cannot both hold,
and the brief itself says local guidance wins. So rather than delete § 7-mandated content to hit a
number, the **load-bearing guarantee is enforced directly**: a test asserts that every exempt tool
states its read/write posture *inside the front block that survives truncation*. The reasoning worth
carrying forward is that **front-loading is the actual protection and the cap is only a proxy for
it** — a caller is harmed when the surviving text doesn't say what a tool does to their account, not
when the total is large. All 19 exemptions carry a written reason in
`OVER_BUDGET_EXEMPTIONS` (`tests/test_tool_schemas.py`), and a guard-the-guard test fails if any
exemption becomes stale, so regrowth cannot hide behind the list.

**Deviation 2 — the index costs ~5.7 k tokens, not the brief's ~2 k.** The brief's figure came from
totalling the docstrings' *physically wrapped* first lines (7,733 chars). That split is an artifact
of source formatting and cuts mid-clause, so it does not yield a usable purpose. A semantically
complete first **sentence** costs ~3× more. I took the honest cost: the index is still ~30× cheaper
than the full advertised surface and is paid only on demand. `purpose_sentence` handles abbreviations
(`e.g.`, `i.e.`, …) so it never truncates mid-clause, and a test asserts every index purpose is a
leading **substring** of its own description — the index can never promise what the description does
not say.

**Deviation 3 — no 99 hand-written help records.** The brief says help must be "generated as a
projection, never hand-written", and I read that strictly: `tool_help.py` derives purpose,
parameters, types, enums, posture, `Returns` and the error catalogue from the **live advertised
schema**. Only four small tables are authored (`COMBINATION_RULES`, `EXAMPLES`, `CHAIN`,
`BFF_TOOLS`), each holding a fact no surface carries today. Consequence for the next author: **a new
tool needs no help record.** It appears in the index and gets a contract automatically, provided its
docstring opens `<Domain> — <purpose>`. The brief's "a tool added without a help record must fail
here" is therefore satisfied by the purpose-line assertion rather than by a registry lookup.

**The error catalogue is derived from the description, which is sound rather than lazy.** The shipped
`TestAdvertisedErrorContract` already asserts that every code a tool can reach is NAMED in its
description. So scanning the description for registry members is complete by construction — and a
second test bounds the claim from the other side, against the same `ast`-derived reachable set, so
help cannot teach recovery from a failure a tool cannot produce.

**Recovery hints are written for the caller's real context (Paul's steer, mid-implementation).**
Most callers here are not bare agents — they are the `gtd` skill, a scheduled worker, or a board
artifact. So a governed-domain failure (`dor_not_met`, `off_enum`, `invalid_note_type`,
`strict_tag_rejected`) names the mechanical fix **and points at the wrapping skill that owns the
judgement**; transport and identity failures stay deliberately general, being equally right for
every caller. The membrane holds: a **pointer** to gtd, never a copy of its vocabulary. `RECOVERY`
covers all 50 `ErrorCode` members, and a test fails if a new member ships without a hint.

**The taxonomy went in the description, not `_meta`.** `_meta` delivery was out of scope (gated on
measuring the other clients), and the measurement that matters is already in: **`_meta` and
`annotations` are not rendered to the model on this client.** So the `<Domain> — ` marker in ordinary
description text is not belt-and-braces — it is the entire model-visible mechanism, and `layer` /
`consumer` (including the `bff` split that naming cannot express) ride in the help payload, which is
a tool *result* and therefore always visible.

## Post-restart finding — tier 3 is largely UNREACHABLE from the Claude Code client

Measured against the live connector immediately after the v3.3.0 restart, and it qualifies the
guarantee ladder this design rests on.

**This client strips unknown arguments before they reach the server.** Two probes:
`get_lists(include_smart=false, include_archives=false)` returned a normal success, and
`rtm_tool_help(tool_nme="get_lists")` returned the **whole index** — i.e. the server saw a
*no-argument* call. Neither reached the middleware. The rejection itself is fine: it fires in-suite
and over a real stdio subprocess. The client simply validates arguments against the fetched
`inputSchema` and discards what does not match.

**Why this matters more than it first looks.** The guarantee ladder ranks a server-forced rejection
as tier 2 — "guaranteed on failure, the one moment the server *makes* the model read". For this
client, on the unknown-parameter path, that guarantee does not hold: the failure is absorbed
upstream. Tiers 1 (front-loaded description) and 4 (`rtm_tool_help`) are doing the real work here,
which strengthens rather than weakens the front-loading investment — but the teaching rejection
should be understood as insurance for *other* callers, not as this client's safety net.

**And the client reproduces the original defect shape.** Asking for `get_lists`' contract via a
misspelt `tool_nme` produced a confident, plausible, wrong answer — the index — with nothing saying
a parameter had been discarded. That is precisely the "confident success a caller reasons from"
failure v3.2.0 was built to close, relocated one layer up where the server cannot see it. It follows
that the original `type_tags` incident arrived through a caller that *does* forward unknown
arguments (a scheduled worker or a board artifact), not through this client. Worth confirming before
relying on it either way.

**Consequences to carry forward.** (1) Do not size the tier-3 work by expected hit-rate on this
client — it will read as zero. (2) The sibling-repo briefs should state which client each caller
population actually uses, because it decides whether tier 3 is live at all. (3) This is measurable
evidence for the input brief's open Q3 ("what is the real-world failure rate this is fixing?"): the
v3.2.0 WARNING log will under-count by construction wherever the caller is this client.

## Gotchas for the next author

- **`rtm_tool_help`'s own description shipped 2,841 bytes over budget on the first pass.** The tool
  implementing the standard violated it. There is now a test pinning specifically that. Expect this
  class of thing: the budget is easy to blow with a thorough docstring.
- **Count bytes, not characters.** Em-dashes are 3 bytes in UTF-8, and this repo's prose is full of
  them. `gtd_item_complete` is over budget in bytes while under in characters — which is why the
  over-budget set is 19 here and 18 in the brief.
- **The projection tests caught a real error in my own authored table**: a chain edge naming
  `assign_location`, which is a tool on the **official RTM connector**, not this server. If you add
  a `CHAIN` / `EXAMPLES` / `COMBINATION_RULES` entry, the guard will reject a name that does not
  resolve — trust it over your memory of the tool list.
- **The 44 fingerprints that moved are exactly the generic primitives** that gained the `RTM — `
  marker; the 55 `gtd_*` tools are byte-identical because they already conformed. So the architect's
  tool-detection scan will see a large but precisely attributable `schema-changed` set: **1 added,
  44 moved, 55 unchanged** — not a blanket re-hash.
- **`make lint` fails on pyright for an environment reason, not code.** The pinned pyright refuses to
  run ("Please install the new version or set `PYRIGHT_PYTHON_FORCE_VERSION`"). With
  `PYRIGHT_PYTHON_FORCE_VERSION=latest` it reports **0 errors, 0 warnings**. Pre-existing, unrelated
  to this change, and worth fixing separately.
- **`tool_help.py` is pure and takes introspected dicts in**, not the server — that is what makes
  every projection unit-testable without a live server, and it follows the repo's pure-builder
  convention. The tool layer does the introspection.

## Membrane / activation

Vault-free, pure RTM, additive and backward-compatible. **No new tag** and **no new `ErrorCode`**, so
there is **no activation-ordering hazard** — nothing needs provisioning in the RTM account first.

**To go live: restart the connector on v3.3.0.** Rollback is a plain revert (the help tool is one
registration; the rejection is one function). No one-way doors.

**Consumer action.** The `gtd` plugin and the board artifacts need **no change to keep working** —
nothing they call changed name or shape. The optional follow-on is the **cite-and-delete** pass the
designed change anticipates: gtd references that shadow-document the mechanical contract can now
cite `rtm_tool_help("<tool>")` instead. Not done here (different repo) and not required for this to
ship.

## Verification done — and what was not

**Run and green:**
- `make test` — **1,653 passed** (was 1,615; +38: 6 budget, 25 projection-agreement, 7 teaching-rejection).
- `make naming` / `--strict` — no findings, every gtd tool classifies and conforms.
- `make format` + `ruff check src tests` — clean.
- `pyright src` with the version override — **0 errors**.
- `make fingerprints` regenerated and the freshness test passes.
- **Real stdio wire-verify** (subprocess, JSON-RPC, not the in-memory client): `instructions` arrives
  at **2,046 bytes** with no disclaimer in the front block; **100 tools** advertised;
  `rtm_tool_help()` returns the 100-tool index over the wire; and the
  `gtd_inbox_capture(text=…, type_tags=[…])` call — the exact historical defect — returns the
  teaching rejection.

**NOT run, explicitly:**
- **No live RTM write of any kind.** Nothing in this change writes, so there was nothing to smoke —
  but note the corollary: the *teaching rejection's* no-write property is proven in-suite
  (`client.call` await count zero, the single chokepoint every tool passes through), not against the
  live account.
- **No behavioural eval.** The designed change offers a paid tier measuring selection accuracy and
  retry-after-rejection on front-loaded versus current descriptions. Deferred to Paul's go, as the
  designed change specifies — so the claim that front-loading *improves model tool selection* is
  reasoned and measured only as a byte budget, **not** demonstrated behaviourally.
- **Not committed, not pushed, no PR.** The working tree carries the change; branching, commit and PR
  were left to Paul rather than assumed.
- **The marketplace-side lockstep is not mine and is unverified from here**: the git-ops standard
  edits (§§ 4.1a / 9 / 10 / 10a) and the architect audit checks (`8.5.34`–`8.5.36`) are recorded in
  the designed change as landed locally at `f34e04aea` with **push pending credentials**. I did not
  and cannot confirm that from this repo.

## Conventions

§ 2 naming (`rtm_tool_help` is noun-first, `rtm_` domain, and passes `--strict`; naming scopes to the
55 gtd tools so it is not in that check's population) · § 3 the six surfaces, now extended in-place
with the three-tier affordance model and the front-load rules · § 5 typed errors (the help miss
reuses `invalid_input` with `candidates` under `details` — no new code minted) · § 7 the enriched
docstring, which **outranked the brief's 2 KB cap** · § 9 documentation lockstep (CHANGELOG,
CLAUDE.md architecture + module table + test-suite inventory, CONTRIBUTING §§ 3 and 12) · § 10 minor
bump, v3.2.0 → **v3.3.0** (additive tool + richer rejection prose) · § 12 the add-a-tool checklist
gained a step 3a for the affordance obligations · § 14 this debrief.

## Open / follow-ups

1. **Sibling repos (sequenced, per the designed change).** `agent-memory-mcp`, `mindmeister-mcp`,
   `meistertask-mcp` follow this pattern — but each brief must carry **its own** measurements. The
   pilot lessons to fold in: count **bytes**; expect the help tool's own docstring to blow the
   budget; the exemption-list-plus-posture-in-front pattern is the resolution where a local docstring
   standard mandates content that cannot fit.
2. **The input design brief (repo root) has open strands this did not touch** — it is still `status:
   OPEN`. Specifically: `outputSchema` trimming (73% of the advertised payload, its own A2 decision),
   `_meta` delivery (workstream D, gated on measuring the other clients), and the co-design questions
   C3/C4 (generated plugin tool inventory; whether prose lockstep is acceptable with no CI in
   `claude-plugins`).
3. **`make lint` pyright environment fix** — unrelated but currently makes the full gate red.
4. **The gtd cite-and-delete pass** (see Membrane above) — optional, different repo.
