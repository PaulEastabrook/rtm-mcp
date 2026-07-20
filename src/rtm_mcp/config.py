"""RTM MCP Configuration management."""

import json
import os
from pathlib import Path

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .note_shape import VALID_STRICT_NOTES_MODES


class RTMConfig(BaseSettings):
    """RTM API configuration.

    Loads from:
    1. Environment variables (RTM_API_KEY, RTM_SHARED_SECRET, RTM_AUTH_TOKEN)
    2. Config file (~/.config/rtm-mcp/config.json)
    3. Legacy config file (~/.config/rtm/config.json)

    Profile support (added in v1.0.1):
        The RTM_PROFILE environment variable selects which credential set the
        server uses. Two profiles:

        - production (default) — uses RTM_API_KEY, RTM_SHARED_SECRET,
          RTM_AUTH_TOKEN env vars OR ~/.config/rtm-mcp/config.json
        - sandpit — uses RTM_SANDPIT_API_KEY, RTM_SANDPIT_SHARED_SECRET,
          RTM_SANDPIT_AUTH_TOKEN env vars OR
          ~/.config/rtm-mcp/config.sandpit.json

        The sandpit profile is intended for fixture-based testing of
        RTM-touching capabilities — see the gtd plugin's test-fixture
        pattern for the full convention.
    """

    model_config = SettingsConfigDict(
        env_prefix="RTM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Aliased fields (auth_token/vault_root) stay addressable by field name
        # too — several call sites construct RTMConfig(auth_token=...) directly.
        populate_by_name=True,
    )

    api_key: str = Field(default="", description="RTM API key")
    shared_secret: str = Field(default="", description="RTM shared secret")
    # validation_alias (not alias): pydantic-settings uses an alias VERBATIM as the env
    # name (the RTM_ prefix is not applied), so a bare alias="token" silently broke the
    # documented RTM_AUTH_TOKEN env var. "token" stays accepted for the kwarg/file path.
    auth_token: str = Field(
        default="",
        validation_alias=AliasChoices("RTM_AUTH_TOKEN", "token"),
        description="RTM auth token",
    )

    # Active profile — populated at load time from RTM_PROFILE env var
    profile: str = Field(default="production", description="Active credential profile")

    # Rate limiting configuration
    bucket_capacity: int = Field(default=3, description="Token bucket capacity (max burst)")
    safety_margin: float = Field(
        default=0.1,
        ge=0.0,
        lt=1.0,
        description="Safety margin (0.0-1.0) reducing effective rate from 1 RPS",
    )
    max_retries: int = Field(
        default=2, description="Max retries on HTTP 503 (total attempts = max_retries + 1)"
    )
    retry_delay_first: float = Field(
        default=2.0, description="Seconds to pause before first 503 retry"
    )
    retry_delay_subsequent: float = Field(
        default=5.0, description="Seconds to pause before 2nd+ 503 retry"
    )

    # Connection retry configuration
    conn_max_retries: int = Field(
        default=3, description="Max retries on transient connection errors"
    )
    conn_retry_delay_first: float = Field(
        default=1.0, description="Seconds before first connection retry"
    )
    conn_retry_delay_subsequent: float = Field(
        default=3.0, description="Seconds before 2nd+ connection retry"
    )

    # Strict-tag mode (existence gate)
    strict_tags: bool = Field(
        default=True,
        description=(
            "Reject tag writes that would introduce a tag not already present in "
            "the RTM account. Env var RTM_STRICT_TAGS. On by default; set "
            "RTM_STRICT_TAGS=0 (or false/no) to allow new tags."
        ),
    )

    # Note-shape mode (mechanical title-grammar gate) — see note_shape.py
    strict_notes: str = Field(
        default="off",
        description=(
            "Gate note-title writes against the mechanical grammar "
            "'YYYY-MM-DD [HH:MM] — TYPE — summary'. Env var RTM_STRICT_NOTES. "
            "'off' (default) inert; 'warn' logs but allows; 'shape' rejects. "
            "SHAPE only — the canonical TYPE vocabulary stays plugin-side."
        ),
    )

    # List-target mode (mechanical writability gate) — see list_targets.py
    strict_list_targets: bool = Field(
        default=False,
        description=(
            "Reject add_task/move_task whose caller-named destination list is smart "
            "or locked. Env var RTM_STRICT_LIST_TARGETS. Off by default; set "
            "RTM_STRICT_LIST_TARGETS=1 to enable. Mechanical writability only — "
            "canonical list policy stays plugin-side."
        ),
    )

    @field_validator("strict_notes")
    @classmethod
    def _validate_strict_notes(cls, value: str) -> str:
        """Fail loudly on a typo'd mode rather than silently running inert.

        A misspelt RTM_STRICT_NOTES would otherwise fall through the mode check in
        `enforce_note_shape` and disable the gate the operator thought they enabled.
        """
        normalized = (value or "off").strip().lower()
        if normalized not in VALID_STRICT_NOTES_MODES:
            raise ValueError(
                f"RTM_STRICT_NOTES must be one of {', '.join(VALID_STRICT_NOTES_MODES)}; "
                f"got '{value}'"
            )
        return normalized

    # Read-only AI Memory vault root — backs companion-metadata resolution on
    # gtd_project_canvas. RTM_VAULT_ROOT (server-local) takes precedence over the
    # shared AI_MEMORY_DIR (the agent-memory plugins' canonical override). When unset,
    # companion.resolve_vault_root falls back to the cross-platform host default
    # (~/Documents/AI Memory) if its memory/_index.md marker exists, else resolution is
    # off and file objects carry no `meta` (graceful no-op). The validation_alias bypasses
    # the RTM_ env_prefix so AI_MEMORY_DIR is honoured verbatim.
    vault_root: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RTM_VAULT_ROOT", "AI_MEMORY_DIR"),
        description=(
            "Read-only AI Memory vault root for resolving filed-artefact companion "
            "metadata on gtd_project_canvas. Env: RTM_VAULT_ROOT (preferred) or "
            "AI_MEMORY_DIR. Unset → host default ~/Documents/AI Memory when present, "
            "else companion resolution is off."
        ),
    )

    @classmethod
    def load(cls) -> "RTMConfig":
        """Load config from environment and/or config files.

        Profile-aware: respects RTM_PROFILE env var. Sandpit profile loads
        from RTM_SANDPIT_* env vars or ~/.config/rtm-mcp/config.sandpit.json.
        """
        profile = os.environ.get("RTM_PROFILE", "production").lower()

        if profile == "sandpit":
            return cls._load_sandpit()
        elif profile == "production":
            return cls._load_production()
        else:
            raise ValueError(f"RTM_PROFILE must be 'production' or 'sandpit', got '{profile}'")

    @classmethod
    def _load_production(cls) -> "RTMConfig":
        """Load production credentials (default behaviour pre-1.0.1)."""
        config = cls()

        if not config.is_configured():
            config = cls._load_from_file(config, profile="production")

        config.profile = "production"
        return config

    @classmethod
    def _load_sandpit(cls) -> "RTMConfig":
        """Load sandpit credentials. Refuses to start if not configured."""
        # Read sandpit env vars explicitly (pydantic doesn't natively support
        # per-profile env prefixes; we read them directly here)
        api_key = os.environ.get("RTM_SANDPIT_API_KEY", "")
        shared_secret = os.environ.get("RTM_SANDPIT_SHARED_SECRET", "")
        auth_token = os.environ.get("RTM_SANDPIT_AUTH_TOKEN", "")

        config = cls(api_key=api_key, shared_secret=shared_secret, auth_token=auth_token)

        if not config.is_configured():
            config = cls._load_from_file(config, profile="sandpit")

        if not config.is_configured():
            raise RuntimeError(
                "RTM_PROFILE=sandpit but sandpit credentials are not configured. "
                "Set RTM_SANDPIT_API_KEY, RTM_SANDPIT_SHARED_SECRET, "
                "RTM_SANDPIT_AUTH_TOKEN env vars OR create "
                "~/.config/rtm-mcp/config.sandpit.json with {api_key, shared_secret, token}. "
                "See the gtd plugin's testing-policy.md for setup guidance."
            )

        config.profile = "sandpit"
        return config

    @classmethod
    def _load_from_file(cls, base_config: "RTMConfig", profile: str = "production") -> "RTMConfig":
        """Load config from JSON file. Profile-aware filename selection."""
        if profile == "sandpit":
            config_paths = [
                Path.home() / ".config" / "rtm-mcp" / "config.sandpit.json",
            ]
        else:
            config_paths = [
                Path.home() / ".config" / "rtm-mcp" / "config.json",
                Path.home() / ".config" / "rtm" / "config.json",  # Legacy location
            ]

        for config_path in config_paths:
            if config_path.exists():
                try:
                    data = json.loads(config_path.read_text())
                    return cls(
                        api_key=data.get("api_key", base_config.api_key),
                        shared_secret=data.get("shared_secret", base_config.shared_secret),
                        auth_token=data.get("token", base_config.auth_token),
                    )
                except (OSError, json.JSONDecodeError, ValidationError):
                    continue

        return base_config

    def is_configured(self) -> bool:
        """Check if all required settings are present."""
        return bool(self.api_key and self.shared_secret and self.auth_token)

    def save(self, path: Path | None = None) -> None:
        """Save config to file. Profile-aware default path."""
        if path is None:
            filename = "config.sandpit.json" if self.profile == "sandpit" else "config.json"
            path = Path.home() / ".config" / "rtm-mcp" / filename

        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "api_key": self.api_key,
            "shared_secret": self.shared_secret,
            "token": self.auth_token,
        }

        # Credentials file: owner-read/write only.
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
        path.write_text(json.dumps(data, indent=2))


# RTM API endpoints
RTM_API_URL = "https://api.rememberthemilk.com/services/rest/"
RTM_AUTH_URL = "https://www.rememberthemilk.com/services/auth/"
RTM_WEB_BASE_URL = "https://www.rememberthemilk.com/app/"
