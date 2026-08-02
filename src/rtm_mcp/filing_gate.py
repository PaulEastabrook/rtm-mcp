"""Filing mode — the artefact-resolution gate on `gtd_note_attach_output` (write gate 4).

The fourth deterministic **write-boundary gate**, and the first to look outside RTM. Filing an
artefact (`agent-memory:file-store`) and journalling it (`gtd_note_attach_output`) are two acts,
and nothing bound them — so the second was forgettable. Measured 2026-08-01 across the whole
estate: **97 of 126 output-side filed artefacts carried no OUTPUT note at all (77%)**, and of the
104 OUTPUT notes that did exist only 37 carried a machine-readable `FILING:` line. This is the
note-type gate's argument one layer out: *a rule a session can forget is not a rule.*

**What it checks — presence, not identity (for now).** Given a vault, the gate resolves
`filing_path` under it and refuses the note when:

    the artefact does not exist            → `rejected_by="artefact_missing"`
    the artefact exists, no companion       → `rejected_by="companion_missing"`

One :class:`ErrorCode` (``FILING_UNRESOLVED``) with the verdict in ``error.details``, following
the v5.2.0 shape-vs-vocabulary precedent exactly: a second code would be a synonym pair, churning
all 100 tool fingerprints for a distinction the details already carry.

**`source_action` is reported, never required — and that is a sequencing fact, not timidity.**
The companion schema already defines `source_action` (the RTM↔vault join key) and
`agent_memory_file_query` already returns it, but a 40-artefact sample on 2026-08-01 found it
populated **0 times**. Requiring it would reject 100% of legitimate calls on day one. So the gate
keys on *path + companion presence*, and :func:`check_source_action` downgrades the join to an
advisory finding (also a `gtd_note_filing_gaps` class). Tightening to a rejection waits on
agent-memory-mcp's backfill — see the designed change § 3.

**An unmounted vault DEGRADES; it never rejects. This is the sharpest constraint in the module.**
:func:`companion.resolve_vault_root` returning ``None`` means the server cannot see the vault, not
that the artefact is missing — a session on a machine without the mount must still be able to
journal. The two cases share no code path and are pinned by separate tests, because a single
fixture that omits the vault would pass a gate that had collapsed them.

Note the interaction with the resolver's own contract: an explicit-but-invalid `RTM_VAULT_ROOT` /
`AI_MEMORY_DIR` returns ``None`` rather than falling through to the host default. So a mis-typed
override lands in the *degrade* branch, not the *reject* branch. That is correct — the server
genuinely cannot see a vault — and is called out here so nobody "fixes" it into a rejection.

**Read-only, and the membrane holds.** This extends the existing read-only companion seam
(`companion.py`, already live on `gtd_project_canvas`); it writes nothing to the vault. Populating
`source_action` is a vault write and therefore agent-memory-mcp's half of the designed change.

Modes (``config.strict_filing``): ``off`` (inert — pre-v6.4.0 behaviour byte-for-byte, and the
whole rollback plan) → ``warn`` (log to the v5.1.0 file sink, allow) → ``reject`` (**the shipped
default**). A typo'd mode fails loudly at config load. CONTRIBUTING § 6 says a *new* gate ships
default-off with the enable decision separate; the design of record approved `reject` and Paul
chose it, so the flag and its enabled default ship together — the deviation is stated rather than
smuggled, and `off` is asserted to reproduce prior behaviour.
"""

import logging
import os
from typing import Any

from .companion import resolve_companion_meta, resolve_vault_root
from .error_codes import ErrorCode
from .response_builder import build_error

logger = logging.getLogger(__name__)

#: The `config.strict_filing` vocabulary. Owned here (the gate owns its own modes) and imported
#: by config.py for field validation, so a typo'd env var fails loudly at load rather than
#: silently leaving the gate inert. Ordered as an escalation.
VALID_STRICT_FILING_MODES = ("off", "warn", "reject")

#: The modes in which the gate rejects rather than merely logging.
_ENFORCING_MODES = ("reject",)

#: The companion field that joins a filed artefact back to the RTM action that produced it.
SOURCE_ACTION_FIELD = "source_action"


def artefact_exists(vault_root: str | None, rel_path: str) -> bool:
    """Whether *rel_path* resolves to a real file inside *vault_root*.

    Containment-guarded exactly as :func:`companion.resolve_companion_meta` is — a path that
    escapes the vault is not an artefact, whatever the filesystem says. Never raises: any OS
    error is "not there", because a gate that can throw is worse than one that can be wrong.
    """
    if not vault_root or not (rel_path or "").strip():
        return False
    vault = os.path.abspath(os.path.expanduser(vault_root))
    target = os.path.normpath(os.path.join(vault, rel_path.strip().lstrip("/")))
    if not target.startswith(vault + os.sep):
        return False
    try:
        return os.path.isfile(target)
    except OSError:  # pragma: no cover — defensive; isfile already swallows most of these
        return False


def check_filing(vault_root: str | None, filing_path: str) -> tuple[str, str] | None:
    """Judge one filing path against the vault. Returns ``(rejected_by, reason)`` or None.

    Returns None — allow — when there is no vault. Absence of a mount is absence of evidence;
    see the module docstring.
    """
    if not vault_root:
        return None
    path = (filing_path or "").strip()
    if not artefact_exists(vault_root, path):
        return (
            "artefact_missing",
            f"no artefact resolves at '{path}' under the AI Memory vault",
        )
    if resolve_companion_meta(vault_root, path) is None:
        return (
            "companion_missing",
            f"'{path}' exists but carries no companion metadata, so it is untracked",
        )
    return None


def check_source_action(
    vault_root: str | None, filing_path: str, task_id: str
) -> tuple[str, str] | None:
    """Advisory: judge the companion's `source_action` join. Returns ``(finding, detail)`` or None.

    ``finding`` ∈ ``source_action_absent`` | ``source_action_mismatch``. **Never a rejection** —
    live population is 0%, so enforcing it today would refuse every legitimate call. It is
    reported on the receipt and counted by `gtd_note_filing_gaps`, which is what will show the
    population reaching zero gaps and make the tightening judgeable.
    """
    if not vault_root:
        return None
    meta = resolve_companion_meta(vault_root, (filing_path or "").strip())
    if meta is None:
        return None  # `check_filing` owns the companion verdict
    raw = meta.get(SOURCE_ACTION_FIELD)
    values = [str(v).strip() for v in (raw if isinstance(raw, list) else [raw]) if v]
    if not values:
        return (
            "source_action_absent",
            f"the companion carries no `{SOURCE_ACTION_FIELD}`, so the artefact cannot be "
            "joined back to this action by id",
        )
    wanted = str(task_id or "").strip()
    if wanted and not any(wanted in v for v in values):
        return (
            "source_action_mismatch",
            f"the companion's `{SOURCE_ACTION_FIELD}` ({', '.join(values)}) does not name "
            f"task {wanted}",
        )
    return None


def guided_error(filing_path: str, rejected_by: str, reason: str) -> dict[str, Any]:
    """Build the self-documenting rejection (teaches recovery, like every sibling gate)."""
    if rejected_by == "companion_missing":
        how = (
            "The file is there but nothing tracks it, so it cannot be found again by anything "
            "except this path — and a path is a location, not an identity. Re-file it through "
            "`agent_memory_file_put`, which writes the artefact and its companion atomically, "
            "then re-issue this call. If the deliverable is genuinely inline message text with "
            "no artefact, pass `unfiled=True` (and leave `filing_path` empty) — the note is "
            "written marked unfiled, with no FILING: line for a reader to follow. To disable "
            "the gate: RTM_STRICT_FILING=warn to log without rejecting, or "
            "RTM_STRICT_FILING=off to turn it off entirely."
        )
    else:
        how = (
            "Nothing resolves at that vault-relative path. Check it with "
            "`agent_memory_file_query` — the commonest causes are a path that was correct "
            "before a vault reorganisation, a leading '/', and a filename typo. File the "
            "artefact first (`agent_memory_file_put`), then journal it: an OUTPUT note whose "
            "FILING: line points nowhere is worse than no note, because it reads as evidence. "
            "If the deliverable is genuinely inline message text, pass `unfiled=True` (and "
            "leave `filing_path` empty). To disable the gate: RTM_STRICT_FILING=warn to log "
            "without rejecting, or RTM_STRICT_FILING=off to turn it off entirely."
        )
    return build_error(
        ErrorCode.FILING_UNRESOLVED,
        f"strict_filing: write rejected — {reason}",
        rejected_path=filing_path,
        reason=reason,
        rejected_by=rejected_by,
        how_to_proceed=how,
        strict_filing_mode=True,
    )


def enforce_filing(client: Any, filing_path: str, *, tool: str) -> dict[str, Any] | None:
    """Gate an artefact-journalling write. Returns a guided-error dict to reject, or None.

    Synchronous and filesystem-only: no RTM call in any mode, so a rejection costs nothing and
    can run before the task resolver.

    The ``"off"`` fallback on the ``getattr`` is for a config object lacking the attribute
    entirely (a test double, an older config): **absent is not unset**, and a gate that fires on
    a config it cannot read would be enforcing on a guess.
    """
    mode = getattr(client.config, "strict_filing", "off")
    if mode not in ("warn", *_ENFORCING_MODES):
        return None

    vault_root = resolve_vault_root(getattr(client.config, "vault_root", None))
    if not vault_root:
        # No mount, no evidence. Deliberately silent at WARNING: on a vault-less host this
        # would fire on every single filing and train the reader to ignore the channel. The
        # caller is told in the response instead, via the receipt advisory.
        logger.info("strict_filing(%s) inert via %s: no AI Memory vault resolved", mode, tool)
        return None

    verdict = check_filing(vault_root, filing_path)
    if verdict is None:
        return None
    rejected_by, reason = verdict

    # WARNING, not INFO — in `warn` mode this record is the gate's ONLY effect, so a level that
    # needs configuration to emit would make the whole mode a no-op (the v3.0.1 lesson, and the
    # reason `RTM_STRICT_NOTES=warn` collected silence for two releases).
    logger.warning(
        "strict_filing(%s) %s via %s: %r — %s",
        mode,
        rejected_by,
        tool,
        filing_path,
        "ALLOWED (observe-before-enforce)" if mode == "warn" else "REJECTED",
    )
    if mode == "warn":
        return None
    return guided_error(filing_path, rejected_by, reason)
