from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurazione validata del backend caricata dalle variabili d'ambiente."""

    app_name: str = "IoT Monitoring Cloud Backend"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", pattern="^(development|test|production)$")
    debug: bool = False
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    cors_allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    auth_secret_key: str = "CAMBIA_AUTH_SECRET_KEY_IN_PRODUZIONE"
    access_token_minutes: int = Field(default=15, ge=1)
    refresh_token_days: int = Field(default=30, ge=1)
    demo_auth_enabled: bool = False
    demo_auth_password: str = ""
    demo_doctor_email: str = ""
    demo_caregiver_email: str = ""
    demo_patient_email: str = ""
    demo_admin_email: str = ""

    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=8883, ge=1, le=65535)
    mqtt_use_tls: bool = True
    mqtt_username: str = "backend"
    mqtt_password: str = ""
    mqtt_client_id: str = "iot-backend-subscriber"
    mqtt_ca_file: str = "../mqtt/certs/ca.crt"
    mqtt_keepalive_seconds: int = Field(default=60, ge=5)
    mqtt_reconnect_min_delay_seconds: int = Field(default=1, ge=1)
    mqtt_reconnect_max_delay_seconds: int = Field(default=30, ge=1)

    database_url: str = ""

    @model_validator(mode="after")
    def reject_missing_secrets_in_production(self) -> "Settings":
        """Blocca l'avvio in produzione se mancano segreti o sono rimasti placeholder."""
        if self.environment != "production":
            return self

        required_values = {
            "IOT_BACKEND_MQTT_PASSWORD": self.mqtt_password,
            "IOT_BACKEND_DATABASE_URL": self.database_url,
            "IOT_BACKEND_AUTH_SECRET_KEY": self.auth_secret_key,
        }
        for env_name, value in required_values.items():
            if not value:
                raise ValueError(f"{env_name} must be configured before running in production.")
            if "CAMBIA_" in value:
                raise ValueError(f"{env_name} must be changed before running in production.")
        return self

    model_config = SettingsConfigDict(
        env_prefix="IOT_BACKEND_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Restituisce la configurazione in cache per test, app e worker."""
    return Settings()
