"""Чтение настроек из .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from loguru import logger
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    max_bot_token: str | None = None
    admin_max_user_id: int | None = None
    # Retained only for the legacy chat flow; never use shared codes in the Mini App.
    admin_access_code: str | None = None
    guard_access_code: str | None = None
    database_url: str = "sqlite+aiosqlite:///./app.db"
    log_level: str = "INFO"
    max_webhook_secret: str | None = None
    max_update_mode: Literal["webhook", "long_polling"] = "webhook"
    max_bot_name: str | None = None
    initial_complex_name: str = "Жилой комплекс"
    initial_complex_city: str = "Укажите город"
    max_api_base_url: str = "https://platform-api2.max.ru"
    app_base_url: str = "http://localhost:8000"
    miniapp_url: str = "http://localhost:5173"
    timezone: str = "Europe/Moscow"
    environment: str = "development"
    demo_mode: bool = True
    cors_origins: str = "http://localhost:5173"
    demo_seed: bool = True

    @model_validator(mode="after")
    def _long_polling_is_development_only(self) -> "Settings":
        if self.max_update_mode == "long_polling" and self.environment.lower() != "development":
            raise ValueError("MAX_UPDATE_MODE=long_polling is allowed only in development")
        return self

    @property
    def demo_auth_enabled(self) -> bool:
        """Whether local seeded accounts can be selected as the active identity."""
        return self.environment.lower() == "development" and self.demo_mode

    @field_validator("admin_max_user_id", mode="before")
    @classmethod
    def _empty_admin_id(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise SystemExit(f"Некорректная конфигурация: {exc}") from exc


settings = get_settings()


def persist_admin_max_user_id(user_id: int) -> None:
    """Запомнить первого админа в памяти и в .env."""
    settings.admin_max_user_id = user_id
    if ":memory:" in settings.database_url:
        return
    _write_env_value("ADMIN_MAX_USER_ID", str(user_id))
    logger.info("В .env записан ADMIN_MAX_USER_ID={}", user_id)


def _write_env_value(key: str, value: str) -> None:
    prefix = f"{key}="
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    else:
        example = ROOT_DIR / ".env.example"
        lines = example.read_text(encoding="utf-8").splitlines() if example.exists() else []

    found = False
    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) or stripped.startswith(f"{key} ="):
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(updated) + "\n", encoding="utf-8")
