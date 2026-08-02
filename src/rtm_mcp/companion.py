"""Companion-metadata resolution for canvas file objects — the file-IO seam.

Locates the read-only AI Memory vault root (cross-platform) and resolves each filed
artefact's companion (`.md`/`.yaml`) metadata, then enriches `gtd_project_canvas` file
objects with a `meta` block. The rest of the canvas pipeline stays pure; this module is
the one place that touches the vault filesystem.

Ported **by contract** (stdlib-only, no import) from the agent-memory file-store skill's
companion reader (`query_outputs.py`: `companion_for` / `parse_frontmatter`) and the vault
`_schema.md`, with two sanctioned extensions the brief calls for:
  * resolve MULTIPLE companion naming forms — the vault conventions are fragmented (a
    file-store coherence issue flagged upstream separately); we resolve robustly regardless;
  * read top-level LIST fields (`authors`/`tags`) that the reference parser deliberately skips.

`meta` is a full pass-through of present top-level frontmatter — every field that exists,
each independently optional, never validated against a vocabulary (real `type` values like
`form-prefilled` must pass through verbatim).

Read-only: no writes, ever. Every IO failure degrades to "no meta" (None), never raises.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Vault marker — the same pair the agent-memory plugins validate against.
_MARKER = ("memory", "_index.md")
# Cowork sandbox mount glob (parity with the plugins' resolver).
_SANDBOX_GLOB = "*/mnt/AI Memory"
# Names that are never artefacts (so never carry/attach companion meta).
_NON_ARTEFACT = {"context.md", "_schema.md", "_reference-index.md", "_index.md"}


def _has_marker(root: Path) -> bool:
    return (root / _MARKER[0] / _MARKER[1]).is_file()


def resolve_vault_root(configured: str | None) -> str | None:
    """Locate the read-only AI Memory vault root, or None (feature off / graceful).

    Mirrors the agent-memory plugins' resolver, cross-platform via ``pathlib`` (no OS
    branching):
      1. explicit override (config: ``RTM_VAULT_ROOT`` / ``AI_MEMORY_DIR``) — used as-is,
         validated by the ``memory/_index.md`` marker; NO fallthrough when invalid (so a
         mis-set path is an honest no-op, not a silent host-default surprise);
      2. Cowork sandbox mount (``/sessions/*/mnt/AI Memory``);
      3. host default ``~/Documents/AI Memory``.

    Returns the marker-validated absolute path as a string, else None — so a missing or
    marker-less vault degrades gracefully (no meta, no error) on any host.
    """
    if configured:
        root = Path(os.path.expanduser(configured))
        return str(root) if _has_marker(root) else None
    sandbox = Path("/sessions")
    if sandbox.is_dir():
        for mount in sorted(sandbox.glob(_SANDBOX_GLOB)):
            if _has_marker(mount):
                return str(mount)
    host = Path.home() / "Documents" / "AI Memory"
    if _has_marker(host):
        return str(host)
    return None


def _coerce_scalar(val: str) -> str:
    """Reference quote-stripping: trim, then strip surrounding double then single quotes."""
    return val.strip().strip('"').strip("'")


def _parse_yaml_lines(lines: list[str]) -> dict[str, Any]:
    """Minimal top-level YAML → dict. Handles scalars (quote-stripped), block lists
    (``key:`` then indented ``- item`` lines) and inline flow lists (``key: [a, b]``).

    Only column-0 keys are read; nested/indented keys and comments are ignored. Blank-valued
    scalars are dropped (matching the reference); an empty inline ``[]`` is kept as ``[]``.
    """
    out: dict[str, Any] = {}
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t", "-"):
            continue  # indented or a stray list item without a key — skip
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        if val.startswith("[") and val.endswith("]"):  # inline flow list
            inner = val[1:-1].strip()
            out[key] = [c for c in (_coerce_scalar(p) for p in inner.split(",")) if c]
        elif val:  # scalar — coerce first, drop if it reduces to empty (e.g. key: "")
            coerced = _coerce_scalar(val)
            if coerced:
                out[key] = coerced
        else:  # empty value → maybe a block list of indented "- item" lines
            items: list[str] = []
            while i < n and lines[i].strip().startswith("-"):
                items.append(_coerce_scalar(lines[i].strip()[1:]))
                i += 1
            items = [it for it in items if it]
            if items:
                out[key] = items
    return out


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Top-level YAML frontmatter between the first two ``---`` fences → dict."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    return _parse_yaml_lines(text[3:end].splitlines())


def parse_yaml_body(text: str) -> dict[str, Any]:
    """Top-level YAML over a ``.yaml`` companion body (an optional leading fence is tolerated)."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return _parse_yaml_lines(text[3:end].splitlines())
    return _parse_yaml_lines(text.splitlines())


def companion_candidates(folder: str, filename: str) -> list[tuple[str, str]]:
    """Ordered ``(companion_path, parse_mode)`` candidates for an artefact, first-existing-wins.

    ``parse_mode`` is ``"frontmatter"`` for ``.md`` companions, ``"yaml"`` for ``.yaml``.
    Forms (priority order): ``X.meta.md`` → ``X.md`` (non-md artefacts only) → ``X.companion.md``
    → ``.companion/X.yaml`` (sidecar folder) → ``X.metadata.yaml``.
    """
    stem, _, ext = filename.rpartition(".")
    if not stem:  # no extension
        stem, ext = filename, ""
    cands: list[tuple[str, str]] = [(os.path.join(folder, stem + ".meta.md"), "frontmatter")]
    if ext.lower() != "md":
        cands.append((os.path.join(folder, stem + ".md"), "frontmatter"))
    cands.append((os.path.join(folder, stem + ".companion.md"), "frontmatter"))
    cands.append((os.path.join(folder, ".companion", stem + ".yaml"), "yaml"))
    cands.append((os.path.join(folder, stem + ".metadata.yaml"), "yaml"))
    return cands


def resolve_companion_meta(vault_root: str | None, rel_path: str) -> dict[str, Any] | None:
    """Resolve a filed artefact's companion metadata → the parsed frontmatter dict, or None.

    Read-only; stays within ``vault_root`` (containment guard); skips non-artefact names; tries
    each companion form in order and returns the first non-empty parse. None when there is no
    vault, no companion, an empty companion, or any read error.
    """
    if not vault_root or not rel_path:
        return None
    vault = os.path.abspath(os.path.expanduser(vault_root))
    artefact = os.path.normpath(os.path.join(vault, rel_path.strip().lstrip("/")))
    if artefact != vault and not artefact.startswith(vault + os.sep):
        return None  # path escapes the vault
    folder, filename = os.path.dirname(artefact), os.path.basename(artefact)
    if (
        not filename
        or filename in _NON_ARTEFACT
        or filename.startswith("_")
        or filename.endswith(".meta.md")
    ):
        return None
    for cand, mode in companion_candidates(folder, filename):
        cand = os.path.normpath(cand)
        if cand != vault and not cand.startswith(vault + os.sep):
            continue
        if not os.path.isfile(cand):
            continue
        try:
            with open(cand, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            # UnicodeDecodeError is a ValueError, not an OSError — a non-UTF-8
            # companion must degrade to "no meta", never raise (module contract).
            continue
        meta = parse_frontmatter(text) if mode == "frontmatter" else parse_yaml_body(text)
        if meta:
            return meta
    return None


#: Non-artefact directories that do NOT announce themselves by prefix, so must be named.
#:
#: Kept as short as possible on purpose. The list this replaced —
#: ``{".git", ".obsidian", ".trash", "node_modules", "__pycache__", ".DS_Store"}`` — was
#: hand-maintained and drifted from what it was meant to describe: it never learned about
#: ``.stversions`` (Syncthing's version history), so a versioned COPY of a real artefact was
#: enumerated as an artefact, and because the whole folder is versioned it carries a companion
#: too — passing the v6.4.1 tracked-ness filter and appearing in `filed_unlinked` as an orphan
#: that can never be journalled. Everything else is now derived from the prefix rule below, so
#: the next `.something` cache directory needs no edit here.
#:
#: `system/` is scheduled-task run logs and the agent-memory write-log (1,256 files at the root,
#: 3 more under `general/`); pruned by NAME at any depth, because the nested one is the same kind
#: of machine output as the root one.
_SKIP_DIRS = {"node_modules", "system"}

# ── Sync-tool artefacts: what was surveyed, and why NO filename rule follows ────────────────
#
# The `.stversions` defect prompted the obvious next question — what else do iCloud, Syncthing
# and Dropbox leave lying about? Surveyed against the live vault 2026-08-02. The answer is that
# the dot-prefix rule above is sufficient, and the reason is structural rather than lucky:
#
#   DIRECTORY-level versioning duplicates the tree VERBATIM, so `X.md` and `X.meta.md` stay
#   paired and the copy resolves a companion — it is TRACKED, passes the v6.4.1 tracked-ness
#   filter, and reads as an orphan that can never be journalled. That is `.stversions`, and it
#   is the dangerous shape. Every such convention is dot-prefixed and already pruned.
#
#   FILE-level conflict copies mangle the STEM, so the duplicate's companion candidates never
#   match its own duplicated companion. iCloud writes `X.md` → `X 2.md` and `X.meta.md` →
#   `X.meta 2.md`; the duplicate then looks for `X 2.meta.md`, which does not exist. Syncthing's
#   `X.sync-conflict-<date>-<time>-<id>.md` behaves identically. They are therefore UNTRACKED by
#   construction, already excluded from `filed_unlinked`, and counted only in the separate
#   `untracked_unlinked_count`. Verified on the live pair at
#   `general/test-fixtures/mcp-write-smoke/2026-07-17/output/`.
#
# Live census: 6 `.sync-conflict-` files, all inside `.auto-memory` / `.obsidian` / `system`
# (already pruned); 1 iCloud ` 2` duplicate (untracked); 0 `~syncthing~` temps, 0 `.icloud`
# placeholders, 0 Dropbox `(conflicted copy)`. Dot-directories present: `.companion`, `.obsidian`,
# `.claude-plugin`, `.trash`, `.stversions`, `.stfolder`, `.auto-memory` — note `.claude-plugin`
# was not in the old hand-maintained list either, and the derived rule covers it for free.
#
# ⚠ DO NOT add a ` <n>.<ext>` exclusion. It reads as the obvious iCloud-duplicate rule and it is
# wrong: it matches three real tracked artefacts on this vault today —
# `AI Daily Briefing - 4 April 2026.md`, `AI Daily Briefing — 5 April 2026.md` and
# `Daily AI Briefing - March 28, 2026.md`. Same trap as "a path has no spaces" (see
# `gtd_chat.is_bare_path`): a rule that rejects real artefacts is worse than the noise it removes.

#: Extensions that are companions rather than artefacts in their own right.
_COMPANION_SUFFIXES = (".meta.md", ".companion.md", ".metadata.yaml")


def _is_artefact_dir(name: str) -> bool:
    """Whether a directory holds artefacts and should be walked.

    **Derived, not enumerated.** A directory beginning ``.`` or ``_`` is tooling state, not
    artefact space — which subsumes ``.git`` / ``.obsidian`` / ``.trash`` / ``.stversions`` /
    ``.stfolder`` / ``.auto-memory`` / ``.companion`` / ``__pycache__`` / ``_dev`` in one rule,
    and resolves an inconsistency in the process: ``_``-prefixed *files* were already skipped
    while ``_``-prefixed *directories* were walked.

    ``.companion/`` is pruned from the WALK (a companion is metadata, not an artefact) but is
    still READ by :func:`resolve_companion_meta`, which resolves it by path rather than by
    discovery. The two are independent and `test_companion.py` pins that.
    """
    return not name.startswith((".", "_")) and name not in _SKIP_DIRS


def walk_artefacts(vault_root: str | None, *, limit: int = 20000) -> list[dict[str, Any]] | None:
    """Enumerate the vault's **companion-tracked** artefacts → ``[{path, meta}]``, or None.

    Returns None — not ``[]`` — when there is no vault. The distinction is load-bearing for
    `gtd_note_filing_gaps`: an empty list means "walked it, found nothing", while None means
    "could not look", and a reconciliation that reported zero drift because nothing was mounted
    would be the silent-control failure this whole programme keeps finding.

    ONE walk, client-side, rather than a resolve per artefact — the `gtd_tag_report` precedent,
    which replaced a per-tag N+1 with a single scan. Companion files and index/schema files are
    excluded (they are metadata, not artefacts); an untracked artefact IS returned, with
    ``meta`` None, because "filed but untracked" is itself a finding class.

    Read-only and total: every OS error is skipped rather than raised (the module contract).
    *limit* is a runaway guard — a truncated walk is reported by the caller, never silently.
    """
    if not vault_root:
        return None
    root = os.path.abspath(os.path.expanduser(vault_root))
    out: list[dict[str, Any]] = []
    try:
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if _is_artefact_dir(d))
            for name in sorted(files):
                if (
                    name in _NON_ARTEFACT
                    or name.startswith((".", "_"))
                    or name.endswith(_COMPANION_SUFFIXES)
                ):
                    continue
                rel = os.path.relpath(os.path.join(folder, name), root)
                out.append(
                    {"path": rel.replace(os.sep, "/"), "meta": resolve_companion_meta(root, rel)}
                )
                if len(out) >= limit:
                    return out
    except OSError:  # pragma: no cover — os.walk already swallows per-directory errors
        return out
    return out


def enrich_files(seed: dict[str, Any], vault_root: str | None) -> dict[str, Any]:
    """Attach a ``meta`` block to each canvas file object whose companion resolves.

    Walks ``seed['frame']['files']`` (project-level support material) and each
    ``seed['seed'][*]['files']`` (per-action artefacts), mutating in place. No-op when
    ``vault_root`` is falsy. Backward-compatible: ``n/ext/kind/path`` are untouched; ``meta``
    is added only where a companion exists.
    """
    if not vault_root or not isinstance(seed, dict):
        return seed
    buckets: list[list[Any]] = []
    frame = seed.get("frame")
    if isinstance(frame, dict) and frame.get("files"):
        buckets.append(frame["files"])
    for it in seed.get("seed") or []:
        if isinstance(it, dict) and it.get("files"):
            buckets.append(it["files"])
    for files in buckets:
        for f in files:
            if not isinstance(f, dict) or not f.get("path"):
                continue
            meta = resolve_companion_meta(vault_root, f["path"])
            if meta:
                f["meta"] = meta
    return seed
