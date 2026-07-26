---
report_type: design-brief
scope: tool-affordance (progressive documentation, teaching rejections, combination rules) + gtd plugin ↔ MCP co-design
derived_at: 2026-07-26
raised_by: Paul Eastabrook
target_repos:
  - rtm-mcp (~/Documents/Code/rtm-mcp)
  - claude-plugins (~/Documents/Code/claude-plugins) — plugins/gtd
session: Cowork design session — this brief is the input, not the answer
relates_to:
  - rtm-mcp v3.2.0 unknown-parameter rejection (RTM 1218862042) — the trigger
  - mcp-tool-documentation-standard.md (git-ops plugin references) — the family standard
  - CONTRIBUTING.md § 3 (six documentation surfaces), § 5 (errors), § 9 (lockstep)
status: OPEN — for design
---

# Design brief — tool affordance, and whether the plugin and its MCP are one product

## 0. Why now

v3.2.0 closed a defect where an MCP tool call carrying an undefined parameter was accepted
silently. The fix rejects it and names the legal parameter names. Reviewing that fix
surfaced a bigger question the fix does not answer:

> **A rejection tells the caller they were wrong. It does not teach them to be right.**

The current rejection returns bare names — no purpose, no types, no required/optional, no
descriptions, and a pointer ("check the tool description") with no payload for any caller
that cannot see the tool listing. Meanwhile every one of those descriptions **already
exists** in the advertised schema and is simply discarded.

That is a small symptom of a larger design space this session should settle. It divides
into three strands, and the last is the most consequential:

- **Affordance** (workstreams A, B) — how a caller discovers the right tool cheaply, learns
  its full correct use only when needed, and recovers from a mistake with enough information
  to retry correctly. Including mistakes that are *not* a bad parameter name: bad
  **combinations**.
- **Classification** (workstream D) — consistent naming separates generic RTM from `gtd_*`,
  but **not** the split that matters most: an artifact-facing (BFF) tool and an agent-facing
  tool are both `gtd_*`. Can the taxonomy be carried as machine-readable metadata on the tool
  index, so a skill selects on *what a tool is for* rather than on a prefix?
- **Co-design** (workstream C) — the gtd plugin and the `gtd_*` tools are now tightly coupled
  (74 distinct tool names referenced across 116 files). Are we treating them as one product
  designed to drive correct use, or as two things that happen to share names? Same question
  for the board/engage artifacts and the tools built specifically to serve them.

Everything below is grounded in measurements taken 2026-07-26 against the live server.

---

## 1. Measured baseline — the facts the design must fit

**What the server advertises today** (99 tools, `list_tools()` → `to_mcp_tool()`):

| Surface | chars | ≈ tokens | share |
|---|---:|---:|---:|
| `outputSchema` | 511,082 | 127,770 | **73%** |
| `description` (full docstring) | 132,432 | 33,108 | 19% |
| `inputSchema` | 53,467 | 13,366 | 8% |
| **Total advertised per connect** | **696,981** | **~174,245** | |

**Against a cheap index:** the *first line only* of all 99 descriptions totals 7,733 chars
(**~1,933 tokens**) — roughly **90× cheaper** than the full surface. Paul's instinct in
raising this ("there is somewhere cheaper to load, with full documentation lazy-loaded")
is quantitatively right, and the ratio is the argument.

**Three structural notes on those numbers:**

1. The `outputSchema` share is inflated by FastMCP 3.x, which **inlines `$defs`** rather than
   referencing them — a nested model repeats in full at every use site. This is documented in
   `CLAUDE.md` and is not a mistake in our models.
2. **This is what the server advertises, not necessarily what a client loads.** Claude Code
   itself defers most tools (name-only until `ToolSearch` fetches the schema). *Measuring what
   each real client actually pays is a task for this session (§ 7, Q0) — do not design against
   the 174k figure until it is confirmed to be the number a caller bears.*
3. Every parameter on all 99 tools **already carries an authored description** — zero gaps.
   The raw material for a good rejection and a good lazy-loaded doc exists; nothing needs
   writing, only routing.

**What naming can and cannot classify** (99 tools):

| bucket | count | separable by name? |
|---|---:|---|
| generic RTM primitives | 44 | **yes** — no `gtd_` prefix |
| `gtd_*` agent-facing | ~43 | **no** |
| `gtd_*` BFF / artifact-facing | ~12 | **no** |

The prefix separates 44 from 55. The split that matters — `gtd_project_canvas` (serves a
board) versus `gtd_capture_candidates` (serves an agent) — is *inside* `gtd_*` and no naming
convention short of a second prefix expresses it. A second prefix would mean renaming 12 tools
two waves after the last rename (v3.0.0/v3.1.0), which is not proportionate. Hence
workstream D.

**Tool-metadata mechanisms, probed 2026-07-26** (fastmcp 3.4.4):

| mechanism | reaches the wire as | in use today |
|---|---|---|
| `@mcp.tool(meta={...})` | `_meta` verbatim, top level | **no — unclaimed** |
| `@mcp.tool(tags={...})` | `_meta.fastmcp.tags` | **no — unclaimed** |
| `annotations=` extras | `annotations` (model allows extras) | annotations used; extras not |

`_meta` is the MCP specification's sanctioned extension point (`mcp.types.Tool` declares it;
both `Tool` and `ToolAnnotations` are `extra="allow"`).

**Decisive cost fact: `_meta` is fingerprint-neutral.** `scripts/dump-tool-fingerprints.py`
hashes exactly four members — `description`, `inputSchema`, `annotations`, `outputSchema`.
`_meta` is not among them, so adding a complete taxonomy to all 99 tools churns **zero**
fingerprints. Carrying the same taxonomy in `annotations` instead would churn **all 99**.
That asymmetry should decide the mechanism.

**The gtd coupling, measured** (`claude-plugins/plugins/gtd`):

| | count |
|---|---:|
| files naming at least one `gtd_` tool | **116** |
| distinct `gtd_` tool names referenced | **74** |
| reference docs under `skills/gtd/references/` | 62 |
| reference docs containing anything resembling a **worked call** | **8** |

74 tool names hand-maintained across 116 files, with worked examples in 8 of 62 references,
is the asymmetry to interrogate in § 5.

---

## 2. What is being asked for

Design (do not yet implement) an approach that delivers all of the following, as one coherent
scheme rather than six patches:

1. **Optimised inline documentation** — specific, complete, and cheap at the point of first
   contact.
2. **Progressive disclosure** — a one-line purpose that lets a caller *identify the right
   tool* before paying for full usage detail; full detail retrieved only when needed.
3. **Inline error codes** — machine-branchable, already partly solved (`error_codes.py`), to
   be extended coherently rather than duplicated.
4. **Teaching rejections** — a rejected call returns what the caller needs to **retry
   correctly**: not just what was wrong, but what right looks like.
5. **Combination rules, not just parameter names** — reject parameter *combinations* that are
   not allowed, with documentation of which combinations are.
6. **No duplication → no drift** — any fact stated in exactly one place, with the other
   surfaces derived from or asserted against it.
7. **A machine-readable tool taxonomy** — so a skill (or a script, or a drift check) can select
   tools by *what they are for* — generic RTM primitive, gtd domain composition, BFF/
   artifact-facing — rather than by parsing a name prefix that cannot express the distinction.

And to **answer**, not merely note, the co-design questions in § 5.

---

## 3. Workstream A — progressive disclosure

### The questions

- **A1.** What is the cheap index? A one-line purpose per tool that is (a) genuinely sufficient
  to *select* a tool, (b) never a truncation of prose written for another purpose, (c) stored
  once. Is the docstring's first line good enough as-is, or does "one-line purpose" need to be
  its own authored field with its own rule (see § 3 recommendation)?
- **A2.** What is the lazy-load mechanism, and does it actually work end-to-end for our
  clients? Candidates, each to be assessed on *does the real client support it*:
  - **MCP resources** — FastMCP exposes `add_resource` / `resource` / `read_resource`. Docs as
    resources, fetched on demand. Question: do Claude Desktop / Claude Code / the sandboxed
    board artifact each support resource reads, and do they do so *lazily*?
  - **A help tool** — e.g. `rtm_tool_help(tool_name)` returning the full contract. Universally
    supported (it is just a tool call), self-documenting, and — crucially — **the same payload
    a rejection can embed or point at**, which is the unification opportunity.
  - **Client-side deferral** — the pattern Claude Code already uses on this very session:
    tools listed by name only, schema fetched via `ToolSearch`. An existence proof that the
    pattern works; the question is whether we can *influence* it from the server side, or
    whether it is purely the client's decision.
  - **Trimming what we advertise** — particularly `outputSchema` (73% of the payload). Is the
    full output schema earning its cost at connect time, or should it be lazy too? Note the
    hard constraint: `output_schema=` is a load-bearing surface of the family standard and
    `TestOutputSchemas` pins it. Any trimming must be argued against that standard, not
    around it.
- **A3.** Does the answer differ per consumer? A main-session agent, a headless scheduled
  worker, a sub-agent with a trimmed toolset, and the sandboxed board artifact have very
  different context budgets and very different ability to see the tool listing at all.

### Recommendation (for the session to accept or reject)

**R1 — Make the one-line purpose a first-class, authored, single-sourced field.** ~1,933
tokens buys tool *selection* across the whole surface. Authored (not derived by truncation),
asserted by test to exist, to be one line, and to be the first line of the docstring — so
there is one copy, not two.

**R2 — Ship a help tool as the lazy-load path, and make the rejection reuse it.** A help tool
is the lowest-risk mechanism (no client capability assumptions) and it collapses two problems
into one: `rtm_tool_help(name)` and "what a rejection embeds" become the *same generated
payload*. If resources prove well-supported, they become an additional transport for the same
content — never a second copy of it.

---

## 4. Workstream B — teaching rejections and combination rules

### The questions

- **B1.** What should a rejection carry? Candidate payload, to be argued up or down:
  - the tool's **one-line purpose** (orients a caller who picked the wrong *tool*, not the
    wrong parameter — arguably the actual `type_tags` case: capture was the wrong tool for
    tagging);
  - each valid parameter with **name, type, required/optional, enum values, description**;
  - a **nearest-name suggestion** for a probable typo;
  - a pointer to the lazy-loaded full contract.
  Measured cost of the descriptions half: median tool ~211 chars, worst case
  (`gtd_surface_create`, 13 params) ~1,566 chars — on a path that only executes when someone
  is already wrong.
- **B2.** Is there precedent to reuse rather than invent? **Yes, and it should be the model:**
  `engage_commit.validate` already rejects an illegal verdict with a **closest-legal
  suggestion**, and `strict_tags.guided_error` already returns a self-documenting rejection
  carrying `how_to_proceed`. The question is whether these become *one* guided-rejection
  shape rather than three similar ones.
- **B3 — the harder half: combinations.** Which tools have parameter-combination rules today,
  where are they enforced, and are they *advertised* anywhere a caller can see before calling?
  Known shapes: `task_name` **or** the three ids (`resolve_task_ids`); `gtd_item_stamp_tokens`
  keyed by `project_id` **or** omitted to sweep; per-kind Definition-of-Ready in
  `gtd_writes.check_dor` (which required fields depend on `kind`); `gtd_engage_commit`'s
  per-kind verdict legality and its `date_phrase` requirement for date verdicts.
- **B4 — a real tension the session must resolve.** JSON Schema's native vocabulary for
  combination rules is `anyOf` / `oneOf` / `dependentRequired`. **This family has an explicit
  rule banning advertised unions on parameters**, because MCP clients flatten `anyOf` to a bare
  `{}` and lose type, description and enum (measured 2026-07-19: 110 such params across 32
  tools; `TestSingleTypedParameters` now pins zero). So the obvious structural answer may be
  actively harmful. Does that mean combination rules **cannot** be advertised structurally and
  must live in prose + a tested runtime rejection? If so, say so explicitly and design the prose
  and the rejection to carry the whole weight.
- **B5.** When should an illegal combination be made **unrepresentable** instead of rejected?
  Strong precedent exists: Wave 2 (D11) split `gtd_query(perspective=…)` into three tools
  precisely so an invalid parameter combination became unrepresentable rather than merely
  rejected. What is the rule for choosing? (Suggested starting point: *split when the illegal
  combinations partition cleanly and the arity stays sane; reject-with-guidance when they
  don't* — but the session should state the rule, because it will be applied repeatedly.)

### Recommendation

**R3 — One guided-rejection shape, generated from the tool's own advertised schema**, carrying
purpose + parameter table + nearest-name suggestion, and reused by the unknown-parameter gate,
the combination gate, and (where it fits) the existing strict-tag and verdict rejections. Not
a fourth bespoke shape.

**R4 — Declare combination rules as data, in one place, and derive three things from them**:
the runtime rejection, the prose in the docstring, and the test that proves they agree. Prefer
unrepresentable-by-construction (split the tool) whenever the § B5 rule allows it.

---

## 5. Workstream C — the co-design question (the one Paul most wants answered)

> *Now we have a tight coupling between a domain plugin (GTD) and the gtd-specific MCP tools,
> are we following best practice to really drive correct use?*

This is not a documentation question. It is a question about whether **the plugin and the
server are one product with one contract, or two products with a naming convention**.

### The questions

- **C1.** Should the gtd skill and the `gtd_*` tools be **explicitly aware of each other and
  designed to complement correct usage**? Today the awareness is one-directional and implicit:
  116 plugin files name tools; the server knows nothing of the skill. What would deliberate
  bidirectional design look like, and what would it cost?
- **C2.** **Worked examples — where do they live, and who owns them?** Only 8 of 62 gtd
  references carry anything resembling a worked call. Options, each with a drift profile:
  - examples authored in the plugin (closest to the workflow; **drifts silently** when the
    server changes — no CI in claude-plugins);
  - examples authored in the server and *served* (one copy, provably in step with the schema,
    testable; further from the workflow narrative);
  - examples authored in the server, *rendered into* the plugin by a sync step (best of both;
    a build step to maintain).
  **Recommendation R5: the server owns the example and the plugin consumes it** — an example
  is a statement about the tool contract, and the tool contract lives here where it can be
  tested. A skill reference should link, not restate.
- **C3.** Should the plugin's tool inventory be **generated** rather than hand-maintained
  across 116 files? Note the existing asset: `tool-fingerprints.json` already gives a
  per-tool schema hash. That is a ready-made drift detector — a plugin referencing a tool
  whose fingerprint has moved could be flagged automatically.
- **C4 — the sharpest one: is prose lockstep good enough?** Several contracts are *already*
  declared to live in two repos at once and stay in step by discipline alone:
  `engage-verdict-grammar.md` (plugin) ↔ `engage_commit.py` (server) ↔
  `validate-engage-verdict.py` (plugin); the tag taxonomy in `tag-taxonomy.md` ↔
  `tag_report.py`; the note catalogue ↔ `note_shape.py`. **claude-plugins has no CI**, so every
  one of these is prose-only lockstep with nothing enforcing it. Is that acceptable, and if not,
  what is the minimum enforcement — a CI job in claude-plugins, a contract file published by
  the server and consumed by the plugin, or a scheduled drift audit?
- **C5 — the same question for the artifacts (BFF).** `gtd_project_canvas`, `gtd_project_index`,
  `gtd_engage_seed`/`gtd_engage_commit` are explicitly backend-for-frontend: built for a
  specific board. **A rendered artifact is a frozen copy of its template** — the Wave 3 lesson,
  where four deprecated tool names survived in a live board seven days after the template moved
  on, *and* in its injected `mcpTools` allowlist, where a half-fix would have silently broken
  the board. Should a BFF tool and its artifact ship a **declared contract and version
  handshake**? Precedent already exists and is generalisable: `gtd_canvas_commit` returns
  `order_persisted: "order-note"` (a string naming the mechanism, deliberately not `true`) so an
  old board stays silent rather than lying. Should that be a pattern, with a rule?

### Recommendation

**R6 — Treat gtd-plugin + `gtd_*` tools + board artifacts as one product with one versioned
contract.** Concretely: the server publishes the contract (purpose, parameters, combinations,
examples, error codes, fingerprints); the plugin and artifacts *consume* it and never restate
it; a drift check runs somewhere that actually executes. The membrane stays exactly where
`CLAUDE.md` puts it — **the server enforces mechanical shape, the plugin owns canonical
vocabulary** — this recommendation is about *who publishes documentation*, and must not be
allowed to erode that boundary.

---

## 6. Workstream D — a machine-readable tool taxonomy

Consistent naming has served well and should not be disturbed, but it has reached its limit:
it separates 44 generic tools from 55 `gtd_*` ones and **cannot** separate the ~12
artifact-facing (BFF) tools from the ~43 agent-facing ones inside that prefix. A skill
instructed to "use the gtd tools" is being told something true and insufficient.

### What is already available (probed, not assumed)

Both `meta=` and `tags=` reach the wire and neither is currently used anywhere in rtm-mcp
(§ 1). Registering `@mcp.tool(tags={"gtd","bff"}, meta={"layer":"bff","domain":"gtd"})`
produces:

```json
"_meta": {
  "layer": "bff",
  "domain": "gtd",
  "fastmcp": { "tags": ["bff", "gtd"] }
}
```

And it is **free**: `_meta` sits outside the fingerprint's four hashed members, so a full
taxonomy across 99 tools churns nothing.

### The catch the session must resolve first

**Wire-visible is not the same as model-visible.** The metadata reaches the *client*; whether
the model reading the gtd skill ever sees it depends on how that client renders the tool
index — and an instruction to "observe the metadata" that the model cannot see would fail
**silently**, which is precisely the failure shape that produced this whole brief.

Evidence at its actual strength, neither more nor less: rtm-mcp sets `annotations` on every
tool today, and those annotations do **not** appear in the tool definitions rendered to the
model in the Claude Code harness (name, description, parameters only). That is suggestive but
not proof — a client may consume annotations for permission decisions without rendering them.
**This needs measuring per client (§ 7, Q4) before any design commits to `_meta` as the
delivery path.**

### The questions

- **D1.** What are the axes? These are independent facts and probably should not be collapsed
  into one enum. Candidate set, to be argued: `layer` (primitive | domain | bff), `domain`
  (rtm | gtd), `consumer` (agent | artifact | either), and possibly `stability` or
  `lifecycle`. Read/write is **already** carried by `annotations` and must not be restated —
  that would be exactly the duplication § 2.6 forbids.
- **D2.** Is `consumer` genuinely distinct from `layer`, or is BFF-ness fully determined by
  who calls it? Note `gtd_project_plan` and `gtd_project_canvas` are both read by the board
  *and* usable by an agent, so "either" may be a real value rather than a fudge.
- **D3.** What should a skill be instructed to *do* with the taxonomy? Selection is the
  obvious use; are there others — refusing to call a BFF tool from a chat context, preferring
  a domain composition over assembling primitives, warning when a primitive would bypass a
  governed write surface?
- **D4.** Where does the taxonomy live so it cannot drift from the tools it describes? It is a
  fact about each tool, so it belongs beside the tool — but it is also consumed by the plugin
  (§ 5), which raises the same publish-and-consume question as C2/C3.
- **D5.** Does the taxonomy subsume or duplicate `scripts/check-tool-naming.py`? That check
  already classifies every tool name against a lexicon and reports `unclassifiable`. If a tool
  declares its own layer, the naming check could **verify the declaration against the name**
  instead of inferring — turning two overlapping sources into one source and one assertion.

### Recommendation

**R7 — carry the taxonomy twice, from one authored source, with a test asserting they agree.**

- **Machine-readable in `_meta`** — free, correct, spec-sanctioned, and the right home for
  anything a script, drift check, or capable client consumes.
- **Model-readable in the description's first line** — the same one-line purpose R1 already
  proposes as the cheap index. A short conventional marker there is *guaranteed* to reach a
  skill's reasoning, because it is ordinary description text that every client renders.

The duplication is deliberate but must be governed exactly as § 2.6 demands: **declare the
taxonomy once as data, generate both surfaces from it, and assert equality in a test.** Then
the skill instruction is robust whichever way the client behaves — select on the visible
marker; any tooling that *can* read `_meta` gets the richer structured form. If Q4 shows a
client does surface `_meta` to the model, the description marker can be reconsidered later; it
cannot be added retroactively to a decision already shipped the other way.

---

## 7. Questions this brief cannot answer — measure them in the session

- **Q0 (do this first).** What does each real client *actually* load? Claude Desktop, Claude
  Code (which defers), a headless scheduled worker, the sandboxed board artifact. The 174k
  figure is what we advertise; the number that matters is what a caller bears. **Every cost
  argument in §§ 3–4 depends on this and should not be settled before it is measured.**
- **Q1.** Do our clients support MCP **resources**, and do they fetch them lazily?
- **Q2.** Can a server influence client-side tool deferral at all, or is it entirely the
  client's choice?
- **Q3.** What is the real-world failure rate this is fixing? We have exactly one observed
  incident (`type_tags`). Is there instrumentation — now that v3.2.0 logs every rejection at
  WARNING — to size the problem before investing in the full scheme?
- **Q4 (gates workstream D).** Does each client render `_meta` — and `annotations` — to the
  *model*, or only consume them internally? Measure across Claude Desktop, Claude Code, a
  headless scheduled worker, and the sandboxed board artifact. If none surface `_meta` to the
  model, R7's description-line half is not belt-and-braces, it is the entire mechanism.

---

## 8. Constraints — non-negotiable unless deliberately overturned

1. **`ErrorCode` is ADDITIVE-ONLY.** A shipped code is never renamed or removed. Note that
   because `ErrorBody.code` is an inlined enum, **any registry addition churns all 99 tool
   fingerprints** — structural and expected, not a signal that 99 tools changed.
2. **No advertised `anyOf` on parameters** (§ B4). Zero union-advertising params remain and a
   test pins it.
3. **The six documentation surfaces** (CONTRIBUTING § 3) are the floor, not a menu.
4. **The membrane holds**: server enforces mechanical shape; the plugin owns canonical
   vocabulary; the server stays vault-free.
5. **Documentation lockstep** (§ 9) and the **test-suite inventory** in `CLAUDE.md` are updated
   with any change.
6. **Additive and restart-activated** wherever possible; name any activation-ordering hazard
   explicitly (new tags must be provisioned *before* the version is activated).
7. **Prefer `_meta` to `annotations` for additive metadata** — the former is fingerprint-neutral,
   the latter churns all 99 fingerprints. Not a prohibition, but a cost to be paid knowingly.
8. **Naming stays as it is.** The v3.0.0/v3.1.0 rename is two releases old and `make naming
   --strict` is part of `make lint`. Workstream D must *augment* naming, never propose renaming
   tools to encode a taxonomy.

---

## 9. Deliverables from the session

1. A decision on **A (progressive disclosure)** — the index, the lazy-load mechanism, and
   whether `outputSchema` stays fully advertised.
2. A decision on **B (rejections + combinations)** — the single guided-rejection shape, and
   the stated rule for *unrepresentable vs rejected*.
3. A decision on **C (co-design)** — specifically C4 (is prose lockstep acceptable without CI)
   and C5 (do BFF tools and artifacts get a version handshake).
4. A decision on **D (taxonomy)** — the axes and their vocabularies, the delivery mechanism
   (gated on Q4), and what the gtd skill is instructed to do with it.
5. A **single-source map**: for each fact about a tool (purpose, parameters, combinations,
   errors, examples, taxonomy), name the one place it lives and how every other surface is
   derived from or asserted against it.
6. A staged implementation plan, additive, each stage independently shippable and restartable —
   this surface is 99 tools across two repos and one live board, and Wave 3 already
   demonstrated what a big-bang cutover costs when a rendered artifact is a caller no grep can
   see.

---

## 10. What "good" looks like

A caller that has never seen this server should be able to:

1. pick the right tool from ~2k tokens of index, not 174k;
2. retrieve that tool's full contract on demand, in one call;
3. call it correctly first time from what it retrieved;
4. and — when it still gets it wrong, including a wrong *combination* — receive a rejection
   that contains enough to retry correctly **without a further lookup**, with nothing written.

And a maintainer should be able to change one fact in one place and have every surface —
schema, docstring, rejection, help payload, plugin reference, artifact — either follow
automatically or **fail a test**.

---

*Source of truth for current behaviour: `CLAUDE.md` (architecture), `CONTRIBUTING.md` §§ 3, 5,
7, 9, 10 (conventions), `mcp-tool-documentation-standard.md` (family standard). All figures
measured 2026-07-26 against rtm-mcp v3.2.0 (99 tools) and claude-plugins/plugins/gtd.*
