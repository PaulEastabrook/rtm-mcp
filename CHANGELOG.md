# Changelog

Notable changes to rtm-mcp. Started at v3.0.0 because that is the first release with a migration
to describe; the full history before it is in the dated `*-debrief.md` files at the repo root, and
the architecture record is `CLAUDE.md`.

## v3.0.0 — the GTD tool rename (breaking)

**25 tools renamed, `gtd_query` split into three, one new area. 55 GTD tools, all conformant to
the naming standard in `CONTRIBUTING.md` § 2.**

**Nothing changed behaviour.** Every renamed tool does exactly what it did — same parameters, same
return shape, same error branches. This release is a name change and nothing else.

### Migration — you probably need to do nothing yet

**All 25 old names remain callable as deprecated aliases, and `gtd_query` still works.** They are
removed at **v3.1.0**. An alias registers the same function under the old name and advertises a
byte-identical schema, so a caller sees no difference until it disappears.

Aliases exist for **cross-repo sequencing**, not for external callers: the server and its
consumers live in separate repos behind an async hand-off, so one is always ahead of the other —
and *either* order breaks without them. Every alias invocation logs at info level, and **that log
is the gate for removal**: the aliases go once a full scheduled-task cycle shows zero hits, not
after some elapsed time.

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
*unrepresentable* rather than merely rejected. `gtd_query` remains as a deprecated dispatcher
that delegates to all three.

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
run against v3.0.0: 52 ok, 3 exempt, 26 deprecated, **0 findings, 0 unclassifiable**.
