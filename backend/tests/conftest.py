"""Shared test configuration for synthetic login rate-limit credentials."""

from collections.abc import Iterator

import pytest
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def synthetic_rate_limit_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("LOGIN_RATE_LIMIT_HMAC_KEY", "x" * 40)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
