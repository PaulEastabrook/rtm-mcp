---
report_type: handback-debrief (marketplace-facing)
audience: the overarching Cowork session — plugin-marketplace-git-ops (standard owner) + plugin-marketplace-architect (enforcer)
scope: rtm-mcp pilot of the Tool Affordance Standard — what landed, and what the designed change must now be amended to say
implemented_by: Claude Code session, rtm-mcp
derived_at: 2026-07-26
target_repo: rtm-mcp (~/Documents/Code/rtm-mcp)
artifact: v3.3.0 — 100 tools; main @ cf4bfb1 (feature commit 8360a51, corrections e222c1f / d5a8091 / cf4bfb1); CI green
relates_to:
  - designed change general/plugin-marketplace-architect/designed-changes/2026-07-26-mcp-tool-affordance-standard.md (approved 2026-07-26)
  - hand-off brief general/plugin-marketplace-architect/handoff-briefs/2026-07-26-rtm-mcp-tool-affordance-brief.md
  - engineering handback (repo root) 2026-07-26-rtm-mcp-tool-affordance-debrief.md
  - predecessor reject-unknown-parameters-debrief.md (v3.2.0 — whose premise this pilot disproves)
status: DONE in rtm-mcp (live-verified after restart) — ACTION REQUIRED marketplace-side
---

# Handback — rtm-mcp pilot of the Tool Affordance Standard

## 0. The headline for you

**Tiers 1 and 2 are validated and shipped. Tier 3's rationale is disproved, and so is the
designed change's guarantee ladder at its second rung.** The pilot did what the debrief loop
exists for — it corrected the brief — but the correction is larger than a detail: the
server-forced rejection, which the designed change ranks as the *one guaranteed* channel after
the description, **cannot fire at all** for the client population we actually run. Measured, not
argued. Four claims I initially reported were refuted by a ten-agent adversarial pass, two of
them my own.

Nothing here invalidates the front-loading work — that is the part that turned out to be doing
all the work. What needs amending is the *justification* for tier 3, the index cost figure, and
the instructions to the three sibling repos.

## 1. What landed (verifiable)

v3.3.0, additive, no new tag, no new `ErrorCode`, restart-activated, `main @ cf4bfb1`, CI green,
1,653 tests.

| Tier | Delivered | Live-verified after restart |
|---|---|---|
| 1 — select | `instructions` **30,506 → 2,046 bytes**; all 100 descriptions open `<Domain> — <purpose>` (the 44 generic primitives gained `RTM — `) | Yes — `get_lists` opens `RTM — `; routing block on the wire |
| 2 — detail | `rtm_tool_help(tool_name=None)` — read-only, **offline**; no-arg index, named contract | Yes — index returns 100 tools; `gtd_engage_commit` contract returns 4 combination rules, 4 examples, full multi-case `Returns`, error catalogue with recovery, chain edges |
| 3 — teach | one guided-rejection shape (`guided_rejection.py`) converging `strict_tags.guided_error` + `engage_commit.validate`, wired into the call-boundary gate | Fires correctly on raw wire and in-suite — **never fires through the live host** (see § 2) |

Fingerprints: **1 added, 44 moved, 55 unchanged** — the churn is exactly the marker additions, so
your tool-detection scan should see a large but precisely attributable `schema-changed` set.

## 2. Findings that AMEND the designed change

### 2.1 The guarantee ladder is wrong at rung 2 (§ 1.3) — highest priority

The designed change ranks "a server-forced rejection" as **guaranteed on failure — the one moment
the server *makes* the model read**. On the Claude Desktop-hosted client that is false.

Claude Desktop re-registers each upstream tool on an in-process TS-SDK server via
`LocalMcpServerManager.createSdkServer` → `jsonSchemaToZodShape(tool.inputSchema)`. That converter
iterates **only** `properties` and `required`, wraps the shape in a plain `z.object` (no
`.strict()`), and forwards the **parsed** output as `arguments`. zod's default is *strip*, so an
undeclared top-level key is **silently deleted client-side** and never reaches the server.

Measured, from shipped source rather than inference:
- the function was extracted from `app.asar` (SHA256-matched) and is **invariant** to
  `additionalProperties` being `false`, `true`, or absent — the key is stripped in all three;
- a strict-honouring converter (zod's `fromJSONSchema`) **is** bundled and is **never called**;
- nested behaviour is the *opposite*: the converter emits `.passthrough()` for nested objects, so
  an unknown key *inside* a declared object parameter survives to the server;
- a sweep of **2,517 transcripts** — every session on this machine, including the whole
  `local-agent-mode-sessions` scheduled-worker population — found **zero** cases of any caller
  receiving the rejection through the MCP boundary.

**Amend § 1.3** to rank the rejection *below* the help tool for hosted clients, and to state that
its reachability is a per-client fact that must be measured, not assumed. **Amend § 2.0's tier-3
row** to justify the rejection as a backstop for *unmeasured* caller populations plus a strictly
better message — not as observed prevention.

### 2.2 A closed advertised schema buys nothing here (affects the whole family)

The designed change and the brief both lean on the family's schema discipline. Worth recording
that on this host our published contract is **discarded, not enforced**: `additionalProperties:
false` (which comes from *pydantic's* `kw_arguments_schema`, not from fastmcp or from us — and
entered our schemas at v1.35.0 when the fastmcp 3.x default flipped) is thrown away by the
normaliser before validation. The outer layer *mutates* the call to fit rather than rejecting it.
So "enforced twice by design / layered defence" — which I briefly reported and have retracted —
is not available as a design argument for any family server on this host.

### 2.3 The model-facing schema is a LOSSY round-trip — this one may undercut surface 2

On the deferred / tool-search path in this session, the schema presented to the model for
`rtm_tool_help` was:

```json
{"$schema":"http://json-schema.org/draft-07/schema#","properties":{"tool_name":{"type":"string"}},"type":"object"}
```

The server advertises that parameter with `additionalProperties:false`, `required`, a default, and
a full description. What reached the model had **no `additionalProperties`, no `required`, and no
parameter description**. Same for `get_lists` (both descriptions gone; one default dropped).

**This is a direct challenge to surface 2 of the six-surface standard** (per-parameter
`Field(description=…)`), which the family mandates precisely because "clients render the schema".
On this path they do not render it fully. I am flagging it rather than concluding it: my evidence
covers two tools on the *deferred* path, and the non-deferred path is unmeasured. **Recommend the
architect measure this before the standard's surface-2 rationale is restated** — if it generalises,
per-parameter descriptions are contingent on client and delivery path, and the tier-1 description
carries even more weight than the designed change already claims.

### 2.4 The help-tool index costs ~5.7 k tokens, not ~2 k (§ 2.0a)

The brief's ~1,933-token figure was computed from the docstrings' **physically wrapped** first
lines. That split is an artifact of source formatting and cuts mid-clause, so it does not yield a
usable purpose. A semantically complete first **sentence** costs ~3× more. rtm-mcp's index is
**~5,749 tokens** for 100 tools and is the honest number; still ~30× cheaper than the full
advertised surface, and paid only on demand. **Amend § 2.0a** to state the basis (first sentence,
not first line) and the realistic per-tool cost so sibling repos budget correctly.

### 2.5 The 2 KB cap can conflict with a repo's own docstring standard — publish the resolution

rtm-mcp's `CONTRIBUTING.md` § 7 *requires* a multi-case `Returns` and an `Args:` section in every
tool docstring, and its registration shim advertises the whole docstring. For a complex governed
write, "fit 2 KB" and "obey § 7" cannot both hold. Local guidance won.

The resolution that works, and which I recommend § 4.1a adopt as the sanctioned pattern:
**front-load, then exempt on the record, and assert the property the cap is a proxy for.** 19
descriptions remain over budget on a reasoned `OVER_BUDGET_EXEMPTIONS` list, and a test asserts
every exempt tool states its **read/write posture inside the front block that survives
truncation**, plus a guard that no exemption is stale. Front-loading is what protects a caller; the
cap is only a proxy for it.

### 2.6 Measure in BYTES

Em-dashes are 3 bytes in UTF-8 and this family's prose is full of them. rtm-mcp's over-budget set
is **19 in bytes** versus the brief's **18 in characters** — one tool differs on that alone. Every
budget assertion and audit check should specify bytes.

### 2.7 v3.2.0's premise was false — relevant to audit check 8.5.36

Not caused by this change, but discovered by it and corrected in the same pass. rtm-mcp asserted in
four places that before v3.2.0 an undeclared parameter "was accepted silently — the extra argument
discarded, nothing said". **Measured false**: a bare fastmcp 3.4.4 server with *no* middleware
rejects it at pydantic's call-schema binding, before the tool body; v3.1.0 (no middleware at all)
refuses the exact historical argument shape over raw JSON-RPC. v3.2.0 replaced a pydantic dump with
a teaching rejection; it did not add a gate. The motivating incident's silence was the **client's**
— the incident call is on record from Claude Code CLI 2.1.219 with three undeclared keys stripped
before the wire, returning the exact `task_id 1218862014` / `transaction_id 24443437944` the brief
quotes.

**Implication for `8.5.36` (teaching-rejection presence):** keep the check — a teaching rejection
is still better than a framework dump — but do not let its rationale claim it closes a
silent-acceptance hole on a pydantic/fastmcp stack. It improves a message that already existed.

## 3. Actions required, by owner

**`plugin-marketplace-git-ops` (standard owner)**
- [ ] § 1.3 / § 2.0 — re-rank the server-forced rejection; reachability is per-client and must be measured.
- [ ] § 4.1a — specify **bytes**; adopt the front-load + reasoned-exemption + posture-in-front pattern for repos whose local docstring standard mandates content that cannot fit.
- [ ] § 10a — correct the index cost basis (first *sentence*) and the realistic figure (~5.7 k for 100 tools).
- [ ] § 10 — drop any "enforced twice / layered defence" framing; a closed advertised schema is not enforced on this host.

**`plugin-marketplace-architect` (enforcer)**
- [ ] `anthropic-best-practices.md` — add a **client-behaviour** block, dated 2026-07-26, scoped to Claude Desktop 1.24012.9 / bundled Claude Code 2.1.219: undeclared top-level args stripped silently (zod strip); nested unknown keys pass through; `additionalProperties` discarded by the normaliser; `annotations` and `_meta` not rendered to the model; the model-facing schema is a lossy round-trip. These are exactly the platform facts that doc exists to hold, and they are on the `best-practice-scan` cadence.
- [ ] `8.5.34` — assert **posture-in-front** as well as length; length alone licenses the wrong fix (deleting mandated content).
- [ ] `8.5.36` — keep, re-justify per § 2.7.
- [ ] Q4 is **partially answered**: `_meta` / `annotations` do **not** reach the model on this client, so the description marker is the entire taxonomy mechanism, not belt-and-braces. Still unmeasured on other clients.
- [ ] New candidate: measure whether per-parameter descriptions survive to the model (§ 2.3) before restating surface 2's rationale.

**Sibling repo briefs (`agent-memory-mcp`, `mindmeister-mcp`, `meistertask-mcp`)**
- [ ] Do **not** repeat the `additionalProperties` rationale — the host strips regardless.
- [ ] Do **not** size tier-3 work by expected hit rate; on a hosted client it is zero. Scope it to caller populations *proven* to forward.
- [ ] Carry each repo's **own** measurements, in bytes.
- [ ] Reuse the exemption-list + posture-in-front pattern and the projection-agreement test shape (`tests/test_tool_help.py` in rtm-mcp is the reference).

**`gtd` (consumer)**
- [ ] Cite-and-delete is now **unblocked**: `rtm_tool_help("<tool>")` is live and serves the mechanical contract, so gtd references can cite rather than shadow-document. No gtd change is *required* — nothing it calls changed name or shape.

## 4. What the pilot validated unchanged

- The three-tier model is sound as a *structure*; only tier 3's guarantee claim failed.
- **Front-loading is the load-bearing intervention**, and this pilot strengthens the case: with the rejection unreachable and `annotations`/`_meta` invisible, the description's front block and the help tool are the only channels that reach the model at all.
- Help-as-projection works and is cheap to maintain: derive from the live schema, author only what no surface carries (combination rules, examples, chain edges, BFF set). **A new tool needs no help record.** The projection-agreement tests caught a real authoring error during the build (a chain edge naming `assign_location`, a tool on the *official* RTM connector, not this server).
- Defined-by-subtraction is the right spec for the help payload — it stayed genuinely complementary rather than duplicating the schema.

## 5. Verification boundary (please carry this honestly)

**Done:** 1,653 tests; `make naming --strict`; ruff; pyright 0 errors (the pinned pyright fails to
*run* locally for an environment reason — CI's lint job passes it); fingerprints regenerated and
freshness-checked; real stdio wire-verify; live post-restart verification of both help arities and
the contract payload; the 2,517-transcript caller sweep; the mechanism read from shipped source and
measured by SHA256-matched extraction; the bare-fastmcp and v3.1.0 rejection controls re-run by me
rather than taken from an agent.

**Not done:** nobody captured the literal `tools/call` wire frame — the strip rests on elimination
plus an exact offline reproduction of the converter. No behavioural eval was run, so
"front-loading improves selection" remains reasoned and byte-measured, **not** demonstrated
(the designed change's paid tier is still deferred to your go). Only **one** caller population has
been measured: a rendered board artifact, MCP Inspector and claude.ai web are untested. All
client findings are version-scoped as above.

## 6. Two items needing your action outside the repos

1. **Rotate `CLAUDE_CODE_OAUTH_TOKEN`.** A verification agent dumped the CLI process environment
   and a live token was written into its transcript.
2. **The write-boundary gates have no observable output in production.** The Desktop-spawned
   rtm-mcp instance's **fd 2 is `/dev/null`** (`lsof` + `stat` confirmed), so every gate WARNING is
   destroyed. This is the v3.0.1 unobservable-control lesson recurring at the *process* level, and
   it applies to any family server launched the same way. Worth a designed change of its own — the
   controls are running blind.

## 7. Handed back open

- The input design brief (`2026-07-26-tool-affordance-and-codesign-brief.md`, now committed at the rtm-mcp repo root) is still `status: OPEN`. Untouched strands: **`outputSchema` trimming** (73% of the advertised payload — its own A2 decision), **`_meta` delivery** (Q4 now partially answered against it), and co-design **C3/C4** (generated plugin tool inventory; whether prose lockstep is acceptable with no CI in `claude-plugins`).
- Whether the client-side strip is intentional product behaviour or a client defect cannot be answered by reading code. If it is a defect, it is worth reporting upstream: it silently discards caller intent and yields a confident wrong result, which is the exact failure class the family's error-teaching principle targets.

---
*Created: 2026-07-26 | rtm-mcp main @ cf4bfb1, v3.3.0 | Engineering handback: `2026-07-26-rtm-mcp-tool-affordance-debrief.md` (repo root) | Measurements against Claude Desktop 1.24012.9 / Claude Code 2.1.219 / fastmcp 3.4.4 / pydantic 2.12.5*
