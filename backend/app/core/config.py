"""Application settings. Commands are run from the backend directory."""

from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: PostgresDsn
    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 30
    notification_dispatcher_enabled: bool = True
    notification_poll_interval_seconds: float = 1.0
    firebase_enabled: bool = False
    firebase_project_id: str | None = None
    geoapify_api_key: str | None = None
    geoapify_timeout_seconds: float = 10.0
    geoapify_max_retries: int = Field(default=2, ge=0, le=5)
    geoapify_cache_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    geoapify_cache_coordinate_precision: int = Field(default=6, ge=4, le=8)
    # Public addresses for links inside calendar feeds; empty values fall back or omit links.
    public_api_url: str | None = None
    frontend_url: str | None = None
    planning_enabled: bool = False
    planner_base_url: str = "http://127.0.0.1:8001"
    planner_service_token: SecretStr = SecretStr("")
    planner_connect_timeout_seconds: float = Field(default=2, gt=0, le=30)
    planner_read_timeout_seconds: float = Field(default=15, gt=0, le=60)
    planning_solve_time_limit_seconds: int = Field(default=5, ge=1, le=10)
    planning_total_timeout_seconds: float = Field(default=60, gt=0, le=300)
    planning_preview_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    # Bounded wait for the shared planning lock; see app/core/planning_guard.py.
    planning_lock_timeout_seconds: float = Field(default=5, gt=0, le=60)
    operation_log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    # Retention (app/modules/maintenance/retention.py); 0 minutes disables the periodic
    # pass, 0 days keeps notification deliveries forever.
    retention_interval_minutes: int = Field(default=60, ge=0, le=1440)
    preview_retention_hours: int = Field(default=24, ge=1, le=720)
    notification_retention_days: int = Field(default=90, ge=0, le=3650)
    planning_max_tickets: int = Field(default=100, ge=1, le=100)
    planning_max_workers: int = Field(default=20, ge=1, le=20)
    planning_max_matrix_cells_total: int = Field(default=100000, ge=1, le=100000)
    planning_provider_concurrency: int = Field(default=4, ge=1, le=8)
    planning_max_snap_meters: float = Field(default=100, gt=0, le=1000)
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000"
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 bytes")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
