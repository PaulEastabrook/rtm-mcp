# Hand-off brief — redaction is a CLIENT-side viewing curtain, not a server data vault

**Repo:** rtm-mcp · **Current version:** 1.29.0 · **Target:** 1.30.0 (minor)
**Date:** 2026-07-13 · **From:** Cowork/GTD session (Paul) · **To:** Claude Code
**Scope:** stop nulling the engage-lens funnel fields on shielded rows in `gtd_project_index`; return the data and let the client shield the display.

---

## 1. Decision & rationale

Redaction (`#redacted`) is a **client-side viewing curtain** — an over-the-shoulder privacy blur — **not a server data vault** (Paul, 2026-07-13). Evidence it's already modelled that way:

- The server **already returns names and due dates** for shielded rows (`build_actions` puts `r["name"]` / `r["due"]` on every row regardless of `redacted`).
- The **GTD board client already shields the display**: shielded rows render as a locked placeholder (no name/path/estimate/energy shown), are **non-selectable**, and are **excluded from the funnel** — there is a client test asserting *"a filter must not leak a hidden estimate via count changes."* So the client, not the server, prevents leaks.

v1.29.0 introduced a **server-side nulling** of `estimate`/`contexts`/`energy`/`exec` for redacted rows in `build_actions`. That is an **inconsistent over-hardening**: names still flow but the engage fields don't, and it means those rows drop out of the engage data entirely (they showed up as ~176 empty-context rows in the live index). Fix: return the engage fields for every row; keep the `redacted` flag; the client shields the display.

*(The alternative — a true data vault that strips everything including names — is explicitly **not** what we want; that would be a much bigger change and contradicts the established behaviour.)*

---

## 1a. The invariant — redaction is SURFACED, never ENFORCED, server-side

**Codify this as a design invariant** (in `CLAUDE.md`): the server may *surface* redaction state and *write* the tag, but **must never *enforce* it by suppressing data.**

- **Allowed server-side (surface + write):** derive and emit the `redacted` boolean on read-tool rows / items / frames so the client can shield; set/unset the `#redacted` tag via `gtd_set_redaction`. These are metadata + the marking mechanism — not enforcement.
- **Forbidden server-side (enforce):** nulling, stripping, withholding, or dropping **any** field or row based on `redacted`. Enforcement — the actual hiding — is **100% client-side** (the board renders the locked placeholder and excludes shielded rows from the funnel).

### Audit — every redaction touch-point in `src/` (2026-07-13)

| Location | What it does | Verdict |
|---|---|---|
| `project_plan.py` — `REDACTED_TAG`, `header.project.redacted` | constant + project flag | **surface — keep** |
| `canvas_seed.py` — `map_redacted`, per-item `redacted`, frame `redacted` | per-item + frame flag | **surface — keep** — *verify it does NOT null context/estimate/energy on shielded items (grep shows flag-only; if it nulls, remove that too)* |
| `project_index.py` — `build_index` / `build_foci` row `redacted` | project + focus flag | **surface — keep** |
| `project_index.py` — `build_actions` `redacted` cascade flag | action flag (own OR project/focus cascade) | **surface — keep** |
| `project_index.py` — `build_actions` engage-field **nulling** (`if redacted: estimate/contexts/energy/exec = None/[]`) | **enforce — data suppression** | **REMOVE** (already removed in the working tree) |
| `tools/gtd.py` — `gtd_set_redaction` | governed write of `#redacted` + REDACTION audit note | **write mechanism — keep** |

**Conclusion:** the **only** server-side redaction *enforcement* was the `build_actions` engage-field nulling. Removing it (done) leaves the server surface-and-write only. Part of this change is to **prove and lock that**: re-run `grep -rn "redact" src/` and confirm every remaining hit is flag-emission or the write tool — never a field/row suppressed on `redacted`.

---

## 2. Current working-tree state (ALREADY DONE — verify with `git diff`)

`src/rtm_mcp/project_index.py` `build_actions` has already been edited (uncommitted, +10/−12): the `if redacted: estimate=None; contexts=[]; energy=None; execv=None` suppression block was removed, so `estimate` / `contexts` / `energy` / `execv` are now **always computed** (`parse_estimate_minutes` / `_contexts` / `_energy` / `_exec`). The inline comments were updated to say redaction is a client-side curtain. The `redacted` flag on the row is unchanged (still emitted).

Confirm the diff is exactly that and nothing else before continuing. (If you'd rather redo it cleanly, `git checkout src/rtm_mcp/project_index.py` and re-apply per §1.)

---

## 3. Remaining work

1. **Docstring.** `build_actions` docstring (~lines 330–333) still states a shielded row carries no engage data (`estimate`/`energy`/`exec` None, `contexts` []). Update it: engage fields are now computed for **every** row; the `redacted` flag tells the client to shield the display (curtain, not vault).

2. **Tests — flip the suppression assertions.**
   - `tests/test_project_index.py::test_shielded_action_suppresses_engage_fields` (~line 820): a shielded row must now **carry** the real `estimate`/`contexts`/`energy`/`exec`, with `redacted` still `True`. Rename to reflect the new contract (e.g. `test_shielded_action_still_carries_engage_fields`).
   - `tests/test_tools/test_gtd_tools.py` (~line 1852, the redaction-cascade action test): if it asserts engage-field suppression, update to assert the fields are present + `redacted` cascades; if it only asserts the `redacted` flag cascades from a redacted project/focus, leave it.

3. **Consistency check — `gtd_project_canvas` seed.** Inspect `src/rtm_mcp/canvas_seed.py` (`map_context` / `map_redacted` / the per-item mapping) and the canvas path for the **same** redaction-nulling of context/estimate/energy on seed items. If the canvas seed also nulls engage/context data on shielded items, apply the **same** change (return the data; keep the per-item `redacted` + `frame.redacted` flags) so the two read tools are consistent. If it only *flags* redaction (no nulling), no change needed — note which in the debrief.

4. **Run tests** — `make test` (`uv run pytest`). All green. Keep the test count in sync with `CLAUDE.md`'s inventory if it tracks per-file counts.

5. **Version + changelog** — bump `1.29.0 → 1.30.0` (minor; a served-field behaviour consumers rely on). Update `pyproject.toml` and any version constant/changelog per CONTRIBUTING versioning.

6. **Handback debrief (required, CONTRIBUTING §14)** — write `redaction-curtain-not-vault-debrief.md` at repo root: the decision, the change, the canvas-seed finding, tests touched, version, and the deploy note.

7. **Commit** — Conventional Commit per CONTRIBUTING, e.g. `feat: redaction is a client-side curtain — engage fields flow for shielded rows (v1.30.0)`.

8. **Deploy** — restart the running rtm-mcp server **through the Claude/Cowork connector** (not a bare `kill`+relaunch — that orphans the host's managed child and throws `write EPIPE`) so the host re-spawns v1.30.0.

---

**Also required — make it an invariant, not a one-off fix:**

- **Codify in `CLAUDE.md`.** The repo's redaction note currently reads *"No server-side name stripping … hardening to null names/notes of redacted rows is a deliberate out-of-scope follow-up."* Replace/extend it with the § 1a invariant: **the server *surfaces* redaction (the derived `redacted` flag) and *writes* the tag (`gtd_set_redaction`), but never *enforces* it by suppressing data; enforcement is client-side.**
- **Prove no other suppression.** `grep -rn "redact" src/` must show only flag-emission + the `gtd_set_redaction` write — no code path nulls / strips / drops a field or row on `redacted`. Keep this as a standing check in the debrief.
- **Guard test.** Add/keep a behavioural test that a shielded row — via its **own** `#redacted` tag *and* via a **cascade** (redacted project / focus) — carries the **full** data (`name`, `estimate`, `contexts`, `energy`, `exec`) with `redacted: true`. That test is what stops the suppression creeping back.

---

## 4. Client side — NO change required

The consuming client is the GTD board's engage lens (`project-plan-artifact.html`) in the **marketplace** repo (`github.com/pauleastabrook/claude-plugins`, gtd plugin) — already released. It shields redacted rows purely on the `redacted` flag (locked placeholder, non-selectable, excluded from the funnel, counts never leak). It does **not** need the server to null the data. No marketplace change is part of this brief.

---

## 5. Acceptance

- `gtd_project_index.actions[]` shielded rows (`redacted: true`) now carry their real `estimate` (minutes), `contexts`, `energy`, `exec` — same as non-shielded rows.
- `gtd_project_canvas` seed consistent with the same principle (or documented as already flag-only).
- **No server-side enforcement anywhere:** `grep -rn "redact" src/` shows only flag-emission + `gtd_set_redaction`; no field/row is suppressed on `redacted`. The § 1a invariant (surface + write, never enforce) is documented in `CLAUDE.md`, and a guard test pins it.
- `make test` green; version 1.30.0; debrief filed; server restarted via the connector.
- On the board: shielded rows still render as locked placeholders and stay out of the funnel (client unchanged) — the curtain is intact, the data simply flows behind it.

---

*Companion context (not needed to execute, for background): this session also landed the gtd-side engage recalibration (band-ceiling estimates ≤2/≤5/≤15/≤30/30+, gap-filter, priority-then-size sort, the ≤2 "Do Now" chip) and backfilled estimates, energy, and action-context tags across the active backlog — so the funnel now has fully populated data to filter once this server change deploys.*
