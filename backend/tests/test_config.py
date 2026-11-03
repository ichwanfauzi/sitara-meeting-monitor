from __future__ import annotations

import pytest
from app.core.config import Settings
from pydantic import ValidationError

_SETTINGS_ENV_KEYS = (
    "APP_NAME",
    "APP_ENV",
    "LOG_LEVEL",
    "DATABASE_URL",
    "ACTION_ITEM_EVIDENCE_STORAGE_PATH",
    "SESSION_TTL_SECONDS",
    "LOGIN_RATE_LIMIT_HMAC_KEY",
    "LOGIN_RATE_LIMIT_MAX_ATTEMPTS",
    "LOGIN_RATE_LIMIT_WINDOW_SECONDS",
    "LOGIN_RATE_LIMIT_STATEMENT_TIMEOUT_MS",
    "CLAMAV_HOST",
    "CLAMAV_PORT",
    "CLAMAV_TIMEOUT_SECONDS",
    "EVIDENCE_SCAN_POLL_SECONDS",
)


@pytest.fixture
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_clamav_settings_have_safe_local_defaults(
    isolated_settings_environment: None,
) -> None:
    settings = _settings()

    assert settings.clamav_host == "127.0.0.1"
    assert settings.clamav_port == 3310
    assert settings.clamav_timeout_seconds == 30
    assert settings.evidence_scan_poll_seconds == 5


def test_clamav_settings_read_environment_variables(
    isolated_settings_environment: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAMAV_HOST", "clamav")
    monkeypatch.setenv("CLAMAV_PORT", "3311")
    monkeypatch.setenv("CLAMAV_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("EVIDENCE_SCAN_POLL_SECONDS", "17")

    settings = _settings()

    assert settings.clamav_host == "clamav"
    assert settings.clamav_port == 3311
    assert settings.clamav_timeout_seconds == 45
    assert settings.evidence_scan_poll_seconds == 17


@pytest.mark.parametrize(
    ("environment_name", "value", "expected"),
    [
        ("CLAMAV_PORT", "1", 1),
        ("CLAMAV_PORT", "65535", 65535),
        ("CLAMAV_TIMEOUT_SECONDS", "1", 1),
        ("CLAMAV_TIMEOUT_SECONDS", "300", 300),
        ("EVIDENCE_SCAN_POLL_SECONDS", "1", 1),
        ("EVIDENCE_SCAN_POLL_SECONDS", "300", 300),
    ],
)
def test_clamav_numeric_settings_accept_range_boundaries(
    isolated_settings_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    value: str,
    expected: int,
) -> None:
    monkeypatch.setenv(environment_name, value)

    settings = _settings()

    field_name = {
        "CLAMAV_PORT": "clamav_port",
        "CLAMAV_TIMEOUT_SECONDS": "clamav_timeout_seconds",
        "EVIDENCE_SCAN_POLL_SECONDS": "evidence_scan_poll_seconds",
    }[environment_name]
    assert getattr(settings, field_name) == expected


@pytest.mark.parametrize(
    ("environment_name", "value"),
    [
        ("CLAMAV_PORT", "0"),
        ("CLAMAV_PORT", ""),
        ("CLAMAV_PORT", "65536"),
        ("CLAMAV_PORT", "not-a-port"),
        ("CLAMAV_TIMEOUT_SECONDS", "0"),
        ("CLAMAV_TIMEOUT_SECONDS", "301"),
        ("EVIDENCE_SCAN_POLL_SECONDS", "0"),
        ("EVIDENCE_SCAN_POLL_SECONDS", "301"),
    ],
)
def test_clamav_numeric_settings_reject_values_outside_range(
    isolated_settings_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(environment_name, value)

    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.parametrize("host", ["clamav", "localhost", "127.0.0.1", "::1"])
def test_clamav_host_accepts_hostname_and_ip_addresses(
    isolated_settings_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.setenv("CLAMAV_HOST", host)

    assert _settings().clamav_host == host


@pytest.mark.parametrize(
    "host", ["", "   ", "clamav daemon", "http://clamav", "-clamav", "clamav-"]
)
def test_clamav_host_rejects_empty_or_invalid_values(
    isolated_settings_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.setenv("CLAMAV_HOST", host)

    with pytest.raises(ValidationError):
        _settings()
