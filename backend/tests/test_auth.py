from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from app.core.config import get_settings
from app.core.security import hash_password, hash_session_token, verify_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.auth import Role, User, UserSession
from app.models.security import LoginRateLimitBucket
from app.services.rate_limiting import (
    LoginRateLimitExceeded,
    enforce_login_rate_limit,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def auth_context() -> Iterator[tuple[TestClient, Session, User]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    role = Role(role_code="PIC", role_name="PIC")
    user = User(
        email="pic@example.test",
        full_name="Test PIC",
        password_hash=hash_password("synthetic-password"),
        is_active=True,
    )
    user.roles.append(role)
    session.add(user)
    session.commit()
    app.dependency_overrides[get_db] = lambda: session

    try:
        yield TestClient(app), session, user
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_login_sets_hardened_session_cookie_and_returns_role(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context

    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email.upper(), "password": "synthetic-password"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "roles": ["PIC"],
        "must_change_password": False,
    }
    session_token = client.cookies.get("sitara_session")
    csrf_token = client.cookies.get("sitara_csrf")
    assert session_token
    assert csrf_token
    csrf_cookie = next(
        cookie.lower()
        for cookie in response.headers.get_list("set-cookie")
        if cookie.lower().startswith("sitara_csrf=")
    )
    assert "; path=/;" in csrf_cookie
    legacy_csrf_deletion = next(
        cookie.lower()
        for cookie in response.headers.get_list("set-cookie")
        if cookie.lower().startswith("sitara_csrf=") and "; path=/api/v1;" in cookie.lower()
    )
    assert "max-age=0" in legacy_csrf_deletion
    assert any(
        "sitara_session=" in cookie.lower()
        and "httponly" in cookie.lower()
        and "samesite=lax" in cookie.lower()
        for cookie in response.headers.get_list("set-cookie")
    )
    stored_session = session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(session_token))
    )
    assert stored_session is not None
    assert stored_session.token_hash != session_token


def test_login_rejects_wrong_password_and_inactive_user(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "wrong-password"},
    )
    assert wrong_password.status_code == 401
    assert not client.cookies.get("sitara_session")

    user.is_active = False
    session.commit()
    inactive_user = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "synthetic-password"},
    )
    assert inactive_user.status_code == 401
    assert inactive_user.json() == wrong_password.json()


def test_current_user_requires_a_session_and_logout_checks_csrf(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context

    assert client.get("/api/v1/auth/me").status_code == 401
    login = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "synthetic-password"},
    )
    assert login.status_code == 200
    assert client.get("/api/v1/auth/me").json() == login.json()

    missing_csrf = client.post("/api/v1/auth/logout")
    assert missing_csrf.status_code == 403

    csrf_token = client.cookies.get("sitara_csrf")
    assert csrf_token
    logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert logout.status_code == 204
    csrf_deletion_cookies = [
        cookie.lower()
        for cookie in logout.headers.get_list("set-cookie")
        if cookie.lower().startswith("sitara_csrf=")
    ]
    assert any("; path=/;" in cookie and "max-age=0" in cookie for cookie in csrf_deletion_cookies)
    assert any(
        "; path=/api/v1;" in cookie and "max-age=0" in cookie for cookie in csrf_deletion_cookies
    )
    assert client.get("/api/v1/auth/me").status_code == 401

    stored_session = session.scalar(select(UserSession))
    assert stored_session is not None
    assert stored_session.revoked_at is not None


def test_temporary_password_requires_change_before_protected_api_access(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context
    user.must_change_password = True
    session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "synthetic-password"},
    )
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    assert client.get("/api/v1/auth/me").json()["must_change_password"] is True
    assert client.get("/api/v1/action-items?limit=100&offset=0").status_code == 403

    csrf_token = client.cookies.get("sitara_csrf")
    assert csrf_token
    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "current_password": "synthetic-password",
            "new_password": "new-strong-synthetic-password",
        },
    )

    assert changed.status_code == 204
    assert client.get("/api/v1/auth/me").json()["must_change_password"] is False
    assert client.get("/api/v1/action-items?limit=100&offset=0").status_code != 403
    assert user.must_change_password is False
    assert verify_password("new-strong-synthetic-password", user.password_hash)
    assert not verify_password("synthetic-password", user.password_hash)


def test_expired_session_is_rejected(
    auth_context: tuple[TestClient, Session, User],
) -> None:
    client, session, user = auth_context
    raw_token = "synthetic-expired-session-token"
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(raw_token),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    session.commit()
    client.cookies.set("sitara_session", raw_token)

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_login_rate_limit_counts_attempts_without_account_enumeration(
    auth_context: tuple[TestClient, Session, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, user = auth_context
    monkeypatch.setenv("LOGIN_RATE_LIMIT_HMAC_KEY", "x" * 40)
    monkeypatch.setenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    try:
        known_account_failure = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong-password"},
        )
        unknown_account_failure = client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.test", "password": "wrong-password"},
        )
        second_known_account_failure = client.post(
            "/api/v1/auth/login",
            json={"email": user.email.upper(), "password": "wrong-password"},
        )
        limited = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "synthetic-password"},
        )

        assert known_account_failure.status_code == 401
        assert unknown_account_failure.json() == known_account_failure.json()
        assert second_known_account_failure.status_code == 401
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) > 0
    finally:
        get_settings.cache_clear()


def test_login_rate_limit_is_scoped_to_the_composite_identity_and_ip(
    auth_context: tuple[TestClient, Session, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, session, user = auth_context
    monkeypatch.setenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "1")
    get_settings.cache_clear()

    try:
        failed = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong-password"},
        )
        same_bucket = client.post(
            "/api/v1/auth/login",
            json={"email": user.email.upper(), "password": "synthetic-password"},
            headers={"X-Forwarded-For": "203.0.113.40"},
        )
        other_ip_client = TestClient(app, client=("203.0.113.40", 54321))
        other_ip = other_ip_client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "synthetic-password"},
        )

        assert failed.status_code == 401
        assert same_bucket.status_code == 429
        assert other_ip.status_code == 200
        bucket_hashes = list(session.scalars(select(LoginRateLimitBucket.bucket_hash)))
        assert len(bucket_hashes) == 2
        assert all(user.email not in bucket_hash for bucket_hash in bucket_hashes)
        assert all("203.0.113.40" not in bucket_hash for bucket_hash in bucket_hashes)
    finally:
        get_settings.cache_clear()


def test_login_rate_limit_window_expires_and_database_failure_fails_closed(
    auth_context: tuple[TestClient, Session, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, session, user = auth_context
    monkeypatch.setenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "10")
    get_settings.cache_clear()
    start = datetime(2026, 1, 1, tzinfo=UTC)

    try:
        enforce_login_rate_limit(session, user.email, "127.0.0.1", now=start)
        with pytest.raises(LoginRateLimitExceeded) as exceeded:
            enforce_login_rate_limit(
                session, user.email.upper(), "127.0.0.1", now=start + timedelta(seconds=1)
            )
        assert exceeded.value.retry_after_seconds == 9

        enforce_login_rate_limit(
            session, user.email, "127.0.0.1", now=start + timedelta(seconds=11)
        )
        assert session.query(LoginRateLimitBucket).count() == 1

        session.execute(text("DROP TABLE login_rate_limit_buckets"))
        session.commit()
        unavailable = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong-password"},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "Login temporarily unavailable"
    finally:
        get_settings.cache_clear()


def test_missing_limiter_key_keeps_application_available_but_login_fails_closed(
    auth_context: tuple[TestClient, Session, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, user = auth_context
    monkeypatch.setenv("LOGIN_RATE_LIMIT_HMAC_KEY", "")
    get_settings.cache_clear()

    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "synthetic-password"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "Login temporarily unavailable"
    finally:
        get_settings.cache_clear()
