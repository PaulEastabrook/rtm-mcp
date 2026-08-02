# RTM MCP Server - Developer Documentation

> **Conventions & standards live in [CONTRIBUTING.md](CONTRIBUTING.md)** — the canonical source
> for coding, testing, and documentation rules (source style, tool patterns, the enriched
> docstring shape, the documentation-lockstep rule, versioning, and the add-a-tool checklist).
> This file owns **architecture, RTM API quirks, and per-feature deep-dives**.

## Architecture Overview

```
src/rtm_mcp/
├── server.py           # FastMCP server, lifespan, tool registration, middleware registration, logging (stderr + the rotating file sink that survives a /dev/null fd 2)
├── middleware.py       # Call-boundary gate — rejects a tool call carrying any parameter the tool does not define (one on_call_tool middleware over all 99 tools; the valid set IS the tool's advertised parameters["properties"])
├── client.py           # Async RTM API client with signing, retry, settings caching (timezone + default list)
├── config.py           # Pydantic settings (env + file + rate limits + connection retry)
├── parsers.py          # RTM response parsing, formatting, normalization, analysis
├── error_codes.py      # Canonical ErrorCode registry (typed error vocabulary) + RTM numeric→code map; ADDITIVE-ONLY leaf module
├── receipt.py          # The teaching receipt (v4.0.0) — the three fields every governed gtd_* write returns: not_applied[] (requested but NOT written, zero-not-absent), guidance (the next step when the outcome was not a clean success), advisory (the call carried none of its optional value-bearing params). Pure leaf (imports only error_codes); attached centrally by tools/gtd.py::_tool, never at 25 call sites
├── response_builder.py # MCP response envelope + structured error constructors + transaction recording + tool behaviour-annotation constants
├── models.py           # Schema-only Pydantic output-schema models (per-tool @mcp.tool(output_schema=...)); not used at runtime
├── lookup.py           # Shared name-to-ID resolution for tasks and lists
├── strict_tags.py      # Write gate 1 — strict-tag mode: existence gate for tag writes (on by default)
├── note_types.py       # The FOUR note-type vocabularies, one leaf home: CATALOGUE (registered canonical, codifies note-shape-catalogue § 2), SURFACE (legacy read-recognition, deliberately NOT writable), RESPONSE, BARE_MARKER — plus the DERIVED WRITE_AUTHORISED_NOTE_TYPES the vocabulary gate consults
├── note_shape.py       # Write gate 2 — note-title grammar, vocabulary AND (v6.4.0) per-TYPE contract gate (RTM_STRICT_NOTES; off/warn/shape/vocabulary, default VOCABULARY since v5.2.0)
├── list_targets.py     # Write gate 3 — list-target mechanical writability gate (RTM_STRICT_LIST_TARGETS, default ON since v5.1.0)
├── filing_gate.py      # Write gate 4 — artefact-resolution gate on gtd_note_attach_output (RTM_STRICT_FILING, default REJECT since v6.4.0). Refuses a filing_path that resolves to no artefact / no companion under the AI Memory vault; INERT with no vault mounted (degrade, never reject). `source_action` is reported, never required (0% populated live)
├── filing_gaps.py      # v6.4.0 read — the RTM↔vault reconciliation behind gtd_note_filing_gaps: six finding classes, and an absent vault produces a PARTIAL result (classes named in gaps[], counts null never 0)
├── note_report.py      # v6.4.0 read — note-shape hygiene (gtd_note_report), running the WRITE GATE'S OWN check_title/check_type/check_contract so audit and gate cannot drift; the free-text rule (no date prefix = Paul's own, never a finding) is normative here
├── detectors.py        # Phase 0 reads — pure faithful ports of the 9 GTD *-candidates.ms / health-check.ms detectors (verbatim filter passthrough + identical client-side logic, typed rows); backs gtd_*_candidates / gtd_cluster_candidates / gtd_health_report
├── gtd_writes.py       # Phase 1 writes — pure grammar for the 4 everyday governed write tools: the SEVEN Tier-1 server-owned vocabularies (D1), structural tag materialisation, the hard-gated per-kind Definition of Ready, note title AND body CONSTRUCTION (`format_note_title` + the v6.0.0 `assemble_note_body` — block order is emitted, never parsed), and the validators (backs gtd_item_create / gtd_note_add / gtd_inbox_capture / gtd_item_transition) + the Phase 2 grammar: completion events (progression-fanout EVENT names, returned as data — never tags), the review→approved transition, the DEPENDS-ON note builder, the Inbox_Stuff close body (v6.3.0: an optional caller `narrative` ABOVE the derived-items list — prose first, machine-read tail last; blank writes no block), and a faithful series_guard port (priority/estimate are taskseries-level; collapse to one write per series on the nearest-active occurrence, surface divergence) + the Phase 3 process-op grammars (INBOX_VERBS / CHASE_VERDICTS / CONSOLIDATE_MOVES, the PROCESS_BATCH_CAP bounded-input split, and the three whole-set validators). NOTE: RTM has NO multi-task write endpoint (measured 2026-07-23 — comma-separated ids and filter-based writes are both rejected), so the process ops are O(N) rate-limited calls; the official server's rtm_batch_* resolve and loop internally
├── contribution.py     # Wave 1b — the CONTRIB state machine (gtd_contribution_transition): six states (one open, three JUDGED, two INVALIDATED), the State:-line rewrite, and the CONTRIB-UPDATE grammar. The judged/invalidated split is the acceptance-rate denominator
├── surface_queue.py    # Wave 1 read — the AI-surface eligibility queue (gtd_surface_queue): frontmatter parse + the two derived signals (auto_close_due, response_detected). NOT a port — built to ai-surface-scan.md §§ 3b/3c
├── engine_report.py    # Wave 1 read — proactive-contribution engine telemetry (gtd_engine_report). Creation-cohort windows; withdrawn/underivable metrics NAMED in gaps[], never zeroed
├── tag_report.py       # Wave 1 read — tag-taxonomy hygiene (gtd_tag_report): the CODIFIED canonical taxonomy + three-way classification (canonical/family/non_canonical) + minimum-tag-set gaps
├── gtd_reports.py      # Wave 1 reads — five small portfolio/hygiene projections (gtd_dependency_gaps / gtd_review_report / gtd_item_stale / gtd_workload_report / gtd_focus_index)
├── gtd_reads.py        # Phase 0 reads — pure builders for the 4 collection/context tools (gtd_query perspectives, gtd_inbox_state, gtd_waiting_for_queue, gtd_item_context STATE-first note-reading-protocol bundle); codify gtd read semantics, not .ms ports
├── project_plan.py     # Pure project-plan-seed/3.1 envelope builder (backs gtd_project_plan)
├── order_note.py       # Pure ORDER-note contract (order-note/1): make/parse/resolve/from_envelope — durable manual plan-order intent (DC-4)
├── tmpl_child.py       # Pure TMPL-CHILD token WRITE grammar (tmpl-child/1): slug gen + note make + DEPENDS-ON token-line author + idempotent plan_backfill (backs gtd_item_stamp_tokens; repeating-templated-project Wave B stamping)
├── project_index.py    # Pure active-#project portfolio roll-up + counts + foci + action index (backs gtd_project_index)
├── engage_seed.py      # Pure overdue + soft-parked set builder (backs gtd_engage_seed) — dated items at/after their date with server-derived flags (kind/has_deadline (=has_due_time)/blocked (thin plan-graph)/postponed/suggested/redacted); curtain-not-vault (emits redacted, never suppresses)
├── engage_commit.py    # Pure server-side engage verdict grammar (backs gtd_engage_commit) — the codified twin of gtd's validate-engage-verdict.py (enum + per-kind legality + deadline/blocked guards + closest-legal suggestion + date-phrase resolution + strict-tag input); the ACL's legality core
├── canvas_seed.py      # Pure envelope→canvas-seed mapper (port of gtd build-canvas-seed.py)
├── plan_graph.py       # Pure deterministic plan-graph engine (port of gtd plan_graph.py)
├── canvas_overlay.py   # Pure seed+graph merge (apply_graph) + lean transform (lean_seed)
├── canvas_commit.py    # Pure closed tag-mapping + commit validators (backs gtd_canvas_commit)
├── canvas_create.py    # Pure create-side tags (project/life/finalise) + validators (backs gtd_project_create)
├── gtd_chat.py         # Pure CHAT-note grammar (title/mode-footer/turn/thread parsing) + turn attachments (FILING/LINK parse + correlation; project-scope descendant scan) + drain-signal tags + cross-project inflight roll-up (backs gtd_chat_post/gtd_chat_thread/gtd_chat_inflight)
├── companion.py        # Read-only vault locate (cross-platform) + companion .md/.yaml reader → canvas file.meta
├── tool_help.py        # Tier-2 affordance surface — the pure index/contract PROJECTIONS behind rtm_tool_help (derived from the live advertised schema; only combination rules / examples / chain edges / the BFF set are authored)
├── guided_rejection.py # Tier-3 affordance surface — the ONE guided-rejection shape (purpose + typed params + nearest-name guess + violated rule + help pointer), converging strict_tags.guided_error and engage_commit.validate
├── tool_params.py      # Shared MCP complex-param coercion + clean-schema Annotated types
├── urls.py             # Web UI URL construction + task hierarchy walking
├── rate_limiter.py     # Token bucket rate limiter + diagnostics stats
├── exceptions.py       # RTMError hierarchy + ERROR_GUIDANCE recovery hints
├── tools/
│   ├── tasks.py        # Task CRUD + metadata + hierarchy (19 tools)
│   ├── lists.py        # List management (7 tools)
│   ├── notes.py        # Note operations (4 tools)
│   ├── utilities.py    # Tags, locations, settings, undo, timeline, diagnostics, URLs (14 tools)
│   ├── help.py         # rtm_tool_help — the affordance help surface, read-only + OFFLINE (1 tool)
│   └── gtd.py          # GTD domain compositions — gtd_project_plan/canvas/index, apply_canvas_commit, create_project, stamp_tokens, chat_post/thread/inflight, set_redaction, engage_seed, apply_engage_commit + Phase 0 typed reads (reassessment/unblock/decision/deliverable/research/calendar_prep/capture_candidates, topic_clusters, health_check, query, inbox_state, waiting_for_queue, context) (25 tools)
└── scripts/
    └── setup_auth.py   # Interactive auth setup CLI
```

### Module Responsibilities

| Module | Single Responsibility |
|--------|----------------------|
| `client.py` | HTTP transport: signing, connection pooling, rate limiting, retry, settings caching (timezone + default list) |
| `parsers.py` | Translate RTM's quirky API responses into clean Python dicts |
| `error_codes.py` | The **canonical typed-code registry** (v2.0.0) — `ErrorCode` (every machine-branchable **outcome**: failures and, since v4.0.0, the receipt's non-failure results, grouped transport/resolution/validation/state/governance/**outcome**/commit/write), `RTM_CODE_MAP` (RTM numeric → semantic code) and `code_for_rtm`. **ADDITIVE-ONLY**: a shipped code is never renamed or removed. The name says "error" for history, not for scope — v4.1.0 corrected the *label* rather than the contents, because **the discriminator is the FIELD, not the registry**: a code in `not_applied[].reason` is an outcome, a code in `error.code` is a failure. Splitting would double what has to be maintained for a distinction the envelope already makes structurally, and force every consumer to know which registry it is reading. A leaf module (imports nothing from the package), so the four `rejected[].reason` / `not_applied[].reason` vocabularies source their members from it without an import cycle — one vocabulary, four scoped views |
| `middleware.py` | The **call-boundary gate**: `RejectUnknownParameters`, one `on_call_tool` middleware refusing any tool call that carries a parameter the tool does not define. Zero API calls, no envelope — it raises `ToolError` before the tool body runs, matching the protocol-level shape the existing missing-required-parameter rejection already uses (deliberately NOT an `ErrorCode`, which would churn every fingerprint for a failure that is not a tool's own). The valid-name set is read live from the tool's advertised `parameters["properties"]`, so it cannot drift from what clients are told |
| `tool_help.py` | The **tier-2 affordance surface** — pure (no-IO) projections behind `rtm_tool_help`: `build_index` (the whole-server purpose table, the cheap "which tool?" answer) and `build_contract` (one tool's full contract). **Defined by subtraction**: it carries only what the other surfaces cannot — the combination rules JSON Schema cannot express (the family bans advertised `anyOf`), worked examples, the multi-case `Returns` in prose, the `annotations` facts rendered as prose (this client never shows them to the model), the typed-error catalogue with recovery, and the mechanical chain edges. Almost everything is **derived** from the live advertised schema, so help cannot drift; only `COMBINATION_RULES` / `EXAMPLES` / `CHAIN` / `BFF_TOOLS` are authored. The error catalogue is derived from the codes the description NAMES — complete by construction, because `TestAdvertisedErrorContract` already asserts a description names every code its tool can reach. `RECOVERY` covers all 50 `ErrorCode` members and is written for the caller's actual context (a governed-domain failure names the mechanical fix AND points at the wrapping skill that owns the judgement — a pointer only, never a copy of gtd's vocabulary) |
| `guided_rejection.py` | The **tier-3 affordance surface** — one rejection shape, three producers. `build_rejection` assembles the teaching payload (tool purpose, the typed parameter table projected from the tool's own `inputSchema`, a nearest-name guess, the violated combination rule, the help pointer) and `render_prose` renders it for the protocol-level `ToolError` path. Converges the two pre-existing shapes (`strict_tags.guided_error`'s `how_to_proceed`, `engage_commit.validate`'s closest-legal suggestion) rather than adding a third. A rejection is the ONE moment the server *makes* a caller read something, which is why the teaching lives here |
| `receipt.py` | The **teaching receipt** — `not_applied[]` / `guidance` / `advisory` on every governed `gtd_*` write. Exists because tier 3 cannot fire: the hosted client deletes an undeclared argument before this server sees it, so a misspelt *optional modifier* produces a **silent partial write** and there is no anomaly to detect — you cannot throw on what you were never told. So it attacks the other end and makes the OUTCOME unmissable. `not_applied_entry` (one requested op that wrote nothing, `reason` from `RECEIPT_REASONS` — the fourth scoped view of the `ErrorCode` registry, and **outcomes not failures**); `build_advisory` (fires only when EVERY optional facet is absent — reasoning about *absence* is the one thing still observable after a strip); `is_facet` (a boolean is a mode switch, not data — a stripped control flag gets the call rejected or changes documented default behaviour, so it can never be the silently-lost value; measured, this took two tools from firing on 100% of legitimate calls to 0%); `build_guidance` (v4.1.0: emitted ONLY on the partial-write and `not_applied` branches — the trial measured **56 of 62** emissions as a restatement of the `rejected[]` array beside it, and a field that repeats its neighbour trains a caller to skip it; partial-write still outranks `not_applied`); `detect_leaked_markup` + `build_markup_advisory` (v6.1.0 — the tool-scoped leaked-tool-call-markup predicate: a closing tag naming a parameter THIS tool declares; 7/7 true positives and 0 false positives over 13,435 live calls, and it OUTRANKS the bare-call advisory because it explains it); `attach` (guarantees the keys, preserves what a tool body populated, and returns an **error** envelope untouched — `data.error` is the union discriminator). Pure leaf, no async, no client import — all three pinned by test, because the receipt must never become a gate |
| `response_builder.py` | Wrap tool output in the standard MCP response envelope; build every structured error (`build_error` / `error_from_exception`); hold the three tool behaviour-annotation constants (`READ_ONLY_`/`ADDITIVE_WRITE_`/`DESTRUCTIVE_WRITE_ANNOTATIONS`) |
| `models.py` | Schema-only Pydantic models generating each tool's MCP `outputSchema` (attached via `@mcp.tool(output_schema=...)`); **not used at runtime** — tools still return the `response_builder` dict, FastMCP advertises the schema without validating. `data` is always a `success \| ErrorData` union — since v2.0.0 `ErrorData.error` is the nested `ErrorBody` (`{code, message, rtm_code, details}`, `extra="forbid"`), not a prose string; the six-surface tool-documentation standard (CONTRIBUTING § 3) |
| `lookup.py` | Resolve human-readable names (task name, list name) to RTM IDs |
| `strict_tags.py` | Strict-tag mode policy: normalize/split tags, extract SmartAdd `#tokens`, and gate tag writes against the account's existing tag set |
| `project_plan.py` | Pure (no IO) reconstruction of the `project-plan-seed/3.1` envelope from parsed tasks — byte-compatible with the gtd plugin's `rtm_fetch.py` reference. Also the home of the `REDACTED_TAG` constant and emits the additive `header.project.redacted` flag + the additive per-note `id` (every envelope note object carries the RTM note id — the ORDER-note resolver tie-breaks on it) + the additive `3.1` repeating-templated-project signals `is_repeating`/`taskseries_id` on every row and `header.project` (True when the task's own parent taskseries recurs — an `rrule`; the gtd `series_guard` detection gate reads them; repeating-templated-project Wave B) + the additive `3.1` resolve-references token surfacing `template_child_id` on every row (from a child's `tmpl-child/1` TMPL-CHILD note; `""` for a one-off) and token-space `deps` (a DEPENDS-ON note's `Template-child-id:` line makes the dep the upstream token, else the raw task_id) — both feed `plan_graph`'s `token_map`/`_resolve_ref` so token-authored deps/pins resolve across recurrence; repeating-templated-project Wave B slice 2) |
| `order_note.py` | Pure (no IO) ORDER-note contract (`order-note/1`) — byte-compatible port of the gtd plugin's `order_note.py` (`make`/`parse`/`resolve`/`from_envelope`; the CLI shim is dropped). The ORDER note on the RTM **project task** is the single durable record of manual plan-order intent (DC-4); the body is strict self-verifying JSON (`count` + `sha256` fail closed — an invalid note is IGNORED, never an error), resolution is deterministic latest-valid-wins (`at` desc → note id desc → checksum desc). Writer: `gtd_canvas_commit` (`source: "board-commit"`); readers: `gtd_project_canvas` (the thin plan-graph `manual_order` bias) and gtd's enriched overlay refresh — one grammar, both membrane sides |
| `tmpl_child.py` | Pure (no IO) TMPL-CHILD token **write** grammar (`tmpl-child/1`) backing `gtd_item_stamp_tokens` (repeating-templated-project Wave B stamping) — the write twin of the read-side surfacing in `project_plan._extract_deps_and_files` / resolution in `plan_graph._resolve_ref`. `new_slug` (8 lowercase hex, `secrets.token_hex(4)`), `make_tmpl_child_note` (title `YYYY-MM-DD — TMPL-CHILD — <slug>` + strict `{"schema":"tmpl-child/1","template_child_id":"<slug>"}` JSON body), the DEPENDS-ON re-author helpers (`is_active_depends_on`/`depends_on_upstream_id`/`has_token_line`/`add_token_line` — appends the additive `Template-child-id: "<slug>"` line, splitting the note into `(note_title, note_text)` per RTM's `body = title\ntext` storage reality so `notes.edit` round-trips), and `plan_backfill` (the idempotent planner: assigns a fresh unique slug to each unstamped open child, keeps existing tokens, and authors token-space dep lines when the upstream slug resolves among siblings; `slug_gen` injectable for tests). Since RTM copies a child's notes verbatim onto each new occurrence, one stamp propagates across recurrence — so a second run is a no-op. One-off projects are never stamped (byte-unchanged read path) |
| `project_index.py` | Pure (no IO) active-`#project` portfolio roll-up backing `gtd_project_index` — `build_index` (per-project rows: selection (incomplete, `#project`, not `#test`; `#hold`/`#someday` policy), life + parent Area-of-Focus resolution, and counts `open_count`/`blocked_count`/`next_tickle` + AI-progressible tallies `ai_quick`/`ai_now`/`ai_later` (canvas `quick_ready` + `map_prog`) + conversation counts `chat_count`/`chat_review_count` (`#ai_chat` / `#ai_output_review_needed`) + engage-filter count `waiting_count` (`#waiting_for`) via `project_plan.build_envelope` + the thin `plan_graph.build_graph`), `build_foci` (every `#focus` area incl. project-less ones), and `build_actions` (every incomplete child under an active project — with `type` (canvas `r.k`) + `due`/`priority`/`blocked` urgency signal for the What's-hot band and find-result glyphs, plus the engage-lens funnel fields `estimate` (minutes) / `contexts` / `energy` / `exec` (the single-value read of the same classifier behind the project `ai_*` tallies) — for cockpit search + the engage lens). Project rows, action rows, and foci rows all carry the `redacted` viewing-curtain flag (`#redacted`); on an **action** it is server-derived and **cascades** (own tag OR redacted project/focus) and a shielded action's engage fields are suppressed (null/`[]`). Vault-free |
| `canvas_seed.py` | Pure mapper: `project-plan-seed/3` envelope → canvas `{mode, frame, seed}` shape — byte-compatible port of the gtd plugin's `build-canvas-seed.py`. `map_redacted` emits the per-item + `frame.redacted` viewing-curtain flag (additive) |
| `plan_graph.py` | Pure deterministic plan-graph engine (DAG, blocked/quick judgement, tiered timeline order with the within-tier MoSCoW band tie-break `Must→Should→Could→untriaged-last` from the RTM priority field, cycles, fingerprint) — byte-compatible port of the gtd plugin's `plan_graph.py`. Resolve-references (repeating templated projects): builds `token_map` (`template_child_id`→current id) from the rows and `_resolve_ref` maps each DEPENDS-ON dep + ORDER-pin entry from token-space to the current occurrence's re-keyed id (a current id stays; a stale-id-without-token is dropped by the `id_set` guard). Empty for a one-off project → byte-identical (the one-off parity golden proves it; the series golden pins the token path) |
| `canvas_overlay.py` | Pure merge of the plan-graph overlay onto the seed (`apply_graph`) + the lean/inline transform (`lean_seed`) — port of the gtd plugin's `build_canvas.py` helpers |
| `canvas_commit.py` | Pure closed canonical classifier→tag mapping + commit validators (`validate_commit`, `collect_commit_tags`) for `gtd_canvas_commit`. `validate_commit` carves `project_id` out of the child-membership gate for the entity-verb maps (`edits`/`notes`/`completes`/`removes`) only (`execute`/`order` stay child-only); `VALID_SCOPES` is the audit-note placement label set |
| `canvas_create.py` | Pure create-side helpers for `gtd_project_create`: the project's own tags (`project_tags` — life + `#project` + `#ai_conversation` + the `#ai_project_needs_finalise` mark), `collect_create_tags`, `validate_create`, and `item_id` (in-draft id ↔ dep mapping). Imports the shared classifier→tag taxonomy from `canvas_commit` — no duplicate taxonomy |
| `gtd_chat.py` | Pure (no IO) helpers for the in-board AI conversation surface (the `CHAT` note class) backing `gtd_chat_post`/`gtd_chat_thread`/`gtd_chat_inflight`: the title grammar (`format_chat_title`/`parse_chat_title` — `YYYY-MM-DD HH:MM — CHAT — <role> — <scope>`), the `me`-turn posture **mode** body-footer round-trip (`append_mode_footer`/`parse_body`), `parse_turn`/`build_thread` (oldest-first, non-CHAT excluded, `since` filter), the **turn attachments** (`parse_filings`/`parse_output_note`/`parse_links`/`_attach_filings` — server-derived `files[]` from OUTPUT-note `FILING:` lines time-correlated to `ai` turns + `links[]` from `LINK:` trailer lines; note-shape-catalogue § 3 / chat-reply-style § 2 mirrored server-side; for a `#project` target the scan also covers the descendant tree via `project_descendants`, entries carrying `item_id`/`item_name` provenance), `build_inflight` (the cross-project live-band roll-up — incomplete `#ai_chat` items with status/scope/nearest-`#project`-ancestor/last-activity), `local_stamp` (tz-localised wall-clock), and the account-provisioned status/drain-signal tag constants (`AI_CHAT_REQUESTED`/`AI_CHAT`/`AI_OUTPUT_REVIEW_NEEDED`). gtd owns the canonical grammar; this mirrors it server-side. Vault-free |
| `engage_seed.py` | Pure (no IO) overdue + soft-parked set builder backing `gtd_engage_seed` — `build_engage_seed(parsed, *, today, timezone)` selects incomplete dated items on-or-before today (NOT `#test`, NOT `#someday`; all kinds carrying a date) and emits per-row server-derived flags: `kind` (from the workflow-state tag; "calendar_entry"/"project" not the canvas glyph), `has_deadline` (= the RTM `has_due_time` primitive — a timed due is the GTD hard landscape), `blocked` (the THIN `plan_graph.build_graph` judgement, an open DEPENDS-ON upstream in the item's project — the same judgement `gtd_project_index` emits), `postponed` (the bump-fatigue signal), `suggested` (the deterministic pre-triage verdict via `engage_commit.suggest_verdict`), and `redacted` (own `#redacted` OR a cascade from a redacted `#project`/`#focus` ancestor). CURTAIN-NOT-VAULT: emits the `redacted` flag, NEVER nulls/withholds a field on it (the guard test pins it). Vault-free |
| `engage_commit.py` | Pure (no IO) server-side **engage verdict grammar** backing `gtd_engage_commit` — the codified twin of the gtd plugin's `scripts/validate-engage-verdict.py`. Both conform to the SAME source of truth (`plugins/gtd/skills/gtd/references/engage-verdict-grammar.md` §§ 1-4) but this repo is standalone (cannot read the marketplace markdown), so the enum (`VERDICT_FAMILY`), per-kind base legality (`BASE_LEGALITY`), and the two flag guards (deadline § 3.1 → `DEADLINE_LEGAL`; blocked § 3.2 → resurface-only-when-blocked) are codified as Python constants — exactly as `canvas_commit.py` holds the tag taxonomy (codification before validation; a verdict is a governed extension, never a local invention). Posture HARD-FAIL: `validate` returns `{ok, results, errors}` with a closest-legal `suggestion`; the tool writes nothing if any item is rejected. Plus `base_verdict`/`verdict_arg` (strip a `:<arg>` suffix), `suggest_verdict` (the seed's pre-triage — deadline→keep, blocked→resurface, waiting-for→nudge, soft action→next_actions), `date_phrase_for` (the parse_time phrase for the date verdicts — today/bump→"in N days"/defer_start), and `collect_engage_tags` (the strict-tag existence-gate input — all existing gtd tags, no new tag). Also the PROGRESS-steer grammar (the per-item `note`, Tier 1): `STEER_VERBS`=`(draft, do_now, nudge)`, `sanitize_steer` (ACL: non-string→drop+warn, control chars/whitespace collapsed, `STEER_MAX_LEN`=500 truncate+warn — a malformed steer never fails a legal renegotiation), `make_steer_note` (title `YYYY-MM-DD HH:MM — STEER — <verb>`, PURE body — the drafting-path instruction, no marker pollution), `steer_note_text` (the idempotency probe: an identical STEER note already on the item is skipped). The legality core of the Anti-Corruption Layer |
| `companion.py` | The vault file-IO seam: locate the read-only AI Memory vault root (cross-platform; `AI_MEMORY_DIR`/host default + `memory/_index.md` marker), resolve each filed artefact's companion (`.md`/`.yaml`) frontmatter, and enrich `gtd_project_canvas` file objects with a `meta` block. Mirrors file-store's `query_outputs.py` by contract (stdlib-only). Graceful: every IO failure → no `meta`, never raises |
| `tool_params.py` | Shared coercion for complex (array/object) MCP params: a `coerce_json` `BeforeValidator` + `Annotated` types presenting a clean single-typed JSON schema (no `anyOf`/null) so clients that stringify union-typed params still interoperate. Also the `coerced_*_schema(...)` builders (str-array / obj-array / object) that return the `WithJsonSchema` dict with a per-param **description** (and optional nested enum) baked in — used inline so a coercion param carries surface-2 documentation (a sibling `Field(description=…)` is dropped by `WithJsonSchema`) |
| `note_types.py` | The **four note-type vocabularies**, one leaf home (v5.2.0). `CATALOGUE_NOTE_TYPES` (registered canonical — the codification of gtd's `note-shape-catalogue.md` § 2; the markdown stays the authority), `SURFACE_NOTE_TYPES` (**legacy read-recognition, deliberately NOT writable** — `Q`/`AR`/`ACTIVITY_REPORT`/the single letters stay readable so existing notes classify, and stop being writable so no new one is minted), `RESPONSE_NOTE_TYPES`, `BARE_MARKER_NOTE_TYPES`, and the **derived** `WRITE_AUTHORISED_NOTE_TYPES` the gate consults. Moved out of `surface_queue.py` because `note_shape` needs the composition and cannot import a high-level read builder without inverting the layering — and because the move closed a measured drift (the five AI-surface body types registered in the markdown 2026-07-25, absent from the server's catalogue for a week). Derived-not-hand-listed is asserted against the SOURCE, since value-equality passes just as happily against a hand-typed duplicate |
| `note_shape.py` | ⚠ **Lockstep trap (v6.0.1, and it applies again at v6.4.0):** this gate is wired into `add_note` / `edit_note`, so **their descriptions are part of its contract** — v5.2.0 changed the gate and left both saying "only the shape is checked", false in the tier-1 surface for a release. When a gate's behaviour changes, grep for the tools it is WIRED INTO, not just the module it lives in. Write gate 2 — the **note-title grammar AND vocabulary** gate (`RTM_STRICT_NOTES`, an escalation: `vocabulary` **default since v5.2.0** — grammar AND a registered TYPE / `shape` grammar only, the v5.1.0 behaviour byte-for-byte and the partial rollback / `warn` log-only / `off` inert). `check_title` judges `YYYY-MM-DD [HH:MM] — TYPE — summary` (real calendar date, both em/en-dash separators, well-formed non-empty TYPE token, non-empty summary); `effective_title` resolves the title RTM actually stores (`note_title`, else the first line of `note_text` — RTM has no title field); `enforce_note_shape` is the sync, zero-API-call gate. **Shape AND vocabulary since v5.2.0** — `check_type` judges the TYPE against `note_types.WRITE_AUTHORISED_NOTE_TYPES`; the shape-vs-vocabulary verdict rides in `error.details.rejected_by`, with NO new `ErrorCode` (a synonym would churn all 100 fingerprints for a distinction the details carry). The reversal was measured, not assumed: a full-estate census on 2026-07-31 found ~40 off-vocabulary tokens across 114 notes over five months, because the client-side validator only runs when a caller remembers it — a gate that can be forgotten is not a gate. **Authorship did not move**: gtd's catalogue is still the authority and this server codifies it, so a new type goes in the markdown first. Wired into `add_note` (always) and `edit_note` (**title-changing path only** — a body-only edit of a legacy note is never blocked) — and **nowhere else**: every `gtd_*` note write calls `rtm.tasks.notes.add` directly, which is why four of them legitimately write a bare marker title (`DEPENDS-ON` / `INCEPTION` / `REDACTION` / `TMPL-STAMP`) this grammar would reject. **Tier 3 since v6.4.0 — the per-TYPE contract** (`check_contract`): `CHAT` is judged by `gtd_chat.parse_chat_title` and `ORDER` by `order_note.parse`, the parsers the server ALREADY holds — which is the whole admission test for a tier-3 check (ten lines over proven code, not a second grammar to keep in step). It runs in `vocabulary` mode ONLY, so `shape` stays a byte-for-byte v5.1.0 rollback step; the verdict rides in `error.details.rejected_by` (`chat_title` / `order_contract`) with **no new `ErrorCode`**. The ORDER check is **body-dependent and therefore skipped on a title-only edit** — `edit_note` passes an empty body on its title-changing path, and judging an absent body would refuse every legitimate ORDER title correction. Also home of the **free-text rule** (normative): a note with no date prefix is Paul's own, typed in the RTM app, and is never a violation — since v6.4.0 `note_report.py` is the consumer that rule was written for |
| `list_targets.py` | Write gate 3 — the **mechanical list-target writability** gate (`RTM_STRICT_LIST_TARGETS`, **default ON since v5.1.0**). `check_target` reads the `smart` / `locked` booleans RTM's own `rtm.lists.getList` already returns → `SMART_LIST_TARGET` / `LOCKED_SYSTEM_LIST` (both codes predate the gate — reused, never re-spelled). Sync, zero-API-call (the resolver already fetched the list). **Mechanical writability only** — canonical list policy (Inbox_Stuff as sole capture point, Processed as gtd-internal) stays in gtd's `list-catalogue.md` / `validate-list-target.py`. Wired into `add_task` + `move_task`, judging **caller-named targets only** (`add_task`'s default-list fallback is deliberately ungated) |
| `filing_gate.py` | Write gate 4 — the **artefact-resolution** gate (`RTM_STRICT_FILING`, default `reject` since v6.4.0). Filing an artefact and journalling it were two unbound acts, so the second was forgettable — **97 of 126 filed artefacts carried no OUTPUT note** (measured 2026-08-01). `check_filing` refuses a `filing_path` that resolves to nothing (`artefact_missing`) or to an untracked file (`companion_missing`) — ONE new `ErrorCode` (`filing_unresolved`) with the verdict in `error.details.rejected_by`, the v5.2.0 precedent. **An unmounted vault DEGRADES, never rejects**: absence of a mount is absence of evidence, the two cases share no code path, and each is pinned separately (a single vault-less fixture would pass a gate that had collapsed them). `check_source_action` is advisory-only — the join key is 0% populated live, so requiring it would refuse every legitimate call; it is reported on the receipt and counted by `gtd_note_filing_gaps` until agent-memory's backfill lands. Read-only w.r.t. the vault: this extends the existing `companion.py` seam and must never widen it |
| `filing_gaps.py` | The RTM↔vault **reconciliation** behind `gtd_note_filing_gaps`. This server is the only process that can see both sides (agent-memory-mcp holds no RTM token; RTM holds no vault), which is why the join is computed here rather than by an agent eyeing two tool outputs. Six classes — `linked_missing` / `filed_unlinked` / `companion_missing` / `join_unpopulated` / `prose_path` / `register_defect` — each with its measured 2026-08-01 baseline in the docstring. `prose_path` **detects, never parses**: ten mutually incompatible dialects were counted, so the note is reported for a human. **An absent vault produces a PARTIAL result** — `VAULT_DEPENDENT` classes are named in `gaps[]` and emitted as `null`, never `0` (the `gtd_engine_report` precedent); `walk_artefacts` returning `None` vs `[]` is what carries that distinction |
| `note_report.py` | Note-shape hygiene as a read (`gtd_note_report`), retiring the surviving half of gtd's `validate-note.py` — whose agent shelled out **one subprocess per note**, 12 of its 16 checks already redundant because the server *constructs* those shapes. **The checks are the write gate's own functions, by object identity** (`note_shape.check_title` / `check_type` / `check_contract`), so audit and gate cannot disagree about what conformant means; a test asserts the identity. The **free-text rule is normative and load-bearing**: no date prefix → Paul typed it in the RTM app, counted in `free_text_count` and NEVER a finding; date-prefixed with a bad TYPE → agent-written, and that IS the finding. Inverting it buries every real finding under his prose |
| `detectors.py` | Pure (no-IO) **faithful ports** of the 9 GTD MilkScript detectors (`reassessment`/`unblock`/`decision`/`deliverable`/`research`/`calendar-prep`/`capture-candidates.ms`, `topic-cluster-detector.ms`, `health-check.ms`). Document-what-is: each `.ms` `rtm.getTasks(filter)` is passed **verbatim** to `rtm.tasks.getList(filter=…)` by the tool layer, and this module replays the identical client-side filter/skip/sort logic (regex pattern sets, tag skips, staleness/horizon thresholds, dedup precedence, source classes) as **typed rows** (the `.ms` printed text). Deterministic enrichments over the reference: `deep_link` (`project_plan._permalink`), `kind` (`canvas_seed.map_kind`), `priority` band. `health-check` is the one intended divergence — one broad `status:incomplete` read + client-side parent→children map, avoiding the `.ms` per-project N+1. Backs the 9 `gtd_*_candidates` / `gtd_cluster_candidates` / `gtd_health_report` read tools. **Also holds `classify_shape`** (Wave 1b, backing `gtd_item_shape`) — single-item lexical classification that REUSES the same compiled pattern objects rather than a second copy, so `shape-patterns.md`'s lockstep contract (*an action the fan-out classifies as `draft` is one the deliverable detector would have found*) holds by construction |
| `gtd_writes.py` | Pure (no-IO) grammar for the **Phase 1 everyday write tools**. Also home of `check_payload` (v5.0.0) — the **present-but-empty payload gate** over the eight parameters whose value IS the work (`items`/`dispositions`/`verdicts`/`moves`/`frame`/`narrative`/`derived_refs` — `body` until v6.0.0). v4.0.0 closed *absence*; `[]`/`{}`/`""` stayed legal as a silent no-op and v4.1.0's guidance narrowing removed the signal that made it visible, so the silent case is removed rather than re-signalled. Generalises the rule `validate_transition` already applied to `add_tags`/`remove_tags` and REUSES its `MISSING_PARAMETER` reason (a new member would churn all 100 fingerprints for a failure the registry already spells). Deliberately NOT a general empty-check: a genuine facet (`due`/`energy`/`extra_tags`) is legitimately empty, a boolean is a mode switch (`receipt.is_facet`), and `rtm_tool_help()` with no argument is a designed **view selector**, not an empty payload — all four asserted. Home of the **Tier-1 shared-kernel promotion (D1)** — the seven structural GTD vocabularies are now server-owned canonical constants (`LIFE_CONTEXTS` incl. `client`; `ITEM_KINDS` = action/waiting_for/calendar_entry, project excluded as it has its own tool; `WORKFLOW_STATES`; `ACTION_CONTEXTS` + `COMMS_MODES` re-exported from `canvas_commit`, never restated; `ENERGY_LEVELS`; `MOSCOW_BANDS` + `MOSCOW_TO_PRIORITY`; `JOURNAL_NOTE_TYPES`), advertised as advisory enums and asserted equal in `test_tool_schemas`. Also `item_tags` (a **calendar entry materialises `action` + `calendar_entry`** — calendar_entry is a Special Tag, not a workflow state), `REQUIRED_AXES`/`check_dor` (the **hard-gated** DoR; the `relational` axis is advisory-only since DEPENDS-ON authoring is a later phase), `format_note_title`/`assemble_note_body`/`state_body` (STATE is latest-wins — the prior note is never deleted). **`check_block_order` was DELETED at v6.0.0**, not deprecated: `assemble_note_body` emits narrative → `--- Sources ---` → `--- AI Context ---` from typed parts, so there is no argument that produces the wrong order and nothing left to validate. `render_sources` / `render_ai_context` are public so the TOOL reaches the same verdict the assembler does when populating the receipt — one rule, one place, rather than re-deriving it from the assembled string, and the four validators + `GTD_WRITE_REJECT_REASONS`. Scoped to the NEW tools only — the generic `add_task`/`add_note` stay permissive (the escape hatch) |
| `gtd_reads.py` | Pure (no-IO) builders for the 4 collection/context read tools — **not** `.ms` ports but a codification of the gtd read semantics (list-catalogue / tag-taxonomy / inbox-stuff-pipeline / weekly-review / journaling-lifecycle note-reading-protocol) as compact typed projections. `build_query_*` (the three `gtd_query` perspectives — next-actions-by-context, today's field, focus-area projects), `build_inbox_state` (the three Inbox_Stuff health signals from one read), `build_waiting_for_queue` (chase queue + >14-day staleness), `build_context` (the STATE-first note-reading-protocol bundle — task + STATE-ordered notes + siblings + ancestry, breadth by `depth`), plus `resolve_task_ref` (id-or-name), `parse_note_type`, `classify_gtd_type`, and the canonical `VALID_PERSPECTIVES` / `VALID_DEPTHS` advisory enums. Vault-free |
| `surface_queue.py` | Pure (no-IO) builder for `gtd_surface_queue` — the AI-surface eligibility read. Replaces `ai-surface-scan-questions.ms` + `ai-surface-scan-activity.ms` and does the work they left to the caller: `parse_frontmatter` (a focused parser for exactly the shape `gtd_writes.surface_body` writes — no YAML dependency), `classify_note` (response / system / unrecognised) and `build_row` (identity + parsed frontmatter + `auto_close_due` + `response_detected`). **Three live-measured design decisions**: absent frontmatter is the COMMON case (11 of 77 `AI_Questions` items carry a block) so a row is never dropped for it; `response_detected` is **INCLUSION**-based, not exclusion against the note catalogue as briefed — measured, every off-catalogue note on the eligible set is engine-authored, so exclusion fires on essentially every item, and the exclusion signal is instead quarantined in `unrecognised_notes[]`; and completed-but-not-terminally-tagged items are IN scope, because `ai-surface-scan.md` § 3b.2's closure-with-response path is otherwise unreachable. Also holds the codified `CATALOGUE_NOTE_TYPES` (note-shape-catalogue § 2) + `SURFACE_NOTE_TYPES` (what the AI-surface lists actually carry — carrying BOTH `ACTIVITY-REPORT` and `ACTIVITY_REPORT` since v5.1.1: the hyphen form is what this server WRITES, the underscore form is what live data CARRIES and can no longer be written, and for two releases only the latter was present, so the server scored its own writes `unrecognised`). Also `_option_list` / `_as_list` (v5.1.1) — `expected_response_options` is typed as an array on the row, and a live item carrying the flow form `[approve, decline, defer]` used to land a STRING there and fail output validation for the WHOLE response, so `surface="questions"` returned nothing at all; the parser now reads the flow form and the row builder coerces regardless, because a read must degrade to a worse row, never to no rows |
| `engine_report.py` | Pure (no-IO) builder for `gtd_engine_report` — proactive-contribution telemetry backing `monitor-outcomes.md` § 4c. **Built to intent; the retired script's arithmetic never produced a real number** — four independent faults, two of them found during this build: non-existent task accessors, a modified-keyed window, non-existent NOTE accessors (`getTitle`/`getBody` do not exist), and a `Phase:` body regex where the canonical field is `State:` (live: `State:` on 33 of 39 notes, `Phase:` on zero). Windows are a **creation cohort**; `touched_in_window` is reported separately and never folded in; `closed_in_window` is the one deliberate modified-keyed figure (closure is an event). `contribution_facets` reads the category from the body `Category:` line (the title segment is a fallback — live, 35 of 39 titles have none). Speculation upgrade rate stays **withdrawn** (D2) and every underivable metric is named in `gaps[]` rather than emitted as a zero |
| `tag_report.py` | Pure (no-IO) builder for `gtd_tag_report` — the read half of the strict-tag gate (the gate stops the server minting tags; this finds what got in through the RTM native clients). Holds the **codified canonical taxonomy** (`tag-taxonomy.md`, as `engage_commit.py` codifies the verdict grammar — the markdown stays the authority, a change there is lockstep here), the registered wildcard families (`ai_*_optin`, `q_<entity-type>` derived from `SURFACE_ENTITY_TYPES`, `agile_wow_*`, `architect_*`, `eval_*`, `communication_*`), and `classify_tag` → canonical / family / retired / people / non_canonical. **Three-way, because binary would lie**; people tags are the honest caveat (indistinguishable from typos by any rule — the payload says so). Usage is tallied client-side from ONE broad read, replacing the script's per-tag N+1 |
| `gtd_reports.py` | Pure (no-IO) builders for five small portfolio / hygiene reads. `build_dependency_gaps` (projects with ≥2 open children and no DEPENDS-ON edge — the RTM-derived **upper bound**; the agent still applies the `context.md` vault filter, and the payload says so; children come from one broad read, not the script's per-project `parent:` N+1; the cap is applied AFTER the largest-first sort, unlike the script). `build_review_report` (the weekly snapshot — the retired script reported **0 completions and 0 additions, always**, because RTM does not parse `"N days ago"` for `completedAfter:`/`addedAfter:`; the cohort now uses the verified `completedWithin:` form and additions are derived client-side from `created`). `build_item_stale` (drops the script's unexplained `isSubtask:true`, which made every top-level project and Area of Focus invisible; groups by workflow state instead). `build_workload_report` (an **aggregation**, not a row list — hence a report, not a `gtd_query` perspective; `estimate_coverage_pct` makes the hours figure honest as a floor). `build_focus_index` (Horizon 2 — a new capability; reuses `project_index._active` so it can never disagree with the portfolio). All use the canonical FOUR life contexts incl. `client` |
| `contribution.py` | Pure (no-IO) codification of the CONTRIB **state machine** (`journaling-lifecycle.md` § "The contribution state machine" is the authority) backing `gtd_contribution_transition`. Six states — `drafted` (open) → `accepted`/`edited`/`discarded` (**judged**) or `superseded`/`stale` (**invalidated**); the split is load-bearing because the acceptance rate is `accepted / judged`, so counting a never-assessed contribution as a miss reads as a rejection Paul never made (`engine_report` excludes `INVALIDATED_STATES` from every denominator). Holds `find_state_note` (the CONTRIB/PREP note that CARRIES `State:` — a `CONTRIB-UPDATE` records a transition and is deliberately excluded), `current_state` (**first token only** — 3 of 39 live notes carry prose after the state word, incl. a whole paragraph; whole-line parsing would make each an unrecognised state, and this also keeps it identical to `engine_report`'s regex), `state_remainder` (that prose, handed to the UPDATE note rather than quietly deleted), `rewrite_state` (replace, or APPEND where no line exists — 6 live notes, whose absence is the old wiring's fault), `make_update_note` and `validate_transition`. **Nothing has ever transitioned a contribution** (live: 32 `drafted`, 1 `surfaced`, zero terminal), which is why the reported 0% acceptance rate is a property of the wiring rather than the work |
| `exceptions.py` | Map RTM error codes to typed exceptions with recovery hints. Its `ERROR_CODE_MAP` keys are pinned equal to `error_codes.RTM_CODE_MAP`'s by a test, so the exception hierarchy and the semantic registry cannot drift apart |
| `urls.py` | Build RTM web UI deep-link URLs; walk parent_task_id chain for hierarchy |
| `rate_limiter.py` | Token bucket pacing + rolling-window diagnostics |
| `tools/*.py` | Register MCP tools — thin glue between `client`, `parsers`, and `response_builder` |

### FastMCP 3.x — the docstring shim and the `$defs` change

This server ran on fastmcp **2.x** until v1.35.0 and now pins `>=3.4.4,<4.0.0`. Two 3.x
behaviours matter, both found by measuring during the migration:

**1. Docstring truncation — why registration goes through a shim.** FastMCP 3.x parses a
Google-style docstring with `griffe` and keeps only the **first text section** as the tool
description; everything from `Args:` on is parsed into other section kinds and discarded.
Measured here: **60,081 authored docstring characters became 34,854 — 42% lost.** The dropped
material is the part a model most needs: `list_tasks`' RTM search-operator table *and* its
"API order is NOT user-visible display order" caveat, `add_task`'s Smart Add syntax, and every
`gtd_*` tool's governance contract.

`server._FullDocstringMCP` wraps the FastMCP instance at the single registration point and
injects the full `inspect.getdoc(fn)` as `description=` — which overrides the truncation **while
FastMCP still lifts `Args:` into per-parameter descriptions**. The five `register_*_tools(...)`
calls take `_registrar`, never `mcp`. On 2.x the whole docstring was advertised natively and no
shim was needed, so this is a 3.x workaround rather than a design choice.

**2. `$defs` are dereferenced.** 2.x left pydantic's `$defs` intact; 3.x **inlines** them, so a
nested model (`PlanHeader`, `CommitRejection`, `Task`, …) appears wherever it is used rather than
in a `$defs` table. Content identical, placement moved. Two output-schema tests reached into
`$defs` and failed honestly; `tests/test_tool_schemas.py::_find_model` now locates a model by
`title` anywhere in the tree, so the assertions track the contract rather than the serialisation.

This is why **all 56 fingerprints changed** on the migration: the `outputSchema` serialisation
genuinely differs, even though the advertised content does not.

## Key Patterns

### Tool Registration

Tools are registered via functions that receive the mcp instance and a client getter:

```python
def register_task_tools(mcp: Any, get_client: Any) -> None:
    @mcp.tool()
    async def list_tasks(ctx: Context, filter: str | None = None) -> dict:
        client: RTMClient = await get_client()
        result = await client.call("rtm.tasks.getList", filter=filter)
        return build_response(data=parse_tasks_response(result))
```

### Response Format

All tools return a consistent envelope:

```python
{
    "data": {...},                    # Main response data
    "analysis": {"insights": [...]},  # Optional insights (e.g. list_tasks)
    "metadata": {
        "fetched_at": "ISO timestamp",
        "transaction_id": "...",       # Write ops only — for undo
        "transaction_undoable": True,  # Write ops only
        "timeline_id": "...",          # Write ops only
    }
}
```

Since **v4.0.0** a governed `gtd_*` write's **success** `data` additionally carries the teaching
receipt — `not_applied[]` (always present, `[]` when everything landed), `guidance`, `advisory`.
Attached centrally by `tools/gtd.py::_tool`, never at the call site; an **error** envelope carries
none of it. See the receipt section above and CONTRIBUTING § 4.1.

### HTTP Transport

Reads use GET with query parameters. Writes (`require_timeline=True`) use POST with form data — RTM silently ignores some parameters (e.g. `note_title`) on GET.

```python
client = RTMClient(config)
result = await client.call("rtm.tasks.add", require_timeline=True, name="Task")
```

The client provides:
- **MD5 request signing** via `sign_request()` (shared by `RTMClient` and `RTMAuthFlow`)
- **Timeline management** for write operations
- **Token bucket rate limiting** (burst to 3 RPS, sustain ~0.9 RPS)
- **HTTP 503 retry** with escalating backoff (2s → 5s, max 2 retries)
- **Connection retry** for transient errors (timeout, DNS, TCP reset) with configurable backoff
- **Settings caching** via `client._get_settings()` — fetches `rtm.settings.getList`
  once per session; `get_timezone()` and `get_default_list_id()` both read from this
  single cached dict (one API call serves both)
- **Account-tag caching** via `client.get_account_tags()` — normalized (trim + lower)
  set of existing account tags from `rtm.tags.getList`, cached with a short TTL
  (`ACCOUNT_TAGS_TTL_SECONDS`, 5 min); `force_refresh=True` bypasses the cache. Backs
  strict-tag mode's allow-list (see below)
- **Error code mapping** to typed exceptions with recovery hints

### Rate Limiting and Connection Retry

Uses a **token bucket** (`rate_limiter.py`) matching RTM's stated limits:

| Parameter | Default | Env var |
|-----------|---------|---------|
| Bucket capacity | 3 tokens | `RTM_BUCKET_CAPACITY` |
| Safety margin | 10% | `RTM_SAFETY_MARGIN` |
| Refill rate | 0.9 tokens/sec (= 1.0 - margin) | Derived |
| Max 503 retries | 2 | `RTM_MAX_RETRIES` |
| First 503 retry delay | 2s | `RTM_RETRY_DELAY_FIRST` |
| Subsequent 503 retry delay | 5s | `RTM_RETRY_DELAY_SUBSEQUENT` |
| Max connection retries | 3 | `RTM_CONN_MAX_RETRIES` |
| First connection retry delay | 1s | `RTM_CONN_RETRY_DELAY_FIRST` |
| Subsequent connection retry delay | 3s | `RTM_CONN_RETRY_DELAY_SUBSEQUENT` |

**Connection retries** are handled by `_attempt_http()` which wraps the HTTP dispatch:
- `ConnectError` (TCP, DNS) — retried for both reads and writes (connection never established)
- `ConnectTimeout` / `PoolTimeout` — retried for both reads and writes (connect-phase timeouts:
  the request never left the client, so a write cannot have been processed)
- `TimeoutException` on reads — retried (safe to replay)
- `TimeoutException` on writes — **not retried** (request may have been processed, risking duplication)
- Mid-flight `TransportError` (`ReadError`, `RemoteProtocolError` — e.g. a TCP reset during the
  response) — retried on reads; on writes raised immediately as `RTMNetworkError` (ambiguous,
  same rationale as the write timeout). Nothing transport-shaped escapes as a raw httpx
  exception; a non-JSON 200 body also raises `RTMNetworkError`.
- TLS certificate errors — never retried
- Connection retries do **not** consume additional rate limit tokens

Request classification uses `require_timeline` as a proxy: `True` = write, `False` = read. This correlates 100% with actual read/write status across all tools. `RateLimitStats` tracks the split (`reads_session` / `writes_session`, surfaced by `get_rate_limit_status`).

**Once-per-session fetches are lock-guarded:** `get_timeline()` and `_get_settings()` use
`asyncio.Lock` double-checks, so concurrent first writes share one timeline (undo depends on the
transaction log matching the timeline the writes executed under). A failed settings fetch is
**not** cached — the next consumer retries, so one transient blip can't disable timezone
localisation for the whole session (`get_account_tags` already re-fetches after its TTL).

### Unknown-parameter rejection (the call-boundary gate, since v3.2.0)

A tool call carrying a parameter the tool does not define is **rejected**, with no write.

> ### ⚠ CORRECTED 2026-07-26 — this section's original premise was false
>
> It read: *"Before v3.2.0 it was accepted silently — the extra argument discarded, nothing
> said."* **Measured false on the pinned stack.** A bare fastmcp 3.4.4 server with NO middleware
> rejects an undeclared argument at pydantic's call-schema binding, before the tool body
> (`unexpected_keyword_argument`); v3.1.0, which has no `middleware.py` at all, does the same over
> raw JSON-RPC. So **v3.2.0 did not add a gate — it replaced a pydantic dump with a teaching
> rejection.** A genuine improvement to the message, and nothing more.
>
> **Where the silence actually came from.** The motivating `gtd_inbox_capture(text=…,
> type_tags=[…])` incident is on record in a Desktop local-agent transcript (Claude Code CLI
> 2.1.219). Its undeclared keys never reached this server: the Claude Desktop host re-registers
> each upstream tool through a JSON-Schema→zod converter (`jsonSchemaToZodShape`) that reads
> **only** `properties` and `required`, wraps the shape in a plain strip-mode `z.object`, and
> forwards the PARSED object — so undeclared top-level keys are silently deleted client-side. The
> shipped converter was measured **invariant** to `additionalProperties` being `false`, `true` or
> absent, so the closed schema we advertise (which comes from pydantic's `kw_arguments_schema`,
> not from us) is discarded upstream rather than enforced.
>
> **So this gate is unreachable through that host.** A sweep of 2,517 transcripts — every session
> on the machine, including the whole scheduled-worker population — found **zero** cases of any
> caller receiving its rejection through the MCP boundary. It is retained as a backstop for
> unmeasured caller populations (a rendered board artifact, MCP Inspector, a non-Desktop client)
> and because a better message is free — but it must not be credited with preventing the incident
> that prompted it. It could not have.
>
> The defect class is real and now sits one hop **outside** this server's reach: a misspelt
> optional on a write tool is stripped by the host, the item is written without that property, and
> success is reported with nothing marking the discarded intent. No server-side change can detect
> that. Also measured: the Desktop-spawned server's **fd 2 is `/dev/null`**, so every
> write-boundary gate WARNING is destroyed — the v3.0.1 unobservable-control lesson, recurring at
> the process level.

**The cost is a confident success a caller reasons from, not a corrupted write.** `gtd_inbox_capture`
called with a non-existent `type_tags` parameter returned a success whose `applied[]` carried
`capture:tags` — the server correctly applying its own `#ai_conversation` pipeline tag — which was
read as the tag write having landed, and a false defect report against the server followed. The tool
told the truth; the missing feedback let a wrong story survive. The quieter and more dangerous case
is a misspelt **optional** on a write tool (`gtd_item_create`, `gtd_item_set_properties`): the item
is written without that property and reported as success, with nothing in `applied[]` or `errors[]`
marking the discarded intent.

**Reject, do not warn.** A `warnings[]` entry in the response body was considered and rejected —
that is precisely the class of signal that gets ignored, and this defect exists *because* a silent
success let a wrong conclusion stand. The accepted counter-cost, recorded so the decision can be
revisited: strict rejection **couples client and server versions** — a skill written against a
newer server passing a parameter an older one lacks now hard-fails rather than degrading. Tolerable
here because both sides are the same author's and move together, and because the failure announces
itself loudly and immediately.

**One middleware, not per-tool.** A single `on_call_tool` hook (`middleware.py`, registered at the
`FastMCP(...)` construction in `server.py`) covers every tool in every module and cannot drift as
tools are added — the same reasoning as the `_tool` registration wrapper in `tools/gtd.py`. Per-tool
`ConfigDict(extra="forbid")` would be 99 things to keep in step. The valid-name set is
`(await server.get_tool(name)).parameters["properties"]` — the tool's own **advertised** schema, so
the gate and the documentation cannot disagree. An unknown *tool* is passed through untouched (the
dispatcher owns that message; pre-empting it would replace a precise "no such tool" with a
confusing "no such parameter"). The message names the unknown parameter(s) **and the full accepted
set** — naming the accepted parameters is what turns a rejection into the answer, which matters
because the caller is by construction confused.

**No protocol-key passlist, and that is measured rather than omitted.** MCP carries `_meta` as a
**sibling** of `arguments` on `CallToolRequestParams` (a pydantic field aliased `_meta`), so it
never reaches the arguments dict; and a client that inlines `_meta` *into* `arguments` is rejected
downstream by FastMCP's own signature binding regardless ("Unexpected keyword argument", measured on
fastmcp 3.4.4). Passing it through would change nothing except substituting a worse message for a
better one. An `_`-prefix rule would have been worse still — `_type_tags` is a typo, not protocol.

**Membrane / activation.** No new tag, no schema change (all 99 fingerprints byte-identical), no
new `ErrorCode`, vault-free. To go live: restart the server on v3.2.0. Rollback is one line
(removing the `add_middleware` call), so this is recoverable rather than a one-way door.

### The teaching receipt — closing the silent-partial-write gap (since v4.0.0)

Implements the approved designed change `2026-07-26-tool-receipts-and-parameter-tightening.md`
§§ 2–3, as a **TRIAL on this server only**; the three sibling MCP servers are gated on its debrief.

**The gap, precisely scoped.** v3.3.0 proved tier 3 unreachable on the hosted client. What remains
is one narrow, real failure:

| Case | Behaviour | Risk |
|---|---|---|
| Misspelt **required** parameter | Loud error — stripped → required key missing → binding rejects | None |
| Misspelt **optional identifier** | Loud error — resolution finds nothing | None |
| Stripped **payload** (`items`, …) | No-op — empty `applied[]`, visible | Low (and § 3 below removes it) |
| **Stripped optional modifier** on a write | **Silent partial** — the write succeeds minus the property | **The whole exposure** |

**You cannot throw on what you were never told.** The server receives `gtd_inbox_capture(text=…)`,
a completely valid call; the information was destroyed client-side. The caller knows its *intent*
and the server knows the *outcome*, so the fix is to make the outcome impossible to misread.

**Three fields on all 25 governed writes.** `not_applied[]` (requested but not written —
**always present, empty when clean**, so a consumer branches unconditionally), `guidance` (the next
step when the outcome was not a clean full success), `advisory` (the call carried none of its
optional value-bearing parameters, named). All three are **advisory data, never a gate** — a caller
that ignores them still gets a correct, complete result.

**Attached centrally, and that is the point.** `tools/gtd.py::_tool` wraps each non-read-only gtd
tool, so the receipt cannot drift as tools are added — the same reasoning as one middleware over 99
per-tool configs. `functools.wraps` is load-bearing: FastMCP builds the advertised schema from
`inspect.signature` (which follows `__wrapped__`) and the docstring shim reads `inspect.getdoc`.
Verified rather than assumed — input schemas and descriptions measured **byte-identical across all
100 tools** against a v3.3.0 worktree, with a control proving the baseline really loaded.

**Two `applied[]` entries were reclassified** in `gtd_engage_commit`: a `keep`/`do_now` verdict (no
durable write by grammar § 4) and a skipped duplicate STEER note — the latter sat *inside* `applied[]`
labelled `"(skipped, duplicate)"`, contradicting the list it was in and inflating `"Applied N
write(s)"` with non-writes. A visible change to that array's contents, not to any field.

**Where a caller learns it exists** — three surfaces, none restating another (§ 3's no-double-authoring
rule): the server `instructions` carry the imperative and stay at **2,046 bytes** (paid for by
trimming tool enumerations `rtm_tool_help()` serves on demand); each governed write's description
carries a ~190-byte block appended by the same wrapper; `rtm_tool_help("<tool>")` carries the full
contract where there is no budget. Two tools cross the 2 KB budget **solely** because of the shared
block and are exempted with that reason.

**Measured during the trial** (both numbers belong in the debrief, and both came from measuring
rather than reasoning): the advisory fired on **82%** of governed-write calls on first
implementation — it fired on *any* absent optional rather than *all*, and the wrapper read `kwargs`
directly so positionally-passed arguments were reported absent. Corrected: **17.3%**. Then
tightening (§ 3) and the advisory turned out to **interact**: with the payloads required, the only
optionals left on `gtd_engage_commit` and `gtd_note_add` were control flags, so both fired on 100%
of legitimate calls. `receipt.is_facet` excludes booleans and took both to 0% — a correctness rule,
not tuning, because a stripped boolean is rejected or changes documented default behaviour and can
never be the silently-lost value.

**Eight parameters tightened to required (BREAKING).** `gtd_engage_commit.items`,
`gtd_inbox_drain.dispositions`, `gtd_waiting_for_sweep.verdicts`, `gtd_cluster_consolidate.moves`,
`gtd_item_transition_batch.items`, `gtd_project_create.frame`, `gtd_note_add.body`,
`gtd_inbox_item_close.derived_refs`. Each permitted a call that was never legitimate (an empty
commit, a no-op, a note with a title and no content). Genuine facets — `gtd_item_create`'s `due` /
`energy` / `comms` — are deliberately **not** tightened; absence is legitimate there, and forcing
explicit nulls would not help anyway since a typo'd facet alongside a correct one still strips.

**Membrane / activation.** Vault-free, **no new tag**, no strict-tag interaction. Three new
`ErrorCode` members (the receipt's outcome vocabulary), so **all 100 fingerprints churn** —
structural, from the enum being inlined into every `ErrorBody.code`, not 100 tools changing
behaviour. To go live: restart the server on v4.0.0. Additive plus a revertable signature change —
no one-way door.

### The Tool Affordance Standard — three tiers of documentation (since v3.3.0)

Implements the family standard's new §§ 4.1a / 9 / 10 (git-ops `mcp-tool-documentation-standard.md`).
The six-surface standard was content-complete but **budget-blind**: it said what a tool's
documentation must contain and nothing about *how much of it the client actually shows the model*.

**The measured problem** (2026-07-26, reproduced exactly in this repo at v3.2.0):

| Finding | Measure |
|---|---|
| Descriptions over the client's ~2 KB budget | **18 of 99** — `gtd_canvas_commit` 4,893 B (58% past), `gtd_engage_commit` 4,586 B, `gtd_project_index` 4,448 B |
| Server `instructions` | **30,506 B, ~93% discarded** — what survived was the legal disclaimer plus two sentences; the tool-family routing was gone |
| What reaches the model | descriptions and `inputSchema` on fetch. **`outputSchema` / `annotations` / `_meta` never do** |

Because a Google-style docstring puts `Returns` / operator tables / caveats **last**, the discarded
tail was exactly the correct-usage material — on the highest-stakes governed writes.

**The guarantee ladder** is the reasoning the whole design rests on. Ranked by what guarantees the
read: (1) `name` then `description` — the only channel every client puts in front of the model
unprompted; (2) a server-forced rejection — the one moment the server *makes* the model read;
(3) a skill-mandated pre-call consult — raises odds, never a guarantee; (4) help tool, `_meta`,
resources — on demand only. So selection-critical facts must live in tiers 1–2, teaching in tier 2,
and depth in tiers 3–4.

**Tier 1 — select.** Every description opens `<Domain> — <purpose>`. All 55 `gtd_*` tools already
did; the 44 non-conforming were exactly the generic primitives, which now carry `RTM — `. That
marker is also the **model-readable half of the taxonomy**: since `_meta` is not rendered to the
model on this client, ordinary description text is the only place a skill can actually select on
(which is why the `_meta` delivery half stayed out of scope, gated on measuring the other clients).
`instructions` is now **2,046 bytes**: what-the-server-is, the two-family split with routing
keywords, a pointer to `rtm_tool_help()`, and the disclaimer last.

**Tier 2 — detail (`rtm_tool_help`).** Read-only and **offline** (zero RTM calls). Two arities, one
tool, so no illegal combination is representable: no argument → the whole-server index; a name →
that tool's contract. **Generated as a projection, never hand-written** — see the `tool_help.py`
row above for what is derived versus authored. The index costs ~5.7 k tokens, not the ~2 k the
brief projected: that figure came from the docstrings' physically *wrapped* first lines, which cut
mid-clause. A semantically complete first *sentence* costs ~3× more and is what a caller can
actually select on — still ~30× cheaper than the full advertised surface, and paid only on demand.

**Tier 3 — teach.** The v3.2.0 gate named the valid parameters and nothing else. It now teaches:
purpose (the original defect was a wrong-*tool* case), typed params with required/optional and
enums, a nearest-name guess, the combination rules a schema cannot express, and a help pointer.
One shape via `guided_rejection.py`. It still writes nothing — `client.call` await count zero is
the complete proof, and a test pins it.

**Why tier 3 never fires here, traced to source (2026-07-26).** An unknown argument sent through
the Claude Desktop host never reaches the middleware: `rtm_tool_help(tool_nme=…)` returns the whole
no-argument index. **It is not fastmcp** — a raw `tools/call` written straight to the server's stdin
*is* rejected, and a bare fastmcp server with no middleware rejects it too, so the stack is
structurally incapable of silently accepting an undeclared kwarg.

The cause is client-side and identified from shipped source, not inferred: Desktop's
`LocalMcpServerManager.createSdkServer` re-registers each upstream tool via
`jsonSchemaToZodShape(tool.inputSchema)`, a converter that iterates **only** `properties` and
`required`, wraps the result in a plain `z.object` (no `.strict()`), and forwards the **parsed**
output as `arguments`. zod's default is *strip*, so undeclared top-level keys are silently deleted.
The shipped function was extracted and measured **invariant** to `additionalProperties` being
`false`, `true` or absent — a strict-honouring converter is bundled but never called.

**This is NOT the layered defence an earlier draft of this section claimed.** Our published closed
schema is discarded upstream rather than enforced; the outer layer *mutates* the call to fit
(a declared sibling key is honoured while the unknown one vanishes) rather than rejecting it, which
is not what `additionalProperties: false` enforcement means. And the middleware was never the second
layer — pydantic already rejected, before the tool body.

Consequences. A sweep of 2,517 transcripts found **no caller has ever received the rejection**
through the MCP boundary, so tier 3 has no live consumer and tiers 1 / 4 carry this client entirely.
The v3.2.0 WARNING log cannot answer "how often does this happen?" — it under-counts by construction,
and on the Desktop-spawned instance its stderr is `/dev/null` anyway. Nested keys behave oppositely
(the converter emits `.passthrough()` for nested objects, so an unknown key *inside* a declared
object parameter survives) — behaviour tracks zod defaults per level, not our keyword. **Unmeasured:**
whether a rendered board artifact, MCP Inspector, or claude.ai web strips or forwards.

#### ⚠ EXTENDED 2026-08-01 — the converter validates far more than this section says

Re-measured against `/Applications/Claude.app` 1.24012.9 (the same binary the 2026-07-26 trace was
taken from) by instrumenting the shipped `.vite/build/index.chunk-6k1UHY_-.js` with a recursive
Proxy and replaying the real advertised `gtd_note_add` schema through a line-by-line transcription
on zod 4.4.3. What stands, and what does not:

| Claim above | Verdict |
|---|---|
| Undeclared top-level keys are silently stripped | **Stands** — reproduced |
| Nested objects get `.passthrough()`, so an unknown key inside a declared object survives | **Stands** — reproduced |
| `jsonSchemaToZodShape` iterates only `properties` / `required` | **Stands of that function** (`p`), but misleads: `p` delegates each property to helper `a`, and the *conversion* reads twelve keywords — `type`, `description`, `enum`, `minimum`, `maximum`, `items`, `properties`, `required`, `default`, `allOf`, `anyOf`, `oneOf` |
| "wraps the shape in a plain `z.object`" | **Wrong attribution, right behaviour.** `p` returns a bare shape and wraps nothing; the vendored MCP SDK wraps it (`validateToolInput` → `V_()` → a ZodMini object with no catchall, i.e. zod's default strip) |
| One call site (`LocalMcpServerManager.createSdkServer`) | **Wrong** — three, and not identical: `LocalMcpServerManager`, `SshMcpServerManager`, `InternalMcpServerManager.createProxyServers` |

**Two consequences that matter more than the corrections themselves.**

**A declared optional is NEVER silently dropped.** Measured per case against the live schema: a
proper `list[str]` passes through unchanged; the JSON **string** `'["a","b"]'` **throws**
(`invalid_type`, path `['sources']`) rather than stripping; a bare string throws the same; an
off-enum value throws (`invalid_value`) — which is the ~2 ms host rejection observed live on
`gtd_note_add(note_type="SCOPE")`, a **zod** error shape, not pydantic's. Only *undeclared* keys
strip. So the failure mode "a correctly-named optional vanishes en route" **does not exist on this
path**, and any future investigation should stop looking for it. (Note the interaction with
`tool_params`: `coerce_json` exists to accept a stringified complex param, but on this host such a
call is rejected upstream and never reaches the `BeforeValidator` at all.)

**`anyOf` / `oneOf` → `z.unknown().optional()`.** A union-typed parameter degrades to *fully
untyped* at the host. This is a measured mechanism for the single-typed-parameter policy in
`tool_params.py`, which until now was justified only by "clients flatten it to a bare `{}`".

**Honest boundary — which binary served the incident is NOT established.** The 2026-08-01 event
came through **local agent mode**, which runs a separate Claude Code sidecar
(`~/Library/Application Support/Claude/claude-code/2.1.219/…`, confirmed as the live process),
whose 257 MB binary contains **zero** occurrences of `jsonSchemaToZodShape` yet does carry
`Input validation error` and `Invalid option: expected one of`. So the table above is measured on
Desktop chat's converter and is *consistent with* the observed rejection shape, but the sidecar's
own validation stack was not extracted. That gap does not affect any conclusion drawn here: the
2026-08-01 loss happened **before** any converter ran (see the next section).

### Leaked tool-call markup — a second, DIFFERENT parameter-loss mechanism (measured 2026-08-01)

A hand-off brief reported a `gtd_note_add` call whose declared, correctly-spelled `sources`
parameter "did not arrive", and hypothesised that the host had begun stripping declared optionals.
**It had not.** The audit record shows the tool_use `input` carried four keys and no `sources` key,
with the entire sources array sitting at character 1,730 of the 2,010-character `narrative` string
as literal text:

```
…how a defect outlives its own fix.</narrative>
<parameter name="sources">["AI Memory general/…", "gtd v0.206.0 …", "RTM 1218844852 — …"]
```

The caller emitted XML-style tool-call delimiters mid-argument and the serialiser folded them into
the preceding string instead of splitting them into sibling JSON keys. **The key never existed**, so
no converter at any layer could have removed it. (The record is an `assistant` message carrying
`request_id`/`usage`, i.e. logged pre-dispatch; and its sibling call — carrying the identical leak —
was *rejected* by the host and therefore never produced a parsed argument object at all, yet its
input is logged in full. The log is pre-strip.)

**Three states, and collapsing any pair is the error.** The brief conflated (1) and (2) and went
hunting a host strip; a first analysis pass here conflated (2) and (3) and declared the write clean.

| | model raw output | post-host arguments | durable RTM note |
|---|---|---|---|
| `sources` | intended, emitted as malformed markup | **absent** — no key, no strip | **present**, verbatim, as literal markup inside the prose |

**Why this one is different from the client strip.** The strip destroys the value upstream, so the
server genuinely cannot detect it — that is the invariant the whole receipt design rests on. Here
the value **arrives**, in the wrong parameter, and is written durably. It is therefore
server-detectable in principle *and* recoverable from the artefact. The sentence in the previous
section — "No server-side change can detect that" — is true of the strip and **false of this**.

**Measured blast radius** (sweep of 20.8 k transcript files / ~104 k distinct tool_use calls,
2026-03-31 → 2026-08-01, adversarially re-verified):

- **13 genuine leak events**, of which **8 succeeded**. Spread across four generations of model and
  four servers — `mcp__rtm__` (6), Claude Code built-ins (4), `mcp__cowork__` (3),
  `mcp__Claude_in_Chrome__` (1). **Not rtm-specific, not `gtd_*`-specific, not one model.**
- **5 corrupted RTM notes**, on 5 tasks, via **three** governed writes — `gtd_inbox_item_annotate`
  ×3 (2026-07-26), `gtd_note_add` ×1 and `gtd_item_complete` ×1 (2026-08-01). Exact within the
  reachable search space, not a floor.
- **2 genuine parameter losses.** `gtd_note_add.sources` (recoverable — the text landed).
  `gtd_inbox_item_annotate.questions` (**semantic loss** — two clarifying questions folded into
  `analysis_body`; the tool returned `questions_count: 0` and no `CLARIFYING QUESTIONS` block was
  emitted, so the only trace is garbage in the body).
- It **clusters within a session** — once it happens it recurs, 3× in one 92-second window — and
  always at the **tail of the longest free-prose parameter** (affected values 1,624–11,034 chars).
- **Two dialects.** `<parameter name="X">` (the brief's case) and bare XML tags
  (`</analysis_body>`, `</completion>`, `</invoke>`). The second accounts for the majority and a
  detector matching only `<parameter name=` would miss it.
- **No gate anywhere caught the markup.** Every rejection among the 13 fired on something else.

### The detector (v6.1.0) — one predicate, two consumers

`receipt.detect_leaked_markup` is the whole rule, and it is **tool-scoped**: a closing tag is a
finding only when its name is a parameter *the tool being called declares*. That scoping is the
entire precision story — measured over **13,435 real RTM calls it fired 7 times with zero false
positives**, including on a full HTML document passed to `add_note` (`</head>`, `</body>`,
`</script>`), which stays silent because none of those is an `add_note` parameter. A bare `</…>`
predicate flags it.

**Both dialects reduce to one `lost` field, and the second half of that was found by a failing
test rather than designed.** Dialect 1 names its target in a `<parameter name="sources">` opener.
Dialect 2 has none — but `</analysis_body>\n<questions>[…]</questions>` closes `questions`, which
is *also* a declared parameter of that tool. So a closing tag naming a declared parameter **other
than the carrier** is itself the lost-parameter signal.

| Consumer | Covers | Channel |
|---|---|---|
| `tools/gtd.py::_with_receipt` → `advisory` | the 25 governed writes | the caller, in the response |
| `middleware.py` (log only, never raises) | all 100 tools | the v5.1.0 file sink, which survives a `/dev/null` fd 2 |

The middleware half exists because that is where the traffic is: `add_note` alone was measured at
**78× the volume of `gtd_note_add`**, and it is the documented escape hatch. It can only raise, so
it cannot report without blocking — hence log-only.

**ADVISORY, NEVER A GATE, and that is a correctness rule.** The anchor cannot separate a genuine
leak from a note *documenting* one, and this repo journals its own defects into RTM through exactly
the tools being watched — a gate would make writing about the bug impossible. It also **closes the
partial-loss blind spot for this cause**: `build_advisory` fires only when *every* facet is absent
(silent for 15 of the 25 governed writes when one facet is supplied and another lost), whereas the
markup advisory fires on the evidence itself. Where both would fire, the markup one **outranks**,
because it explains the absence and names the lost parameter.

Cost, measured: **25 fingerprints** — the governed writes, from the shared `RECEIPT_DOC` block
being reworded, not from 25 tools changing behaviour. No new `ErrorCode` (the ladder: a new member
churns all 100; adding an existing code to `RECEIPT_REASONS` churns 25; reusing one already in both
changes nothing). `not_applied[]` is deliberately **not** used — the write happened, so "you asked
for this and nothing was written" would be false. Note also `instructions` sits at **2,046 of its
asserted 2,048-byte budget**, so there is no room to document a gate on the selection surface even
if one were wanted.

**The 2 KB cap versus CONTRIBUTING § 7 — the divergence that matters.** § 7 *requires* a multi-case
`Returns` and an `Args:` section in every tool docstring, and the `_FullDocstringMCP` shim
advertises the whole docstring as the description. For a genuinely complex governed write, "fit
2 KB" and "obey § 7" cannot both hold — and § 7 wins, being the host repo's own standard. So
**19 descriptions stay over budget on a reasoned, asserted exemption list**, and the load-bearing
guarantee is enforced directly instead: a test asserts every exempt tool states its read/write
posture **inside the front block that survives truncation**. Front-loading, not the cap, is what
protects a caller; the cap is a proxy for it.

**Combinations are prose + runtime, never structural.** JSON Schema would express them as
`anyOf` / `oneOf` / `dependentRequired`, and this family bans advertised unions on parameters
(clients flatten them to a bare `{}`, losing type, description and enum). So they are declared as
data once and projected onto the tier-1 hint, the tier-2 contract and the tier-3 rejection. Prefer
**unrepresentable-by-construction** (the v3.0.0 `gtd_query` → three split) where the illegal
combinations partition cleanly; reject-with-guidance otherwise.

**Membrane / activation.** Vault-free, additive, **no new tag and no new `ErrorCode`** (so
fingerprint churn is confined: 1 added, 44 moved — exactly the marker additions — and 55
unchanged). No tool changes behaviour, capability, write safety, or return shape. To go live:
restart the server on v3.3.0. Rollback is a revert.

### Error Handling

Two layers of error handling:

**RTM API errors** — `raise_for_error()` in `exceptions.py` maps RTM error codes to exception classes (`RTMAuthError`, `RTMValidationError`, `RTMNotFoundError`, etc.) and appends recovery guidance from `ERROR_GUIDANCE`:

```python
# exceptions.py
ERROR_GUIDANCE: dict[int, str] = {
    98: "Re-run rtm-setup to get a fresh auth token.",
    340: "Call get_lists to see available list names.",
    341: "Call list_tasks to find the correct task name or IDs.",
    4040: "Subtask features require an RTM Pro account.",
    # ... 18 codes total
}

def raise_for_error(code: int, message: str) -> None:
    error_class = ERROR_CODE_MAP.get(code, RTMError)
    guidance = ERROR_GUIDANCE.get(code)
    full_message = f"{message} — {guidance}" if guidance else message
    raise error_class(full_message, code)
```

**Application-level errors** — `resolve_task_ids` and `resolve_list_id` (in `lookup.py`) and tool
functions return a **structured error** via `build_response(data=build_error(...))` carrying both a
machine-branchable `code` and the actionable prose that guides an agent to the next step:

```python
build_error(ErrorCode.TASK_NOT_FOUND,
            "Task not found: 'Buy milk'. Use list_tasks to search by filter or check spelling.",
            query="Buy milk")
# → {"error": {"code": "task_not_found",
#              "message": "Task not found: 'Buy milk'. Use list_tasks to search by …",
#              "rtm_code": None,
#              "details": {"query": "Buy milk"}}}
```

**BREAKING in v2.0.0.** Through v1.35.0 `data.error` was the prose **string** itself. It is now the
object above: the prose survives **verbatim** as `error.message` (only its location moved), and
consumers branch on `error.code` instead of pattern-matching English. The recovery material that
used to sit as *siblings* of `data.error` (the strict-tag gate's `strict_tag_mode` /
`how_to_proceed` / `rejected_tags`; a resolver's `candidates`) now rides under `error.details`.
See CONTRIBUTING § 5 for the construction rules and the additive-only registry discipline.

Two distinct error shapes exist and only the first changed:

| Shape | Where | Contract |
|---|---|---|
| **Envelope error** | `data.error` | The `success \| error` union discriminator — the structured `ErrorBody` above |
| **Per-op batch failure** | `data.errors[]` inside a **successful** envelope | `{"op", "id", "error": str(exc)}` — flat, reports partial failure in a batch that otherwise applied. Deliberately **unchanged**; unifying it is a separate change |

The commit engines' per-item `rejected[].reason` is a third, *flat* surface — its vocabulary is
drawn from the same `ErrorCode` registry, but a rejection entry is `{reason, detail, …}`, never a
nested envelope error.

### Task and List Identification

RTM uses three IDs for task operations:
- `list_id`: Which list the task is in
- `taskseries_id`: The task series (for recurring tasks)
- `task_id`: The specific task instance

Tools accept either `task_name` (fuzzy search) or all three IDs. **Fuzzy matching** (`lookup.py:find_task`) searches incomplete tasks, preferring exact matches over substrings and more recently modified tasks over stale ones. All tool docstrings include a caution that fuzzy matching may hit unintended tasks.

List tools accept `list_name` which is resolved to `list_id` via `lookup.py:resolve_list_id`.

### Subtask Hierarchy

RTM supports parent/child task relationships (Pro required, max 3 levels):

- **`parent_task_id`** is extracted from the `taskseries` element (not `task`) and appears as empty string for top-level tasks — the parser normalises this to `None`
- Subtasks are sibling taskseries entries under the same list, NOT nested inside their parent
- **`subtask_count`** is computed client-side from the current result set via `_apply_subtask_counts()` — it does not make a secondary API call
- `list_tasks` accepts a `parent_task_id` parameter: it injects `isSubtask:true` into the server-side filter, then applies client-side filtering by parent ID
- `add_task` accepts `parent_task_id` to create a task as a subtask
- `set_parent_task` reparents a task or promotes it to top-level (pass empty `parent_task_id`)
- If the parent is in a different list, the task is **implicitly moved** to that list
- Repeating tasks cannot be parents or children of other repeating tasks
- `isSubtask:true` is an **undocumented** RTM filter — client-side filtering by `parent_task_id` is the reliable fallback
- RTM error codes: 4040 = Pro required, 4050 = invalid parent, 4060 = max nesting exceeded, 4070 = repeating task conflict, 4080 = due date before start date, 4090 = self-parenting

### Strict-Tag Mode (existence gate)

A control (`config.strict_tags`, env `RTM_STRICT_TAGS`, **on by default**; set
`RTM_STRICT_TAGS=0` to disable) that refuses any tag write which would introduce a tag not
already present in the RTM account. RTM auto-creates a tag on first use, so this is the
chokepoint that stops accidental tag minting via the MCP.

**Design — deliberately decoupled.** The runtime allow-list is simply the account's
current tag set (`client.get_account_tags()`), read live from RTM. The server has **no
knowledge of any canonical taxonomy and needs no sync** — "is this an *allowed* tag?"
(canonical policing) stays plugin-side; the server only enforces "does this tag *exist*?".

**Components:**
- `strict_tags.py` — pure policy: `normalize_tag` (trim + lower), `split_tags`
  (comma-split → normalized, de-duped), `extract_smartadd_tags` (regex `#tokens` from a
  SmartAdd name), `guided_error` (the self-documenting rejection — since v2.0.0 a structured
  `strict_tag_rejected` error whose recovery material (`rejected_tags` / `reason` /
  `how_to_proceed` / `strict_tag_mode`) rides under `error.details` rather than as siblings of
  `data.error`), `as_rejection` (flattens that envelope into the commit engines' `{reason, detail,
  …}` entry shape — details are spread FIRST so the canonical `reason` always wins over the
  guided error's own explanatory `reason` detail key), and
  `enforce_strict_tags(client, requested, *, tool)` → returns a guided-error dict to
  reject or `None` to allow.
- `client.get_account_tags()` — the TTL-cached, normalized allow-list (see HTTP Transport).

**`enforce_strict_tags` flow:**
1. `if not client.config.strict_tags: return None` — zero-cost when off (no API call).
2. Normalize (trim + lower) and drop empties; no tags → allow (defensive: the allow-list is normalized, so the comparison is like-for-like even for an un-normalized caller).
3. Compare requested against `get_account_tags()`. On a miss, **re-fetch live**
   (`force_refresh=True`) and recompare — cache-miss safety so a tag created moments ago
   out-of-band isn't falsely rejected.
4. Still offending → `logger.info(...)` and return `guided_error(offending)`; else allow.

**Wiring (`tools/tasks.py`):** `add_task` (when `parse=True`, on `extract_smartadd_tags(name)`),
`add_task_tags` and `set_task_tags` (on `split_tags(tags)` — for `setTags` the resulting set
*is* the passed tags). `remove_task_tags` is **never** gated (removal reduces entropy).

**Caveats:**
- `extract_smartadd_tags` is a documented best-effort approximation of RTM's SmartAdd tag
  tokenizer. Over-matching a stray `#word` is intentional (it's the accidental-minting case);
  the guided error tells the caller to re-issue with `parse=False` or fix the name.
- **Testing gotcha:** the `mock_client` is an `AsyncMock`, so `client.config.strict_tags`
  is a *truthy Mock* unless set — the `test_task_tools.py` fixture sets
  `client.config = MagicMock(strict_tags=False)` so tag-write tests behave as today; strict
  tests flip it True and stub `client.get_account_tags`.

### Note-shape mode + list-target mode (write gates 2 and 3, since v2.2.0)

Two further **write-boundary gates**, extending the strict-tag precedent: instead of a call-site
validator an agent must remember to run, the server refuses the malformed write itself, so the
discipline is an invariant no session, sub-agent, or scheduled engine can forget. Both shipped
**off by default** and were **switched on in v5.1.0** (see the observability section below);
flags-off still reproduces pre-gate behaviour byte-for-byte, and that revert is the rollback plan.

**The governing compromise: the server ENFORCES; gtd OWNS. For two of the three gates those are
the same line; for notes, since v5.2.0, they are not** (CONTRIBUTING § 6):

| | Server enforces | gtd owns |
|---|---|---|
| Notes | the title **parses** as `YYYY-MM-DD [HH:MM] — TYPE — summary` **AND TYPE is registered** (v5.2.0+) | which TYPEs exist — `note-shape-catalogue.md` § 2 is the **authority**; the server codifies it |
| List targets | the list is not `smart` / `locked` per RTM's own flags | which *writable* list is correct (`list-catalogue.md`, `validate-list-target.py`) |
| Tags (gate 1) | the tag **exists** in the account | which tags are canonical (`validate-tags.py`) |

The note row moved because the split was **measured** rather than assumed: ~40 off-vocabulary
tokens across 114 notes over five months (census 2026-07-31), because a client-side validator only
runs when a caller remembers it. Authorship did not move — a new type still goes in the markdown
first, and the server's copy follows in a release. **This paragraph is the one a future change
must re-read**: five separate surfaces still asserted the pre-v5.2.0 form days after the flip
(v6.0.1, v6.0.2 and v6.0.3 corrected them), because the rule is quoted in more places than the code
that implements it.

A well-shaped note title carrying an off-vocabulary TYPE **passes the server by design** and is
caught by the plugin validator / weekly notes-audit. **Tag canonicality is a deliberate
non-goal** — `validate-tags.py` is untouched; the asymmetry is a decision, not drift.

**`note_shape.py` (`RTM_STRICT_NOTES`: `off` | `warn` | `shape`).** Pure policy, no API call in
any mode. A typo'd mode **fails loudly at config load** (a `field_validator`) rather than
leaving the gate silently inert — an operator who believes the gate is on and is wrong is worse
off than one with no gate. `warn` logs a malformed title and allows the write: the
observe-before-enforce stage.
- *Where the title comes from:* RTM has no note-title field — `notes.add`/`.edit` store the body
  as `<note_title>\n<note_text>` and return an empty title on read (the same storage reality the
  CHAT / ORDER / TMPL-CHILD grammars rely on). So `effective_title` is `note_title` when given,
  else the **first line of `note_text`** — which is what a caller authoring the grammar inline
  actually writes, so the gate is not trivially bypassable.
- *Legacy safety (the invariant):* wired into `add_note` always, but into `edit_note` **only on
  the title-changing path** — an edit supplying no `note_title` is a body-only edit and is never
  judged. Judging the body's first line there would block every note whose title predates the
  grammar from ever having its body corrected. The consequence, accepted deliberately: a caller
  who rewrites a title *inline via `edit_note`'s body* is not gated — the server cannot
  distinguish that from preserving a legacy line 1, and the legacy-safety invariant wins.

**`list_targets.py` (`RTM_STRICT_LIST_TARGETS`).** Reads the `smart` / `locked` booleans
`parse_lists_response` already coerces from RTM's `"1"`/`"0"` — so no extra API call and, more
importantly, **no taxonomy**. `archived` is deliberately **not** gated (RTM still accepts items
into an archived list, so refusing one would be policy the server does not own).
- *Scope — caller-named targets only:* `add_task(list_name=…)` and `move_task(to_list_name=…)`
  are gated; `add_task`'s **default-list fallback is not**. An account whose configured default
  is the locked built-in Inbox would otherwise have every bare capture rejected — a behaviour
  change the caller never asked for and cannot fix from the call site.
- *Codes are REUSED, not minted:* `smart_list_target` and `locked_system_list` already shipped
  (commit validation / `delete_list`). A `list_target_rejected` synonym would have recreated
  exactly the drift the unified registry removed in v2.0.0.

**Membrane / activation.** No new tag, no strict-tag interaction, no vault. `note_shape_rejected`
is the only **new** `ErrorCode` — and because `models.ErrorBody.code` is typed as the enum (which
FastMCP 3.x inlines rather than `$ref`s), adding it **churns all 56 tool fingerprints**. That is
structural and expected for any additive registry change, not a signal that 56 tools changed
behaviour. To go live: restart the server on v2.2.0 (both gates inert), then enable per gate.

### Write-gate observability — a log sink that survives, and both gates on (since v5.1.0)

Implements the approved designed change `2026-07-26-write-boundary-gate-observability.md`,
Stages 1–3. The "enable per gate" step the v2.2.0 section above deferred, plus the prerequisite
that made it judgeable.

**What was actually wrong — narrower than an early framing claimed.** All three gates enforce
correctly and **return a structured typed error to the caller**; there was never a safety hole,
and the designed change corrects its own earlier overstatement. Two real losses remained:

| Loss | Why it matters |
|---|---|
| **Headless flows are blind** | On a Desktop-spawned server **fd 2 is `/dev/null`** (`lsof` + `stat`), so every gate WARNING is destroyed. In a scheduled worker the typed error reaches *an agent*, which handles or retries it — Paul never sees it. The log was the only human-facing channel for those runs. |
| **Gate liveness is unobservable** | An inert gate returns no error *and* writes no log — identical in every observable respect to a working gate that never fires. With two of three off, "is it on?" was unanswerable from outside. |

*Deliberately downgraded:* "we cannot count how often gates fire" — true, but nice-to-have, and
the v3.2.0 case once cited as evidence was a different problem entirely (the client stripped the
argument upstream, so no working logging would have counted anything).

**Stage 1 — the sink.** A bounded `RotatingFileHandler` (1 MiB × 3 backups) at
`~/.config/rtm-mcp/logs/rtm-mcp.log`, **alongside** the stderr handler so a terminal-launched
server is unchanged. Location overridable with `RTM_LOG_DIR`; level still `RTM_LOG_LEVEL`, which
governs both handlers because they sit at `NOTSET` and the level lives on the tree. `~/.config`
rather than the clone: the launch config is `uv run --project <clone>`, so the process *can*
write to the working tree, but logs there mean `.gitignore` maintenance, `git status` noise and a
real chance of committing them. An unopenable sink **warns and continues** — an observability
improvement must not become an outage.

**The test is the deliverable, not the handler.** An in-process "the record was emitted" assertion
passes against a server with no sink at all — the exact vacuity CONTRIBUTING § 7a already warns
about. So the load-bearing test runs a **real gate in a child process with fd 2 redirected to
`/dev/null`** and asserts the file received it; a companion test runs the same probe with the sink
unopenable and asserts the gate still fires and **leaves no trace anywhere**, which is the
pre-v5.1.0 server reproduced mechanically. Confirmed by stubbing the sink out: the load-bearing
test fails without it.

**Stage 2 — list-target ON.** Zero rollout risk: it refuses only `smart` / `locked` lists, both of
which fail at RTM anyway, so enabling it converts a confusing downstream failure into a precise
immediate one. No `warn` stage exists or is needed. `add_task`'s **default-list fallback stays
ungated** — that carve-out is load-bearing *now* rather than hypothetically, since a configured
default of the locked built-in Inbox would otherwise reject every bare capture on activation.

**Stage 3 — note-shape straight to `shape`, skipping `warn`.** Paul's decision, and the reason the
skip is safe is itself a consequence of Stage 1: `warn` is log-and-allow, so with stderr dead it
neither blocked nor recorded — **the designed middle step did not exist in production**. The live
sample makes it unnecessary anyway. Every agent-written title parses (`ORDER`, `CONTEXT`,
`AI-LINK`, `PROGRESS`, `INCEPTION`, `DEPENDS-ON`), as do the legacy spellings `ACTIVITY`, `AR` and
`ACTIVITY REPORT` — the gate checks shape, not vocabulary, and a space is legal in a TYPE token.
`ACTIVITY_REPORT` (underscore) fails correctly and was **verified absent from live data**.

**The free-text rule (normative).** A note with **no date prefix** is Paul's own, typed into the
RTM app, and is never a violation. The gate is safe on that by construction — it governs MCP
writes and never sees the app — but the rule is recorded in `note_shape.py` because it binds the
gtd-side **notes-audit**, which scans existing notes and would otherwise report them: *no date
prefix → informational, never a finding; date-prefixed but off-vocabulary TYPE → agent-written,
and that is the finding.*

**Blast radius, measured rather than asserted.** `note_shape` is wired into the generic `add_note`
and `edit_note` **only**. All 37 `gtd_*` note writes call `rtm.tasks.notes.add` directly and never
reach it — which is why four of them legitimately write a bare marker title (`DEPENDS-ON`,
`INCEPTION`, `REDACTION`, `TMPL-STAMP`) that this grammar would reject. **Those are correct and
must not be "fixed"**: `project_plan._extract_deps_and_files` round-trips on them. So Stage 3
governs exactly the escape hatch, which is where drift enters.

**Vocabulary gating is explicitly NOT here.** The gate stays mechanical-shape-only. Promoting the
full 27-type `note-shape-catalogue.md` § 2 vocabulary server-side (13 are already server-owned via
`JOURNAL_NOTE_TYPES` + `SURFACE_BODY_NOTE_TYPE`) is its own designed change, deliberately
sequenced *after* this one so the shape gate is proven live first.

**Membrane / activation.** Vault-free, **no new tag**, no new `ErrorCode`, no schema/signature
change. Fingerprint churn is **4 tools** (`add_note`, `edit_note`, `add_task`, `move_task`) —
description-only, from documenting the now-live gates. To go live: restart the server on v5.1.0.
**Rollback is one env var per gate** (`RTM_STRICT_NOTES=off`, `RTM_STRICT_LIST_TARGETS=0`), each
asserted by test — no one-way door.

### GTD domain tools & the `gtd_project_plan` envelope

`gtd_project_plan` (`tools/gtd.py`) is the server's first **domain-composition** tool — it
speaks a consuming domain's language (a GTD "project plan") rather than mapping 1:1 to an RTM
method. **Naming convention:** generic RTM primitives stay bare verbs (`add_task`,
`list_tasks`); domain compositions carry a `<domain>_` prefix (`gtd_<concept-noun>`), so the
tool list self-documents the split and a future lift of all `gtd_*` tools into a separate
server is mechanical. Document new domain tools the same way.

**Read-only:** the tool issues one `rtm.tasks.getList`
(`filter="status:incomplete OR status:completed"`, optionally `list_id`-scoped) — no timeline,
no writes (a test asserts the tool makes no extra direct calls) — then resolves the project and
reconstructs the tree in memory. It also calls `client.get_timezone()` (a **session-cached**
`rtm.settings.getList`, shared with every other tz/default-list consumer) so the envelope's date
fields are localised to the account timezone before truncation (see the tz fix below).

**`project_plan.py` (pure) is byte-compatible with the gtd plugin's `rtm_fetch.py`** reference
(`reconstruct`/`to_ndjson`), the frozen `project-plan-seed/3` contract the canvas mapper
consumes — **except** the tz date-localisation below, a deliberate correctness divergence.
Originally verified by feeding one live `getList` response to both pipelines → identical
envelope. Server-port adaptations (the first three preserve output; the last fixes a bug):
- note bodies via `parsers.extract_note_body` (server notes carry the body in `$t`, not `body`);
- `name`/`estimate`/`url` coerced to `""` (server parsing yields `None` for empties);
- permalinks reuse `urls.build_task_url` with an **id-based** ancestor chain (`_ancestor_chain`)
  that includes an ancestor even when its row isn't in the fetched set — NOT
  `urls.walk_parent_chain`, which truncates at a missing parent and would drop the top segment.
- **tz localisation (date off-by-one fix):** RTM returns timestamps in **UTC** — a London-BST
  date-only due of 22 Jun arrives on the wire as `2026-06-21T23:00:00Z`, so a raw `[:10]`
  truncation rolls every BST/DST date back a day (Paul hit this live: a 22 Jun tickle showed
  21 Jun). `_norm_date(iso, timezone)` now converts to the account zone (via
  `parsers._convert_rtm_date`) **before** truncating, applied to every date field
  (`due`/`start`/`completedDate` + note dates). The gtd read tools pass `client.get_timezone()`;
  with no tz (settings read failed) it falls back to the raw `[:10]` (never raises). This
  **diverges** from the raw-UTC reference `rtm_fetch.py` for BST/DST dates — the reference was
  itself emitting the wrong local day; upstream parity (localising there too) is a follow-up.

### Canvas tools (`gtd_project_canvas` / `gtd_canvas_commit`)

The project-plan **canvas** (a live artifact in the gtd plugin) reads and writes RTM through two
`gtd_` domain tools — the read-sibling and write-counterpart of `gtd_project_plan`.

**`gtd_project_canvas` (read-only)** returns the *rendered-shape* seed the canvas template
consumes directly, so the page never re-implements GTD ordering/blocking. It runs the same single
read-only `rtm.tasks.getList` as `gtd_project_plan`, then composes three **pure, byte-compatible
ports** of the gtd plugin's scripts:
- `canvas_seed.build_seed` ← `build-canvas-seed.py` — envelope → `{mode, frame, seed}`. Each row
  also carries an optional `prog` ("now" from `#ai_progress_requested` / "later" from
  `#ai_progress_deferred`; omitted when neither, "now" wins if both) via `canvas_seed.map_prog` —
  the read-side mirror of the commit's execute write, so the canvas pill reflects committed state
  on reload. Server-emitted field, additive to the reference (upstream parity is a follow-up).
- `plan_graph.build_graph` ← `plan_graph.py` — the deterministic DAG/judgement/order overlay
  (mechanical-only: no vault, so `outputs_index=None` — edges come from active DEPENDS-ON notes
  alone). Since DC-4, `manual_order` is the **latest valid ORDER note** on the project
  (`order_note.from_envelope` over the envelope's `header.project.notes` — vault-free, same
  one-call read), so the board seed shows the dragged order immediately on reload. Clamping
  semantics are identical to gtd's enriched engine (the parity-pinned `_timeline_order`): the pin
  biases cosmetic tiering only, never topology — a consumer never sorts before its producer;
  unlisted ids fall to the end of their ready cohort; ids not in the plan are pruned. An invalid
  note fails closed (resolution falls back to the next-latest valid; none → no bias).
- `canvas_overlay.apply_graph` / `lean_seed` ← `build_canvas.py` helpers — merge + inline profile.

  The merge stamps **only** `quick` (when `quick_ready`) and sibling `deps` (sorted) and reorders
  `seed[]` by the timeline order. It does **NOT** add a `blocked` or integer `order` field — the
  canvas template derives `blocked` from `deps[]`. (`lean=True`, the default, drops note bodies
  and caps notes per item with an honest `nc` — byte-compatible with `build_canvas --emit
  html-lean`.) Read-only invariant: only `rtm.tasks.getList`; no timeline, no writes.

  **Companion metadata (`file.meta`) + `frame.files`.** After the overlay/lean pass, `companion.py`
  enriches every file object — per-action `seed[*].files[]` **and** project-level `frame.files` —
  with a `meta` block: the artefact's companion (`.md`/`.yaml`) frontmatter (title/type/status/
  dates/authors/tags/decision/…), read from the **read-only AI Memory vault**. `meta` is a full
  pass-through of present top-level fields — **never** vocabulary-validated (real `type` values like
  `form-prefilled` pass through verbatim). Backward-compatible: `n/ext/kind/path` are unchanged;
  `meta` is added only where a companion exists, omitted otherwise. The reader mirrors file-store's
  `query_outputs.py` by contract, extended to resolve multiple companion forms (`X.meta.md` →
  `X.md` (non-md) → `X.companion.md` → `.companion/X.yaml` → `X.metadata.yaml`) and to read list
  fields (`authors`/`tags`) the reference parser skips. `frame.files` is the project-level
  support-material roll-up: filed paths scraped from the **project's own** notes
  (`project_plan.build_envelope` now also emits `header.project.files`, additive to the
  `project-plan-seed/3` envelope — `rtm_fetch.py` parity is an upstream follow-up), mapped via
  `parse_file` in the `outputs_index is None` branch.

  **Vault resolution (`companion.resolve_vault_root`)** mirrors the agent-memory plugins,
  cross-platform via `pathlib` (macOS + Windows, no OS branching): explicit override
  `config.vault_root` (env `RTM_VAULT_ROOT`, preferred, or the shared `AI_MEMORY_DIR`) → Cowork
  sandbox mount (`/sessions/*/mnt/AI Memory`) → host default `~/Documents/AI Memory`; each
  validated by the `memory/_index.md` marker. An explicit-but-invalid override does **not**
  fall through (honest no-op). Unset/absent vault ⇒ no `meta`, no error — the read-only invariant
  holds (companion reads are filesystem-only; still only `rtm.tasks.getList` hits the API).

**`gtd_canvas_commit` (constrained write)** is the single governed write surface for a
canvas commit — safe by construction (artifacts call connectors without prompting). It runs
**validate-then-apply**:
- *Validate (no writes):* one read of the project tree → `plan_ids`; resolve the `Processed`
  list (must exist and be non-smart); `canvas_commit.validate_commit` collects rejections
  (cross-project id, unconfirmed `completes`/`removes`, unknown add type, invalid execute value,
  smart-list target, **and since v6.2.0 a blank / whitespace-only / non-string add `text`**); a
  single `enforce_strict_tags` existence-gate pass over `collect_commit_tags(ops)`. Any rejection
  → return with **nothing written**.
- *Apply (durable-first):* `adds` (create on `Processed` → tags → priority → **estimate** →
  due → reparent last), `edits`, `execute` (a **durable now/later/off split**: `now`/`quick` write
  `#ai_progress_requested`; `later` writes `#ai_progress_deferred` — the two are mutually
  exclusive, so switching state drops the stale sibling via `removeTags` so an item never carries
  both; `#ai_deferred_pending_unblock` is still added when the item is blocked — it does **not**
  execute AI work. `off` is the **instant-control clear** — it `removeTags` any progression-directive
  tag present (`EXECUTE_CLEAR_TAGS` = the exact inverse of the set-paths: `#ai_progress_requested` /
  `#ai_progress_deferred` / `#ai_deferred_pending_unblock`), idempotent (0 writes when none present),
  fires no engine, never strict-gated (removal reduces entropy); `execute` stays child-only, and the
  commit-only `VALID_EXECUTE_COMMIT` = `VALID_EXECUTE ∪ {off}` keeps create — which has nothing to
  clear — on the set-only `VALID_EXECUTE`), `notes`, then `completes` / `removes` (RTM soft-delete), then — when the commit
  carries a non-empty `order` — the **ORDER note** (DC-4, see below), then a `COMMIT` audit
  note on the project, and finally — on **any** non-empty commit — the **overlay-refresh mark**
  `#ai_overlay_refresh_needed` (`addTags`) is stamped on the project (Piece 0b; inside `if applied:`,
  so a zero-apply commit stamps nothing — an order-only commit IS non-empty since the note landed).
  Each write records its transaction (so `batch_undo`
  works); per-op failures are captured and the batch continues. (`#ai_progress_deferred` is a **new**
  tag — under strict-tag mode a `later` commit is rejected with a guided error until it's provisioned
  in RTM; the gate requires it only when a `later` is actually present, so `now`/`quick` commits stay
  backward-compatible. `gtd_project_canvas` mirrors this on read via `canvas_seed.map_prog` → the
  per-row `prog` field.)
- *The classifier vocabulary is CLOSED and now SAYS SO (v6.2.0).* `classifiers_to_tags` reads a
  fixed key set and ignores the rest. That is correct as a mapping and was a data-loss bug as a
  *surface*: `energy` and `estimate` were passed by callers for months, never read, never rejected,
  never reported — 17 live items landed without the two designations the Definition of Ready calls
  **required** for an action, with zero signal. Three things changed, and the third is the durable
  one. (1) **`classifiers.energy`** maps like `context`/`comms` — it *is* a tag, so routing it
  through the one function means `collect_commit_tags` / `collect_create_tags` feed it to the
  strict-tag gate for free. (2) **`estimate`** is applied on `adds[]` as it already was on
  `items[]`. (3) **`CLASSIFIER_KEYS` / `ADD_KEYS` / `ITEM_KEYS` name what each surface reads, and
  `unknown_keys` reports anything outside them into the receipt's `not_applied[]`** (reusing
  `NO_DURABLE_WRITE` — a new `ErrorCode` re-fingerprints all 100 tools). Checked at **both** levels,
  because the two measured losses sat one at each. The rule matters more than the two facets: **an
  unrecognised key is reported, never dropped**, which makes the next divergence between the three
  sibling item-creation surfaces self-announcing instead of silent.
- *`calendar_entry` is an accepted synonym of `calendar` (v6.2.0), and the asymmetry is the point.*
  The canvas grammar says `calendar`; `gtd_item_create` says `calendar_entry` — one domain concept,
  two spellings across sibling create surfaces, which cost a live 17-item plan its entire create.
  Widening is **additive**; renaming either spelling is not, because a *rendered* artifact board is
  a frozen copy of its template and therefore a live caller no repo grep can see (CONTRIBUTING
  § 2.8). Both map to the same `calendar_entry` tag, so nothing downstream can distinguish them;
  `calendar` remains canonical and is the only spelling the rejection prose offers. Full
  key-unification (`text`↔`name`, `type`↔`kind`) needs § 2.8's one-release alias machinery and is
  deliberately **not** done here.
- *ORDER note (DC-4 — durable reorder):* RTM has no sibling-order field, so a board drag is
  persisted as an **ORDER note on the project task** (`order_note.make` — title
  `YYYY-MM-DD HH:MM — ORDER — <n> items` in the account wall-clock, body one strict JSON object
  `{schema: "order-note/1", order, count, sha256, source: "board-commit", at}`); every consumer
  derives order from the **latest valid** note (this server's thin plan-graph on canvas read;
  gtd's enriched `plan_graph_refresh` from the same envelope notes), making RTM the single source
  of truth for order intent. Append-only: superseded notes are retained (latest-valid-wins makes
  pruning unnecessary); the note write is transaction-recorded like every other op, so
  `batch_undo` reverts it with the commit. Write ordering: the ORDER note lands **before** the
  overlay-refresh stamp, so a finalise fired off the mark can never read a commit whose note
  hasn't landed. The return flips `order_persisted` from `false` to the string `"order-note"`
  (naming the mechanism, deliberately not `true` — the board gates its optimistic "order saved"
  chip on exactly this value; an old board ignores it, a new board on an old server sees `false`
  and stays silent). No new tag — a note write, not a tag write; the strict-tag gate is untouched
  (though `collect_commit_tags` now counts `order` as an actionable op for the overlay-refresh
  mark, since an order-only commit stamps it).
- *Overlay-refresh mark (Piece 0b):* the enriched plan-graph overlay (the persisted AI-Memory DAG,
  written gtd-side by `plan_graph_refresh.py`) goes stale after a commit that carries no `execute`
  (a pure edit / reorder / note / complete / remove), because the progression engine drains the
  `#ai_progress_requested` work-list and stops on an empty list without refreshing. So every
  non-empty commit stamps `#ai_overlay_refresh_needed` (`collect_commit_tags` includes it in the
  up-front gate); the gtd-side `gtd-project-finalise` engine drains it (recompute + persist the
  overlay, then `removeTags`). The commit-path twin of `canvas_create.FINALISE_MARK` — same
  blackboard pattern, server stays vault-free. It is a **new** tag: under strict-tag mode it must be
  provisioned in RTM **before this server version is activated**, else the gate rejects every
  non-empty commit. (Only the *enriched* tier is affected — the thin graph is always recomputed
  server-side on read.)
- *Discipline:* tag writes use a **closed canonical classifier→tag mapping** (`canvas_commit`) +
  the strict-tag existence gate — the server holds no taxonomy (see Strict-Tag Mode). `order` ids
  are membership-checked like every other op and persisted via the ORDER note (the v1 no-op was
  retired by DC-4). Created/edited items carry `#ai_conversation`.
- *Commit `scope` + per-scope audit note + project-entity verbs (since v1.26.0):* an optional
  `scope` (`"instant" | "item" | "project" | "plan"`, default `"plan"` — `canvas_commit.VALID_SCOPES`;
  an unknown value is rejected up-front with an `invalid_scope` reason, nothing written) is a **label
  only** — it changes neither validation, the strict-tag gate, durable-first apply, nor `batch_undo`.
  It places the **one per-commit audit note** (written only `if applied`, on any non-empty commit):
  `instant`/`item` → on the single referenced item (its own id, else a freshly-created add, else the
  project as a defensive fallback); `project` → on the project entity, titled `COMMIT (<scope>)` so it
  never reads as a plan-wide COMMIT; `plan` → the bare-titled `COMMIT` note on the project (the
  pre-scope behaviour, byte-unchanged). The **overlay-refresh mark always stays on the project**
  regardless of scope — it is a finalise signal, not an audit trail. The **project-entity verbs**:
  `validate_commit` carves `project_id` out of the child-membership gate for `edits`/`notes`/
  `completes`/`removes` **only** (a project is renamed / journalled / completed / soft-deleted via its
  own id — `notes[project_id]` added in v1.27.0, since a note ON the project is a legitimate
  project-level journal entry), so those maps accept `project_id`; `execute`/`order` stay child-only.
  A `scope:"project"` add-project-note commit therefore writes **two** notes on the project — the
  user's content note AND the `COMMIT (project)` audit note (expected, not coalesced). The carve-out
  is `project_id`-only — an arbitrary non-child is still `cross_project`-rejected; the destructive
  verbs still require `confirm_destructive`. Completing/deleting the project writes the durable RTM
  state only — the
  server does **not** fire the gtd-side finalise engine (a board-side scheduled task owns that).
  Additive + backward-compatible: **no new tag** (the audit note is a note write), so no strict-tag
  interaction and no activation hazard beyond restarting the server on v1.26.0.
- *Complex-param contract:* the ops params (`order`/`edits`/`adds`/`completes`/`removes`/`execute`/
  `notes`) use the `tool_params` `Annotated` types — a **clean single-typed JSON schema** (no
  `anyOf`/null union, which some MCP clients serialise as a JSON string) plus a `coerce_json`
  `BeforeValidator`, with an in-body `coerce_json` belt-and-braces for callers that bypass
  pydantic. So the tool accepts both structured JSON and a JSON-string for any op.

**`gtd_project_create` (constrained write)** is the **create-sibling** of the commit tool: where
commit edits an existing project, create builds a brand-new one from a canvas draft. Same
validate-then-apply discipline, reusing the commit's tag taxonomy (`classifiers_to_tags`,
`execute_progress_tags`), strict-tag gate, `#ai_conversation` stamp, per-write transaction
recording (so `batch_undo` works), and batch-resilient `_write` helper. Payload: `frame`
(`{life, focus, name, outcome}`) + `items[]` + project-level `notes[]`.
- *Resolve + validate (no writes):* one read (`status:incomplete`) → `project_plan.resolve_focus`
  maps `frame.focus` to the destination **Area of Focus** (areas carry no marker tag — they are the
  parents of `#project` tasks; an explicit area id is also accepted; ambiguous name →
  `{candidates}`, miss → actionable `{error}`, **never create loose**). Then
  `canvas_create.validate_create` (missing_name, invalid_life, unknown_add_type, invalid_execute,
  unknown_dep) + one `enforce_strict_tags` pass over `collect_create_tags`. Any rejection → return
  with **nothing written**.
- *Order:* a **thin deterministic graph** — `build_graph` over synthesised rows carrying the items'
  in-draft `deps` — gives the dependency-respecting creation order and the per-item `blocked`
  judgement (used for the execute path). No vault access.
- *Apply (durable-first):* the project task is created **directly under the area** (`rtm.tasks.add`
  with `parent_task_id`, inheriting the area's list — **no `Processed` staging/reparent**, since
  create then attaches notes to the new tasks and a reparent would invalidate the add-response
  `list_id`) → `project_tags` (life + `#project` + `#ai_conversation` + the `#ai_project_needs_finalise`
  mark). Each child is created under the project (in graph order) → tags → priority → due → start →
  estimate. Then a second pass writes the **`DEPENDS-ON` notes** mapping each in-draft producer id to
  its created RTM id (the exact body `project_plan._extract_deps_and_files` round-trips, so the
  canvas shows the dependency graph on first reload), `execute` progression tags (mirroring commit;
  blocked items also get `#ai_deferred_pending_unblock`), per-item notes, create-then-complete for
  `done` items, project-level notes, and an `INCEPTION` audit note (with the outcome + counts).
- *The finalise mark:* `#ai_project_needs_finalise` is stamped on **every** created project — the
  durable signal the gtd-side discipline tail (vault folder / `context.md` / progression fan-out)
  drains. It is a **new** tag: under strict-tag mode it must be provisioned in RTM or every create
  is rejected up-front by the existence gate (unlike `later`'s `#ai_progress_deferred`, which is
  gated only when present, the finalise mark is unconditional). The progression **fan-out** itself
  is gtd-side; the server only writes the durable execute tags + the finalise mark.
- *Complex-param contract:* `frame`/`items`/`notes` use the same `tool_params` `Annotated` types +
  in-body `coerce_json` as the commit tool, so each accepts structured JSON or a JSON-string.

### Portfolio index (`gtd_project_index`)

`gtd_project_index` (`tools/gtd.py`, backed by the pure `project_index.py`) is the **read-only
portfolio roll-up** that powers the project-plan-canvas **navigator** (the Phase C cockpit picker) —
the third gtd read tool alongside `gtd_project_plan` / `gtd_project_canvas`. It answers "what's the
whole active-project landscape, and where does each project stand?" in ONE read.

**Read-only, one `getList`.** The tool issues a single `rtm.tasks.getList(filter="status:incomplete")`
(plus the session-cached `get_timezone`) — no timeline, no write — then hands the parsed tasks to the
three pure builders. That comprehensive read (the same posture as `gtd_project_plan`) carries every
project, every `#focus` area, AND every child in one response, so all three collections — and the
per-project counts — need no N+1 fan-out.

**Response shape `{projects, foci, actions}` (since v1.10.0).** The tool returns an object, not a bare
list. It is **backward-compatible** for the shipped navigator, which reads `data.projects` (the old
bare list became the `projects` key); the updated navigator additionally reads `foci` to render empty
focus areas and `actions` for fast search / jump-to. The three builders share one lifecycle gate
(`_active`: not completed, not `#test`, `#hold` always excluded, `#someday` opt-in) layered with the
membership tag (`#project` / `#focus`):
- `build_foci` — every active Area of Focus (incomplete `#focus`, same gate) as `{focus_id, focus,
  life}`, sorted `life → focus`. Sourced from the `#focus` tag directly so a focus with **zero active
  projects** still appears (the per-project `projects` rows can never surface one) — the gap that
  motivated the change (Paul noticed empty foci like a line-management area missing from the cockpit).
- `build_actions` — every incomplete child under an active project (actions + waiting-fors + calendar
  entries, all jumpable; an individual child tagged `#test` is skipped) as `{action_id, name,
  project_id, project, focus, life, type, due, priority, blocked, estimate, contexts, energy, exec,
  redacted}`, sorted `life → focus → project → name`. Reuses `project_plan.build_envelope` for each
  active project's rows, so attribution matches the canvas; every row carries a real project (no
  dangling-project rows; a top-level project's actions inherit `focus="(unfiled)"`). The kind +
  urgency fields come from work already done: `type` is the canvas's own `r.k` classification
  (`canvas_seed.map_kind` → `"action"|"waiting_for"|"calendar"`, since v1.12.0, for the find-result
  glyph); `due` the row's localised own date (`""` when none); `priority` the `"1"|"2"|"3"|""`
  encoding shared with the project rows; and `blocked` the per-row judgement of the **same thin
  `plan_graph.build_graph`** that feeds each project's `blocked_count` (so they agree by construction —
  an open `DEPENDS-ON` upstream within the project's own rows). `due`/`priority`/`blocked` shipped
  v1.11.0; `type` added v1.12.0.
  - The **engage-lens funnel fields** (since v1.29.0 — the Allen four-criteria model: context / time /
    energy / priority, each independently absent-able so a null exempts rather than hides): `estimate`
    = the RTM time estimate normalised to whole minutes (`parsers.parse_estimate_minutes`, or null);
    `contexts` = the action-context tags present (`_contexts`, verbatim, may be `[]` — no default,
    unlike `canvas_seed.map_context`); `energy` = `"high"|"low"|null` from the `#high_energy`/
    `#low_energy` pair (`_energy`; both present → null, a defensive data-error posture); `exec` =
    `"quick"|"now"|"later"|null` (`_exec`) — a **single-value read of the SAME classifier** behind the
    project `ai_quick`/`ai_now`/`ai_later` tallies (one classifier, two aggregations), precedence
    `now > later > quick`, so the engage lens's quick-win segment and the board's execute pill read one
    truth (they reproduce the tallies exactly on non-overlapping rows).
  - **Redaction on an action is server-derived and CASCADES** (since v1.29.0): a row is `redacted` when
    its own `#redacted` tag is set OR its project OR its Area-of-Focus is redacted — the earlier
    client-side cascade (see the Redaction surface note) is now enforced server-side, because the
    engage-field suppression depends on it. A **shielded** row leaks no characterising engage data:
    `estimate`/`energy`/`exec` are null and `contexts` is `[]`. (`build_index`/`build_foci` rows still
    carry `redacted` from their own tag only — actions are the only cascade.)

**`build_index` (pure).** For each project — incomplete, `#project`, **not** `#test`; `#hold` always
excluded and `#someday` excluded unless `include_someday=True` — it reuses the **parity-pinned**
engines so the navigator's numbers match the canvas exactly: `project_plan.build_envelope` (children +
localised dates + active `DEPENDS-ON` `deps`) and the **thin** `plan_graph.build_graph` (the blocked
judgement). It emits one row per project: `{life, focus, focus_id, project, project_id, priority,
open_count, blocked_count, next_tickle, updated, ai_quick, ai_now, ai_later}`, sorted
`life → focus → project`. Decisions:
- `open_count` = **all** incomplete children (actions + waiting-fors + calendar entries — the read
  only fetches incomplete, so it's `len(rows)`); `blocked_count` = children the thin graph judges
  `blocked` (an open `DEPENDS-ON` upstream **within the project's own rows** — cross-project /
  completed upstreams don't count, consistent with `gtd_project_canvas`).
- `next_tickle` = the earliest open `due` across the project's rows **including overdue** (`""` when
  none) — no clock dependency, so the builder stays deterministic.
- `ai_quick`/`ai_now`/`ai_later` (since v1.13.0) = the navigator's AI-progressible sort lens, tallied
  off the **same** classification the canvas uses so the index and an open plan can't disagree:
  `ai_quick` = rows the thin graph judges `quick_ready` (the canvas's `r.quick` — unblocked 2-minute
  `#quick_win` actions, stamped by `canvas_overlay.apply_graph`); `ai_now`/`ai_later` = rows whose
  `canvas_seed.map_prog(tags)` is `"now"`/`"later"` (the `#ai_progress_requested` / `#ai_progress_deferred`
  signal, the canvas's `r.prog`). `now` excludes blocked defensively; `later` may be blocked
  (queued-until-unblocked). Always present (`0` when none).
- `chat_count`/`chat_review_count` (since v1.16.0) = the per-project conversation counts for the
  navigator's conversation chip + "Conversations" sort lens — a standing count the artifact can't
  derive for a **non-open** project (it only loads the open project's rows). `chat_count` = incomplete
  items tagged `#ai_chat` (a conversation is underway); `chat_review_count` = incomplete items tagged
  `#ai_output_review_needed` (AI replied — Paul's turn). Review is a **subset** signal counted
  independently (the chip shows the total, tints amber when review > 0); the project task itself counts
  when it carries the tag (a project-scoped conversation). Incomplete-only (guarded on the row's
  `completed`, so a completed `#ai_chat` item never counts). Always present (`0` when none). Twin of
  the live-band `gtd_chat_inflight`: that is the real-time cross-project fleet, this is the standing
  per-project count in the index.
- `waiting_count` (since v1.18.0) = the engage-filter roll-up for the navigator's **Focus pill** —
  incomplete `#waiting_for` items in the project (the canvas's `r.k` `"waiting_for"` classification via
  `canvas_seed.map_kind`, so it matches the board glyph), unlocking the pill's deferred "waiting-for"
  segment. Same row set + completed-guard as the counts above; always present (`0` when none). Its
  sibling **`decision_count`** (the pill's "decisions" segment) is **not yet emitted** — the gtd tag
  taxonomy has no per-item "needs-you decision" marker (decisions live in the separate `AI_Questions`
  list, not as a `#decision`-tagged plan item), so the tag/rule is an open question for the gtd side
  (see the v1.18.0 handback debrief). The board reserves the segment slot and lights it up on a later
  additive bump with no board change.
- `focus`/`focus_id` come from the project's **parent** Area-of-Focus task; a top-level project is
  kept as `focus="(unfiled)"`, `focus_id=""` (never dropped). `priority` is the project's raw RTM
  priority coerced to `"1"|"2"|"3"|""`; dates are localised to the account tz (the BST off-by-one
  fix, via `project_plan._norm_date`).

**Vault-free (the membrane).** Counts derive only from the server's thin plan-graph — the enriched
AI-Memory overlay stays gtd-side, exactly as for the canvas/commit tools. Purely additive and
read-only: **no new tag, no strict-tag-gate interaction**, so no activation-ordering hazard.

### Conversation surface (`gtd_chat_post` / `gtd_chat_thread`)

The project-plan-canvas's **in-board AI conversation surface** — at the project level and on each
plan item Paul types an instruction (discuss / progress / query); a `runScheduledTask`-spawned
**headless worker** session acts on it and replies. The board's JS can call connector MCP tools but
not desktop-internal ones, so the board and worker converse through **RTM notes** (the system of
record), not a live session. The conversation is a new journalled note class, **`CHAT`**, attached
to the target task. These two `gtd_` tools are the efficient post + poll path; the full thread also
flows unchanged through `gtd_project_canvas` / `gtd_project_plan` as ordinary notes.

**The CHAT grammar (gtd owns the canonical definition; `gtd_chat.py` mirrors it server-side).** One
turn = one RTM note on the target task, title `YYYY-MM-DD HH:MM — CHAT — <role> — <scope>`
(space-em-dash-space separators; timestamp localised to the account tz). `<role>` ∈ `me` (Paul) |
`ai` (worker reply); `<scope>` is a display label (the attachment task is the real scope). Body =
the message; a `me` turn's posture `mode` (`discuss`|`act`) is a trailing `Mode: <mode>` footer line
that round-trips on read. **The title is the FIRST LINE of the note body, not a separate field** —
the RTM API has no note-title field, so the write stores `title\nmessage` in the single body field and
`rtm.tasks.getList` returns an empty `title`. A note is a CHAT turn iff its **body's first line**
matches `^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — CHAT — (me|ai) — ` (line 1 = title, lines 2..N = message);
`parse_turn` splits the body on the first newline accordingly — robust to notes authored by either
tool (the worker may use `add_note` directly with the same grammar). (Parsing the always-empty
`title` field instead was the v1.14.1 bug that returned an empty thread.)

**`gtd_chat_post` (governed write).** Validate-then-apply, nothing written on rejection. It
validates `role`/`mode`, resolves the task by id from **one** `rtm.tasks.getList` (`status:incomplete`
— chat lives on active work; `taskseries_id`/`list_id` resolved internally so the caller passes only
the id it has), then — for a `me` turn — runs the strict-tag existence gate over the two drain-signal
tags before any write. It writes the CHAT note, then manages the signal: `me` → `addTags`
`#ai_chat_requested` (the worker's durable work-list signal) + `#ai_chat` (has-a-thread marker); `ai`
→ `removeTags` `#ai_chat_requested` (the turn is answered), leaving `#ai_chat`. Each write records
its transaction (undoable via `batch_undo`); the helper is batch-resilient (per-op failures captured
in `errors`). The two tags are a **new** pair — under strict-tag mode they must be provisioned in RTM
account-side **before** activation, exactly as `#ai_overlay_refresh_needed` was for Piece 0b (the gate
requires `#ai_chat_requested`/`#ai_chat` only on the `me`-turn add path; the `ai` removal is never
gated). Tag removal reduces entropy, so it is never gated (CONTRIBUTING.md § 6).

**`gtd_chat_thread` (read).** The cheap poll path vs re-reading the whole canvas: **one**
`rtm.tasks.getList`, no write, no timeline, **no settings read** (so the read-only call surface is
exactly `["rtm.tasks.getList"]`). Since v1.16.1 the resolve read spans **`status:incomplete OR
status:completed`** — a prior conversation stays viewable after the task is done (CHAT notes persist),
so the board can offer "view prior thread" on a completed item without falling back to a misleading
empty state. It resolves the task by id, parses its CHAT notes into turns oldest-first (`build_thread`
— non-CHAT notes excluded, optional `since` ISO-8601 incremental filter), and reports `requested` =
whether `#ai_chat_requested` is currently set (so the board shows a "thinking…" state without a second
call) — naturally `False` for a completed task (no pending worker), so its history renders read-only.
Per-turn `created` is RTM's value (UTC, not re-localised — the localised display stamp lives in the
note title the canvas already renders). **Posting still requires an incomplete task**: `gtd_chat_post`
stays `status:incomplete`-only (the worker only drains `#ai_chat_requested` on incomplete items), and
on a miss does a second `status:completed` lookup so a completed target gets a clear "conversation is
read-only — reopen to continue" error instead of the generic not-found.

**Turn attachments (`files[]` / `links[]`, since v1.19.0; project-scope descendant scan since v1.20.0 — board-chat enrichment stages 2/2b).** Every
turn additionally carries server-derived attachments, **always present** (`[]` when none —
zero-not-absent, matching the index counts). `files` = `[{path, label, note_id}]`: the authoritative
record of a filed artefact is the **OUTPUT note's `FILING:` line on the same task**
(note-shape-catalogue § 3 — both the single-line `FILING: <vault-relative path> (+ .meta.md)` form
and the labelled continuation, where the FILING line ends with a dash and the path sits on the next
line). The selector is the note's **title type** (the body's first line, like CHAT): only
OUTPUT-typed notes are scanned — historic `FILING`-typed notes predate the convention and must not
match. The path passes through **verbatim** (companion marker stripped); an absolute or backslashed
path is malformed and skipped, never "repaired" (the gtd notes-audit owns flagging those). The
verbatim path is the client's **dedup guarantee**: it compares equal to a `FILED:` trailer echo in
the turn text, so the board prefers `files[]` and suppresses its own `FILED:` parse when the key is
present. *Time-correlation is conservative* (designed change § 2.8): an OUTPUT note attaches to the
**earliest `ai` turn created at-or-after it** — the worker files first, then writes the reply, so
the filing falls in the window `(previous ai turn, this ai turn]`; an OUTPUT note after the last
`ai` turn (or with no `created`) attaches to **nothing** (unattached is correct, never guess).
*Scope* (stage 2b, since v1.20.0): for an **item** target the scan covers the task's own notes only
(the v1 shape, byte-identical — no extra fields); for a **`#project`** target it additionally covers
the project's **descendant tasks** (`gtd_chat.project_descendants` — the same ≤3-level
`parent_task_id` tree `gtd_project_plan` walks, breadth-first; deleted excluded, **completed
included** — a completed action's filed output is still a project output), because a project's
artefacts are filed against its child actions. Each descendant-filed entry carries two extra
provenance fields `item_id`/`item_name` (the descendant that filed it; an OUTPUT note on the project
task itself keeps the plain three-field shape). The gate is the `#project` tag, not subtask
presence, and the same one-call read serves it — the broad `getList` already carries the children,
so the call surface stays exactly `["rtm.tasks.getList"]`. Correlation runs
over the **full** thread before the `since` filter, so incremental polls see the same attachments.
`label` = the OUTPUT note's title summary; `note_id` = the OUTPUT note (provenance). Only `ai` turns
carry files. `links` = `[{url, label}]`: `LINK: <url> — <label>` trailer lines parsed from the
turn's own text (line-anchored, uppercase keyword; em/en-dash or spaced-hyphen separator — the same
split the board's `chatParseTrailer` uses; no separator → label `""`). The trailer lines are left
**in** `text` — the board strips them client-side, and removing them server-side would break the
stage-1 fallback contract on older boards.

**`gtd_chat_inflight` (read, since v1.15.0).** The conversation cockpit's **cross-project live band**
(the F3 horizon): every incomplete item carrying an open CHAT thread (`#ai_chat`), across all
lists/projects, in ONE read — the "all my agents working right now" view the per-project canvas can't
produce. Same read posture as `gtd_chat_thread`: **one** `rtm.tasks.getList(status:incomplete)`, no
write/timeline/settings (call surface exactly `["rtm.tasks.getList"]`). The **broad** incomplete read
(not a `tag:ai_chat`-filtered one) is deliberate — each item's enclosing project is resolved by
walking `parent_task_id` (`project_plan._ancestor_chain`) to the nearest `#project`, and those
ancestor project tasks don't carry `#ai_chat`, so they must be in the result set. `build_inflight`
(pure) selects incomplete `#ai_chat` non-`#test` tasks and emits `{task_id, name, scope
("item"|"project"), status, project_id, project_name, last_activity}` per item, sorted status →
recency → name: `status` from tags (`#ai_chat_requested` → `in_flight`; else
`#ai_output_review_needed` → `awaiting_review`; else `open`), `scope` from `#project`, `last_activity`
= the most-recent CHAT note's `created` via the same `build_thread` (`""` when none). A loose item
with no `#project` ancestor keeps `project_id=""` (chip shows; can't load).

**Membrane / activation.** Vault-free — no AI-Memory awareness, pure RTM. The server introduces **no
new tag itself** (it *reads/sets* `#ai_chat_requested` / `#ai_chat`, and *reads* the account-
provisioned `#ai_output_review_needed`), so no activation-ordering hazard beyond provisioning those
tags + restarting the server on v1.14.0 (`gtd_chat_post`/`gtd_chat_thread`) / v1.15.0
(`gtd_chat_inflight`) so the tools are exposed. The gtd-side consumers (the
`project-plan-artifact.html` compose row + the F3 live band + the `gtd-chat-agent` scheduled task)
ship in parallel and hide entirely when a tool is absent/errors, so the board behaves exactly as
before until the server is on the matching version.

### Redaction surface (`redacted` read flag + `gtd_item_set_redaction`, since v1.17.0)

The project-plan-canvas's **viewing curtain**: a project or item tagged `#redacted` renders as a
locked placeholder (privacy for casual over-the-shoulder viewing). The sandboxed board may call only
`gtd_*` tools — not `list_tasks` / `add_task_tags` / `remove_task_tags` — so this adds the minimal
governed surface to *learn* and *set* redaction, keeping the "board never raw-writes RTM" discipline.

**Read side (additive, derived boolean).** `#redacted` surfaces as a `redacted` bool with **no new
tag, no strict-tag interaction on read**:
- `gtd_project_canvas` — each `seed[*]` item carries `redacted` (always emitted, from the item task's
  tag via `canvas_seed.map_redacted`), and `frame.redacted` carries the project's own state (from
  `project_plan.build_envelope`, which now also emits `header.project.redacted` — additive to the
  `project-plan-seed/3` envelope, so `gtd_project_plan`'s header carries it too; rtm_fetch.py parity
  is an upstream follow-up, same pattern as the earlier `files`/`prog` additions).
- `gtd_project_index` — each project row, each action row, **and** each `foci[]` row carries `redacted`
  (the board redacts at all three levels), derived in `project_index.build_index` / `build_actions` /
  `build_foci`. Project and foci rows derive it from the task's own tag; the **action** row is
  server-derived and **cascades** (since v1.29.0): own tag OR a redacted project OR a redacted focus
  (so the cockpit locks anything under a shielded parent from a single server-side flag). The focus
  flag (since v1.17.1) lets the navigator collapse a whole Area of Focus — name + its projects
  hidden — to a single "Redacted Area of Focus" row; the cascade onto that focus's *projects* is
  client-side. The `redacted` flag is **surface only** — every row (shielded or not) still carries its
  full data, including the engage fields; see the invariant below.

The tag constant `REDACTED_TAG = "redacted"` is defined once in `project_plan.py` (the low membership-
tag layer, alongside `_PROJECT_TAG`/`_TEST_TAG`) and imported upward (`canvas_seed`, `project_index`,
`tools/gtd`) — the same convention as those tags.

**Invariant — redaction is SURFACED, never ENFORCED, server-side (since v1.30.0).** Redaction is a
**client-side viewing curtain, not a server data vault** (Paul, 2026-07-13). The plaintext — names,
dates, notes, and the engage-lens funnel fields (`estimate`/`contexts`/`energy`/`exec`) — **flows to
the board for every row, shielded or not**; the board renders the locked placeholder, makes the row
non-selectable, and excludes it from the funnel (counts never leak). Enforcement — the actual
hiding — is **100% client-side**.
- **Allowed server-side (surface + write):** derive and emit the `redacted` boolean on read-tool
  rows / items / frames; set/unset `#redacted` via `gtd_item_set_redaction`. Metadata + the marking
  mechanism — not enforcement.
- **Forbidden server-side (enforce):** nulling, stripping, withholding, or dropping **any** field or
  row based on `redacted`. `grep -rn "redact" src/` must show only flag-emission + the
  `gtd_item_set_redaction` write — never a field/row suppressed on `redacted`. (v1.29.0 briefly nulled the
  action engage fields on shielded rows — an inconsistent over-hardening, since names already flowed;
  v1.30.0 removed it and codified this invariant. `test_project_index.py`'s
  `test_shielded_action_still_carries_engage_fields` /
  `test_own_tag_shielded_action_still_carries_engage_fields` are the guard.)

Hardening to a true data vault (null names/notes of redacted rows) would contradict this invariant
and is explicitly **not** wanted.

**Write side (`gtd_item_set_redaction`, constrained write).** Keyed by `task_id` (the board always has it
from the index/seed — no fragile name resolution). Resolves the task's full triple from **one**
`rtm.tasks.getList(status:incomplete OR status:completed)` (done items redact too), then a single tag
write: `redacted=true` → `addTags #redacted` (behind the strict-tag existence gate — `#redacted` is
account-provisioned, so it passes; a missing tag yields the guided error with nothing written);
`redacted=false` → `removeTags #redacted` (**never gated** — removal reduces entropy, CONTRIBUTING § 6).
The transaction is recorded (undoable via `undo`/`batch_undo`). Since v1.26.0 a one-line `REDACTION`
audit note ("curtain drawn"/"curtain lifted") is written on the item after the tag write — best-effort
(a note failure never undoes the tag write) and transaction-recorded (so `batch_undo` reverts it with
the tag change). It carries **no** `#ai_conversation` stamp — this is a user viewing-state change, not
an AI write. Returns `{task_id, redacted}`.

**Membrane / activation.** Vault-free, pure RTM. The server introduces **no new tag** — `#redacted`
already exists in the account, so there is **no activation-ordering hazard** (unlike the finalise /
overlay-refresh marks). Purely additive + backward-compatible: absence of the flag on older rows reads
as not-redacted; the board degrades cleanly (redaction shows nothing / marking no-ops) until the server
is on v1.17.0 and restarted.

### Template-child token stamping (`gtd_item_stamp_tokens`, since v1.25.0)

The **write** half of the repeating-templated-project feature. The read side landed in v1.24.0 (the
thin engine *resolves* token-space deps/pins — `project_plan._extract_deps_and_files` surfaces
`row.template_child_id` + token-space deps, `plan_graph._resolve_ref` maps a token to the current
occurrence's id) but was **dormant on live data** — no children carried tokens. This tool writes them,
switching the resolver on.

**The problem.** A repeating templated project re-keys every occurrence's children with fresh
`task_id` **and** `taskseries_id` (verified live 2026-07-05), so a DEPENDS-ON dep or ORDER pin authored
against a prior occurrence's raw id goes stale — the canvas shows wrong blocked/order after the project
recurs. **The mechanism that makes it fixable:** RTM copies a child's notes **verbatim** onto each new
occurrence. So a durable identity carried in a note survives recurrence — the **template-child token**.

**Grammar (note-shape-catalogue § 5b, ratified — the pure `tmpl_child.py`):**
- TMPL-CHILD note: title `YYYY-MM-DD — TMPL-CHILD — <slug>`, body
  `{"schema": "tmpl-child/1", "template_child_id": "<slug>"}`. `<slug>` = 8 lowercase hex
  (`secrets.token_hex(4)`), one per child, unique within the plan.
- DEPENDS-ON gains an additive `Template-child-id: "<upstream-slug>"` line (the raw `task_id:` line is
  retained as the human/fallback reference). This line **replaces** the raw id as the dep entry in the
  seed surface (`_extract_deps_and_files`), so once authored the seed emits the token and `_resolve_ref`
  maps it forward.

**Back-fill is the primary switch-on.** Because RTM propagates the notes, a token stamped **once** on
the current occurrence's children carries to every future occurrence — so the migration is: stamp the
current children of each existing recurring project once, and RTM does the rest. `gtd_item_stamp_tokens`
(constrained write): one `rtm.tasks.getList(status:incomplete)` + the session-cached settings read (for
the note date), then per unstamped **open** child a TMPL-CHILD note (`rtm.tasks.notes.add`) and per
active DEPENDS-ON note a re-author adding the token line (`rtm.tasks.notes.edit`), plus a `TMPL-STAMP`
audit note on the project (carrying the `#ai_conversation` marker in its body, keeping the TMPL-CHILD
JSON bodies pure). Each write is transaction-recorded (undoable via `batch_undo`).
- **Keyed by `project_id`** (validate `is_repeating`), or **omit to sweep** every active repeating
  templated project (`#project`, not `#test`, `is_repeating`). `dry_run=True` returns the plan
  (`stamped`/`dep_lines`) with nothing written.
- **Idempotent** — a child already carrying a `tmpl-child/1` token is **skipped** (never re-slugged;
  re-slugging would break the identity RTM has already propagated); a DEPENDS-ON already carrying the
  line is left alone. A second run is a no-op (no writes → no audit note).
- **One-off projects are never stamped** (no `is_repeating` → `skipped_reason: "not_repeating"`); their
  DEPENDS-ON stays raw-id, byte-unchanged, and the read path is identical (the one-off parity golden).
- **RTM note storage reality** (verified live): `notes.add`/`.edit` store the body as
  `<note_title>\n<note_text>` and return an EMPTY title field on read (the same fact the CHAT/ORDER
  grammars rely on). So to append the token line the reader body is split on the first newline — line 1
  is the title, the remainder + the new line is the text — and re-written via `notes.edit`.

**Add-time stamping (`gtd_canvas_commit`).** When an `adds` item lands on a repeating templated
project (`by_id[pid].is_repeating`), the commit stamps its TMPL-CHILD note after the reparent (fresh
slug, seeded-unique against the rows' existing tokens). Commit-adds carry no DEPENDS-ON, so no token
line is authored there. `gtd_project_create` needs no change — it never creates a recurring project, so
back-fill covers a project that later becomes recurring.

**Membrane / activation.** Vault-free, pure RTM. Introduces **no new tag** — the TMPL-CHILD body is
strict `tmpl-child/1` JSON, not a tag write, so there is **no strict-tag interaction and no
activation-ordering hazard**. Additive + backward-compatible: until stamped, a recurring project's deps
stay in raw-id space (the pre-Wave-B behaviour). To go live: restart the server on v1.25.0, then run
`gtd_item_stamp_tokens` (per project or a sweep) over the existing recurring projects. **Still open** (out of
scope): per-occurrence overlay keying in agent-memory `plan_graph_store`.

### Engage renegotiation surface (`gtd_engage_seed` / `gtd_engage_commit`, since v1.31.0)

The board-transport layer of the gtd **engage overdue renegotiation sweep** (approved designed change
`2026-07-14-engage-overdue-renegotiation-surface.md`, Increment 3): two governed tools letting the live
engage board run the same overdue-renegotiation sweep the chat funnel runs, across the sandbox membrane.
Processing the overdue field in GTD engage is a **renegotiation, not a reschedule** — most "overdue"
items carry a soft parked-date, not a real deadline ([[book-getting-things-done]]: the calendar is the
*hard landscape*; next actions live undated), so the sweep re-decides each item and routes it to its
correct GTD home; re-dating is only one verdict among several.

**The contract (single source of truth).** The verdict vocabulary, per-kind legality, the two flag
guards, and the verdict→RTM-write mapping are defined in the marketplace repo at
`plugins/gtd/skills/gtd/references/engage-verdict-grammar.md` (§§ 1-4). Both this server (`engage_commit.py`)
and the chat-side `validate-engage-verdict.py` conform to that grammar **independently** — codification
before validation; the server codifies the enum / legality / guards as Python constants (it is standalone
and cannot read the marketplace markdown at runtime). A grammar edit is a lockstep change to both.

**`gtd_engage_seed` (read-only).** ONE `rtm.tasks.getList(status:incomplete)` + the session-cached
`get_timezone` (for the localised `today`); no write, no timeline. Returns the overdue + soft-parked set
(`build_engage_seed`) — every incomplete dated item on-or-before today (overdue OR due today), NOT `#test`,
NOT `#someday`, all kinds — each with the server-derived flags (`kind`, `has_deadline` = `has_due_time`,
`blocked` = the thin plan-graph, `postponed`, `suggested`, `redacted`) + `current_date`. Modelled on
`gtd_project_index` (same read discipline, same flag-emission style). **Curtain-not-vault** (the v1.30.0
invariant): the seed emits `redacted` but NEVER nulls/withholds any field on it — the board is the sole
enforcer (locked placeholder, funnel exclusion, and the `askClaude` PII shield — redacted contents never
enter an `askClaude`/`callMcpTool` payload). A guard test pins no server-side suppression.

**`gtd_engage_commit` (the governed write — gtd's Anti-Corruption Layer).** Accepts the bounded
payload `{items: [{id, verdict, date_phrase?}]}` and re-validates EVERYTHING server-side — the board's
`askClaude` is advisory, never authorising a write. Modelled on `gtd_canvas_commit` (validate-then-
apply, batch, per-write transaction recording for `batch_undo`, `#ai_conversation`). The ACL discipline:
- *The only trusted client inputs are `id` / `verdict` / optional `date_phrase` (a hint).* Every legality
  flag (`kind` / `has_deadline` / `blocked`) is **re-derived server-side** from a fresh read (Paul's
  decision, 2026-07-14) — a hostile/buggy client cannot smuggle a bad flag past the deadline/blocked
  guards.
- *Verdict legality (HARD-FAIL).* `engage_commit.validate` rejects an off-enum or type-illegal verdict
  (the deadline guard: a `has_deadline` item allows only `do_now`/`to_calendar`/`keep`/`drop`; the blocked
  guard: `resurface` only when `blocked`) with a closest-legal suggestion. Any rejection → **nothing
  written** (no partial apply). `drop` needs `confirm_destructive`; a strict-tag gate runs over
  `collect_engage_tags` (all existing gtd tags — no new tag).
  **v2.0.0 LOCKSTEP:** the three emitted `reason` values were normalised from hyphens to underscores
  (`off-enum`→`off_enum`, `unknown-kind`→`unknown_kind`, `type-illegal`→`type_illegal`) when the
  reject vocabularies were unified into the `error_codes.ErrorCode` registry. These are
  **grammar-bound** — gtd's `validate-engage-verdict.py`, its tests, and `engage-verdict-grammar.md`
  were changed in the same release. Never re-spell them on one side alone.
- *Dates through `parse_time` (Europe/London, authoritative).* Resolved via `rtm.time.parse` in phase 1
  (before any write) — a hallucinated/unparseable `date_phrase` (e.g. on a `defer_start`) is a `bad_date`
  rejection that fails the batch, so a client-hallucinated final date is never written.
- *Verdict → RTM write (grammar § 4):* `next_actions`/`resurface` → clear the due; `today`/`bump:+<n>d` →
  set the due via parse_time; `defer_start:<phrase>` → set the START date; `nudge` → re-tickle the
  waiting-for's due to today (the chase draft is a chat concern, out of this tool); `someday` → add
  `#someday`; `to_calendar` → add `#calendar_entry`; `draft` → add `#ai_progress_requested` (hand to the
  progression engine; a blocked draft also gets `#ai_deferred_pending_unblock`); `do_now`/`keep` → no
  durable write; `drop` → soft-delete. Every tag/date write carries `#ai_conversation`.
- *Progression signal.* `someday`/`resurface` stamp `#ai_overlay_refresh_needed` on the item's nearest
  `#project` ancestor (deduped) — the server-side equivalent of firing `state_transition`, reusing the
  canvas-commit overlay-refresh signal so the gtd finalise engine recomputes the plan-graph overlay.
- *PROGRESS steer note (the per-item `note`, Tier 1 — since v1.32.0).* The board sends a short steer
  (Paul's typed text or its Tier-2.1 KG-grounded suggestion) alongside the three PROGRESS verdicts —
  `draft`/`do_now`/`nudge` (`STEER_VERBS`); every other verdict ignores any `note` silently. A consumed
  `note` is ACL-sanitised (`sanitize_steer` — advisory DATA never an instruction, never touching the
  legality re-derivation) and attached as a **`STEER` note** (`make_steer_note`: title
  `YYYY-MM-DD HH:MM — STEER — <verb>`, PURE body) on the item, so the `#ai_progress_requested` drafting
  path reads it as the first-pass instruction (`draft`), a chase steer (`nudge`), or a note-to-self
  (`do_now` — which otherwise has no durable write). Posture: a malformed steer (non-string / oversize)
  is DROPPED with a per-item `warnings[]` entry, the verdict write STANDS (a bad steer never fails a
  legal renegotiation). Idempotent — a re-commit of the same steer on the same item is skipped
  (`steer_note_text` probe; replace-or-skip), never duplicated. The note write joins the item's batch
  (reversed by the single `batch_undo`). The STEER note shape is minted here server-side; the gtd
  `note-shape-catalogue.md` entry + the `engage-verdict-grammar.md` § 4 note-attachment row are the
  lockstep gtd-side pieces (queued, not blocking — the board already sends `note` harmlessly, so the
  server lands first). **Follow-up (out of scope, flagged):** the drafting path must READ the STEER
  note for the payoff to land — confirm whether `#ai_progress_requested` already reads task notes, else
  a gtd-side change wires it.
- *Redaction-safe echo.* The success echo names each item by `id` + `op` ONLY (never its name/contents),
  so a redacted item leaks nothing.

**Membrane / activation.** Vault-free, pure RTM. Introduces **no new tag** — every write reuses an
existing gtd tag (`#someday`, `#calendar_entry`, `#ai_progress_requested`, `#ai_deferred_pending_unblock`,
`#ai_conversation`, `#ai_overlay_refresh_needed`), so there is **no strict-tag activation-ordering
hazard**. Additive + backward-compatible: to go live, restart the server on v1.31.0 (the PROGRESS-steer
`note` consumption landed additively in v1.32.0 — the field was previously tolerated-and-ignored, so an
older board sends it harmlessly and the server can land first). The board artifact profile that consumes
these tools (`engage-board-artifact.html`) is a separate Cowork follow-on.

### Wave 1 — retiring the MilkScript library (eight reads, since v2.9.0)

Eight additive read tools that replace the remaining nine `.ms` files in the gtd plugin's
MilkScript library (nine others already had `gtd_*` ports from Phases 0–4). Designed change:
`2026-07-25-gtd-milkscript-retirement`, Wave 1 of four.

**Why they are not ports.** A live sweep on 2026-07-24 found **~155 call sites across 18 `.ms`
files invoking methods that do not exist** — `getCreated`/`getModified` (the real names are
`getCreatedDate`/`getModifiedDate`), `tags[i] === "name"` (`getTags()` returns Tag **objects**),
`note.getTitle()`/`getBody()` (a Note has only `getContent()`). Every one had been live since the
file was written, hidden by the `x.getFoo ? x.getFoo() : null` guard idiom: **a null-coalescing
guard on a misspelt method never throws — it degrades into `null`, which downstream code reports
as "no data" and a human reads as "no activity".**

So the scripts are **not a reference implementation and there is no output-parity oracle** —
comparing against them would validate known-wrong behaviour. Each tool is built to its
**consumer's documented need** (designed change D1), and every deliberate divergence is named in
the owning module's docstring and pinned by a test. The rule that follows, and which this server
already obeys by being typed: **never guard a method call — guard values.**

**Two further defect classes were found during this build**, beyond the three the sweep named:

| Defect | Where | Effect |
|---|---|---|
| `Phase:` vs `State:` | `engine-telemetry-aggregator.ms` | The canonical CONTRIB body field is `State:` (`journaling-lifecycle.md`); `phase` is the *artefact frontmatter* field, which lives in the vault. Live: `State:` on 33 of 39 notes, `Phase:` on **zero** — the regex could never match, so every contribution's state was `unknown` |
| `"N days ago"` is not parsed | `weekly-review-stats.ms` | Not a MilkScript fault at all — an **RTM filter** one. `completedAfter:`/`addedAfter:` are real operators but do not accept that relative phrase. Measured: `completedAfter:"7 days ago"` → **0** rows; `completedWithin:"7 days of today"` → **53**. Every COMPLETED and ADDED figure the weekly review has ever shown was zero |

Combined with the two briefed faults, `gtd_engine_report`'s predecessor had **four independent
paths to a 0% acceptance rate** — which is why `monitor-outcomes-weekly` and
`-monthly` have been raising adaptation proposals from telemetry that was structurally zero.

**The tools** (all read-only — `readOnlyHint` + `idempotentHint`; no write, no timeline):

| Tool | Replaces | Consumer |
|---|---|---|
| `gtd_surface_queue` | `ai-surface-scan-questions.ms` + `-activity.ms` | `ai-surface-scan.md` §§ 3b/3c |
| `gtd_engine_report` | `engine-telemetry-aggregator.ms` | `monitor-outcomes.md` § 4c |
| `gtd_dependency_gaps` | `dependency-graph-detect.ms` | `dependency-graph-proposal.md` bulk pass |
| `gtd_tag_report` | `tag-audit.ms` | the `tag-audit-weekly` task |
| `gtd_review_report` | `weekly-review-stats.ms` | weekly review (in-conversation) |
| `gtd_item_stale` | `stale-items.ms` | weekly review |
| `gtd_workload_report` | `workload-balance.ms` | weekly review |
| `gtd_focus_index` | *(new capability)* | Horizon-2 view |

**`gtd_surface_queue` — the boundary that matters.** The server detects that a response
**EXISTS**; the agent decides what it **MEANS**. Intent parsing against `expected_response_shape`
stays agent-side, and `response_detected` is a filter, never a verdict. It is **inclusion**-based
across three named paths (`q_answered_tag`, `completed_unresolved`, `response_note`) — a
deliberate divergence from the brief, which specified detection by *exclusion* against
`note-shape-catalogue.md` § 2. Measured on the live lists, exclusion is unusable: **all 44** notes
on eligible items whose titles do not parse are engine-authored, as are the 50 parsed-but-off-
catalogue ones, so exclusion would fire on essentially every item. A false positive costs a wrong
resolve; a false negative costs one scan's delay — precision wins. The exclusion signal is not
discarded, it is quarantined in `unrecognised_notes[]` for the agent to judge.

**Cost discipline.** Three of these replace N+1 fan-outs with one broad read plus client-side
work: `gtd_dependency_gaps` (the `.ms` ran a `parent:` query per project — ~107 signed calls),
`gtd_tag_report` (a `tag:<name>` query per non-canonical tag — up to 87), and — as
`detectors.build_health_check` already did — the parent→children map. `gtd_engine_report` is the
one multi-read tool (five filters); every other Wave 1 tool is one `rtm.tasks.getList`, and
`gtd_tag_report` adds only `rtm.tags.getList`.

**Membrane / activation.** Vault-free, pure RTM, **read-only**. **No new tag**, no strict-tag
interaction, no write of any kind — so there is no activation-ordering hazard. Purely additive:
no existing tool changes name or shape, so the 36 scheduled tasks are unaffected and this can
ship at any hour. To go live: restart the server on v2.9.0. The gtd-side consumer migration, the
eighteen `.ms` deletions and the seven thin-launcher refactors land separately in the marketplace
repo.

**Naming.** All eight are born conformant to the CQS + aggregate-grouped standard now frozen in
CONTRIBUTING § 2 (designed change D6–D14), so the Wave 2 rename (v3.0.0, 24 tools) never touches
them.

### Wave 1b — closing four remembered-discipline gaps (since v2.10.0)

Each item deletes a rule a prompt or an agent had to *remember* and replaces it with something the
server enforces. Designed change: `2026-07-25-gtd-milkscript-retirement`, Wave 1b.

| Item | Deletes |
|---|---|
| `gtd_item_shape` | an agent hand-matching regexes read out of a markdown file |
| `clear_signal` on `gtd_chat_post` | a critical-marked "TRANSPORT RULE" telling the worker to BYPASS the governed write |
| `ACTIVITY_REPORT` → `ACTIVITY-REPORT` | a note title the server's own gate would reject |
| `gtd_contribution_transition` | a six-state machine that nothing has ever transitioned |

**`gtd_item_shape` — mechanism, not judgement.** `progression-fanout.md` § 3.created.a
classifies one newly-created action into a contribution shape; until now the agent read
`shape-patterns.md` at session start and applied the regexes by hand. The tool is **offline** — no
RTM call at all — and lives in `detectors.py` because it **reuses the same compiled pattern
objects** the `gtd_*_candidates` detectors use. That makes `shape-patterns.md`'s lockstep contract
(*an action the fan-out classifies as `draft` is one the deliverable detector would have found*)
hold **by construction** rather than by two lists being kept in step; a test asserts the object
identity, so a future copy-paste fails. `brief` is deliberately not returned — it is the
`#calendar_entry` tag, which a name-only classifier cannot see.

**`clear_signal` — a parameter replacing a bypass.** `gtd_chat_post(role="ai")` conflated writing
the note with clearing `#ai_chat_requested`. Right for a final reply, wrong for the interim step
notes a long turn journals so the board renders a live timeline — so `chat-worker.md` § 3.6 carried
a critical-marked transport rule telling the worker to hand-write those via `add_note`, *bypassing
the governed write*, leaving a hand-typed title for the note-shape gate to judge. `clear_signal`
defaults to **True**: the failure mode of the wrong default is a board polling forever, so a caller
who forgets it strands nothing.

**`ACTIVITY-REPORT` — an input vocabulary leaking into an output one.** The surface body-note title
was built as `item_type.upper()`, so `activity_report` produced `ACTIVITY_REPORT` — and the
note-title TYPE token is `[A-Z][A-Z -]*`, with **no underscore**, so `note_shape.check_title`
rejected it. **The server could write a title its own validator refuses**; latent only because
`RTM_STRICT_NOTES=shape` is off by default. Fixed by an explicit `SURFACE_BODY_NOTE_TYPE` map —
**the input enum and the output token are different vocabularies and must be MAPPED, never
derived** (identically to `q_activity` vs `q_activity_report` in Phase 4b). A test asserts every
emitted title passes the gate, and that the underscore form is exactly what it rejects. No existing
note is rewritten — the live legacy spellings (`ACTIVITY` ×13, `AR` ×4, `ACTIVITY REPORT` ×1) are a
measured backlog recorded gtd-side.

**`gtd_contribution_transition` — the metric that never meant anything.** Six states, one open,
three **judged**, two **invalidated**; the split is load-bearing because the acceptance rate is
`accepted / (accepted + edited + discarded)` and counting a never-assessed contribution as a miss
reads as a rejection Paul never made. `gtd_engine_report` now excludes the invalidated pair (and
anything not yet transitioned) from every rate denominator and reports `judged_count` /
`invalidated_count` / `unjudged_count` alongside, so a rate can never be read without its base.

*Nothing has ever transitioned a contribution.* Producing agents write `State: drafted` and never
touch the note again — live 2026-07-25: **32 `drafted`, 1 `surfaced`, 6 with no `State:` line,
zero terminal**. That is why the reported 0% acceptance rate is a property of the wiring rather
than of the work.

**Two live-data realities the parser has to survive** (both pinned by tests against the exact live
shapes): 6 notes carry no `State:` line at all, so the line is **appended** rather than the
transition refused — the absence is the old wiring's fault, and refusing would leave exactly those
permanently stuck. And 3 notes carry prose *after* the state word (one an entire paragraph), so
`current_state` reads the **first token only** — which also keeps it identical to `engine_report`'s
regex, so the two can never disagree. That prose is handed to the CONTRIB-UPDATE note rather than
quietly deleted.

**The vault mirror is the caller's.** The note's `State:` is the system of record and the
artefact's `phase:` mirrors it (inverted gtd-side on 2026-07-25 — RTM is queryable, the vault is
not). This server is vault-free, so the response returns `artefact_path` + `vault_mirror_pending`
and the caller does the mirror — the same posture as `gtd_dependency_gaps`' `vault_filter_pending`.

**Membrane / activation.** Vault-free, pure RTM. **No new tag** — `gtd_contribution_transition`
writes only notes, so there is no strict-tag interaction and no activation-ordering hazard. One new
`ErrorCode` (`no_contribution_note`), which — because `ErrorBody.code` is the inlined enum —
churns every tool fingerprint; that is structural and expected, not 97 tools changing behaviour.
Additive and backward-compatible: `clear_signal` defaults to today's behaviour and the
`ACTIVITY-REPORT` change affects only newly-written notes. To go live: restart the server on
v2.10.0.

### Wave 2 — the rename (v3.0.0, breaking)

25 tools renamed, `gtd_query` split into three, `contribution` added as a twelfth area. **55 GTD
tools, every one conformant to `CONTRIBUTING.md` § 2.** Nothing changed behaviour — same
parameters, same return shapes, same error branches. The full rename table is in `CHANGELOG.md`.

**Deprecated aliases carry the cutover.** All 25 old names remain callable, plus `gtd_query`, and
are removed at v3.1.0. An alias registers the SAME function object under the old name
(`mcp.tool(name=…)`) through a wrapper that does nothing but log — so there is exactly one
implementation per tool and the alias advertises a byte-identical schema (asserted, not assumed).
They exist for **cross-repo sequencing**, not for external callers: server and consumers live in
separate repos behind an async hand-off, so one is always ahead of the other and *either* order
breaks without them. **The invocation log is the gate for removal** — zero hits across a full
scheduled-task cycle, not elapsed time.

`gtd_query` is the one deprecated surface that SPLIT rather than renamed, so it is retained as a
dispatcher delegating to `gtd_item_today` / `gtd_next_actions` / `gtd_focus_projects`. Each of
those takes only the parameters its own view needs, making an invalid combination
**unrepresentable** rather than merely rejected (D11).

**The two amendments to the frozen map.** Both are consequences of Wave 1b shipping after the map
was written, and the first is the more instructive: `gtd_item_classify` was an imperative verb on
a read-only tool — **the standard drifted within four days of being frozen, in a wave whose own
brief claimed conformance.** It is `gtd_item_shape` from v3.0.0. And `contribution` became an area
because `gtd_contribution_attach` and `gtd_contribution_transition` are two operations on one
domain object with a lifecycle; splitting them across `note` and `contribution` would have put
siblings in different places, the precise outcome aggregate grouping exists to prevent.
`gtd_note_attach_output` stays under `note` — an output has no lifecycle, so there is no state
machine to hang an aggregate on, and the asymmetry is deliberate.

**D9 moved into this wave** (`scripts/check-tool-naming.py`, `make naming`) rather than waiting
for Wave 3, because an unenforced convention drifted in four days. Report-only at v3.0.0 — it
cannot block while the aliases are exposed, since the aliases *are* the non-conformant names.
A name matching neither lexicon is `unclassifiable` and never silently passes; `tests/
test_tool_naming.py` asserts the check FIRES on known-bad and unrecognised fixtures, because a
conformance check reporting zero findings because it skipped everything is worse than no check.

**Membrane / activation.** No behaviour change, no new tag, vault-free. To go live: restart the
server on v3.0.0. The consumer migration (33 files in the marketplace repo) lands separately, and
the aliases are what make that hand-off survivable in either order.

### Wave 3 — dropping the aliases (v3.1.0, breaking)

**26 deprecated surfaces → 0**, and `make naming` promoted to `--strict` (now part of `make
lint`). The tool count is unchanged at 55. `CHANGELOG.md` carries the old→new migration table,
which with the aliases gone is the **only** remaining migration path.

**Removal was judged by enumerating callers, not by watching a log.** The original gate — zero
alias hits across a full scheduled-task cycle — was dropped as disproportionate for a single-user
tool. Direct enumeration proved both cheaper and more effective:

| Population | Result |
|---|---|
| marketplace repo | 0 live call sites |
| scheduled-task specs | 0 — thin launchers name no tools |
| **rendered live artifacts** | **4 old names, found and fixed** |

**A rendered artifact is a frozen copy of its template, so it is a live caller no repo grep can
see.** The standing board held four deprecated names in its code *and* in its injected `mcpTools`
allowlist, seven days after the template had moved on. The two halves are coupled: an allowlist
naming only the old tool while the code calls the new one fails the permission check, so fixing
one without the other converts a working board into a silently broken one.

This also corrects a reasoning error in the designed change (§ 2a, D8), which argued for **no
alias window** on the grounds that `plugin-marketplace-ui-patterns` slots the tool name. True of
the base scaffold; false of gtd's own profile, which hardcodes the names — and once rendered,
freezes them. **The sweep checked the template layer and concluded about the rendered layer.**
Wave 2 shipped aliases anyway, for an unrelated reason (cross-repo doc sequencing), so the
compatibility layer that saved the live board was justified by an argument that had nothing to do
with the risk it actually covered. The next "clean break, no callers" judgement should ask
*rendered or source?* before concluding.

**The removal test owns its own list of 26 names** rather than importing the constant being
deleted — an imported list that had silently emptied would make every removal assertion pass
without checking anything, and the length is asserted before any iteration.

**A new stray-reference test found four stale user-facing strings** the rename had left behind:
two runtime error messages and the server's own advertised instructions still directed callers at
`gtd_query`. Nothing had ever asserted on those, so they would have survived indefinitely. The
test flags a removed name only OUTSIDE backticks — a backticked mention is documentation
explaining history and is correct to keep, which is the same live-call-site-vs-prose distinction
the caller enumeration drew.

**Also removed as dead scaffolding:** `GTD_QUERY_OUTPUT` (`models.py`) and `VALID_PERSPECTIVES`
(`gtd_reads.py`).

**Membrane / activation.** No behaviour change to any surviving tool, no new tag, vault-free. To
go live: restart the server on v3.1.0. **Rollback is a patch release** — restoring an alias is one
registration — so this is recoverable rather than a one-way door.

### Note-body construction — the tool constructs, the model supplies semantics (v6.0.0, breaking)

Implements the approved designed change `2026-08-01-note-body-construction.md`. **The LLM supplies
semantics; the tool supplies syntax** — anything a machine reads is *constructed* from typed
parameters, never *parsed* back out of model prose. Validation is the fallback for what you could
not construct.

The server was already most of the way there: `format_note_title` builds every title,
`state_body` builds the STATE marker, and every side-effect note's shape is built by its owning
tool (`gtd_note_attach_output`, `gtd_dependency_link`, `gtd_chat_post`, ORDER / TMPL-CHILD /
STEER). **One parameter was left.** `gtd_note_add(body=…)` was a single free string carrying three
structurally distinct things, and `check_block_order` validated only their ORDER, after the fact.

**`body: str` → `narrative: str` + `sources: list[str] | None` + `ai_context: dict | None`.**
`gtd_writes.assemble_note_body` emits narrative → `--- Sources ---` → `--- AI Context ---`
(note-shape-catalogue § 6 stays the authority for what that shape *is*), each block only when it
has content. **`check_block_order` was deleted, and the deletion is the deliverable** — a wrong
block order stopped being *rejected* and became *unrepresentable*.

Three decisions worth keeping:

- **The registry member survives its last caller.** `ErrorCode.INVALID_BLOCK_ORDER` is retired
  from `GTD_WRITE_REJECT_REASONS` (a scoped view) but stays in `error_codes.py`: the registry is
  **additive-only**, and a shipped code is never removed even when nothing can reach it.
- **Fingerprint churn was 18 tools, not one.** The designed change *reasoned* it would be confined
  to `gtd_note_add`; **measured, it is not** — `models.GtdWriteRejection.reason` advertises a
  closed enum sourced from `GTD_WRITE_REJECT_REASONS`, so shrinking that frozenset re-serialises
  the output schema of every governed write that can return a rejection. Structural, and the exact
  mirror of the documented "adding an `ErrorCode` churns all 100 fingerprints".
- **The advisory went live on this tool, by design.** Before v6.0.0 `gtd_note_add`'s only optional
  was `timestamp`, a boolean — excluded by `receipt.is_facet`, so the bare-call advisory could
  never fire. `sources` / `ai_context` are genuine facets, so it now fires on a narrative-only
  call, which is the modal journal note. That is the receipt working, not regressing: a caller who
  misspells `sorces=[…]` has it stripped client-side and reads *"none of: ai_context, sources"* —
  precisely the silent-partial-write the receipt exists for. An explicit `sources=[]` counts as
  *supplied* and silences it; a `sources` that arrives all-blank writes no block and says so in
  `not_applied[]`.

**Membrane / activation.** Vault-free, **no new tag**, no strict-tag interaction, no new
`ErrorCode`, no `note_shape` wiring (this tool calls `rtm.tasks.notes.add` directly, as all 37
`gtd_*` note writes do — the gate governs the generic escape hatch only). **Breaking on one
governed write:** every `gtd_note_add` call site changes shape. To go live: restart the server on
v6.0.0, in lockstep with the gtd-side edits (`SKILL.md` § System Journal,
`journaling-lifecycle.md`, `validate-note.py`'s block-order check becoming audit-only). Rollback is
a signature revert plus restoring `check_block_order` from history — no data migration, no
live-state change.

### The same rule applied to the close note — `gtd_inbox_item_close.narrative` (v6.3.0, additive)

`gtd_inbox_item_close` composed its COMPLETION body **entirely** from `derived_refs`: there was no
parameter for caller-supplied content, so a handler that wanted to record *why* an item was routed
the way it was had nowhere to put it in the note that closes the loop. The live consequence is on
record — the `plugin-marketplace-architect` `improvement_candidate` executor handler writes a
**preceding CONTEXT note** instead (claude-plugins `7f94464f1`). That is correct but worse in a
specific way: two notes where one was intended, joined only *positionally* — and the note-reading
protocol orders notes STATE-first, so "the note above" is not a stable pointer.

One optional `narrative`, threaded into `gtd_writes.inbox_close_body`. Four decisions:

- **Above the list, not below.** The derived items and the SOURCE back-pointer are what close the
  audit loop and are read mechanically; appending prose after them would put unstructured text
  between a reader and the structured tail. Same order `assemble_note_body` emits.
- **A FACET, not a payload.** It is legitimately absent — most closes have nothing to add — so it
  is deliberately NOT added to the eight v5.0.0 required-and-non-empty payload parameters.
  `derived_refs` stays required and non-empty, unchanged.
- **A blank narrative writes no block and says so**, reusing the v6.0.0 `not_applied[]` /
  `NO_CHANGE` precedent rather than emitting a bare blank line.
- **The advisory now fires on a bare close, and that is the accepted cost.** This tool declared no
  optionals at all, so `build_advisory` was silent by construction; `narrative` is its only one, so
  a close that supplies none reads *"none of: narrative"*. Exactly the `gtd_note_add` situation
  above — the modal call trips it — and accepted for the same reason: it is the only signal that
  survives a client-side strip of `narative=`.

**Membrane / activation.** Vault-free, **no new tag**, no new `ErrorCode`, no `note_shape` wiring
(the title is `format_note_title`'s and already conforms; this tool calls `rtm.tasks.notes.add`
directly). Additive and backward-compatible — a close without `narrative` writes a **byte-identical**
body, which is the load-bearing test. **One** fingerprint churns (`gtd_inbox_item_close`). To go
live: restart the server on v6.3.0. Rollback is a signature revert. Follow-on, gtd-side and out of
scope: the architect handler collapses back to one note.

### Output-filing integrity — the gate, the derived register, the reconcile read (v6.4.0)

Implements the approved designed change `2026-08-02-output-filing-integrity.md`, Moves 2, 3, 4
and 6a/6b. Moves 1 and 5 (artefact identity, the `source_action` write, the file-store tree gate)
are agent-memory-mcp's and do not touch this repo. **Move 6c — the four pure push-downs
(`band_closure` / `pin_feasibility` / `plan_item_defaults` / `draft_judgement`) — is deliberately
a later slice** and is scoped in the brief, not here.

**The measured problem, two root causes.** A read-only reconciliation on 2026-08-01 over **104
OUTPUT notes and 171 companion-tracked artefacts**:

| Finding | Measure |
|---|---|
| OUTPUT notes carrying a machine-readable `FILING:` line | **37 of 104 (36%)** — the rest in ten mutually incompatible prose dialects |
| Output-side filed artefacts with **no** OUTPUT note | **97 of 126 (77%)** |
| `FILING` paths broken by the 18 July vault reorganisation | **4** — the files exist at the new path; nothing detected it for a fortnight |
| `source_action`, the RTM↔vault join field that already exists in the schema | populated in **0 of 40** sampled |
| OUTPUTS registers across 11 projects | 4, of which 4 non-conformant and 1 project holding two |

1. **The join key is a location.** `FILING: work/…/x.md` records where a file *was*. Any
   reorganisation silently invalidates it — the four July breakages were correct when written.
2. **Filing and journalling are two unbound acts.** Nothing bound them, so the second was
   forgettable, and 77% of the time it was forgotten. `FIXTURE-A` and `FIXTURE-B` are the same
   seeded fixture run the same day through the same workflow; B produced a register and A did
   not, which is a reproducible demonstration that the write was **non-deterministic rather than
   gated**.

**Move 2 — the gate (`filing_gate.py`, `RTM_STRICT_FILING`, default `reject`).** With a vault
mounted, `gtd_note_attach_output` refuses a `filing_path` resolving to no artefact, or to one
with no companion. ONE new `ErrorCode` (`filing_unresolved`) with `error.details.rejected_by` ∈
`artefact_missing` | `companion_missing` — the v5.2.0 ladder, because a synonym would churn all
100 fingerprints for a distinction the details already carry. The gate runs **before the
resolver**, so a refusal costs zero API calls (asserted).

*The three constraints most likely to be got wrong, all pinned by test:*

- **An unmounted vault DEGRADES, never rejects.** `resolve_vault_root` returning `None` means the
  server cannot *see* the vault, not that the artefact is missing. The write proceeds and the
  receipt says it went unverified. Getting this wrong makes the server unusable on any machine
  without the mount.
- **"The vault is not here" and "the vault is here and the artefact is not" share no code path**,
  and are pinned separately. A single fixture that omits the vault would pass a gate that had
  collapsed the two — which is exactly how this defect would ship.
- **`resolve_vault_root` does not fall through on an explicit-but-invalid override**, so a
  mis-typed `RTM_VAULT_ROOT` lands in the *degrade* branch. Correct (an honest no-op), and noted
  here so nobody "fixes" it into a rejection. It is also the only hermetic way for a test to say
  "no vault": `vault_root=None` falls through to the host default, which on the development
  machine is Paul's real vault, and a test that walks it is not a test.

**`source_action` is checked but NOT required, and that is sequencing rather than timidity.**
Live population is **0 of 40**; requiring it would reject 100% of legitimate calls on day one. It
is reported on the receipt and counted by the reconcile read, which is what will make the
tightening judgeable once agent-memory's backfill lands.

**`unfiled=True` is the escape**, for the six measured cases where the deliverable is genuinely
inline message text. It skips the gate, requires an empty `filing_path` (claiming both is an
`invalid_input` rejection — a combination rule JSON Schema cannot express, so it is also a
`tool_help.COMBINATION_RULES` entry), and writes an `UNFILED:` marker **instead of** a `FILING:`
line. That substitution is load-bearing, not cosmetic: `gtd_chat.parse_filings` scrapes `FILING:`
lines to build a turn's `files[]`, so a placeholder path would be scraped as a real artefact and
re-enter the reconciliation as a broken link — manufacturing the very defect class being removed.

**A stated deviation from CONTRIBUTING § 6.** § 6 requires a *new* gate to ship default-off with
the enable decision separate. The design of record approved `reject` and Paul chose it, so the
flag and its enabled default ship together. `off` reproduces v6.3.0 byte-for-byte and is the
whole rollback plan; `warn` is genuinely observable now that the v5.1.0 file sink exists, unlike
the `warn` stage `RTM_STRICT_NOTES` skipped.

**Move 3 — the OUTPUTS register becomes DERIVED.** Rebuilt on every attach from the project's
descendant OUTPUT notes (`gtd_chat.project_descendants` + `parse_output_note` + `parse_filings` —
**reused, never a third parser**), deduped by path with the earliest date winning, ordered
date → action name → note id. That regeneration is the repair for four defects at once rather
than four separate fixes:

| Defect | Measured | Fixed by |
|---|---|---|
| the header line written TWICE | 4 of 4 live registers | `build_outputs_register` emits no header — RTM stores `note_title\ntext`, so the title IS line 1 |
| title truncated mid-word at 60 | 3 of 4 | cap removed (a project name is bounded in practice) |
| the register table's Output cell truncated mid-word | 3 registers | cap removed — it is a **human-read table** |
| the OUTPUT note's own title truncated mid-word | present, unnamed in the census | `elide()` — the one surviving cap, word-boundary-safe with a visible ellipsis |

**⚠ The migration trap, and why deriving dissolves it.** The duplicated line 2 was
*load-bearing*: RTM returns an empty title on read, so the old finder's second disjunct
(`extract_note_body(n).startswith("OUTPUTS:")`) was what actually matched. Removing the
duplication without updating the finder breaks re-location on every unmigrated register;
rewriting titles without updating the finder **reproduces the live duplicate-register failure**
on all four projects. So writer, finder and migration land together — and because the register is
now regenerated, migration is a rebuild rather than a careful edit.

**The finder matches the parsed TYPE, never a string prefix** (`is_outputs_register` via
`gtd_reads.parse_note_type`), because a prefix embeds the project name and a rename orphans the
register — which is not hypothetical: *Claude Coworking* holds **two** registers created 99
minutes apart on 2026-04-06, because `startswith("OUTPUTS:")` could not see the date-prefixed
one. The legacy prefix is accepted **for one release** so the release that lands the canonical
title does not orphan every existing register. With several present, `resolve_outputs_register`
picks the latest (the `order_note.resolve` precedent) and **reports the losers in
`duplicate_register_ids`, never deletes them** — silently merging two registers would destroy the
evidence that they diverged.

**Rebuilding drops what it cannot re-derive, and says so.** A register row whose OUTPUT note was
deleted, or which was hand-typed, disappears. That is correct for a projection — a projection
that preserves unsourceable rows is an accumulator wearing a projection's name — but it must not
be silent, so `register_paths()` diffs the old table against the derived set and the difference
is reported in the receipt's `not_applied[]`.

**Move 4 — `gtd_note_filing_gaps` (`filing_gaps.py`).** Six finding classes, read-only, one
`rtm.tasks.getList` plus ONE client-side vault walk (`companion.walk_artefacts` — the
`gtd_tag_report` precedent, replacing a per-artefact N+1). **An absent vault produces a PARTIAL
result**: the four `VAULT_DEPENDENT` classes are named in `gaps[]` and their `count` is `null`,
never `0` (`gtd_engine_report`'s rule). `walk_artefacts` returning `None` vs `[]` is what carries
that — "could not look" and "looked, found nothing" are different answers, and collapsing them is
what would let a vault-less run read as clean.

`prose_path` **detects and does not parse.** Ten mutually incompatible dialects were counted; the
server's job is to notice a path is being described, and interpreting ten dialects is not it.

**Move 6a — CHAT / ORDER contracts into `note_shape`** (tier 3). See the module-responsibility
row; the short version is that a tier-3 check earns its place only when the server *already*
holds the parser, and today exactly two TYPEs qualify.

**Move 6b — `gtd_note_report` (`note_report.py`).** The read that retires the `notes-audit`
agent's per-note subprocess. It calls the write gate's own functions **by object identity**
(asserted), so audit and gate cannot drift.

**Membrane / activation.** Vault-free in the write direction (the companion seam stays read-only),
**no new tag**, no strict-tag interaction, therefore **no activation-ordering hazard**. One new
`ErrorCode`, so **all fingerprints churn** — structural, from the enum being inlined into every
`ErrorBody.code`, not 102 tools changing behaviour. **Breaking on one tool**: `gtd_note_attach_output`
gains a rejection path it did not have, deliberately, with the `unfiled` escape in the same
release. To go live: restart the server on v6.4.0. Rollback: `RTM_STRICT_FILING=off` for the gate
(asserted), a signature revert for the rest. **The four live registers were NOT rewritten by this
change** — the derived writer regenerates each on its next attach, and the pre-migration bodies
are captured in the debrief; note edits are not undoable in RTM, so a bulk rewrite is a separate,
explicitly-authorised operational step.

## RTM API Quirks

### Response Normalization

RTM returns single items as dicts and multiple items as arrays. Use `ensure_list()` from `parsers.py`:

```python
from rtm_mcp.parsers import ensure_list

data = ensure_list(result.get("locations", {}).get("location", []))
# Always returns a list, even for single-item or empty responses
```

RTM also wraps arrays in dict containers (e.g. `{"tag": ["a", "b"]}`). Use `parse_nested_list()`:

```python
from rtm_mcp.parsers import parse_nested_list

tags = parse_nested_list(ts.get("tags", []), "tag")
# Handles: {"tag": "single"}, {"tag": ["a","b"]}, [], None
```

### Write Response Format

RTM returns different JSON structures for reads vs writes:
- **Read** (`getList`): `{"tasks": {"list": [...]}}`
- **Write** (`add`, `complete`, `setTags`, etc.): `{"list": {...}}`

`parse_tasks_response` handles both via fallback:
```python
task_lists = result.get("tasks", {}).get("list", [])
if not task_lists and "list" in result:
    task_lists = result["list"]
```

### Default List Resolution (tasks.add ignores settings.defaultlist)

RTM's `rtm.tasks.add` ignores the account's default-list setting when called without a
`list_id` — the task lands in the built-in Inbox (`7271150`), **not** `settings.defaultlist`
(the web UI's quick-add honors it; the API does not). `add_task` compensates: when no
`list_name` is given **and** the task is not a subtask, it calls `client.get_default_list_id()`
and passes the result as `list_id`. Subtasks are skipped (the parent's list governs). Falls
back to RTM's built-in Inbox only when no default is configured. The default is read from the
user's RTM settings, never hardcoded.

### List Flag Coercion (smart / locked / archived)

RTM returns list flags as the strings `"1"`/`"0"`. `parse_lists_response` coerces them to
bools, but `format_list` is **also** called directly on *raw* write responses (`add_list`,
`rename_list`, `archive_list`, `unarchive_list`). It therefore uses `_is_true()`, which accepts
both the raw string and an already-parsed bool — so the formatter is correct whether fed parsed
dicts (the `get_lists` path) or raw RTM dicts (the write-tool path). A naive `== "1"` check broke
the `get_lists` path because the value was already a bool there.

### Timeline Requirement

All write operations require a timeline:

```python
await client.call("rtm.tasks.complete", require_timeline=True, ...)
```

### Transaction Log and Undo

All write tools record their transaction in an in-memory log on `RTMClient` via `record_and_build_response()`. This helper extracts the transaction ID and undoable flag, records the entry, and builds the response envelope in one call:

```python
return record_and_build_response(client, result, data={...}, tool_name="add_task")
```

The transaction log (`client.get_all_transactions()`) enables:
- `get_timeline_info` — inspect the session's full write history
- `batch_undo` — undo multiple operations in reverse chronological order
- `undo` — marks the transaction as undone in the log after successful undo

Key classes:
- `TransactionEntry` (dataclass in `client.py`): `transaction_id`, `method`, `undoable`, `undone`, `summary`
- `record_and_build_response` (in `response_builder.py`): combines `get_transaction_info` + `client.record_transaction` + `build_response`

### Note Body Extraction

RTM stores note body text in `$t` (XML text node) or `body` depending on context. Use `extract_note_body()`:

```python
from rtm_mcp.parsers import extract_note_body
body = extract_note_body(note)  # Handles both "$t" and "body" keys
```

## Testing

Test-writing conventions (the respx + `FakeMCP`/`mock_client` patterns, the read-only
call-surface assertion, strict-tag rejection setup) are canonical in
[CONTRIBUTING.md](CONTRIBUTING.md) § 8. Run with `make test` (= `uv run pytest`).

### Test-suite inventory

This inventory is the canonical per-file test count (keep it in sync — CONTRIBUTING.md § 9).

Test files (1958 tests total):
- `tests/test_tool_schemas.py` — the six-surface tool-documentation contract, introspecting the REAL server (`rtm_mcp.server.mcp` → `get_tools()` → `to_mcp_tool()`): every tool + param described; behaviour annotations correct per class (read-only / additive / destructive; openWorldHint everywhere); closed-vocabulary enums asserted EQUAL to the canonical constants (priority/direction/scope/role/mode/execute/verdict — drift-proof); complex params expose a clean single-typed schema; every `outputSchema.properties.data` is a `success|error` union; success-shape spot-checks; the committed `tool-fingerprints.json` freshness guard (recomputes per-tool sha256 from the live server, asserts equality with the file, and asserts qualified-`mcp__rtm__` sha256 shape — family standard § 5); **the advertised error contract** (`TestAdvertisedErrorContract`, v2.1.1) — every tool that can return an envelope error documents one, and every code it can actually produce (derived from its own source via `ast`: direct `ErrorCode` refs + what `resolve_task_ids`/`resolve_list_id`/`enforce_strict_tags`/`error_from_exception` surface on its behalf) is NAMED in the description, so a new failure path fails the suite until documented; plus a guard-the-guard that some tools stay classified non-failable (else the other two pass vacuously); the perspective/depth advisory enums asserted equal to VALID_PERSPECTIVES/VALID_DEPTHS; the eight Wave 1 reads registered read-only and `_bounded_int` registered as an error-surfacing helper so their invalid_input contract is genuinely enforced; the contribution-state enum asserted equal to TERMINAL_STATES with the open state absent, and the shape-verdict vocabulary sourced from the detector constants; **the v3.1.0 removal contract** (a test-OWNED list of the 26 removed surfaces whose length is asserted BEFORE any iteration — an imported list that had emptied would pass vacuously; every removed name unresolvable; the `DEPRECATED_ALIASES` constant itself gone; all 28 replacements resolving; the tool count pinned at 55; no fingerprint records a removed surface) and **the `gtd_query` split** (each tool takes only its own parameters, none carries `perspective` forward, the cross-perspective parameters are gone, all three read-only); **the v3.3.0 selection-surface budgets** (`TestSelectionSurfaceBudgets`) — server `instructions` ≤ 2 KB and not leading with the legal disclaimer; every description ≤ 2 KB **or** on the reasoned `OVER_BUDGET_EXEMPTIONS` list, with a guard-the-guard asserting no exemption is stale (one that now fits would quietly license regrowth) and none names a dead tool; **every exempt tool states its read/write posture inside the front block that survives truncation** — the assertion that actually protects a caller, since the cap itself is only a proxy for front-loading; and every description opening as `<Domain> — <purpose>`, the marker being the model-readable half of the taxonomy; the v4.0.0 exemption list gains `gtd_surface_resolve` / `gtd_dependency_link`, both over budget SOLELY by the shared receipt block (47 tests)
- `tests/test_receipt.py` — the teaching receipt (v4.0.0). The two load-bearing properties are asserted against the **REAL server**, not a fixture, because the failure mode is a tool shipping without a receipt: every governed write documents it, and **no read does** (a receipt on a read would be a null advisory on every read in the server). Plus the reason vocabulary (`RECEIPT_REASONS` ⊆ `ErrorCode`, and an `ast` sweep asserting no call site stamps a *failure* code into `not_applied[]` — that would make a successful write look failed); the advisory's rules, each pinned to the measurement that produced it (fires only when EVERY facet is absent — the any-vs-all bug measured 82% vs 17.3%; silent when the tool declares no optionals; **a boolean is not a facet**, with a guard that `True` is excluded even though `isinstance(True, int)`); guidance severity ordering (a partial write must say PARTIAL and name `batch_undo`, or a blind retry double-applies what succeeded); `attach` preserving tool-populated entries and leaving an **error** envelope untouched; the eight tightened parameters asserted required + non-nullable on the **advertised** schema and rejected over a real in-memory client; that the receipt survives **MCP serialisation** in BOTH `structured_content` and the text block (the FakeMCP tests call functions directly and bypass that path entirely) — a test that must stub `RTMConfig.load` AND install its fake INSIDE the client context, because entering `Client(mcp)` runs the real lifespan and overwrites the client global, silently sending the call to the live account; and that `receipt.py` is a pure leaf with no async and no client import, so it can never become a gate; and the v4.1.0 narrowing (guidance SILENT on a full rejection and on a bare zero-applied response, present on partial-write and not_applied, partial-write still outranking not_applied) plus the cross-version dedent guards — a unit test on the wrapper and a server-wide check that each governed write's description reaches column 0 once the appended block is removed, both confirmed to FAIL on the pre-v4.0.1 form under Python 3.12; and the v6.0.5 advisory-prose guard — the advisory must NAME both recorded causes and ASSERT neither, the markup cause first, replacing a test that for four releases asserted only that the word "drop" appeared and so passed happily while the message told every caller a cause measured wrong 0 of 2 times; and the v6.1.0 leaked-markup detector — the tool-scoped anchor (the same string is a finding on one tool and silent on another), the HTML document that a naive `</…>` predicate flags and this one does not, the bare-tag dialect still naming what was lost, markup OUTRANKING the bare-call advisory, and the case that justifies it existing at all (it fires where the all-absent rule is silent) — plus `TestTheDetectorRunsOnTheRealServer`, the anti-vacuity pair driving the in-memory protocol end-to-end, because every pure-function test above would pass against a server that never calls the detector (60 tests)
- `tests/test_client.py` — client signing, API calls, settings + account-tag caching (incl. failure-not-cached + concurrent-timeline lock), transaction log, 503 retry, connection retry incl. connect-phase-timeout-on-write retry + mid-flight ReadError wrap + non-JSON response, POST/GET split (47 tests)
- `tests/test_config.py` — the v6.4.0 filing-gate flag (default `reject` — a stated § 6 deviation, asserted rather than assumed; all three modes; switchable off, which IS the rollback plan; a typo'd mode failing loudly at load rather than leaving the gate silently inert). Plus config load/save, file fallback (corrupt/wrong-type/unreadable JSON), RTM_AUTH_TOKEN env + token/auth_token kwargs, safety-margin bounds, 0600 save permissions, strict-tag toggle, write-gate flags (both default off, strict_notes mode vocabulary + normalisation + loud failure on a typo, list-target env toggle; **both gates asserted ON by default since v5.1.0**, each with its switchable-off escape hatch) (40 tests)
- `tests/test_error_codes.py` — the typed-error registry + v2.0.0 envelope: registry integrity (unique values, lower_snake_case spelling guard, str-mixin wire equality), RTM numeric mapping (key-set parity with `exceptions.ERROR_CODE_MAP`, known numerics, unmapped/None → `invalid_input`), `build_error` (minimal shape, `details` omitted-not-null, rtm_code preserved, prose carried verbatim, code serialised as a plain string), `error_from_exception` (RTM code mapped + numeric preserved; non-RTM fallback), the unified reject vocabularies (every reason is a registry member; shared reasons have one spelling; `destructive_unconfirmed` reconciliation; the three lockstep verdict reasons), and `ErrorBody` (`extra="forbid"`; canonical shape), write-boundary gate codes (note-shape has its own; list-target REUSES the pre-existing smart/locked codes; no synonym minted) (28 tests)
- `tests/test_middleware.py` — the call-boundary gate. **Every test runs through the REAL server via an in-memory `Client`**, not against the middleware class in isolation: the defect was never a validator's logic, it was that no validator ran on that path, and an isolated test would pass just as happily on a server that never registered the middleware. Valid calls pass unchanged (offline `gtd_item_shape`; a parameterless tool against a REAL client, since a mock's attributes don't serialise through the output schema); an invented parameter raises with a message naming BOTH it and the full valid set, and every unknown is named rather than only the first; **the rejection performs no write** — `client.call` is the single chokepoint every tool goes through, so zero awaits is the complete proof, and this is the assertion that matters (the rest are ergonomics); required-parameter validation still rejects, proving the fix added a check rather than replacing one; the no-passlist decision pinned at both halves (`_meta` is a sibling field on `CallToolRequestParams`; inlining it is rejected here with the better message, and an `_`-prefix rule would have let `_type_tags` through); an unknown tool is not this middleware's error; a guard that the middleware is actually registered on the real server; and the historical regression — the exact `gtd_inbox_capture(text=…, type_tags=[…])` call, naming `type_tags` and listing the four real parameters; and that the rejection actually EMITS its WARNING record (the v3.0.1 lesson — a control whose only output is a log record is unobservable if it reaches no handler); plus **v3.3.0's `TestRejectionTeaches`** — asserted on the message a real client receives through the real server: the rejection states what the tool is FOR (the wrong-*tool* case, which is what the original defect actually was), types each parameter and marks required, suggests the probable typo, carries the combination rule a schema cannot express (`gtd_inbox_capture` is text-only by design — the very rule the original caller violated), points at both the per-tool and index help payloads, still writes nothing, and stays coherent on a zero-parameter tool; and **v6.1.0's `TestLeakedMarkupIsLoggedNotBlocked`** — the leak detector covering the other 75 tools LOGS and never raises (asserted on `add_note`, 78x the traffic of `gtd_note_add` and the escape hatch where drift enters), with the guard-the-guard that a clean call logs nothing, and **exactly one** record per event on a governed write — the wrapper detects for the advisory but does not log, since two records would silently double-count the very measurement this detector exists to enable (25 tests)
- `tests/test_tool_help.py` — the **projection-agreement contract** (v3.3.0), the point of the affordance design: help is a projection, so these assert the projections AGREE with their source rather than restating them — a duplicated expectation would be the very drift the design prevents. The load-bearing tests iterate **every** registered tool: the contract's parameter table equals the advertised `inputSchema` properties exactly (no invented params, none omitted), required flags and enums match, and the error catalogue claims **only** codes the `ast`-derived reachable set allows (bounded against the SAME derivation `TestAdvertisedErrorContract` uses, so the two cannot disagree). Plus: every tool appears in the index and its purpose is a leading **substring** of its own description's first block (so the index can never promise what the description does not say); no tool yields a blank purpose (a tool added without a well-formed selection line fails here); the gtd family really does split into `bff`/`domain`, else the taxonomy adds nothing over the prefix; every `ErrorCode` member has a `RECOVERY` hint (an additive guard — a new code would otherwise silently degrade to the fallback); no stale entry in any authored table, **which caught a real error during the build** (a chain edge naming `assign_location`, a tool on the *official* RTM connector rather than this server); both arities are offline via `respx` with zero routes registered, so any RTM call would raise rather than pass silently; and `rtm_tool_help`'s own description is within the budget it enforces — it shipped 2,841 bytes over on the first pass; and (v5.1.1) a collection-shaped read is classified `bff` — `gtd_surface_queue`, absent from the authored table until it blew the client's tool-result ceiling in chat — asserted `either` rather than `artifact` because no board reads it, which is the evidence that shape and audience are two axes (27 tests)
- `tests/test_note_types.py` — the four vocabularies: the write set is the documented union AND is composed by union **in the source** (an `ast` check — value-equality passes against a hand-typed duplicate that matches today); the ASYMMETRY both ways (no legacy spelling is writable; every legacy spelling is still recognised) — losing the second half does not raise, it silently mis-classifies live notes; the underscore form readable, unwritable, and unwritable by construction; a legacy rejection says LEGACY not unknown; every emitted surface body type and every `JOURNAL_NOTE_TYPES` member is writable (the governed path can never write what the escape hatch refuses); every bare marker writable when date-prefixed; the five surface body types are catalogue members not legacy; SCOPE registered; and the tokens the remediation rewrites are NOT registered — registering any would make the pass pointless (13 tests)
- `tests/test_note_shape.py` — note-shape gate (write gate 2): **`TestTheContractTier` + `TestTheShippedContractTierIsLive`** (v6.4.0) — the tier-3 per-TYPE contract: a malformed CHAT title and a non-conformant ORDER body each rejected with their own `rejected_by` and NO new `ErrorCode`; conformant ones pass; **a title-only ORDER edit is NOT judged** (the check reads the body, and `edit_note` supplies none on its title-changing path); **`shape` mode does NOT run the tier**, which is what keeps it a byte-for-byte v5.1.0 rollback step rather than something merely close to it; an unaffected TYPE passes untouched; the guidance names the constructing tool AND its own shipped default; plus the real-`RTMConfig` liveness test, because every test in the tier class passes against a server whose default never reaches tier 3 — the exact vacuity that let the shape gate ship inert for two releases. Also: the mechanical grammar (well-formed titles incl. hyphenated/spaced TYPE, T-separator, en-dash tolerated as the gtd validator tolerates it; malformed titles; impossible calendar date + wall-clock time rejected; **an unknown TYPE PASSES — the ownership boundary**, i.e. `check_title` is shape-only and always was; the VOCABULARY verdict is `check_type`'s), `effective_title` (explicit title wins, else the body's first line — RTM's `title\ntext` storage), the three modes (off inert, absent-config-attribute inert, warn logs-but-allows, shape rejects/allows, body-first-line judged), guided error (code + rejected_title + expected_shape + how_to_proceed pointing at the plugin catalogue, and **naming the shipped default** — the pre-v5.1.0 text told a caller to *unset* the var, which after the flip is advice to leave it on); **the shipped default is LIVE** (`TestTheShippedDefaultIsLive` drives a REAL `RTMConfig` rather than a mode-forced double — every other test in the file passed for the two releases the gate shipped inert: malformed rejected with no env set, off-vocabulary TYPE now REJECTED — that assertion was INVERTED at v5.2.0 and carries its previous claim in the docstring; the legacy `ACTIVITY`/`AR`/`ACTIVITY REPORT` spellings now fail on VOCABULARY while `ACTIVITY_REPORT` still fails on SHAPE, Paul's free-text note rejected only because it is an MCP write, and `off` restoring pre-gate behaviour); **the vocabulary tier** (v5.2.0 — a registered type passes, an unregistered one is rejected, `shape` mode still lets it through so the rollback lands on the PREVIOUS behaviour rather than near it, an unparseable title is a SHAPE finding and a well-shaped unknown type a VOCABULARY one, no new `ErrorCode` minted, and the guidance teaches codification-before-validation); and `TestTheShippedVocabularyDefaultIsLive` over a REAL `RTMConfig` — because every test in the tier class passes against a server still defaulting to `shape`, the exact vacuity that let the shape gate ship inert for two releases with a green suite. **Four pre-existing tests were INVERTED** and carry their previous claim in the docstring, since a test whose assertion silently flips has stopped documenting a decision (66 tests)
- `tests/test_list_targets.py` — list-target gate (write gate 3): `check_target` (writable passes; smart → SMART_LIST_TARGET; locked → LOCKED_SYSTEM_LIST; smart wins when both set — one input, one verdict; **archived NOT gated** — RTM still accepts items, so refusing is policy the server doesn't own; missing flags default allowed), `enforce_list_target` (off inert, absent-config-attribute inert, on accepts/rejects + logs), guided error (code + rejected_list + how_to_proceed naming get_lists and the plugin list-catalogue, and **matching the shipped default**); **the shipped default is LIVE** (`TestTheShippedDefaultIsLive` over a REAL `RTMConfig`: smart + locked each rejected with no env set, writable passes, **archived still passes** — deliberately ungated, load-bearing now the gate is on — and `0` restoring pre-gate behaviour) (19 tests)
- `tests/test_strict_tags.py` — strict-tag guard: normalize/split/SmartAdd-extract + enforce_strict_tags (off / reject / live-refetch / input normalization) (13 tests)
- `tests/test_project_plan.py` — project-plan-seed/3 envelope builder: header/row mapping, priority word-form, id-based permalink (absent ancestor), deps/files extraction, project-level `header.project.files`, None→"" coercion, tz date-localisation (BST off-by-one fix, GMT-unaffected, no-tz fallback, completed/note dates), resolve_project disambiguation, resolve_focus (by id/name/substring, area-from-project-parents, ambiguity, miss, project-less area), header.project.redacted flag, envelope note objects carry the RTM note id, seed-3.1 repeating signals (is_repeating/taskseries_id default-false on rows + header.project; surface True from the parsed rrule flag), seed-3.1 resolve-references token surfacing (template_child_id default-"" on rows; a TMPL-CHILD `tmpl-child/1` note surfaces the row token; a DEPENDS-ON `Template-child-id:` line authors the dep in token-space) (34 tests)
- `tests/test_project_index.py` — portfolio builders: `build_index` (selection (incomplete/#project/not-#test; #hold always excluded; #someday default-out/opt-in; completed-project excluded; empty), field-set shape, life-from-tag, focus/focus_id from parent (+ top-level → `(unfiled)` not dropped), priority mapping (1/2/3 and N→""), `updated` tz-localisation (BST), open_count = all incomplete children, blocked_count from a DEPENDS-ON edge, next_tickle earliest incl. overdue (+ empty), life→focus→project sort); AI-progressible counts (ai_quick unblocked #quick_win actions, excludes blocked + waiting-for; ai_now #ai_progress_requested excl. blocked; ai_later #ai_progress_deferred incl. blocked; zero-not-absent; canvas-seed parity); conversation counts (chat_count incomplete #ai_chat + chat_review_count #ai_output_review_needed; completed excluded; review subset-not-additive; project-scoped counts the project; zero-not-absent); engage counts (waiting_count incomplete #waiting_for, canvas-kind parity, completed excluded, zero-not-absent); `build_foci` (all #focus areas incl. project-less; field-set; life-from-tag; #test/#hold excluded; #someday gated; untagged area not a focus; life→focus sort); `build_actions` (incomplete children of active project; field-set + attribution incl. type/due/priority/blocked; #test child excluded; excluded-project child not emitted (+#someday opt-in); top-level → `(unfiled)`; deterministic grouped sort); action kind + urgency fields (type matches canvas r.k incl. default; due carried + localised + empty; priority encoding; blocked matches plan-graph (+ false on absent/cross-project upstream); waiting-for/calendar due); action engage fields (estimate normalised to minutes incl. ISO + null; contexts pass-through in canonical order + empty; energy high/low/both-null/neither-null; exec quick/now/later/abstain + now-directive-beats-quick + blocked-now-abstains + tallies-match-project ai_* counts); redaction (project-row + focus-row `redacted` from own `#redacted`; action-row own tag + CASCADE from redacted project + CASCADE from redacted focus; shielded action still carries full engage fields via own tag AND via cascade — surface-not-enforce invariant); completed-row guards (counts/next_tickle/actions exclude completed children when fed a broader parsed set) (73 tests)
- `tests/test_engage_commit.py` — server-side engage verdict grammar: enum + families, per-kind base legality (action/waiting-for/calendar-entry/project edges), the two flag guards (deadline collapses the set + precedes blocked; blocked enables resurface), off-enum/type-illegal/unknown-kind rejection with closest-legal suggestion, `suggest_verdict` (pre-triage + always-legal invariant), `base_verdict`/`verdict_arg`, `date_phrase_for` (today/bump→"in N days"/defer_start/non-date→None), `collect_engage_tags` (per-verdict tag union; no-op verdicts write no tag); PROGRESS steer helpers (`STEER_VERBS` = draft/do_now/nudge only; `sanitize_steer` clean/none/empty no-op, non-string drop+warn, control-char+whitespace collapse, oversize truncate+warn; `make_steer_note` title + pure body; `steer_note_text` round-trip + multiline + non-STEER rejection) (34 tests)
- `tests/test_engage_seed.py` — overdue-set builder: selection (overdue + due-today in, future/undated out; completed/#test/#someday excluded; due→name sort; empty), server-derived flags (kind from workflow tag incl. calendar_entry/project; has_deadline from has_due_time + suggested keep/next_actions; postponed carried; blocked from the thin plan-graph + resurface suggestion; waiting-for→nudge), redaction curtain-not-vault (own #redacted + cascade from redacted #project/#focus; unshielded false; every shielded row carries the full field set — the no-suppression guard) (14 tests)
- `tests/test_gtd_writes.py` — Phase 1 pure write grammar: the seven Tier-1 vocabularies (client in life contexts, project excluded from item kinds, calendar_entry NOT a workflow state, energy/MoSCoW/journal-type membership), tag materialisation (calendar entry = action + calendar_entry, action context default, waiting-for gets no context/energy, extra-tag merge), the hard-gated DoR per kind + relational-advisory, note grammar (em-dash title, STATE marker idempotent) + the **v6.0.0 body ASSEMBLY** — the byte-equality test that proves this is a surface change (`assemble_note_body` reproduces the exact string the deleted `check_block_order` accepted as well-formed), each block alone, a caller's own bullet absorbed rather than doubled, an AI-Context value flattened to one line, an empty block emitting no bare delimiter, and the render helpers agreeing with what assembly emits (one rule, one place — so the receipt can never disagree with the body); plus `TestBlockOrderIsUnrepresentable`, which REPLACES the rejection tests rather than adapting them — `check_block_order` is gone, so the assertion moves from *the bad order is refused* to *the bad order cannot be asked for*, and the retired reason is asserted absent from the scoped view while still present in the additive-only registry; and every validator rejection path (off-enum, missing name, DoR gap, smart Processed, note type, empty capture, transition overlap + double workflow state + double life context); plus the v6.3.0 inbox-close narrative (rendered ABOVE `DERIVED ITEMS CREATED:` by byte-equality, a blank one collapsing to no block AND no bare blank line, and — the load-bearing one — an absent narrative reproducing the pre-parameter body byte-for-byte, since the parameter must be invisible to every existing caller) (114 tests)
- `tests/test_contribution.py` — the CONTRIB state machine: the six states and the judged/invalidated split carried on every one; every terminal reachable from `drafted` and every terminal→terminal rejected; the open state and each RETIRED value rejected as `off_enum` with a reason that says which; a missing CONTRIB note as its own reason, checked AFTER the input error; note location (CONTRIB and PREP found, **`CONTRIB-UPDATE` is NOT the state bearer**, latest wins, hyphenated types not split at their own hyphen); body fields (state/category/artefact, PREP→brief, rewrite replaces-or-appends, indentation preserved, only the first line rewritten); the CONTRIB-UPDATE note (**title passes `note_shape.check_title` for every terminal** — the ACTIVITY_REPORT defect cannot recur; `Update mode:` only for the invalidated pair, where the catalogue's reassessment vocabulary actually maps); and `TestLiveStateLineContamination` — the three exact live `State:` lines carrying prose, pinned so first-token parsing, transitionability, clean rewrite, prose preservation and agreement with `engine_report` all hold (50 tests)
- `tests/test_shape_classify.py` — single-item shape classification: **every pattern in the vocabulary classifies to its own shape and every anti-pattern knocks out what it claims to**, each with a guard-the-guard test asserting the sample set actually trips every pattern (so a new or mis-transcribed regex fails here rather than sitting unused); the `evaluate the options` ambiguity resolves to `research` AND reports `decide` as also-matched; an unclassifiable name returns `none` with no guess; a calendar-entry name returns `none` because `brief` is not lexical; a knocked-out shape explains the `none`; and the lockstep asserted by OBJECT IDENTITY with the detector constants, so a future copy-paste fails (81 tests)
- `tests/test_detectors.py` — faithful-port unit tests for the 9 detector builders: reassessment (CONTRIB/PREP tag_set, personal-optin skip, stale-threshold skip, id dedup, oldest-modified sort), unblock (5 source classes + dedup precedence, active-BLOCKER-title vs BLOCKER-RESOLVED, disqualifying-tag skip, cap-applied-last, speculative-stale gate), decision/deliverable/research (pattern match + anti-pattern skip, personal opt-in tags, research default-horizon active, exclude_drafted, effective-date sort), calendar-prep (horizon window + HH:MM time + the `||2` zero-quirk), capture (window cutoff, status, newest-first sort), topic-cluster (threshold + ≥2-projects + person-tag type, trivial-tag + workflow-state gates), health-check (5 categories incl. stuck-project vs has-next-action, subtask-only #2/#3, non-subtask #4/#5) (28 tests)
- `tests/test_filing_gaps.py` — the v6.4.0 reconciliation builder. **The two load-bearing classes are the guard-the-guard and the absent-vault pair.** One fixture trips all six finding classes at once, and `test_each_class_has_at_least_one_row` fails if it stops doing so — otherwise a class could go dead and every per-class assertion would pass vacuously. `TestAnAbsentVaultIsPartialNeverClean` pins the whole point of the tool: the vault-dependent classes NAMED in `gaps[]`, their counts **`None`, never `0`**, the RTM-only classes still answering, and — the other half of the distinction — a **mounted-but-empty** vault reading as genuinely clean, since collapsing `[]` into `None` would make an empty vault indistinguishable from an absent one. Plus per-class row shapes, truncation announced with a true count, and the vault walker (companions and the vault marker excluded, untracked artefacts INCLUDED with `meta: None` because "filed but untracked" is itself a finding, and the runaway limit) (16 tests)
- `tests/test_note_report.py` — the v6.4.0 note audit. **The free-text rule first**, in all four directions: no date prefix is never a finding, a date-prefixed bad TYPE is the finding, a date-prefixed title that fails to PARSE is still agent-written (the discriminator is deliberately looser than the strict title regex, which would exempt exactly the malformed titles that matter), and the rule is restated in the payload. **`test_it_uses_the_gates_own_functions` asserts OBJECT IDENTITY** with `note_shape.check_title`/`check_type`/`check_contract` — a copy-pasted second grammar would pass a value comparison happily on the day it was written and drift the week after. Plus the CHAT/ORDER contract classes, FILING-path shape (with the two-line labelled-continuation form tolerated, since a dangling FILING line belongs to the two-line parser), a reachability guard over every class, and announced truncation (13 tests)
- `tests/test_gtd_reads.py` — collection/context builders: parse_note_type grammar + classify_gtd_type precedence; gtd_query (context attribution incl. using_device default + filter, today's-field overdue-first sort, focus-projects attribution + unfiled + scoped); inbox three signals; waiting-for staleness + stale-first sort; resolve_task_ref (id/name/miss/ambiguous candidates); context bundle (STATE-first note order, medium siblings+ancestors, shallow omits relations, deep includes bodies); **`TestHyphenatedTypesAreOneToken`** (v6.1.1) — the hyphenated-TYPE guard, whose sample set is DERIVED from `note_types.WRITE_AUTHORISED_NOTE_TYPES` so a new hyphenated type joins the test automatically, with a guard-the-guard asserting the set is non-empty (a hand-listed set that had emptied would pass vacuously against the very regex that carried the bug); every hyphenated type parses whole; the exact regression (`AI-LINK`); **all three read parsers agree** (the cross-module invariant that would have caught it — reaching for the private regexes deliberately, since the agreement is the contract and has no public surface); the spaced-hyphen separator still parses (so the fix was not achieved by simply banning the loosening the guard protects); and the write gate pinned as safe *for a different reason* — `note_shape._DASH` excludes the plain hyphen — so nobody "harmonises" the four grammars onto one form and reintroduces the defect from the other direction (20 tests)
- `tests/test_canvas_seed.py` — canvas mapper: kind/priority/context/comms, `map_prog` tri-state + per-row `prog` emit, parse_note (dash/colon forms, body-omit), parse_file filtering, map_row, `map_redacted` + per-item `redacted` always-emitted + `frame.redacted` from project, build_seed frame + sibling-deps + history placement + v1 `frame.files` from project files (23 tests)
- `tests/test_plan_graph.py` — plan-graph engine: DEPENDS-ON edges + blocked, quick-from-tag (and blocked/waiting-for guards), tiered topological order, cycle fallback, fingerprint stability; manual-order pin (clamping parity with the gtd suite one-for-one: pin reorders independent siblings, cannot violate topology, unpinned fall after pinned, cleaned to current ids, no-pin unchanged, excluded from fingerprint); MoSCoW band within-tier sort (parity with the gtd suite one-for-one: Must>Should>Could>untriaged-last, untriaged after Could, numeric "1"/"2"/"3" surface accepted, band-beats-date, tier-outranks-band, never-violates-topology, pin-outranks-band, band change flips fingerprint incl. band→absent); resolve-references token resolution (parity with the gtd `test_plan_graph_series.py` cases: token-space dep resolves to the current re-keyed id, stale-id-without-token dropped, mixed raw+token, token ORDER-pin resolves, stale pin entry dropped, no-tokens byte-unchanged) (32 tests)
- `tests/test_canvas_overlay.py` — apply_graph (reorder + quick + sorted deps, no blocked/order field) and lean_seed (body-strip, cap, honest nc) (5 tests)
- `tests/test_canvas_commit.py` — closed classifier→tag mapping, `execute_progress_tags` now/later split, collect_commit_tags (later pulls deferred into gate; now-only stays backward-compatible), overlay-refresh gate (present for each actionable op incl. completes/removes-only and order-only (DC-4); absent for empty ops), validate_commit rejection paths (cross-project, destructive-confirm, unknown type, invalid execute, smart-list), project-entity carve-out (project_id accepted in edits/notes/completes/removes; still rejected in execute/order; non-child still rejected), execute "off" (accepted as a commit value, off-only gates no progression tags + only the overlay-refresh mark, mixed off+set still gates the set tags, off stays child-only); and the v6.2.0 divergence fixes — `energy` mapped as a classifier tag (both levels, non-canonical dropped, and it enters the strict-tag gate via `collect_commit_tags`), `calendar_entry` accepted as a synonym of `calendar` (same tag, neither spelling rejected, only the canonical one advertised in the rejection prose), `unknown_keys` (sorted, tolerant of None/non-mapping), and `blank_text_rejection` / blank-add-`text` rejection naming the `text`/`name` confusion (47 tests)
- `tests/test_canvas_create.py` — create-side pure helpers: `item_id` (explicit/index/empty), `project_tags` (life + project + ai_conversation + finalise mark), `collect_create_tags` (project tags; later pulls deferred into gate; now-only backward-compat; no-execute omits progress tags), `validate_create` rejection paths (missing_name, invalid_life, unknown_add_type, invalid_execute, unknown_dep, dep-by-index, duplicate_id incl. explicit-vs-positional collision, self_dep); v6.2.0 item-`text` validation (missing / whitespace-only / empty / non-string rejected, the rejection carries its `index` and names the `text`-vs-`name` confusion, one bad item rejects the whole draft) and `ITEM_KEYS` (extends `ADD_KEYS` by exactly the five create-only extras; every documented item field is recognised, so the receipt cannot cry wolf on the tool's own advertised shape) (30 tests)
- `tests/test_gtd_chat.py` — CHAT-note pure helpers: `format_chat_title`/`parse_chat_title` round-trip (+ non-CHAT/`ai`-role/empty/bad-role → None), `append_mode_footer`/`parse_body` round-trip (with/without mode; footer only on the final line; discuss), `parse_turn` (title from the body's FIRST LINE — real getList shape, title field empty/ignored; CHAT vs non-CHAT, mode present omits-key-when-absent, `$t` vs `body` body keys, single-line body → empty text, mode footer on realistic shape), `build_thread` (filters non-CHAT, oldest-first sort, out-of-order input, `since` filter, empty, single-dict normalised), `build_inflight` (selection incomplete/#ai_chat/not-#test/not-completed; status precedence in_flight>awaiting_review>open; scope project-vs-item; nearest-#project ancestor incl. deep-nested + nested-project-attributes-to-nearest (not topmost) + loose→""; last_activity latest CHAT note + empty; status→recency→name ordering; empty→{items:[],count:0}), turn attachments (`parse_filings` single-line + labelled-continuation + companion-marker-optional + absolute/backslashed skipped + multiple + none; `parse_output_note` OUTPUT-title selector incl. timestamped variant + non-OUTPUT/`FILING`-typed ignored + no-filing → None + label from title summary; `parse_links` em/en-dash + spaced-hyphen separators + no-separator → empty label + line-anchored uppercase only + ordering; `build_thread` correlation: OUTPUT before/equal ai turn attached, after last ai turn unattached, two-ai-turn windows, never on me turns, LINK parsed + retained in text, empty arrays default, since-filter keeps full-thread correlation; item-scope entries carry no provenance fields), project-scope attachments (`project_descendants` BFS children+grandchildren, completed included, deleted + cycle excluded, project itself excluded, no-descendants → []; `build_thread(descendants=...)` child filing attached with `item_id`/`item_name`, grandchild included, after-last-ai-turn unattached, two-window discipline across children, own-note entry keeps plain shape, descendant CHAT notes never become turns), `local_stamp` (shape + tz fallback), tag constants (75 tests)
- `tests/test_companion.py` — companion reader: parse_frontmatter (scalars/quote-strip, block + inline lists, empty-scalar drop, closing-fence stop), companion_candidates ordering, resolve_vault_root (explicit/host-default/marker), resolve_companion_meta (5 forms + precedence + containment + non-artefact skip + non-UTF-8 companion → no meta / falls through), enrich_files (32 tests)
- `tests/test_tool_naming.py` — the D9 conformance check: **the assertions that matter are that it FIRES** — an imperative on a read (including the real `gtd_item_classify` drift and the ⚠ `gtd_health_check`) and a result-noun suffix on a write are both findings; the unclassifiable path is exercised on a novel verb and on `gtd_inbox_zero`, with `zero` asserted OUT of the imperative lexicon (it was briefly in, which made the check bless the very name Wave 2 renames); the suffix beats an imperative-looking noun adjunct across the whole `gtd_<shape>_candidates` family (the check's own first false positive); `gtd_item_stale` resolves via the documented adjective-filter form, with `stale` asserted absent from `RESULT_NOUNS` so that branch cannot go dead; every exemption carries a stated reason; and against the live server, zero findings, zero unclassifiable, every tool reaching a verdict; plus the v3.1.0 strict promotion — `--strict` exits NON-ZERO on a known-bad fixture and zero on the real suite (a check that cannot fail is worthless), nothing buckets as `deprecated` any more, and a stray-reference sweep asserting no removed name survives in live source or tests OUTSIDE backticks — it found four stale user-facing strings on its first run (36 tests)
- `tests/test_tool_params.py` — shared complex-param coercion: `coerce_json` (parse/passthrough/blank/invalid) + Annotated types (string→structured via BeforeValidator, clean single-typed schema, no `anyOf`) (11 tests)
- `tests/test_tools/test_gtd_tools.py` — gtd_project_plan + gtd_project_canvas (seed shape, read-only call surface, lean cap, name/ambiguity/not-found, per-row `prog` from progression tags, BST due renders local day + no-tz fallback, companion `file.meta` + `frame.files` from a tmp vault, no-meta-when-absent) + gtd_canvas_commit (staged-commit apply, JSON-string ops defensive path, now/later execute split + stale-sibling drop both directions, execute `off` clears the progression directive (removeTags the present tags, no progression addTags) + idempotent no-op when none present + now→off round-trip, `later` strict-gate rejection + `now` backward-compat, all four rejection-without-write paths, overlay-refresh mark stamped on successful commit + not on zero-apply) + ORDER note / DC-4 (commit with `order` writes a conformant order-note/1 note on the project + returns order_persisted:"order-note" + records the tx + COMMIT note still lands; note written strictly BEFORE the overlay-refresh stamp; commit without order writes no note + order_persisted:false; order-only commit stamps the mark; canvas seed honours the latest valid ORDER note in ONE read; invalid note ignored → default order; pin clamped so a producer never follows its consumer) + gtd_project_create (project + children in dep order under the area, DEPENDS-ON note → producer's new id, finalise-mark + life + #project on the project, INCEPTION note, undoable; create-then-complete; now/later execute split + blocked→deferred; JSON-string params; focus ambiguity/miss without writes; missing-name + finalise-mark-absent strict rejection without writes; now-only backward-compat; reads once before writing) + gtd_project_index ({projects, foci, actions} object shape, project-row field-set + life/focus/focus_id + open/blocked counts + ai_quick/ai_now/ai_later + chat_count/chat_review_count + waiting_count, foci incl. empty focus area, actions under active project field-set (incl. engage fields estimate/contexts/energy/exec) + attribution + type/due/priority/blocked, read-only call surface + no transaction, include_someday passthrough) + gtd_chat_post (me-turn posts a CHAT note with the title grammar + adds #ai_chat_requested,#ai_chat; ai-turn removes #ai_chat_requested and never adds; task_id resolves series/list internally; mode footer round-trips into gtd_chat_thread; invalid role/mode + task-not-found (two reads) + completed-task read-only rejection rejected without writing; strict-tag rejection writes nothing) + gtd_chat_thread (only CHAT turns oldest-first, since filter, `requested` reflects the tag, empty thread, reads a COMPLETED task's thread with requested:false + filter spans incomplete OR completed, read-only call surface + no transaction, server-derived turn attachments: FILING continuation form → files[] on the correlated ai turn verbatim + LINK trailer → links[] retained in text + me-turn empty arrays, OUTPUT after last ai turn stays unattached; project-scope target aggregates descendant filings — open child + COMPLETED child + grandchild — with item_id/item_name provenance on the correlated ai turn in ONE read; non-#project target with a subtask stays same-task-only) + gtd_chat_inflight (cross-project roll-up: two projects' chat items with status/scope/project attribution + last_activity, #test excluded, empty portfolio, read-only call surface + no transaction) + project chat_count/chat_review_count (non-zero across the index) + redaction (canvas seed-item + frame.redacted; index project-row + focus-row redacted from own tag; action-row redacted CASCADES from a redacted project + focus) + gtd_item_set_redaction (add-path addTags #redacted + records tx; remove-path removeTags; unknown id errors without write; strict-tag rejection writes nothing; round-trips on a focus-shaped task id) + gtd_chat_post note-write-failure (signal tags skipped, me and ai turns) + gtd_project_create duplicate-in-draft-id rejection without writes via FakeMCP + gtd_item_stamp_tokens (back-fill stamps TMPL-CHILD notes on both open children + re-authors the DEPENDS-ON token line with the upstream slug + TMPL-STAMP audit note; idempotent second run writes nothing; not-repeating project skipped with skipped_reason; dry_run computes the plan but writes nothing; bad project_id errors; sweep selects only repeating projects; getList-first call surface) + gtd_canvas_commit repeating adds (a child added to a repeating project is stamped a TMPL-CHILD note; a one-off project stamps none) + commit scope + project verbs (default scope → bare COMMIT note on project; unknown scope rejected without writing; instant/item audit note on the referenced item; project scope note distinctly titled on the project; project rename via edits[project_id].text; add-project-note via notes[project_id] lands a content note on the project alongside the COMMIT (project) audit note; project complete needs confirm; project delete soft; execute[project_id] still rejected; carve-out is project_id-only) + gtd_item_set_redaction audit note (add-path/remove-path write a REDACTION note without #ai_conversation; strict-tag rejection writes no audit note) + gtd_engage_seed (read-only call surface + no transaction; server-derived flags + suggestions across kinds incl. has_deadline from has_due_time, blocked from the thin plan-graph, current_date stamped) + gtd_engage_commit (next_actions clears the due + stamps #ai_conversation; today sets the due via parse_time not the client text; someday adds #someday + the overlay-refresh mark on the nearest #project ancestor; resurface clears the due + signals; draft adds #ai_progress_requested; keep is a no-op; drop needs confirm; the ACL rejects — without writing — deferring a re-derived hard deadline, an off-enum verdict, a hallucinated date (parse_time no-$t → bad_date), and a not-found id fails the batch; records transactions for undo; strict-tag rejection writes nothing) + gtd_engage_commit PROGRESS steer note (draft+note attaches a STEER note with the pure body + still fires #ai_progress_requested + records the note tx; do_now+note attaches a note-to-self with no progression tag; nudge+note re-tickles to today + attaches; note on a defer/guard verdict (today/keep) ignored; oversize note truncated to 500 + note_truncated warning; non-string note dropped + note_not_string warning while the verdict still commits; idempotent re-commit of the same steer writes no duplicate note) + gtd_note_add body construction (TestGtdAddNote, v6.0.0: the conforming title; the STATE snapshot marker still on the FIRST body line when blocks follow it; the server assembling `--- Sources ---` / `--- AI Context ---` byte-for-byte from typed parts the caller never writes; both complex params accepting a JSON string; an all-blank block writing no delimiter, landing the note anyway and reporting `no_change` in `not_applied[]`; and `sources=[]` vs an omitted `sources` — same body, deliberately different receipt, since an explicit empty is evidence the call was not stripped bare and silences the advisory) + v6.4.0 output-filing integrity (TestTheFilingGate: a resolvable artefact with a companion passes; a missing artefact and a missing companion each reject with their OWN `rejected_by` under ONE code and **zero API calls** — the gate runs before the resolver; **no vault DEGRADES and the write lands**, driven through a real marker-less directory rather than a stubbed resolver because the marker check IS the behaviour, with the counterfactual reject test beside it so the two branches are proven separate; `off` reproduces pre-gate behaviour and `warn` both logs AND allows; `source_action` absent is advisory not a rejection and a matching one is silent; `unfiled` writes an UNFILED marker that `parse_filings` returns nothing for, and rejects when a `filing_path` is also given. Plus the derived register: the legacy `OUTPUTS:` form still FOUND and rebuilt in place into the catalogue title with the header appearing exactly once across `note_title + note_text`, idempotence on a repeat attach, a row with no live OUTPUT note **dropped but REPORTED**, and a second register reported in `duplicate_register_ids` and never deleted. Plus TestV640FilingReads: the read-only call surface of both new tools, the partial-vs-clean vault distinction end to end, the free-text exclusion, and an out-of-range cap rejected without a read — every vault-less case driven through `_no_vault(tmp_path)`, an explicit marker-less override, because `vault_root=None` falls through to the host default, which on the development machine is Paul's real vault) + Phase 0 typed reads (TestGtdPhase0Reads: read-only call surface across all 13 tools + shape/typed-error spot-checks — decision candidates, health-check stuck_project, topic clusters, gtd_query bad-perspective invalid_input + today's-field shape, inbox three signals, gtd_item_context task_not_found miss + STATE-first bundle) + gtd_inbox_item_close narrative (v6.3.0: the prose lands above the derived list in the ONE completion note the handler workaround needed two for; an absent narrative writes the pre-parameter body; a blank one writes no block, reports `no_change` in `not_applied[]` and still closes; and `narrative` is a receipt FACET — the bare-call advisory now names it, and goes silent as soon as one is supplied) + Wave 1b (TestWave1bItemClassify: offline — zero RTM calls; ambiguity + knocked-out reporting. TestWave1bClearSignal: an interim note writes the CHAT note and touches NO tags — the regression that silently kills the board's poll — final reply still clears by default, a `me` turn unaffected. TestWave1bActivityReportTitle: every emitted surface body-note title passes `note_shape.check_title`, the underscore form is exactly what it rejects, the token is MAPPED not derived. TestWave1bContributionTransition: State: rewritten + CONTRIB-UPDATE journalled + both writes transaction-recorded; every terminal reachable from drafted; terminal→terminal, no-CONTRIB-note and off-enum each rejected WITHOUT writing; a note with no State: line gets one appended; unknown task errors without writing) + Wave 1 reads (TestWave1Reads: read-only call surface across all eight + gtd_tag_report's two-method surface; surface_queue frontmatter parse + derived signals + metadata-less row kept + both-issues-two-reads + unknown-surface rejection without a read; engine_report five-filter read + named gaps + out-of-range window rejection; dependency_gaps shape + skip reasons + vault caveat; review_report uses the VERIFIED completedWithin filter and never completedAfter/addedAfter; item_stale / workload aggregation-not-rows + coverage / focus_index grouping + someday opt-in; tag_report non-canonical split) (317 tests)
- `tests/test_surface_queue.py` — AI-surface queue builder: frontmatter (every scan field, entity id-triple, literal `null`→None, fence on line 1, absent vs unterminated vs incomplete distinguished, a prose `---` rule is not a fence); malformed metadata NEVER drops the row (absent/unterminated/incomplete each return usable + `metadata_missing_count`); `auto_close_due` at both ends of the day + absent + the BST boundary; **`response_detected` across all three inclusion paths plus the negative that matters** (an item carrying only system notes — CONTEXT/CONTRIB/UPDATE/AI-LINK/OUTCOME/Q-UPDATE, every shape live on the eligible set — must NOT trip it), the item's own frontmatter note is never evidence, a pre-baseline note is ignored, an unknown note is quarantined not asserted, baseline falls back to item creation; note classification (catalogue + surface types system, DECISION's deliberate response precedence, hyphenated `AI-LINK`/`DEPENDS-ON` and underscored `ACTIVITY_REPORT` survive the type split); timestamps; bundle sort keys (questions oldest-MODIFIED, activity oldest-CREATED); **inline `expected_response_options` never fails the read** (flow-style `[a, b, c]` parses as a list, quotes/spacing tolerated, a bare scalar becomes one option rather than an error, block-style unchanged, the ROW field is always a list whatever the frontmatter carried, and the whole read survives an odd item — the v5.1.1 outage, where one live item's flow-form metadata made `surface="questions"` return nothing); **the server recognises what the server writes** (every `SURFACE_BODY_NOTE_TYPE` value classifies as `system` AND passes `note_shape.check_title`, pinning the read and write sides together, plus the legacy underscore spelling still recognised) (42 tests)
- `tests/test_engine_report.py` — engine telemetry: **`TestRegressionAgainstTheRetiredScript`** — one fixture per fault, each built so the OLD logic scores 0 and the correct logic does not (task accessors; created-outside-but-modified-inside, the canonical case, which must leave the cohort yet still appear as touched; the two figures genuinely diverging; note accessors resolving instead of `unknown`; `State:` vs `Phase:`; and all four together on one cohort scoring 50% where the old pipeline scored 0% on four separate grounds). Plus contribution facets (category from the BODY not the title, a title summary masquerading as a category rejected, PREP→brief, latest-note-wins so CONTRIB-UPDATE supersedes, an off-vocabulary observed state still counted, undated creation counted not assumed); surface side (closure keys off MODIFIED because it is an event, per-item-type breakdown, queue-bloat thresholds, latency reported as approximate or null); speculation withdrawn (no upgrade rate emitted at all, the gap named); report shape (window bounds, underivable metrics named never zeroed, deferred is a current snapshot) (26 tests)
- `tests/test_gtd_reports.py` — the six remaining Wave 1 builders, with a test naming each deliberate divergence: dependency gaps (eligible set, every exclusion reported with a reason, a RESOLVED DEPENDS-ON still counts as captured, DEPENDS-ON must be the note TITLE not prose, completed children don't keep a project eligible, **cap applied AFTER the largest-first sort**, vault caveat in the payload); review report (completions/additions by life context, **the fourth `client` context not dropped**, no-life-context counted not discarded, projects/foci excluded from completions, overdue + inbox depth, velocity, undated creation); item stale (threshold, someday excluded, **top-level projects and foci INCLUDED** — the dropped `isSubtask:true`, oldest-first, completed/test excluded, missing modification counted not assumed stale); workload (cells, **estimates summed for every state not only actions**, `estimate_coverage_pct` showing the hours are a floor, unclassified counted, every cell present when empty); focus index (project + direct-item counts, the active gate matching `gtd_project_index`, canonical life ordering, unclassified sorts last, **redaction surfaced never enforced**, a project-tagged focus is not an area); tag report (three-way classification, the twelve tags the script's list missed asserted canonical, family prefix alone is not a member, unused non-canonical are the deletion candidates, retired-in-use is its own finding, usage from one scan, minimum-tag-set gaps, an account-list orphan surfaced, the people caveat in the payload) (42 tests)
- `tests/test_exceptions.py` — error code mapping including subtask codes 4040-4090 + transient 102 → RTMNetworkError (17 tests)
- `tests/test_rate_limiter.py` — token bucket acquire/refill/pause (tokens_available honest during pause), rate limit stats incl. read/write session split (17 tests)
- `tests/test_response_builder.py` — envelope builder, transaction info, record_and_build_response, parsers (incl. `is_repeating` from the taskseries `rrule`) (47 tests)
- `tests/test_logging.py` — that the server's records actually EMIT (v3.0.1). **Every assertion is on an emitted record, never on the source** — a test checking the call site existed would have passed against v3.0.0, in which six of nine log statements reached no handler. Configuration (stderr only and never the stdout protocol stream, INFO reaching a handler, `RTM_LOG_LEVEL` override, an unparseable level falling back rather than crashing the server, idempotent re-configuration); all three write-boundary gates emitting; **`RTM_STRICT_NOTES=warn` emitting AND allowing the write** — both halves, because fixing one leaves it useless — and `off` staying silent; the empty-allow-list degradation found by the silent-control sweep; and a level check pinning the five self-defending records at `WARNING`. `caplog` is used WITHOUT `set_level`, deliberately: setting the level would configure the thing under test. Plus **v5.1.0's `TestTheSinkThatSurvivesDevNull`** — the load-bearing test runs a REAL gate in a **child process with fd 2 redirected to `/dev/null`** and asserts the record reached the file (an in-process emission assertion passes against a server with no sink at all), with the **counterfactual** beside it: the same probe with an unopenable sink, asserting the gate still fires and leaves no trace anywhere — the pre-v5.1.0 server, reproduced mechanically. Also: stderr still attached (additive, never a replacement), `RTM_LOG_LEVEL` reaching the FILE too (one env var, both channels, because the level lives on the tree), rotation genuinely rolling over AND staying bounded, the shipped 1 MiB x 3 bounds, an unopenable sink warning rather than failing silently or stopping the server, and the default location being config state and NOT the repo clone (with a blank `RTM_LOG_DIR` falling back rather than writing to cwd, since `Path("")` is `.`) (24 tests)
- `tests/test_lookup.py` — find_task disambiguation, resolve_task_ids, resolve_list_id (16 tests)
- `tests/test_tools/test_task_tools.py` — all 19 task tools via FakeMCP, incl. strict-tag-mode gating, unknown-list_name error paths (add_task/list_tasks), user-filter parenthesization, day-scale estimates; the list-target gate (add_task accepts writable / rejects smart + locked without writing; move_task same; default-list fallback NOT gated; flag-off inert) + `TestTheShippedDefaultIsLiveEndToEnd` (v5.1.0 — the same paths over a REAL `RTMConfig`, proving shipped default -> config -> tool wiring rather than a forced flag; the default-list carve-out re-asserted against the live default, where a locked configured default would otherwise reject every bare capture on activation) (90 tests)
- `tests/test_tools/test_tasks.py` — `_apply_subtask_counts` and `analyze_tasks` helpers (17 tests)
- `tests/test_tools/test_list_tools.py` — all 7 list tools via FakeMCP, incl. set_default_list transaction recording (18 tests)
- `tests/test_tools/test_note_tools.py` — all 4 note tools via FakeMCP, incl. get_task_notes name-lookup spanning completed tasks; the note-shape gate (accept / reject-without-writing / flag-off inert / warn-mode logs-but-writes; title-in-body gated when no note_title given; edit_note gates a title CHANGE; **a legacy body-only edit is never blocked** — the legacy-safety invariant) + `TestTheShippedDefaultIsLiveEndToEnd` (v5.1.0 — add_note rejects a malformed title with NO env set and writes nothing, still accepts the grammar, and the legacy body-only edit survives the flip) (25 tests)
- `tests/test_urls.py` — URL builders and parent chain walking incl. depth-exhaustion truncation warning (16 tests)
- `tests/test_tools/test_utility_tools.py` — all 14 utility tools via FakeMCP, incl. batch_undo JSON-string ids coercion + undo session-log validation (unknown id / already-undone rejected without an API call) (45 tests)
- `tests/test_tools/test_lists.py` — list response filtering and sorting (3 tests)
- `tests/test_order_note.py` — ORDER-note contract (order-note/1): make/parse round-trip (+ singular title, unknown source), fail-closed conformance (checksum/count/title-count mismatch, duplicates, non-JSON, wrong schema, bad `at`), title-line-in-body tolerance (the RTM storage reality), resolve (latest-valid-wins by `at`, note-id tie-break, invalid-latest fallback, non-ORDER ignored, input-order determinism), from_envelope (header.project.notes + empty) — mirrors the gtd suite case-for-case (19 tests)
- `tests/test_tmpl_child.py` — TMPL-CHILD token write helpers (tmpl-child/1): new_slug shape, make_tmpl_child_note title/body, note_child_token (from stored body + JSON-key-required guard), is_active_depends_on (active/resolved/obsolete/non-depends), depends_on_upstream_id, has_token_line, add_token_line round-trip; plan_backfill (assigns to unstamped; skips already-stamped incl. no re-slug; authors token-space dep line with the upstream slug; idempotent dep-line skip; upstream-not-a-sibling keeps raw; unique-slug collision avoidance; next-occurrence carries the same slug (note-copy propagation model); empty no-op) (16 tests)
- `tests/test_plan_graph_parity.py` — golden-file parity pins for the plan-graph port: the one-off contract golden + the series (resolve-references) golden, both copied byte-for-byte from the gtd engine (2 tests)

### Integration Testing

Use MCP Inspector:

```bash
make inspect
# or
npx @modelcontextprotocol/inspector uv run rtm-mcp
```

### Manual Testing

```python
# Quick API test
python -c "
import asyncio
from rtm_mcp.config import RTMConfig
from rtm_mcp.client import RTMClient

async def test():
    config = RTMConfig.load()
    client = RTMClient(config)
    result = await client.test_echo()
    print(result)
    await client.close()

asyncio.run(test())
"
```

## Adding New Tools

The canonical step-by-step checklist is [CONTRIBUTING.md](CONTRIBUTING.md) § 12 (with the tool
pattern in § 3 and the enriched-docstring shape in § 7). The worked example below shows the
pattern in context.

Example:

```python
from ..lookup import resolve_task_ids
from ..response_builder import build_response, record_and_build_response

@mcp.tool()
async def set_task_location(
    ctx: Context,
    location_id: str,
    task_name: str | None = None,
    task_id: str | None = None,
    taskseries_id: str | None = None,
    list_id: str | None = None,
) -> dict[str, Any]:
    """Assign a saved location to a task. Use get_locations to find location IDs.
    Use list_tasks with filter "location:name" to find tasks at a location.

    Identify the task by either task_name or all three IDs.

    Caution: task_name uses fuzzy matching across all tasks. For common names,
    prefer passing task_id + taskseries_id + list_id to avoid matching an
    unintended task.

    Returns:
        {"message": "Location set"} with transaction_id for undo.
    """
    client: RTMClient = await get_client()
    ids = await resolve_task_ids(client, task_name, task_id, taskseries_id, list_id)
    if "error" in ids:
        return build_response(data=ids)

    result = await client.call(
        "rtm.tasks.setLocation",
        require_timeline=True,
        location_id=location_id,
        **ids,
    )

    return record_and_build_response(
        client, result,
        data={"message": "Location set"},
        tool_name="set_task_location",
    )
```

## Deployment

### PyPI Release

```bash
uv build
uv publish
```

### Docker

```bash
docker build -t rtm-mcp .
docker push ghcr.io/pauleastabrook/rtm-mcp
```

## Common Issues

### "RTM not configured"

Run `rtm-setup` or set environment variables.

### Rate Limiting

Client uses a token bucket (burst to 3, sustain ~0.9 RPS). HTTP 503 responses trigger automatic retry with backoff. Use `get_rate_limit_status` to diagnose. If 503s occur regularly, increase `RTM_SAFETY_MARGIN` (default 0.1).

### Connection Failures

Transient connection errors (TCP timeout, DNS, connection reset) are retried automatically up to `RTM_CONN_MAX_RETRIES` (default 3). Write timeouts are **not** retried to avoid duplicates. Check `connection_retries_last_60s` in `get_rate_limit_status` output.

### Token Expiry

RTM tokens don't expire, but can be revoked. Re-run `rtm-setup` if needed.
