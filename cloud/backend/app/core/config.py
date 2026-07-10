from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated backend settings loaded from environment variables."""

    app_name: str = "IoT Monitoring Cloud Backend"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", pattern="^(development|test|production)$")
    debug: bool = False
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=8883, ge=1, le=65535)
    mqtt_use_tls: bool = True

    database_url: str = "postgresql+psycopg://iot_backend:IotBackendLocal001!@localhost:5432/progetto_iot"

    model_config = SettingsConfigDict(
        env_prefix="IOT_BACKEND_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings so tests and app startup use the same values."""
    return Settings()
