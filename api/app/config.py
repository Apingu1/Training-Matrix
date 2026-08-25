from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Eaststone Training Matrix"
    app_version: str = "0.2.1"
    app_env: str = "development"
    timezone: str = Field("Europe/London", alias="TZ")

    database_url: str = "sqlite:///./training_matrix.db"
    jwt_secret: str = "development-only-secret-change-before-production"
    jwt_expires_minutes: int = 480
    session_idle_minutes: int = 15
    login_max_failures: int = 5
    login_lock_minutes: int = 15

    initial_admin_username: str = "admin"
    initial_admin_password: str = "ChangeMe-Training-Matrix-2026!"

    document_root: Path = Path("/controlled-documents")
    backup_root: Path = Path("/backups")
    document_cache_root: Path = Path("/document-cache")
    runtime_root: Path = Path("/runtime")
    backup_time: str = "02:30"
    backup_timezone: str = "Europe/London"
    backup_retention_days: int = 30

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "Settings":
        if self.app_env.lower() == "production" and "development-only" in self.jwt_secret:
            raise ValueError("JWT_SECRET is required in production and may not use the development default")
        if self.app_env.lower() == "production" and self.initial_admin_password.startswith("ChangeMe-"):
            raise ValueError("INITIAL_ADMIN_PASSWORD must be replaced before production startup")
        return self

    @field_validator("jwt_secret")
    @classmethod
    def validate_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters")
        if value.lower().startswith(("change_me", "replace_with")):
            raise ValueError("JWT_SECRET must be replaced before startup")
        return value

    @field_validator("session_idle_minutes")
    @classmethod
    def validate_idle_timeout(cls, value: int) -> int:
        if not 5 <= value <= 120:
            raise ValueError("SESSION_IDLE_MINUTES must be between 5 and 120")
        return value

    @field_validator("initial_admin_password")
    @classmethod
    def validate_admin_password(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("INITIAL_ADMIN_PASSWORD must contain at least 12 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.backup_root.mkdir(parents=True, exist_ok=True)
    settings.document_cache_root.mkdir(parents=True, exist_ok=True)
    settings.runtime_root.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
