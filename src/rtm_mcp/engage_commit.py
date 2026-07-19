"""Engage verdict grammar (server-side) — the pure contract backing `gtd_apply_engage_commit`.

The server-side twin of the gtd plugin's `scripts/validate-engage-verdict.py`. Both conform to the
SAME source of truth — `plugins/gtd/skills/gtd/references/engage-verdict-grammar.md` (§§ 1-4) — but
this repo is standalone (it cannot read the marketplace markdown at runtime, as the chat-side
validator does), so the enum / per-kind base legality / two flag guards are **codified here as
Python constants**, exactly as `canvas_commit.py` holds the closed classifier→tag taxonomy. When the
grammar doc changes, this module is the lockstep edit (codification before validation — the grammar
invariant: a verdict is a governed extension of the contract, never a local invention).

Posture — HARD-FAIL (grammar § "Posture", unlike the report-and-resolve Definition-of-Ready): a
verdict is a committed intent to write RTM, so an off-enum or type-illegal verdict fails the batch
with a closest-legal suggestion; `gtd_apply_engage_commit` writes NOTHING when any item is rejected.
This module is the deterministic legality core; the tool re-derives each item's kind / has_deadline /
blocked SERVER-SIDE (the ACL — the client's flags are never trusted) and feeds them here.

Vault-free, pure (no IO). British English.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from .canvas_commit import (
    AI_CONVERSATION,
    AI_DEFERRED,
    AI_PROGRESS,
    OVERLAY_REFRESH,
)
from .error_codes import ErrorCode

# `#someday` / `#calendar_entry` are existing gtd taxonomy tags (reused, not minted here) — the
# `someday` and `to_calendar` verdict writes. Defined locally to keep the grammar self-contained.
SOMEDAY_TAG = "someday"
CALENDAR_ENTRY_TAG = "calendar_entry"

# The four item kinds legality is keyed by (grammar § 2 — resolved from the workflow-state tag).
KINDS = ("action", "waiting_for", "calendar_entry", "project")

# § 1 — the verdict enum → family (progress | defer | guard). Codified from the grammar § 1 table.
VERDICT_FAMILY: dict[str, str] = {
    "do_now": "progress",
    "draft": "progress",
    "nudge": "progress",
    "to_calendar": "progress",
    "next_actions": "defer",
    "today": "defer",
    "defer_start": "defer",
    "bump": "defer",
    "resurface": "defer",
    "someday": "defer",
    "keep": "guard",
    "drop": "guard",
}

# The `reason` values `validate` (the pure verdict-legality core) can attach to an illegal item.
# LOCKSTEP (v2.0.0): these three mirror gtd's `validate-engage-verdict.py` under the ratified
# `engage-verdict-grammar.md`. They were hyphenated (`off-enum`/`unknown-kind`/`type-illegal`)
# through v1.35.0 and were normalised to underscores when the reject vocabularies were unified
# into the ErrorCode registry — the gtd validator, its tests, and the grammar document were
# changed in the same release. Never re-spell them on one side alone.
VERDICT_REJECT_REASONS = frozenset(
    {ErrorCode.OFF_ENUM, ErrorCode.UNKNOWN_KIND, ErrorCode.TYPE_ILLEGAL}
)
# The complete `rejected[].reason` vocabulary gtd_apply_engage_commit can emit — the canonical
# source the output-schema model cites (drift-proof, like COMMIT_REJECT_REASONS). It is
# VERDICT_REJECT_REASONS (produced here by `validate`) plus the reasons produced in the tool
# wrapper: `task_not_found` (id absent from the account — v2.0.0 reconciled the former bare
# `not_found` onto the registry's resolution code), `destructive_unconfirmed` (a `drop` without
# confirm_destructive — formerly `confirm_destructive_required`, one concept that had two names),
# `bad_date` (a date phrase parse_time could not resolve), and `strict_tag_rejected` (the
# strict-tag existence gate — formerly `non_canonical_tag`).
ENGAGE_REJECT_REASONS = VERDICT_REJECT_REASONS | frozenset(
    {
        ErrorCode.TASK_NOT_FOUND,
        ErrorCode.DESTRUCTIVE_UNCONFIRMED,
        ErrorCode.BAD_DATE,
        ErrorCode.STRICT_TAG_REJECTED,
    }
)

# § 2 — per-kind base legality (L = legal). The two flag guards (§ 3) then override this per item.
# Keyed [verdict][kind] → bool. Codified byte-for-byte from the grammar § 2 matrix.
_L = True
_X = False
BASE_LEGALITY: dict[str, dict[str, bool]] = {
    #               action  waiting_for  calendar_entry  project
    "do_now": {"action": _L, "waiting_for": _X, "calendar_entry": _L, "project": _X},
    "draft": {"action": _L, "waiting_for": _X, "calendar_entry": _X, "project": _X},
    "nudge": {"action": _X, "waiting_for": _L, "calendar_entry": _X, "project": _X},
    "to_calendar": {"action": _L, "waiting_for": _X, "calendar_entry": _X, "project": _X},
    "next_actions": {"action": _L, "waiting_for": _X, "calendar_entry": _X, "project": _X},
    "today": {"action": _L, "waiting_for": _L, "calendar_entry": _L, "project": _X},
    "defer_start": {"action": _L, "waiting_for": _X, "calendar_entry": _X, "project": _X},
    "bump": {"action": _L, "waiting_for": _L, "calendar_entry": _L, "project": _X},
    "resurface": {"action": _X, "waiting_for": _X, "calendar_entry": _X, "project": _X},
    "someday": {"action": _L, "waiting_for": _L, "calendar_entry": _L, "project": _L},
    "keep": {"action": _L, "waiting_for": _L, "calendar_entry": _L, "project": _L},
    "drop": {"action": _L, "waiting_for": _L, "calendar_entry": _L, "project": _L},
}

# § 3.1 — deadline guard: when has_deadline, the legal set collapses to exactly these.
DEADLINE_LEGAL = ("do_now", "to_calendar", "keep", "drop")

# Preference order for a closest-legal suggestion when a verdict is type-illegal (mirrors the
# chat-side validator's SUGGEST_ORDER so both surfaces recommend the same correction).
_SUGGEST_ORDER = (
    "keep",
    "next_actions",
    "today",
    "do_now",
    "bump",
    "someday",
    "defer_start",
    "to_calendar",
    "drop",
    "draft",
    "nudge",
    "resurface",
)


def base_verdict(verdict: str) -> str:
    """Strip a `:<arg>` suffix (`defer_start:next friday`, `bump:+3d`) → the bare verb. The grammar
    governs the verb; the date argument is resolved server-side by parse_time."""
    return str(verdict or "").split(":", 1)[0].strip()


def verdict_arg(verdict: str) -> str:
    """The inline `:<arg>` suffix (the date phrase / bump), or "" when the verdict is bare."""
    parts = str(verdict or "").split(":", 1)
    return parts[1].strip() if len(parts) == 2 else ""


def is_legal(verb: str, kind: str, has_deadline: bool, blocked: bool) -> bool:
    """Legality = base matrix (§ 2) overridden by the two flag guards (§ 3). The deadline guard
    (§ 3.1) takes precedence over the blocked guard (§ 3.2)."""
    if has_deadline:
        return verb in DEADLINE_LEGAL
    if verb == "resurface":
        return bool(blocked)  # § 3.2 — base-illegal for every kind; enabled only when blocked
    return BASE_LEGALITY.get(verb, {}).get(kind, False)


def _suggest(kind: str, has_deadline: bool, blocked: bool) -> str | None:
    for cand in _SUGGEST_ORDER:
        if is_legal(cand, kind, has_deadline, blocked):
            return cand
    return None


def suggest_verdict(kind: str, has_deadline: bool, blocked: bool) -> str:
    """The deterministic pre-triage verdict for the seed (grammar-adjacent; the honest default per
    the designed change): a hard deadline → `keep` (surface for action); a blocked item →
    `resurface` (hand to the graph); a waiting-for → `nudge`; a soft-parked action → `next_actions`
    (strip the date). Calendar entries and projects default to `keep`. Precedence deadline > blocked
    > kind — and every branch returns a type-legal verdict."""
    if has_deadline:
        return "keep"
    if blocked:
        return "resurface"
    if kind == "waiting_for":
        return "nudge"
    if kind in ("calendar_entry", "project"):
        return "keep"
    return "next_actions"


def validate(items: list[dict[str, Any]]) -> dict[str, Any]:
    """items: [{id, verdict, kind, has_deadline?, blocked?}] with SERVER-DERIVED flags.

    Returns {ok, results, errors}. Each result: {id, verdict, base, kind, family, legal, reason,
    suggestion}. `reason` is None or one of VERDICT_REJECT_REASONS. HARD-FAIL: `ok` is
    True iff every item is legal (the tool writes nothing otherwise). Mirrors the chat-side
    validate-engage-verdict.py case-for-case.
    """
    results: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        rid = it.get("id", i)
        raw = it.get("verdict", "")
        kind = it.get("kind")
        has_deadline = bool(it.get("has_deadline", False))
        blocked = bool(it.get("blocked", False))
        verb = base_verdict(raw)
        res: dict[str, Any] = {
            "id": rid,
            "verdict": raw,
            "base": verb,
            "kind": kind,
            "family": VERDICT_FAMILY.get(verb),
            "legal": False,
            "reason": None,
            "suggestion": None,
        }
        if verb not in VERDICT_FAMILY:
            res["reason"] = ErrorCode.OFF_ENUM.value
            close = difflib.get_close_matches(verb, list(VERDICT_FAMILY), n=1, cutoff=0.4)
            res["suggestion"] = close[0] if close else None
        elif kind not in KINDS:
            res["reason"] = ErrorCode.UNKNOWN_KIND.value
        elif not is_legal(verb, kind, has_deadline, blocked):
            res["reason"] = ErrorCode.TYPE_ILLEGAL.value
            res["suggestion"] = _suggest(kind, has_deadline, blocked)
        else:
            res["legal"] = True
        results.append(res)
    errors = [r for r in results if not r["legal"]]
    return {"ok": not errors, "results": results, "errors": errors}


def date_phrase_for(verb: str, arg: str, date_phrase: str | None) -> str | None:
    """The natural-language phrase a date-verdict feeds to parse_time (Europe/London, authoritative),
    or None for a verdict that writes no date. The client's `date_phrase` (or the inline `:<arg>`) is
    a HINT for `defer_start` only — never a final date; parse_time resolves it server-side.

    - `today`            → "today"
    - `bump:+<n>d`       → "in <n> days" (RTM-parseable; forward from now — the renegotiation intent;
                            defaults to 1 day, RTM `postpone` parity, when the count is absent/garbage)
    - `defer_start`      → the supplied phrase (free text, e.g. "next monday"); "today" if none given
    - anything else      → None (no date write)
    """
    phrase = (arg or date_phrase or "").strip()
    if verb == "today":
        return "today"
    if verb == "bump":
        m = re.search(r"(\d+)", phrase)
        n = int(m.group(1)) if m else 1
        return f"in {n} days"
    if verb == "defer_start":
        return phrase or "today"
    return None


# ── Progress steer (the per-item `note` — Tier 1 of the engage steer tiering) ──────────────────────
# The board sends a short steer alongside the three PROGRESS verdicts (`draft`/`do_now`/`nudge`):
# Paul's typed text or the board's Tier-2.1 KG-grounded suggestion. The server attaches it as a
# dedicated STEER note so the #ai_progress_requested drafting path can read it as the first-pass
# instruction. `note` is UNTRUSTED input (the ACL): advisory DATA, never an instruction to the server,
# and it NEVER influences verdict legality or the server's flag re-derivation. Only these verbs consume
# it; every other verdict ignores any `note` silently (the board never sends one for them).
STEER_VERBS = ("draft", "do_now", "nudge")
STEER_NOTE_TYPE = "STEER"
STEER_MAX_LEN = 500  # cap the advisory steer; a longer note is truncated, not rejected

# A STEER note's title line (the body's first line, per RTM's `body = title\ntext` storage reality).
_STEER_TITLE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} — STEER — \S+")


def sanitize_steer(note: Any) -> tuple[str | None, str | None]:
    """ACL-sanitise the untrusted per-item steer → ``(clean_text, warning)``.

    Posture (grammar-adjacent, per the Tier-1 brief): a malformed steer must never fail an otherwise
    legal renegotiation — it is DROPPED with a per-item warning, the verdict write still proceeds.
    - non-string          → ``(None, "note_not_string")`` (dropped)
    - None / empty / all-whitespace → ``(None, None)`` (nothing to attach, no warning)
    - control characters   → replaced with a space, whitespace collapsed
    - longer than STEER_MAX_LEN → truncated, ``warning = "note_truncated"``
    """
    if note is None:
        return None, None
    if not isinstance(note, str):
        return None, "note_not_string"
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", note)  # strip control chars (incl. newlines/tabs)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()  # collapse whitespace
    if not cleaned:
        return None, None
    if len(cleaned) > STEER_MAX_LEN:
        return cleaned[:STEER_MAX_LEN].rstrip(), "note_truncated"
    return cleaned, None


def make_steer_note(stamp: str, verb: str, text: str) -> tuple[str, str]:
    """``(note_title, note_text)`` for a progress-verdict steer. Title carries the localised timestamp
    + STEER type + verb (so the drafting path selects the latest STEER note deterministically); the
    body is the PURE sanitised steer text — no marker pollution, so the drafting agent reads a clean
    instruction. Mirrors the CHAT/ORDER timestamped-title convention."""
    return f"{stamp} — {STEER_NOTE_TYPE} — {verb}", text


def steer_note_text(body: str) -> str | None:
    """The steer text carried by an existing STEER note body (``title\\ntext``), or None when the note
    is not a STEER note. The idempotency probe: a re-commit of the same steer compares equal here and
    is skipped (replace-or-skip), so a note is never duplicated."""
    if not body:
        return None
    line1, _, rest = body.partition("\n")
    if _STEER_TITLE_RE.match(line1.strip()):
        return rest.strip()
    return None


def collect_engage_tags(items: list[dict[str, Any]]) -> set[str]:
    """The union of tags the batch would WRITE across its legal verdicts — the strict-tag existence
    gate's input (mirrors `canvas_commit.collect_commit_tags`). Every write carries #ai_conversation;
    `someday`/`resurface` also stamp the progression-signal mark; `to_calendar` adds #calendar_entry;
    `draft` adds the progression tags. All are EXISTING gtd tags (no new tag → no activation hazard).
    A blocked `draft` may also add #ai_deferred_pending_unblock, included conservatively. `do_now`/
    `keep`/`drop` write no tag.
    """
    tags: set[str] = set()
    for it in items:
        verb = base_verdict(it.get("verdict", ""))
        if verb in ("keep", "do_now", "drop"):
            continue
        tags.add(AI_CONVERSATION)
        if verb == "someday":
            tags.update({SOMEDAY_TAG, OVERLAY_REFRESH})
        elif verb == "resurface":
            tags.add(OVERLAY_REFRESH)
        elif verb == "to_calendar":
            tags.add(CALENDAR_ENTRY_TAG)
        elif verb == "draft":
            tags.update({AI_PROGRESS, AI_DEFERRED})
    return tags
