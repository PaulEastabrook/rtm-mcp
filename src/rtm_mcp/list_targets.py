"""List-target mode — the *mechanical* writability gate for item-write targets.

The third write-boundary gate, alongside ``strict_tags.py`` (tag existence) and
``note_shape.py`` (note-title grammar). When ``config.strict_list_targets`` is enabled, the
server refuses an ``add_task`` / ``move_task`` whose destination list is **mechanically
known** to be an unwritable target:

- ``smart=true``  → a saved-search view. Items cannot live in it.
- ``locked=true`` → an RTM system list (Inbox, Sent).

Both flags come from RTM's own ``rtm.lists.getList`` response, which the resolver already
reads — so the gate needs no extra API call and, critically, **no taxonomy**.

**Mechanical writability only — never canonical writability.** Whether a *writable* list is
the RIGHT target (Inbox_Stuff as the sole capture point, Processed as gtd-internal, the
per-list writability classes) is plugin-owned policy: the gtd list catalogue
(``references/list-catalogue.md``, enforced by ``validate-list-target.py``). That stays
plugin-side. The server enforces only what RTM itself tells it about a list's nature —
mirroring how strict-tag mode gates existence while canonicality stays plugin-side.

**Scope: caller-named targets only.** The gate judges a list the caller explicitly asked
for (``add_task(list_name=…)``, ``move_task(to_list_name=…)``). ``add_task``'s
default-list fallback is deliberately NOT gated: an account whose configured default is the
locked built-in Inbox would otherwise have every bare capture rejected, which is a
behaviour change the caller never asked for and cannot fix from the call site.
"""

import logging
from typing import Any

from .error_codes import ErrorCode
from .response_builder import build_error

logger = logging.getLogger(__name__)


def check_target(lst: dict[str, Any]) -> tuple[ErrorCode, str] | None:
    """Judge a resolved list dict. Returns ``(code, reason)`` to reject, or None to allow.

    Reads the ``smart`` / ``locked`` booleans ``parse_lists_response`` already coerces from
    RTM's ``"1"``/``"0"`` strings.
    """
    if lst.get("smart"):
        return (
            ErrorCode.SMART_LIST_TARGET,
            "it is a smart list (a saved-search view, not a container for items)",
        )
    if lst.get("locked"):
        return (
            ErrorCode.LOCKED_SYSTEM_LIST,
            "it is a locked system list (e.g. Inbox, Sent)",
        )
    return None


def guided_error(list_name: str, code: ErrorCode, reason: str) -> dict[str, Any]:
    """Build the self-documenting rejection (teaches recovery, like the strict-tag gate)."""
    return build_error(
        code,
        f"strict_list_targets: write rejected — cannot write to '{list_name}': {reason}",
        rejected_list=list_name,
        reason=reason,
        how_to_proceed=(
            "Call get_lists with include_smart=false to see the writable lists, then "
            "re-issue against one of those. Which writable list is the CORRECT target is "
            "plugin-side policy — see the gtd list catalogue "
            "(plugins/gtd/skills/gtd/references/list-catalogue.md) and its "
            "validate-list-target.py. To disable the gate entirely, unset "
            "RTM_STRICT_LIST_TARGETS (default: off)."
        ),
        strict_list_targets_mode=True,
    )


def enforce_list_target(
    client: Any, resolved: dict[str, Any], list_name: str, *, tool: str
) -> dict[str, Any] | None:
    """Gate an item-write target. Returns a guided-error dict to reject, or None to allow.

    ``resolved`` is a successful ``resolve_list_id`` result — its ``list`` key carries the
    full parsed list dict. No-op (returns None) when the gate is off (the default), so
    behaviour is byte-identical to pre-gate unless deliberately switched on. Synchronous:
    the resolver already fetched the list, so the gate makes no API call in any mode.
    """
    if not getattr(client.config, "strict_list_targets", False):
        return None

    verdict = check_target(resolved.get("list") or {})
    if verdict is None:
        return None

    code, reason = verdict
    logger.info("strict_list_targets rejected %r via %s (%s)", list_name, tool, code.value)
    return guided_error(list_name, code, reason)
