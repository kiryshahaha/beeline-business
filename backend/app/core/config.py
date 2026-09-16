"""Application settings. Commands are run from the backend directory."""

from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: PostgresDsn
    jwt_secret_key: str = "secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    notification_dispatcher_enabled: bool = True
    notification_poll_interval_seconds: float = 1.0
    firebase_enabled: bool = False
    firebase_project_id: str | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
