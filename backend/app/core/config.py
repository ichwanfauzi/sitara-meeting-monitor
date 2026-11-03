"""Application settings loaded from environment variables."""

import ipaddress
import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DNS_LABEL_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


class Settings(BaseSettings):
    """Typed runtime configuration; secrets must come from the environment."""

    app_name: str = "SITARA API"
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str | None = None
    action_item_evidence_storage_path: Path | None = None
    clamav_host: str = "127.0.0.1"
    clamav_port: int = Field(default=3310, ge=1, le=65_535)
    clamav_timeout_seconds: int = Field(default=30, ge=1, le=300)
    evidence_scan_poll_seconds: int = Field(default=5, ge=1, le=300)
    session_ttl_seconds: int = 43_200
    login_rate_limit_hmac_key: SecretStr | None = None
    login_rate_limit_max_attempts: int = Field(default=10, ge=1, le=1000)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1, le=86_400)
    login_rate_limit_statement_timeout_ms: int = Field(default=2_000, ge=100, le=30_000)

    @field_validator("clamav_host")
    @classmethod
    def validate_clamav_host(cls, value: str) -> str:
        host = value.strip()
        if not host:
            raise ValueError("CLAMAV_HOST must be a hostname or IP address")

        try:
            ipaddress.ip_address(host)
        except ValueError:
            hostname = host[:-1] if host.endswith(".") else host
            labels = hostname.split(".")
            if (
                not hostname
                or len(hostname) > 253
                or not all(_DNS_LABEL_PATTERN.fullmatch(label) for label in labels)
                or all(label.isdigit() for label in labels)
            ):
                raise ValueError("CLAMAV_HOST must be a valid hostname or IP address") from None
        return host

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings; clear cache in tests when environment changes."""
    return Settings()
