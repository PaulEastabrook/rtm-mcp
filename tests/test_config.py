"""Tests for RTM configuration loading and saving."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

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
        config_file.write_text(
            json.dumps(
                {
                    "api_key": "fk",
                    "shared_secret": "fs",
                    "token": "ft",
                }
            )
        )

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Clear env vars so file loading kicks in
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        config = RTMConfig.load()
        assert config.api_key == "fk"
        assert config.shared_secret == "fs"
        assert config.auth_token == "ft"

    def test_load_falls_back_to_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        legacy_dir = tmp_path / ".config" / "rtm"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "config.json").write_text(
            json.dumps(
                {
                    "api_key": "lk",
                    "shared_secret": "ls",
                    "token": "lt",
                }
            )
        )

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        config = RTMConfig.load()
        assert config.api_key == "lk"

    def test_load_survives_corrupt_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / ".config" / "rtm-mcp"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text("{bad json")

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        config = RTMConfig.load()
        assert not config.is_configured()


class TestStrictTagsConfig:
    def test_default_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RTM_STRICT_TAGS", raising=False)
        config = RTMConfig(api_key="k", shared_secret="s", token="t")
        assert config.strict_tags is True

    def test_disabled_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RTM_STRICT_TAGS", "0")
        assert RTMConfig().strict_tags is False

    def test_enabled_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RTM_STRICT_TAGS", "1")
        assert RTMConfig().strict_tags is True


class TestEnvVarCredentials:
    """RTM_AUTH_TOKEN must work as documented (regression: alias='token' made
    pydantic-settings expect a bare `token` env var instead)."""

    def test_rtm_auth_token_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RTM_API_KEY", "ek")
        monkeypatch.setenv("RTM_SHARED_SECRET", "es")
        monkeypatch.setenv("RTM_AUTH_TOKEN", "et")
        config = RTMConfig()
        assert config.api_key == "ek"
        assert config.shared_secret == "es"
        assert config.auth_token == "et"
        assert config.is_configured()

    def test_token_kwarg_still_works(self) -> None:
        config = RTMConfig(api_key="k", shared_secret="s", token="t")
        assert config.auth_token == "t"

    def test_auth_token_field_name_still_works(self) -> None:
        config = RTMConfig(api_key="k", shared_secret="s", auth_token="t")
        assert config.auth_token == "t"


class TestSafetyMarginBounds:
    def test_rejects_margin_of_one(self) -> None:
        # 1.0 would zero the refill rate → divide-by-zero in TokenBucket.acquire
        with pytest.raises(ValidationError):
            RTMConfig(api_key="k", shared_secret="s", token="t", safety_margin=1.0)

    def test_rejects_negative_margin(self) -> None:
        with pytest.raises(ValidationError):
            RTMConfig(api_key="k", shared_secret="s", token="t", safety_margin=-0.1)

    def test_accepts_valid_margin(self) -> None:
        config = RTMConfig(api_key="k", shared_secret="s", token="t", safety_margin=0.5)
        assert config.safety_margin == 0.5


class TestLoadFromFileResilience:
    def test_wrong_type_json_falls_through_to_legacy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # api_key as int → pydantic ValidationError; loader must continue to the
        # next config path rather than crash.
        config_dir = tmp_path / ".config" / "rtm-mcp"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"api_key": 123, "shared_secret": "s", "token": "t"})
        )
        legacy_dir = tmp_path / ".config" / "rtm"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "config.json").write_text(
            json.dumps({"api_key": "lk", "shared_secret": "ls", "token": "lt"})
        )

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        config = RTMConfig.load()
        assert config.api_key == "lk"

    def test_unreadable_file_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_dir = tmp_path / ".config" / "rtm-mcp"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text(
            json.dumps({"api_key": "fk", "shared_secret": "fs", "token": "ft"})
        )

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.delenv("RTM_API_KEY", raising=False)
        monkeypatch.delenv("RTM_SHARED_SECRET", raising=False)
        monkeypatch.delenv("RTM_AUTH_TOKEN", raising=False)

        def _deny(self: Path, *a: object, **kw: object) -> str:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "read_text", _deny)

        config = RTMConfig.load()  # must not raise
        assert not config.is_configured()


class TestSavePermissions:
    def test_save_sets_owner_only_permissions(self, tmp_path: Path) -> None:
        config = RTMConfig(api_key="k", shared_secret="s", token="t")
        path = tmp_path / "config.json"
        config.save(path)
        assert (path.stat().st_mode & 0o777) == 0o600
