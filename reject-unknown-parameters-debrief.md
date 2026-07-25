---
report_type: handback-debrief
scope: rtm-mcp-reject-unknown-parameters
implemented_by: Claude Opus 5 (Claude Code)
derived_at: 2026-07-25
target_repo: rtm-mcp
artifact:
  branch: feat/reject-unknown-parameters
  feature_commit: 7a027e1
  version: v3.2.0 (MINOR — see "why minor" below)
  pr: not yet raised
relates_to:
  - Hand-off brief — reject unknown tool parameters (RTM 1218862042)
  - v3.0.1 logging-emission fix (the "does the record actually emit" discipline reused here)
status: needs-restart  # code + docs landed; the § 6 live check needs the connector on v3.2.0
---

# Handback debrief — reject unknown tool parameters (v3.2.0)

## What shipped

An MCP tool call carrying a parameter the tool does not define is now **rejected**, and
performs **no write**. Before v3.2.0 it was accepted silently — the extra argument
discarded, the call reported as a success, and nothing anywhere saying an argument had
been thrown away.

The rejection names the unknown parameter(s) **and the full accepted set**:

```
unknown parameter(s) ['type_tags'] for tool 'gtd_inbox_capture'. This tool accepts:
['pre_analysis', 'source_body', 'source_type', 'text']. No write was performed. If the
parameter you wanted exists on a different tool, check the tool description; if you
believe it should exist here, raise an improvement candidate rather than working around it.
```

Naming the accepted set is the load-bearing half: the caller is, by construction,
confused, so a rejection that also answers the question is worth several that don't.

**Nothing else changed.** No tool signature, no envelope, no output schema — all 99 tool
fingerprints are byte-identical. Required-parameter validation is untouched.
`gtd_inbox_capture` still has no tag parameter (capture stages raw; classifying is
clarify-time work), which was explicitly out of scope and stayed out.

## Design decisions & deviations

**Reject, not warn.** The alternative was a `warnings[]` entry with the call proceeding.
Rejected because a warning in a response body is precisely the class of signal that gets
ignored — and this defect exists *because* a silent success let a false conclusion stand.
A `warnings[]` entry would have been read exactly as carelessly as the `applied[]` entry
was.

**Why this is a MINOR bump and not a MAJOR one.** CONTRIBUTING § 10 reserves major for
"breaking envelope/signature changes", and none occurred: a caller conforming to the
advertised schema is unaffected *by construction*. The only calls that break are ones
already violating the schema and being tolerated — which is the defect. The counter-cost
is real and is named in both `CHANGELOG.md` and `CLAUDE.md` rather than buried: **strict
rejection couples client and server versions.** A skill written against a newer server
passing a parameter an older one lacks now hard-fails rather than degrading. If plugin
and server ever stop moving together, this is the decision to revisit.

**One middleware, not per-tool.** A single `on_call_tool` hook covers all 99 tools across
`gtd.py` / `tasks.py` / `notes.py` / `lists.py` / `utilities.py` and cannot drift as tools
are added — the same reasoning behind the `_tool` registration wrapper in `tools/gtd.py`.
Per-tool `ConfigDict(extra="forbid")` would have been 99 things to keep in step, i.e. the
defect class this repo keeps closing. The valid-name set is read live from the tool's own
`parameters["properties"]`, so the gate and the advertised documentation **cannot
disagree**.

**`ToolError`, deliberately not an `ErrorCode`.** The call never reaches the tool body, so
there is no envelope to put a structured error in — and the existing missing-required-
parameter rejection already surfaces at exactly this protocol level, so the two directions
now match. Minting an `ErrorCode` would also have churned every tool fingerprint for a
failure mode that belongs to no tool.

**Deviation from the brief: there is no protocol-key passlist.** The brief specified one
for `_meta` and asked it be verified before shipping. Verified, and the finding inverts the
instruction:

1. `_meta` is a **sibling field** of `arguments` on `CallToolRequestParams` (a pydantic
   field aliased `_meta`), so it is parsed out of the params object and never reaches the
   arguments dict at all.
2. A client that inlines `_meta` *into* `arguments` is rejected downstream by FastMCP's own
   signature binding regardless of what this middleware does — measured: `Unexpected
   keyword argument`.

So a passlist would change nothing except substituting a worse, less diagnostic message for
a better one. An `_`-prefix rule would have been worse still: `_type_tags` is a typo, not
protocol. Both halves of that reasoning are pinned by tests, because "no passlist" is only
correct for as long as they hold.

**An unknown *tool* is passed straight through.** `get_tool` returns `None`, and the
dispatcher below owns that message; pre-empting it would replace a precise "no such tool"
with a confusing "no such parameter".

## Membrane / activation

Additive and backward-compatible for any conformant caller. **No new tag**, no strict-tag
interaction, no schema change, no new `ErrorCode`, vault-free — so there is no
activation-ordering hazard.

To go live: **restart the MCP server on v3.2.0.** Nothing else.

Rollback is one line (delete the `mcp.add_middleware(...)` call in `server.py`), so this is
recoverable rather than a one-way door.

## Verification done

**Passed:** `make test` — **1615 tests** (1601 before; +14 in the new
`tests/test_middleware.py`). `make lint` — ruff check, ruff format, pyright (0 errors),
and `make naming --strict` clean. Tool fingerprints unchanged, confirmed by the existing
freshness guard rather than by inspection.

The new tests run **through the real server via an in-memory `Client`**, not against the
middleware class in isolation. That is deliberate: the defect was never a validator's
logic, it was that no validator ran on that path — so an isolated test would pass just as
happily against a server that never registered the middleware, reproducing the same vacuous
pass the defect itself had. The assertion that matters is `test_rejection_performs_no_write`
(`client.call.await_count == 0` — that is the single chokepoint every tool's RTM traffic
goes through, so zero awaits is a complete proof); the rest are ergonomics.

**NOT run: the § 6 live check, in full.** The live connector loads the *installed* server
and I cannot restart it. What I could do at zero cost, I did — probing the live connector
with `gtd_item_shape(name=…, tpye="action")`, an offline read-only tool that makes no RTM
call and writes nothing:

```
{"data":{"name":"Draft the quarterly board update","shape":"draft",
 "matched_pattern":"^\\s*(draft|write|compose|prepare)\\b","also_matched":[],"knocked_out":[]},
 "metadata":{"fetched_at":"2026-07-25T23:17:51.472464"}}
```

`tpye` was silently accepted. **That is the defect reproduced live**, on the pre-v3.2.0
server, without a stray write.

I deliberately did **not** run the live `gtd_inbox_capture` half. On the still-running old
server the `type_tags` call would have *succeeded* — creating a real stray Inbox_Stuff task
to demonstrate a bug already demonstrated above for free — and the correct call would have
proven only that unchanged behaviour is unchanged. Both halves are worth running, but only
**after** the restart, when they actually test the new server.

**Post-restart, run these two (they are the § 6 check verbatim):**

1. `gtd_inbox_capture(text: "probe", type_tags: ["improvement_candidate"])` → expect the
   rejection above, naming the four real parameters, and **no new Inbox_Stuff task**.
2. `gtd_inbox_capture(text: "probe")` → expect the capture to land with `#ai_conversation`
   and the SOURCE note, exactly as before.

## Conventions

§ 2 naming (no new tool). § 6 write discipline (no tag written; the gate precedes every
write). § 9 documentation lockstep — `CLAUDE.md` gains a module-table row, an architecture
section, and a test-inventory entry, with the total count re-synced 1601 → 1615;
`CHANGELOG.md` gains the v3.2.0 entry. § 10 version — minor, reasoning above. § 11 quality
gate — both halves run. § 14 — this document.

## Open items / handback

- **Paul:** restart the MCP server on v3.2.0, then run the two live calls above.
- **Consumer (gtd plugin, board artifacts, scheduled tasks) — no action.** Every conformant
  caller is unaffected; a rejection would mean that caller was already passing a parameter
  the server discarded, which is a bug on the caller's side that this now surfaces.
- Branch `feat/reject-unknown-parameters` is committed but **not pushed and no PR raised**.

## Durable lesson / gotcha

**A guard on a call site is not a guard on the path.** This is the third instance in this
repo of the same shape: v3.0.1's six log statements that reached no handler, the
`x.getFoo ? x.getFoo() : null` MilkScript idiom that degraded misspelt methods into `null`,
and now a validator that ran in one direction only. In each, something that *looked* checked
was structurally incapable of firing, and in each the absence was indistinguishable from a
clean result. The countermeasure is the same every time: **assert on the observable
outcome through the real path, never on the existence of the mechanism.** That is why
`tests/test_middleware.py` drives an in-memory `Client` against `rtm_mcp.server.mcp` rather
than calling `RejectUnknownParameters.on_call_tool` directly, and why it also asserts the
rejection's WARNING record actually *emits*.

**The specific trap for the next author:** `FastMCP.get_tool` is **async** on 3.4.4 and
returns `None` (it does not raise) for an unknown name — and `list_tools()`/`get_tool()`
differ across the FastMCP majors, which is why `tests/test_tool_schemas.py` carries a
tolerance shim. Also: a fastmcp `Client` call result exposes deserialised models on
`.data`, so structural assertions need `.structured_content`; and mocking the RTM client
with an `AsyncMock` breaks any tool with an `output_schema`, because Mock attributes do not
serialise — use a real `RTMClient(mock_config)` for tools that read only in-memory state.

## Footer

Source of truth: `CLAUDE.md` § "Unknown-parameter rejection (the call-boundary gate, since
v3.2.0)" and the module docstring in `src/rtm_mcp/middleware.py`. Origin: RTM
[1218862042](https://www.rememberthemilk.com/app/#list/51526642/1218862042).
