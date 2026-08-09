"""Application settings loaded from environment variables (.env)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings. Secrets come from .env (never committed)."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    dhan_client_id: str = Field(default="", validation_alias="DHAN_CLIENT_ID")
    dhan_access_token: str = Field(default="", validation_alias="DHAN_ACCESS_TOKEN")
    dhan_env: str = Field(default="PROD", validation_alias="DHAN_ENV")

    upstox_analytics_token: str = Field(default="", validation_alias="UPSTOX_ANALYTICS_TOKEN")

    def require_dhan_credentials(self) -> None:
        if not self.dhan_client_id or not self.dhan_access_token:
            raise RuntimeError(
                "DhanHQ credentials missing. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to .env"
            )

    def require_upstox_credentials(self) -> None:
        if not self.upstox_analytics_token:
            raise RuntimeError("Upstox analytics token missing. Add UPSTOX_ANALYTICS_TOKEN to .env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
