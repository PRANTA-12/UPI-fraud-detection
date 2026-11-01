"""Environment-based configuration. Secrets only come from the environment, never from code."""
from __future__ import annotations

import socket
from functools import lru_cache
from urllib.parse import quote

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_env: str = "development"          # development | production | test
    log_level: str = "INFO"

    # --- database (DATABASE_URL wins, e.g. for Neon; otherwise the DB_* vars you already use)
    database_url: str | None = None
    db_host: str = "db"
    db_port: int = 5432
    db_name: str = Field("upi_fraud_db", validation_alias=AliasChoices("DB_NAME", "POSTGRES_DB"))
    db_user: str = Field("postgres", validation_alias=AliasChoices("DB_USER", "POSTGRES_USER"))
    db_password: str = Field("", validation_alias=AliasChoices("DB_PASSWORD", "POSTGRES_PASSWORD"))
    db_sslmode: str = "prefer"
    db_pool_max: int = 10

    # --- redis / streaming
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str | None = None
    stream_name: str = "transactions_stream"
    dlq_stream_name: str = "transactions_stream:dlq"
    consumer_group: str = "fraud_consumer_group"
    alert_channel: str = "fraud_alerts"
    consumer_name: str = Field(default_factory=socket.gethostname)
    producer_min_delay_ms: int = 200
    producer_max_delay_ms: int = 1500
    stream_maxlen: int = 200_000
    max_retries: int = 5                  # deliveries before a message is dead-lettered
    retry_idle_ms: int = 30_000           # a pending message idle this long is re-claimed

    # --- security
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    admin_username: str = "admin"
    admin_password: str | None = None
    auth_required: bool = True            # protects the NEW dashboard APIs
    ws_require_auth: bool = True          # /ws/live needs ?token=<jwt>
    legacy_endpoints_public: bool = True  # keeps GET /, /health, /stream/status, POST /predict open
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    models_dir: str = "models"
    mlflow_tracking_uri: str = "sqlite:///mlflow.db"

    @field_validator("jwt_secret")
    @classmethod
    def _secret_len(cls, v: str, info):
        return v

    @model_validator(mode="after")
    def _validate(self):
        if self.app_env != "test":
            if len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random string of at least 32 characters "
                                 "(generate: python -c \"import secrets; print(secrets.token_urlsafe(48))\")")
        if self.app_env == "production" and not self.auth_required:
            raise ValueError("AUTH_REQUIRED=false is not allowed when APP_ENV=production")
        if self.producer_min_delay_ms > self.producer_max_delay_ms:
            raise ValueError("PRODUCER_MIN_DELAY_MS must be <= PRODUCER_MAX_DELAY_MS")
        return self

    @property
    def dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{quote(self.db_user, safe='')}:"
            f"{quote(self.db_password, safe='')}@"
            f"{self.db_host}:{self.db_port}/"
            f"{self.db_name}?sslmode={self.db_sslmode}"
        )

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
