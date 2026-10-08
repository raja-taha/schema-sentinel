from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ENV_CANDIDATES = (
    Path.cwd() / ".env",
    _REPO_ROOT / ".env",
    Path(__file__).resolve().parents[2] / ".env",
)
_ENV_FILE = next((p for p in _ENV_CANDIDATES if p.is_file()), _REPO_ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SchemaSentinel"
    app_env: str = "development"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    api_key: str = "change-me-to-a-strong-secret"
    secret_key: str = "change-me-jwt-or-session-secret"

    database_url: str = (
        "postgresql+asyncpg://sentinel:sentinel@localhost:5434/schemasentinel"
    )
    database_url_sync: str = (
        "postgresql://sentinel:sentinel@localhost:5434/schemasentinel"
    )
    redis_url: str = "redis://localhost:6380/0"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    agent_mode: Literal["auto", "openai", "mock"] = "auto"
    risk_threshold_high: float = 0.7
    risk_threshold_medium: float = 0.4
    default_table_row_estimate: int = 1_000_000

    target_database_url: str = ""

    github_webhook_secret: str = ""
    github_token: str = ""
    github_app_id: str = ""
    github_check_name: str = "SchemaSentinel"

    otel_enabled: bool = False
    otel_export_otlp: bool = False
    otel_service_name: str = "schema-sentinel-api"
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_openai(self) -> bool:
        if self.agent_mode == "mock":
            return False
        if self.agent_mode == "openai":
            return bool(self.openai_api_key)
        return bool(self.openai_api_key)

    @property
    def samples_dir(self) -> Path:
        return _REPO_ROOT / "samples"


@lru_cache
def get_settings() -> Settings:
    return Settings()
