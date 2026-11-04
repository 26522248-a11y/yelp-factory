"""Typed settings loaded from config.yaml + .env (pydantic-settings)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config.yaml"
DEFAULT_ENV = ROOT / ".env"


class GPMConfig(BaseModel):
    flavor: Literal["global-v1", "gpm-v3"] = "global-v1"
    base_url: str = "http://127.0.0.1:9495"
    mcp_url: str = "http://127.0.0.1:9495/mcp"
    mcp_token: str = ""
    license_key: str = ""
    data_dir: str = ""
    read_only: bool = False
    connect_timeout_s: float = 20.0
    start_timeout_s: float = 60.0
    # Browser build must exist inside GPM; empty = ask the API for the newest one.
    browser_version: str = ""
    os_type: int = 1  # 1 = Windows
    browser_type: int = 1  # 1 = Chrome


class ConcurrencyConfig(BaseModel):
    workers: int = 8
    max_profiles: int = 8
    ram_guard_pct: float = 85.0


class TargetConfig(BaseModel):
    country: str = "US"
    cities: list[str] = Field(default_factory=lambda: ["Austin, TX"])
    zip_pool_file: str = "data/zips_us.json"


class ProxyConfig(BaseModel):
    kind: str = "residential"
    sticky_minutes: int = 45
    probe_timeout_s: float = 8.0
    max_fail_streak: int = 2
    default_raw: str = ""
    # Fail when a real page needs more than this to load (E-11).
    slow_page_p95_s: float = 25.0


class EmailConfig(BaseModel):
    provider: Literal["ms_graph", "imap", "fake"] = "ms_graph"
    domains: list[str] = Field(default_factory=lambda: ["fviainboxes.com"])
    poll_timeout_s: int = 180
    resend_wait_s: int = 60
    graph_client_id: str = ""
    graph_refresh_token: str = ""
    graph_tenant: str = "consumers"
    imap_host: str = "outlook.office365.com"
    blocked_domain_hours: int = 24


class SMSConfig(BaseModel):
    provider: str = "hup"
    api_key: str = ""
    # HupSMS service id (84 = Hotmail/Microsoft on Server 1; pick the target app's id).
    service_id: int = 84
    status_path: str = "/rent/status"
    cancel_path: str = "/rent/cancel"
    country: str = "US"
    max_price: float = 0.35
    timeout_s: int = 180


class CaptchaConfig(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["capsolver", "2captcha"])
    capsolver_key: str = ""
    two_captcha_key: str = ""
    timeout_s: int = 90
    human_in_loop: bool = True
    poll_interval_s: float = 3.0


class WarmingConfig(BaseModel):
    enabled: bool = True
    max_sessions_per_day: int = 3
    phase_days: dict[str, int] = Field(
        default_factory=lambda: {"P0": 2, "P1": 3, "P2": 5, "P3": 10, "P4": 10}
    )


class RetentionConfig(BaseModel):
    artifacts_days: int = 7


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YF_",
        env_nested_delimiter="__",
        env_file=str(DEFAULT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5433/yelp_factory"
    master_key: str = ""
    admin_token: str = ""
    admin_host: str = "127.0.0.1"
    admin_port: int = 8787
    artifacts_dir: str = "artifacts"
    log_level: str = "INFO"

    gpm: GPMConfig = Field(default_factory=GPMConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    sms: SMSConfig = Field(default_factory=SMSConfig)
    captcha: CaptchaConfig = Field(default_factory=CaptchaConfig)
    warming: WarmingConfig = Field(default_factory=WarmingConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _yaml_defaults(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _env_secrets() -> dict[str, Any]:
    """Secrets never live in YAML; they come from .env / Credential Manager."""
    mapping = {
        "YF_MASTER_KEY": "master_key",
        "YF_ADMIN_TOKEN": "admin_token",
        "YF_DATABASE_URL": "database_url",
    }
    out: dict[str, Any] = {}
    for env_name, field in mapping.items():
        if (value := os.environ.get(env_name)):
            out[field] = value
    return out


def load_settings(config_path: str | Path | None = None, env_file: str | Path | None = None) -> Settings:
    raw = _yaml_defaults(Path(config_path) if config_path else DEFAULT_CONFIG)
    # pydantic-settings reads nested env vars on top of these initial values.
    settings = Settings(**raw, _env_file=str(env_file or DEFAULT_ENV))
    for field, value in _env_secrets().items():
        setattr(settings, field, value)
    if settings.gpm.mcp_token:
        os.environ.setdefault("YF_GPM__MCP_TOKEN", settings.gpm.mcp_token)
    return settings


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
