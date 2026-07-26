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

## Post-restart finding — where an unknown argument actually dies, and why tier 3 rarely fires

Measured against the live connector after the v3.3.0 restart, then traced layer by layer. The
first version of this section blamed the client; that was wrong in an instructive way, so the
investigation and the correction are both recorded.

**The observation.** Two probes through the Claude Code client succeeded instead of rejecting:
`get_lists(include_smart=false, include_archives=false)` returned lists, and
`rtm_tool_help(tool_nme="get_lists")` returned the **whole index** — i.e. the server saw a
*no-argument* call.

**It is NOT fastmcp.** A raw JSON-RPC probe (`tools/call` written straight to the server's stdin,
no fastmcp `Client` in the path) shows the server receiving `tool_nme`, rejecting it with the full
teaching message, and logging the WARNING. fastmcp 3.4.4 forwards unknown arguments faithfully in
both directions — server-side to the middleware, and client-side when its own `Client` sends them.

**The argument never reached the server.** The live connector's own log
(`~/Library/Caches/claude-cli-nodejs/<cwd-slug>/mcp-logs-rtm/*.jsonl`) records both probes as
`completed successfully` with **zero** rejection records, at the exact timestamps. So the drop is
upstream of the wire, in the Claude Code harness.

**It is NOT our advertised `additionalProperties: false` either — that was my second wrong answer.**
I first claimed the harness was "honouring the contract we publish". A ten-agent adversarial pass
refuted it from shipped source. Claude Desktop owns the pipes and re-registers each upstream tool on
an in-process TS-SDK server via `LocalMcpServerManager.createSdkServer` →
`jsonSchemaToZodShape(tool.inputSchema)`. That converter iterates **only** `properties` and
`required`; `additionalProperties` appears nowhere in it. The shape is wrapped in a plain `z.object`
— no `.strict()` — and zod's default is **strip**, with the *parsed* output forwarded as
`arguments`. The shipped function was extracted from `app.asar` (SHA256-matched) and measured: with
`additionalProperties` `false`, `true`, or absent, an undeclared key is stripped in **all three**.
Invariant to the keyword. A strict-honouring converter *is* bundled and is never called. So our
closed schema is **discarded** upstream, not enforced — and no server-side change can affect it.
(The keyword is also pydantic's, from `kw_arguments_schema`, not fastmcp's or ours.)

**Which means "layered defence, working as designed" was wrong too.** The outer layer *mutates* the
call to fit the schema (a declared sibling key is honoured while the unknown one vanishes) rather
than rejecting it, which is not what `additionalProperties: false` enforcement means. And the
middleware was never the second layer.

**The larger casualty: v3.2.0's own premise is false.** A bare fastmcp 3.4.4 server with NO
middleware rejects an undeclared argument at pydantic's call-schema binding, before the tool body —
verified directly, and again against v3.1.0 (no `middleware.py`) over raw JSON-RPC. **v3.2.0 replaced
a pydantic dump with a teaching rejection; it did not add a gate.** The repo asserted the opposite in
four places (`CLAUDE.md`, `CHANGELOG.md`, the `middleware.py` docstring, `tests/test_middleware.py`),
all now corrected.

**And the incident is identified, contradicting my caller attribution.** It is on record in a Desktop
local-agent transcript from Claude Code CLI 2.1.219: at 21:22:33 `gtd_inbox_capture` with
`{name, type_tags, source, body}` and no `text` drew a *zod*-shaped `-32602` that never reached the
server; the 21:22:48 retry added `text`, kept the three undeclared keys, and succeeded — returning
`task_id 1218862014` and `transaction_id 24443437944`, byte-identical to the hand-off brief. So the
caller **stripped**, and the middleware could never have prevented the incident that motivated it.

**Tier 3 has no live consumer.** A sweep of 2,517 transcripts — every session on this machine,
including the whole `local-agent-mode-sessions` scheduled-worker population — found **zero** cases
of any caller receiving the rejection through the MCP boundary (every textual hit was my own `Bash`
or `Read` output). Retain the middleware as a backstop for unmeasured populations and for its better
message; do not justify it by observed prevention.

**The genuine residual defect is outside this repo.** The strip is silent: a misspelt optional on a
write tool is deleted by the host, the item is written without that property, and success is reported
with nothing marking the discarded intent. That is the original defect shape one hop beyond the
server's reach. Worth raising with whoever owns the host.

**Operational finding, unrelated but important.** The Desktop-spawned server's **fd 2 is
`/dev/null`** (`lsof` + `stat` confirm), so every write-boundary gate WARNING is destroyed. That is
the v3.0.1 unobservable-control lesson recurring at the process level, and it means the gates
currently have no observable output in production.

**Consequences to carry forward.** (1) Do not size tier-3 work by hit-rate — measured zero. (2) The
v3.2.0 WARNING log cannot answer the input brief's Q3: it under-counts by construction *and* its
stderr is discarded. (3) Sibling-repo briefs must not repeat the `additionalProperties` story; the
host strips regardless, so the tier-3 investment only pays for callers proven to forward. (4) Nested
keys behave oppositely — the converter emits `.passthrough()` for nested objects, so an unknown key
*inside* a declared object parameter survives to the server.

**Still unmeasured.** Nobody captured the literal wire frame (the conclusion rests on elimination
plus an exact offline reproduction of the converter). Whether a rendered board artifact, MCP
Inspector, or claude.ai web strips or forwards is untested. All findings are version-scoped to
Claude Desktop 1.24012.9 / bundled Claude Code 2.1.219.

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
