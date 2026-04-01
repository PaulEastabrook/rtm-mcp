"""Tests for RTM configuration loading and saving."""

import json
from pathlib import Path

import pytest

from rtm_mcp.config import RTMConfig


class TestIsConfigured:
    def test_fully_configured(self) -> None:
        config = RTMConfig(api_key="k", shared_secret="s", token="t")
        assert config.is_configured()

    def test_missing_key(self) -> None:
        config = RTMConfig(api_key="", shared_secret="s", token="t")
        assert not config.is_configured()

    def test_missing_secret(self) -> None:
        config = RTMConfig(api_key="k", shared_secret="", token="t")
        assert not config.is_configured()

    def test_missing_token(self) -> None:
        config = RTMConfig(api_key="k", shared_secret="s", token="")
        assert not config.is_configured()


class TestSave:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        config = RTMConfig(api_key="key1", shared_secret="sec1", token="tok1")
        out = tmp_path / "config.json"
        config.save(out)

        data = json.loads(out.read_text())
        assert data["api_key"] == "key1"
        assert data["shared_secret"] == "sec1"
        assert data["token"] == "tok1"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        out = tmp_path / "a" / "b" / "config.json"
        config = RTMConfig(api_key="k", shared_secret="s", token="t")
        config.save(out)
        assert out.exists()

    def test_save_overwrites(self, tmp_path: Path) -> None:
        out = tmp_path / "config.json"
        RTMConfig(api_key="old", shared_secret="s", token="t").save(out)
        RTMConfig(api_key="new", shared_secret="s", token="t").save(out)
        assert json.loads(out.read_text())["api_key"] == "new"


class TestLoadFromFile:
    def test_load_from_config_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / ".config" / "rtm-mcp"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({
            "api_key": "fk",
            "shared_secret": "fs",
            "token": "ft",
        }))

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Clear env vars so file loading kicks in
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        config = RTMConfig.load()
        assert config.api_key == "fk"
        assert config.shared_secret == "fs"
        assert config.auth_token == "ft"

    def test_load_falls_back_to_legacy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        legacy_dir = tmp_path / ".config" / "rtm"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "config.json").write_text(json.dumps({
            "api_key": "lk",
            "shared_secret": "ls",
            "token": "lt",
        }))

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        config = RTMConfig.load()
        assert config.api_key == "lk"

    def test_load_survives_corrupt_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = tmp_path / ".config" / "rtm-mcp"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text("{bad json")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        config = RTMConfig.load()
        assert not config.is_configured()
