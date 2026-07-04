"""Tests for companion-metadata resolution (the read-only vault file-IO seam)."""

from rtm_mcp.companion import (
    companion_candidates,
    enrich_files,
    parse_frontmatter,
    parse_yaml_body,
    resolve_companion_meta,
    resolve_vault_root,
)

FM = (
    "---\n"
    'schema_version: "1.0.0"\n'
    'title: "Decision X"\n'
    "type: form-prefilled\n"  # out-of-vocab value — must pass through verbatim
    "status: review-needed\n"
    "authors:\n"
    '  - "Paul (directing)"\n'
    "  - Claude\n"
    "tags: [sam, placement]\n"
    'decision: ""\n'  # empty scalar — must be dropped
    "---\n"
    "body text — not parsed\n"
)


def _make_vault(root, *, marker=True):
    if marker:
        (root / "memory").mkdir(parents=True, exist_ok=True)
        (root / "memory" / "_index.md").write_text("# index\n")
    return str(root)


class TestParseFrontmatter:
    def test_scalars_quote_stripped_and_passthrough(self):
        m = parse_frontmatter(FM)
        assert m["title"] == "Decision X"
        assert m["schema_version"] == "1.0.0"
        assert m["type"] == "form-prefilled"  # never vocab-validated
        assert m["status"] == "review-needed"

    def test_block_list(self):
        assert parse_frontmatter(FM)["authors"] == ["Paul (directing)", "Claude"]

    def test_inline_flow_list(self):
        assert parse_frontmatter(FM)["tags"] == ["sam", "placement"]

    def test_empty_scalar_dropped(self):
        assert "decision" not in parse_frontmatter(FM)

    def test_no_frontmatter_returns_empty(self):
        assert parse_frontmatter("just a body, no fences\n") == {}

    def test_stops_at_closing_fence(self):
        assert "body" not in parse_frontmatter(FM)


class TestParseYamlBody:
    def test_plain_yaml(self):
        assert parse_yaml_body('title: "T"\ntype: reference\n') == {
            "title": "T",
            "type": "reference",
        }

    def test_tolerates_leading_fence(self):
        assert parse_yaml_body("---\ntitle: T\n---\n")["title"] == "T"


class TestCompanionCandidates:
    def test_md_artefact_order(self):
        cands = companion_candidates("/d", "report.md")
        paths = [p for p, _ in cands]
        assert paths[0] == "/d/report.meta.md"  # dominant form first
        assert "/d/report.md" not in paths  # the .md form is skipped for md artefacts
        assert "/d/report.companion.md" in paths
        assert "/d/.companion/report.yaml" in paths
        assert "/d/report.metadata.yaml" in paths

    def test_non_md_artefact_includes_stem_md(self):
        paths = [p for p, _ in companion_candidates("/d", "report.docx")]
        assert paths[0] == "/d/report.meta.md"
        assert "/d/report.md" in paths  # non-md → stem.md form available

    def test_parse_modes(self):
        modes = {p: mode for p, mode in companion_candidates("/d", "x.pdf")}
        assert modes["/d/x.meta.md"] == "frontmatter"
        assert modes["/d/.companion/x.yaml"] == "yaml"
        assert modes["/d/x.metadata.yaml"] == "yaml"


class TestResolveVaultRoot:
    def test_explicit_valid(self, tmp_path):
        root = _make_vault(tmp_path)
        assert resolve_vault_root(root) == str(tmp_path)

    def test_explicit_invalid_returns_none(self, tmp_path):
        assert resolve_vault_root(str(tmp_path / "nope")) is None  # no marker, no fallthrough

    def test_explicit_present_but_no_marker(self, tmp_path):
        assert resolve_vault_root(_make_vault(tmp_path, marker=False)) is None

    def test_host_default(self, tmp_path, monkeypatch):
        vault = tmp_path / "Documents" / "AI Memory"
        (vault / "memory").mkdir(parents=True)
        (vault / "memory" / "_index.md").write_text("x")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows parity
        assert resolve_vault_root(None) == str(vault)

    def test_none_when_nothing_resolves(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        assert resolve_vault_root(None) is None


class TestResolveCompanionMeta:
    def _artefact(self, root, rel, companion_name, body):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artefact\n")
        (path.parent / companion_name).write_text(body)
        return rel

    def test_md_artefact_meta_md(self, tmp_path):
        rel = self._artefact(tmp_path, "personal/p/output/d.md", "d.meta.md", FM)
        meta = resolve_companion_meta(str(tmp_path), rel)
        assert meta["type"] == "form-prefilled"
        assert meta["authors"] == ["Paul (directing)", "Claude"]

    def test_docx_artefact_meta_md(self, tmp_path):
        rel = self._artefact(
            tmp_path, "work/p/output/r.docx", "r.meta.md", "---\ntype: report\nstatus: final\n---\n"
        )
        meta = resolve_companion_meta(str(tmp_path), rel)
        assert meta == {"type": "report", "status": "final"}

    def test_docx_artefact_stem_md(self, tmp_path):
        rel = self._artefact(tmp_path, "work/p/output/r.docx", "r.md", "---\ntype: report\n---\n")
        assert resolve_companion_meta(str(tmp_path), rel) == {"type": "report"}

    def test_companion_md_form(self, tmp_path):
        rel = self._artefact(
            tmp_path, "work/p/output/r.pdf", "r.companion.md", "---\ntype: reference\n---\n"
        )
        assert resolve_companion_meta(str(tmp_path), rel) == {"type": "reference"}

    def test_metadata_yaml_form(self, tmp_path):
        rel = self._artefact(
            tmp_path, "work/p/output/r.pdf", "r.metadata.yaml", "type: data\nstatus: draft\n"
        )
        assert resolve_companion_meta(str(tmp_path), rel) == {"type": "data", "status": "draft"}

    def test_sidecar_companion_folder_yaml(self, tmp_path):
        path = tmp_path / "work/p/output/r.pdf"
        path.parent.mkdir(parents=True)
        path.write_text("x")
        (path.parent / ".companion").mkdir()
        (path.parent / ".companion" / "r.yaml").write_text("type: presentation\n")
        meta = resolve_companion_meta(str(tmp_path), "work/p/output/r.pdf")
        assert meta == {"type": "presentation"}

    def test_meta_md_wins_over_companion_md(self, tmp_path):
        path = tmp_path / "work/p/output/r.pdf"
        path.parent.mkdir(parents=True)
        path.write_text("x")
        (path.parent / "r.meta.md").write_text("---\ntype: WINNER\n---\n")
        (path.parent / "r.companion.md").write_text("---\ntype: loser\n---\n")
        assert resolve_companion_meta(str(tmp_path), "work/p/output/r.pdf")["type"] == "WINNER"

    def test_no_companion_returns_none(self, tmp_path):
        path = tmp_path / "work/p/output/r.pdf"
        path.parent.mkdir(parents=True)
        path.write_text("x")
        assert resolve_companion_meta(str(tmp_path), "work/p/output/r.pdf") is None

    def test_non_artefact_name_skipped(self, tmp_path):
        path = tmp_path / "work/p/context.md"
        path.parent.mkdir(parents=True)
        path.write_text("x")
        (path.parent / "context.meta.md").write_text("---\ntype: x\n---\n")
        assert resolve_companion_meta(str(tmp_path), "work/p/context.md") is None

    def test_containment_guard(self, tmp_path):
        assert resolve_companion_meta(str(tmp_path / "vault"), "../escape/x.md") is None

    def test_no_vault_root(self, tmp_path):
        assert resolve_companion_meta(None, "work/p/output/r.md") is None


class TestEnrichFiles:
    def _vault_with(self, tmp_path):
        path = tmp_path / "work/p/output/r.md"
        path.parent.mkdir(parents=True)
        path.write_text("x")
        (path.parent / "r.meta.md").write_text("---\ntype: report\n---\n")
        return str(tmp_path)

    def test_attaches_meta(self, tmp_path):
        vault = self._vault_with(tmp_path)
        seed = {
            "frame": {"files": [{"n": "r.md", "path": "work/p/output/r.md"}]},
            "seed": [{"id": "c1", "files": [{"n": "r.md", "path": "work/p/output/r.md"}]}],
        }
        enrich_files(seed, vault)
        assert seed["frame"]["files"][0]["meta"] == {"type": "report"}
        assert seed["seed"][0]["files"][0]["meta"] == {"type": "report"}

    def test_no_meta_without_companion(self, tmp_path):
        seed = {"frame": {}, "seed": [{"id": "c1", "files": [{"path": "work/p/output/x.md"}]}]}
        enrich_files(seed, str(tmp_path))
        assert "meta" not in seed["seed"][0]["files"][0]

    def test_noop_without_vault(self):
        seed = {"seed": [{"id": "c1", "files": [{"path": "work/p/output/r.md"}]}]}
        enrich_files(seed, None)
        assert "meta" not in seed["seed"][0]["files"][0]


class TestNonUtf8Companion:
    def test_non_utf8_companion_yields_no_meta(self, tmp_path):
        # Contract: every IO failure → no meta, never raises. UnicodeDecodeError
        # is a ValueError, so it must be caught explicitly alongside OSError.
        path = tmp_path / "work" / "p" / "output" / "r.docx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artefact\n")
        (path.parent / "r.meta.md").write_bytes(b"\xff\xfe\x00b\x00a\x00d")  # UTF-16-ish bytes
        assert resolve_companion_meta(str(tmp_path), "work/p/output/r.docx") is None

    def test_non_utf8_first_candidate_falls_through_to_next(self, tmp_path):
        # A binary dominant-form companion must not mask a valid later form.
        path = tmp_path / "work" / "p" / "output" / "r.docx"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("artefact\n")
        (path.parent / "r.meta.md").write_bytes(b"\xff\xfe\x00b\x00a\x00d")
        (path.parent / "r.companion.md").write_text("---\ntype: report\n---\n")
        assert resolve_companion_meta(str(tmp_path), "work/p/output/r.docx") == {"type": "report"}
