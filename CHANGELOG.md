# Changelog

Notable changes to rtm-mcp. Started at v3.0.0 because that is the first release with a migration
to describe; the full history before it is in the dated `*-debrief.md` files at the repo root, and
the architecture record is `CLAUDE.md`.

## v3.3.0 — the Tool Affordance Standard: front-loaded selection, help on demand, teaching rejections

Implements the family Tool Affordance Standard (git-ops `mcp-tool-documentation-standard.md`
§§ 4.1a / 9 / 10). Additive: no tool changes behaviour, capability, write safety, or return shape,
and no new tag or `ErrorCode` is introduced. **100 tools** (99 + `rtm_tool_help`).

**The gap it closes.** The six-surface standard was excellent on *what* a tool's documentation
contains and silent on *how much of it the client actually shows the model*. Measured here on
2026-07-26 and reproduced exactly in this repo: **18 of 99 tool descriptions exceeded the ~2 KB the
client keeps** (worst: `gtd_canvas_commit` at 4,893 bytes, losing 58% — its governance contract),
and the server `instructions` block was **30,506 bytes, of which ~93% was discarded** — leaving the
RTM legal disclaimer where the tool-family routing keywords should have been. A Google-style
docstring puts `Returns` / operator tables / caveats *last*, so the discarded tail was precisely
the correct-usage material, on the highest-stakes governed writes.

**Three tiers, keyed to what guarantees the read.**

| Tier | Surface | Carries |
|---|---|---|
| 1 — select | `name` + description front block + `instructions` front | purpose, when-NOT, write-safety posture, domain marker |
| 2 — detail | `rtm_tool_help` | combination rules, worked examples, full Returns, error catalogue, chain edges |
| 3 — teach | the guided rejection | purpose, typed params, nearest-name guess, violated rule, help pointer |

**`instructions`: 30,506 → 2,046 bytes.** The ~400-line per-tool catalogue is gone; the front now
carries what-the-server-is, the two-family split with routing keywords, and a pointer to
`rtm_tool_help()`. The legal disclaimer moved to the end. The catalogue's genuinely non-obvious
facts (default-list resolution, smart lists being read-only, strict-tag mode) live in the owning
tools' descriptions, where a caller of *that tool* actually sees them.

**New tool `rtm_tool_help(tool_name=None)`** — read-only and **offline** (zero RTM calls, like
`gtd_item_shape`). No argument returns the whole-server index: one purpose line per tool, grouped
by family. A name returns that tool's full contract. It is **generated as a projection** of the
live advertised schema, never hand-written — parameters come from `inputSchema`, posture from
`annotations`, `Returns` from the docstring, and the error catalogue from the codes the description
names (which `TestAdvertisedErrorContract` already guarantees is complete). Only four small tables
are authored: combination rules, worked examples, chain edges, and the BFF set.

**Teaching rejections.** The v3.2.0 gate named the valid parameters and nothing else. It now names
them *with* types, required/optional and enums, plus the tool's own purpose (the original defect was
a wrong-*tool* case — capture was simply the wrong tool for tagging), a nearest-name guess for a
probable typo, the combination rules a JSON schema cannot express, and a pointer to the help
payload. Built through one shared generator (`guided_rejection.py`) that converges the two
pre-existing shapes — `strict_tags.guided_error`'s `how_to_proceed` and `engage_commit.validate`'s
closest-legal suggestion — so the paths speak with one voice. It still writes nothing.

**Front-loading.** All 55 `gtd_*` tools already opened as `<Domain> — purpose`; all 44
non-conforming descriptions were exactly the generic primitives, which now carry the `RTM — `
marker. That marker is also the model-readable half of the taxonomy: `_meta` is **not** rendered to
the model on this client, so ordinary description text is the only place a skill can actually
select on. `list_tasks` gained the read-only invariant and the smart-list `status:incomplete`
caveat in its front block.

**Nineteen descriptions remain over budget, deliberately and on a reasoned, asserted exemption
list.** The constraint is local and outranks the brief: CONTRIBUTING § 7 *requires* a multi-case
`Returns` and an `Args:` section in every docstring, and the `_FullDocstringMCP` shim advertises the
whole docstring. For a genuinely complex governed write, "fit 2 KB" and "obey § 7" cannot both
hold. So the load-bearing guarantee is enforced instead: a test asserts that **every** exempt
tool states its read/write posture *inside the front block that survives truncation* — a caller
never learns what a tool does to their account only from a discarded tail.

**Fingerprints: 1 added, 44 moved, 55 unchanged.** The churn is exactly the 44 primitives that
gained the domain marker, plus the new tool — not a blanket re-hash.

**Tests: 1,653 (+38).** `TestSelectionSurfaceBudgets` pins both budgets, the exemption list's
freshness (a stale exemption fails), the posture-in-front guarantee, and the `<Domain> — purpose`
shape. New `tests/test_tool_help.py` holds the projection-agreement contract: every tool resolves
in the index, its purpose is a leading substring of its own description, its contract's parameters
equal the advertised `inputSchema`, and its error catalogue claims only codes the `ast`-derived
reachable set allows. That last guard caught a real error during the build — an authored chain edge
naming `assign_location`, a tool on the *official* RTM connector rather than this server.

To go live: restart the server on v3.3.0. Rollback is a revert.

## v3.2.0 — unknown tool parameters are rejected

> **⚠ CORRECTED 2026-07-26.** This entry's premise — "previously it was accepted silently" — is
> measured **false**. On the pinned stack (fastmcp 3.4.4 / pydantic 2.12.5) a server with **no**
> middleware already rejects an undeclared argument at call-schema binding, before the tool body;
> v3.1.0 was executed over raw JSON-RPC and refuses the exact historical argument shape. **v3.2.0
> replaced a pydantic dump with a teaching rejection; it did not add a gate and closed no
> silent-success hole.** The silence in the motivating incident was the *client's*: the Claude
> Desktop host strips undeclared keys before the wire (a JSON-Schema→zod converter that reads only
> `properties`/`required` and forwards the parsed, strip-mode object). The rejection is therefore
> unreachable through that host — a sweep of 2,517 transcripts found no caller ever receiving it.
> The change is still worth having (a far better message, and a backstop for unmeasured callers),
> but it cannot be credited with preventing the incident that prompted it. See `CLAUDE.md`
> § "Unknown-parameter rejection" and `middleware.py` for the measurements.

A tool call carrying a parameter the tool does not define now returns an error and performs no
write. Previously it was accepted silently: the extra argument was discarded and nothing said so.

**Why this is a minor bump and not a major one.** No advertised contract changed — no signature,
no envelope, no output schema; every tool fingerprint is byte-identical. A caller that conforms to
the advertised schema is unaffected by construction. The only calls that break are ones that were
already violating the schema and being tolerated, which is the defect. That said, the cost is real
and worth naming: **strict rejection couples client and server versions.** A skill written against
a newer server that passes a parameter an older server lacks now hard-fails rather than degrading.
Accepted because both sides here move together and because the failure announces itself
immediately — but if that stops being true, this is the decision to revisit.

**Rejection, not a warning.** The alternative considered was a `warnings[]` entry in the response
with the call proceeding. Rejected: a warning in a response body is exactly the class of signal
that gets ignored, and this defect exists *because* a silent success let a wrong conclusion stand.

**How it was found, which is the argument for fixing it.** `gtd_inbox_capture` was called with
`type_tags: ["improvement_candidate"]` — a parameter it does not have, and deliberately so
(capture stages raw; classifying is clarify-time work). The call returned a success whose
`applied[]` carried `capture:tags` — the server correctly applying its own `#ai_conversation`
pipeline tag — which was read as the tag write having landed. A false defect report against the
server followed. The tool told the truth; the missing feedback let a wrong story survive. The
dangerous version is quieter: a misspelt *optional* on `gtd_item_create` or
`gtd_item_set_properties` writes the item without that property and reports success, with nothing
in `applied[]` or `errors[]` marking the discarded intent.

The asymmetry that made this worth closing: required parameters were already validated strictly —
omitting `text` returns a missing-argument error naming the path. The strictness existed; it just
did not run in this direction.

**Implementation.** One `on_call_tool` middleware (`middleware.py`), registered once in
`server.py`, covering all 99 tools — not per-tool `extra="forbid"`, which would be 99 things to
keep in step as tools are added. The valid-name set is the tool's own advertised
`parameters["properties"]`, so it cannot drift from what clients are told. The error message names
both the unknown parameter(s) and the full accepted set, because naming the accepted parameters is
what turns a rejection into the answer.

Not changed: required-parameter validation, and `gtd_inbox_capture` still has no tag parameter.

## v3.1.0 — the deprecated aliases are removed (breaking)

**26 deprecated surfaces → 0.** The 25 renamed aliases and the `gtd_query` dispatcher shipped at
v3.0.0 for exactly one release and are gone. Calling one now returns a tool-not-found. **The tool
count is unchanged at 55** — nothing was added or removed from the live surface.

**This table is the migration path.** With the aliases gone it is the only one, which raises its
importance rather than lowering it: if you hit a tool-not-found, the replacement is here.

| Removed at v3.1.0 | Call instead |
|---|---|
| `gtd_add_note` | `gtd_note_add` |
| `gtd_annotate_clarification` | `gtd_inbox_item_annotate` |
| `gtd_apply_canvas_commit` | `gtd_canvas_commit` |
| `gtd_apply_engage_commit` | `gtd_engage_commit` |
| `gtd_attach_contribution` | `gtd_contribution_attach` |
| `gtd_attach_output` | `gtd_note_attach_output` |
| `gtd_batch_transition` | `gtd_item_transition_batch` |
| `gtd_capture` | `gtd_inbox_capture` |
| `gtd_chase_sweep` | `gtd_waiting_for_sweep` |
| `gtd_close_inbox_item` | `gtd_inbox_item_close` |
| `gtd_complete_action` | `gtd_item_complete` |
| `gtd_consolidate_apply` | `gtd_cluster_consolidate` |
| `gtd_context` | `gtd_item_context` |
| `gtd_create_item` | `gtd_item_create` |
| `gtd_create_project` | `gtd_project_create` |
| `gtd_edit_note` | `gtd_note_edit` |
| `gtd_health_check` | `gtd_health_report` |
| `gtd_inbox_zero` | `gtd_inbox_drain` |
| `gtd_item_classify` | `gtd_item_shape` |
| `gtd_link_dependency` | `gtd_dependency_link` |
| `gtd_query` | `gtd_item_today / gtd_next_actions / gtd_focus_projects` |
| `gtd_set_properties` | `gtd_item_set_properties` |
| `gtd_set_redaction` | `gtd_item_set_redaction` |
| `gtd_stamp_tokens` | `gtd_item_stamp_tokens` |
| `gtd_topic_clusters` | `gtd_cluster_candidates` |
| `gtd_transition_state` | `gtd_item_transition` |

`gtd_query`'s `perspective` was a **mode** parameter — it changed which other parameters were
valid, the row shape, and the error branches — so it was a tool boundary. Each replacement takes
only the parameters its own view needs.

### The naming check is now blocking

`make naming` runs `--strict` and is part of `make lint`. It ran report-only through v3.0.x
because it *could not* block: the deprecated aliases **were** the non-conformant names, so it
fired on all 26 by construction. With them gone: **52 ok, 3 exempt, 0 findings, 0 unclassifiable.**

### Also removed

- `GTD_QUERY_OUTPUT` (`models.py`) and `VALID_PERSPECTIVES` (`gtd_reads.py`) — dead with the
  dispatcher. The three perspectives are three tools now, so a vocabulary naming them has nothing
  left to validate.
- Stale pointers in **user-facing strings**, found by a new test rather than by reading: two
  runtime error messages and the server's own advertised instructions were still directing callers
  at `gtd_query`. Those would have survived the rename indefinitely — no test had ever asserted on
  them.

### How removal was judged safe

Not by watching a log. By **enumerating the callers**: the marketplace repo (0 live call sites),
the scheduled-task specs (0 — thin launchers name no tools), and the **rendered live artifacts**.
That last one is the reason it was worth doing — the standing board held four old names in both
its code *and* its `mcpTools` allowlist, seven days after the template had moved on. **A rendered
artifact is a frozen copy of its template, so it is a live caller no repo grep can see.**

## v3.0.1 — make the records emit

**Six of nine log statements never reached a handler.** There was no logging configuration
anywhere in the repo: every module called `logging.getLogger(__name__)` and logged, but Python's
root logger defaults to `WARNING` and with no handler the `lastResort` fallback emits only
`WARNING` and above. Every `INFO` and `DEBUG` record was discarded before a handler saw it.

Silent until now:

| Record | Was |
|---|---|
| `strict_tags` — a rejected tag write | `INFO`, discarded |
| `note_shape` — a rejected/observed note title | `INFO`, discarded |
| `list_targets` — a rejected write target | `INFO`, discarded |
| the deprecated-alias record (×2) | `INFO`, discarded |
| `client` raw API response | `DEBUG`, discarded — **correctly**, and left alone |

**All three write-boundary gates logged their rejections into nothing.** Callers still got their
structured errors, so behaviour was intact — but "how often is the note-shape gate firing, and on
what?" was unanswerable.

### `RTM_STRICT_NOTES=warn` was a complete no-op

`warn` mode does not block a malformed note title; its *only* effect is the record. With the
record discarded, the observe-before-enforce mode did nothing observable at all — anyone who set
it to gather evidence before enabling `shape` collected silence and would have concluded the
estate was clean. It now warns, and the record names the outcome
(`ALLOWED (observe-before-enforce)` vs `REJECTED`).

### What changed

- **`server.configure_logging()`**, called from `main()`. Scoped to the `rtm_mcp` logger tree so
  importing this package never hijacks a host application's logging. Level `INFO`, overridable
  with **`RTM_LOG_LEVEL`**. Idempotent.
- **The handler writes to stderr, never stdout** — this is a stdio MCP server and stdout carries
  the JSON-RPC stream. A test asserts no handler is on stdout.
- **The five records are now `WARNING`, not `INFO`.** A refused write and a call to a name that
  disappears next release are both exceptional, and `WARNING` emits through `lastResort` with no
  configuration at all — so losing the configuration again cannot silence them. The configuration
  still matters for formatting (timestamp, level, logger name) and for `DEBUG`.
- **`client.get_account_tags` now warns when it caches an empty allow-list.** Found by a sweep for
  controls whose failure produces no record: a failed `rtm.tags.getList` cached an empty set, so
  the strict-tag gate rejected *every* tag write while telling the caller its tags did not exist —
  true of an empty set, and wholly misleading about the cause.

### Why it matters beyond observability

The alias-removal gate was originally *"the alias-invocation log shows zero hits across a full
scheduled-task cycle"*, and before this release that log could not have recorded a hit if one
occurred — everything logged before v3.0.1 was unmeasured, not clean. **The gate was subsequently
dropped as disproportionate for a single-user tool** and removal was judged by enumerating callers
instead (v3.1.0). The logging fix stands on its own: three write-boundary gates and a mode that
did nothing observable.

## v3.0.0 — the GTD tool rename (breaking)

**25 tools renamed, `gtd_query` split into three, one new area. 55 GTD tools, all conformant to
the naming standard in `CONTRIBUTING.md` § 2.**

**Nothing changed behaviour.** Every renamed tool does exactly what it did — same parameters, same
return shape, same error branches. This release is a name change and nothing else.

### Migration — you probably need to do nothing yet

**Superseded by v3.1.0, which removed them.** At v3.0.0 all 25 old names remained callable as
deprecated aliases, alongside `gtd_query`; each registered the same function under the old name
and advertised a byte-identical schema, so a caller saw no difference. They are gone as of
v3.1.0 — see that entry for the migration table.

Aliases exist for **cross-repo sequencing**, not for external callers: the server and its
consumers live in separate repos behind an async hand-off, so one is always ahead of the other —
and *either* order breaks without them. *(The alias-invocation log was originally intended as the
removal gate. In the event removal was judged by enumerating callers instead — cheaper, and it
found a caller no log would have shown. See v3.1.0.)*

### The renames

Four ⚠ names actively misled about what the tool does; the rest are consistency.

| Old name | New name | Note |
|---|---|---|
| `gtd_add_note` | `gtd_note_add` | |
| `gtd_annotate_clarification` | `gtd_inbox_item_annotate` | |
| `gtd_apply_canvas_commit` | `gtd_canvas_commit` | |
| `gtd_apply_engage_commit` | `gtd_engage_commit` | |
| `gtd_attach_contribution` | `gtd_contribution_attach` | new `contribution` area |
| `gtd_attach_output` | `gtd_note_attach_output` | stays under `note` — see below |
| `gtd_batch_transition` | `gtd_item_transition_batch` | |
| `gtd_capture` | `gtd_inbox_capture` | |
| `gtd_chase_sweep` | `gtd_waiting_for_sweep` | |
| `gtd_close_inbox_item` | `gtd_inbox_item_close` | |
| `gtd_complete_action` | `gtd_item_complete` | ⚠ handled all three item kinds despite saying *action* |
| `gtd_consolidate_apply` | `gtd_cluster_consolidate` | |
| `gtd_context` | `gtd_item_context` | |
| `gtd_create_item` | `gtd_item_create` | |
| `gtd_create_project` | `gtd_project_create` | |
| `gtd_edit_note` | `gtd_note_edit` | |
| `gtd_health_check` | `gtd_health_report` | ⚠ read as an imperative; it is a read |
| `gtd_inbox_zero` | `gtd_inbox_drain` | ⚠ read as a state; it writes |
| `gtd_item_classify` | `gtd_item_shape` | ⚠ imperative verb on a read-only tool |
| `gtd_link_dependency` | `gtd_dependency_link` | |
| `gtd_set_properties` | `gtd_item_set_properties` | |
| `gtd_set_redaction` | `gtd_item_set_redaction` | |
| `gtd_stamp_tokens` | `gtd_item_stamp_tokens` | |
| `gtd_topic_clusters` | `gtd_cluster_candidates` | |
| `gtd_transition_state` | `gtd_item_transition` | |

### `gtd_query` splits into three

`perspective` was a **mode** parameter, not a scope one: `context` was valid only for one
perspective and `focus` only for another, the rows carried different fields per perspective, and
`focus_not_found` applied to a single branch. Three tools wearing a trenchcoat.

| Perspective | Now |
|---|---|
| `todays_field` | `gtd_item_today` — no parameters |
| `next_actions_by_context` | `gtd_next_actions` — keeps `context` as a genuine scope parameter |
| `focus_projects` | `gtd_focus_projects` — keeps `focus` |

Each takes only the parameters its own view needs, so an invalid combination is now
*unrepresentable* rather than merely rejected. `gtd_query` remained as a deprecated dispatcher
delegating to all three, and was removed at v3.1.0.

### Two amendments to the frozen rename map

**`gtd_item_classify` → `gtd_item_shape`.** The standard drifted within four days of being
frozen: Wave 1b shipped an imperative verb on a read-only tool, in a wave whose own brief claimed
conformance. *Shape* is the domain's own word (`shape-patterns.md`), so this is not a coinage.

**`contribution` becomes an area (the twelfth).** `gtd_contribution_attach` and
`gtd_contribution_transition` are two operations on one domain object; splitting them across
`note` and `contribution` would have put siblings in different places — the precise outcome
aggregate grouping exists to prevent. A contribution has a lifecycle (the six-state machine);
the note is its *storage*, not its identity.

**`gtd_note_attach_output` stays under `note`, and the asymmetry is deliberate.** An output has no
lifecycle — it is filed, journalled, and done. There is no state machine to hang an aggregate on.

### New: the D9 naming-conformance check

`scripts/check-tool-naming.py` (`make naming`) flags any tool whose name form disagrees with its
`readOnlyHint` annotation. **Report-only at v3.0.0, blocking at v3.1.0** — it cannot block while
the aliases are exposed, because the aliases *are* the non-conformant names.

A name matching neither lexicon is reported `unclassifiable` and **never silently passes**. First
run against v3.0.0: 52 ok, 3 exempt, 26 deprecated, **0 findings, 0 unclassifiable**. Promoted to
blocking at v3.1.0.
