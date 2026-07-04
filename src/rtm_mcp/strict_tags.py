"""Strict-tag mode — the *existence* gate for tag writes.

When ``config.strict_tags`` is enabled, the server refuses to apply any tag that
does not already exist in the RTM account. The runtime allow-list is simply the
account's current tag set (``client.get_account_tags()``) — the server has no
knowledge of the canonical taxonomy and never mints tags implicitly. Canonical
policing (whether an *existing* tag is the right/allowed one) stays plugin-side.

This module is pure policy glue: normalization, SmartAdd ``#token`` extraction,
and the guided-error response. The cache + RTM fetch live on the client.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Match a SmartAdd tag token: a '#' at the start or after whitespace, then the
# run of non-whitespace, non-'#' characters. Best-effort approximation of RTM's
# own SmartAdd tag tokenizer — over-matching a stray '#word' is intentional (it
# is exactly the accidental-minting case we want to catch); the guided error
# tells the caller to re-issue with parse=False or fix the name.
_SMARTADD_TAG_RE = re.compile(r"(?:^|\s)#([^\s#]+)")


def normalize_tag(tag: str) -> str:
    """Normalize a tag for comparison — trim + lower-case (matches RTM)."""
    return tag.strip().lower()


def split_tags(tags: str) -> list[str]:
    """Split a comma-separated tag string into normalized, de-duped names.

    Empty/whitespace fragments (from sloppy comma-splitting) are dropped.
    """
    seen: set[str] = set()
    out: list[str] = []
    for fragment in (tags or "").split(","):
        name = normalize_tag(fragment)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def extract_smartadd_tags(name: str) -> list[str]:
    """Extract normalized SmartAdd ``#tokens`` from a task name (parse=True path)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in _SMARTADD_TAG_RE.findall(name or ""):
        tag = normalize_tag(raw)
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def guided_error(rejected: list[str]) -> dict[str, Any]:
    """Build the self-documenting rejection response (teaches recovery)."""
    return {
        "error": "strict_tag_mode: write rejected — tag does not exist in the account",
        "rejected_tags": rejected,
        "reason": (
            "Strict mode blocks creating new tags via this server. Only tags that "
            "already exist in your RTM account may be applied."
        ),
        "how_to_proceed": (
            "Use an existing tag (call get_tags to see the available set). If you "
            "genuinely need a NEW tag, it must be created deliberately and "
            "out-of-band: (1) codify it in the gtd tag taxonomy "
            "(plugins/gtd/skills/gtd/references/tag-taxonomy.md), then (2) create it "
            "in RTM via the native client (mobile/web) — Paul does this by hand, then "
            "(3) retry — once it exists, this server will accept it. The server never "
            "mints tags implicitly."
        ),
        "strict_tag_mode": True,
    }


async def enforce_strict_tags(
    client: Any, requested: list[str], *, tool: str
) -> dict[str, Any] | None:
    """Gate a tag write. Returns a guided-error dict to reject, or None to allow.

    No-op (returns None) when strict mode is off or there are no tags to check.
    Validates against the account tag set; on a miss it does a live re-fetch
    before failing, so a tag created moments ago out-of-band isn't falsely
    rejected. Logs every rejection at info level.
    """
    if not getattr(client.config, "strict_tags", False):
        return None

    # Defensive normalization: the allow-list is normalized (trim + lower), so
    # compare like-for-like even if a caller passes un-normalized tags.
    wanted = [normalize_tag(t) for t in requested]
    wanted = [t for t in wanted if t]
    if not wanted:
        return None

    allowed = await client.get_account_tags()
    offending = [t for t in wanted if t not in allowed]
    if offending:
        # Cache-miss safety: re-check live before rejecting.
        allowed = await client.get_account_tags(force_refresh=True)
        offending = [t for t in wanted if t not in allowed]

    if offending:
        logger.info(
            "strict_tag_mode rejected %s via %s (requested=%s)",
            offending,
            tool,
            wanted,
        )
        return guided_error(offending)

    return None
