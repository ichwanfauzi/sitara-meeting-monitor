from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.core.security import hash_password, hash_session_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditEvent
from app.models.auth import Role, User, UserSession
from app.services.audit import AuditEventWriteError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


@pytest.fixture
def admin_context() -> Iterator[tuple[TestClient, TestClient, Session, User]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    super_admin_role = Role(role_code="SUPER_ADMIN", role_name="Super Admin")
    secretariat_role = Role(role_code="SEKRETARIAT", role_name="Sekretariat")
    warek_role = Role(role_code="WAREK", role_name="Wakil Rektor")
    admin = User(
        email="admin@example.test",
        full_name="Synthetic Admin",
        password_hash=hash_password("synthetic-admin-password"),
        is_active=True,
    )
    admin.roles.append(super_admin_role)
    operational_user = User(
        email="secretariat@example.test",
        full_name="Synthetic Secretariat",
        password_hash=hash_password("synthetic-secretariat-password"),
        is_active=True,
    )
    operational_user.roles.append(secretariat_role)
    session.add_all([admin, operational_user, warek_role])
    session.commit()

    def override_get_db() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    admin_client = TestClient(app)
    operational_client = TestClient(app)
    admin_token = f"synthetic-admin-session-{uuid4()}"
    session.add(
        UserSession(
            user_id=admin.id,
            token_hash=hash_session_token(admin_token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    operational_token = f"synthetic-operational-session-{uuid4()}"
    session.add(
        UserSession(
            user_id=operational_user.id,
            token_hash=hash_session_token(operational_token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    session.commit()
    admin_client.cookies.set("sitara_session", admin_token)
    operational_client.cookies.set("sitara_session", operational_token)
    csrf_token = f"synthetic-csrf-{uuid4()}"
    admin_client.cookies.set("sitara_csrf", csrf_token)
    admin_client.headers["X-CSRF-Token"] = csrf_token

    try:
        yield admin_client, operational_client, session, operational_user
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_admin_user_listing_requires_super_admin_and_redacts_credentials(
    admin_context: tuple[TestClient, TestClient, Session, User],
) -> None:
    admin_client, operational_client, _, _ = admin_context

    admin_response = admin_client.get("/api/v1/admin/users")

    assert admin_response.status_code == 200
    users = admin_response.json()["items"]
    assert {user["email"] for user in users} == {
        "admin@example.test",
        "secretariat@example.test",
    }
    assert all(
        not {"password", "password_hash", "token", "token_hash"} & user.keys() for user in users
    )
    assert operational_client.get("/api/v1/admin/users").status_code == 403


def test_admin_can_create_operational_user_with_one_time_temporary_password(
    admin_context: tuple[TestClient, TestClient, Session, User],
) -> None:
    admin_client, _, session, _ = admin_context

    response = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "new-secretariat@example.test",
            "full_name": "Synthetic New User",
            "job_title": "Wakil Rektor I Bidang Akademik",
            "role_code": "WAREK",
        },
    )

    assert response.status_code == 201
    result = response.json()
    assert result["user"]["email"] == "new-secretariat@example.test"
    assert result["user"]["roles"] == ["WAREK"]
    assert result["user"]["must_change_password"] is True
    assert len(result["temporary_password"]) >= 24
    assert "password_hash" not in result["user"]
    event = session.query(AuditEvent).filter_by(object_id=UUID(result["user"]["id"])).one()
    assert event.action == "user.created"
    assert event.actor_user_id is not None
    assert event.actor_roles == ["SUPER_ADMIN"]
    assert "temporary_password" not in str(event.after_values)
    assert "password_hash" not in str(event.after_values)


def test_admin_cannot_assign_pic_or_super_admin_roles(
    admin_context: tuple[TestClient, TestClient, Session, User],
) -> None:
    admin_client, _, _, _ = admin_context

    for role_code in ("PIC", "SUPER_ADMIN"):
        response = admin_client.post(
            "/api/v1/admin/users",
            json={
                "email": f"{role_code.lower()}-user@example.test",
                "full_name": "Synthetic User",
                "job_title": "Synthetic Position",
                "role_code": role_code,
            },
        )
        assert response.status_code == 422


def test_deactivated_user_sessions_stay_revoked_after_reactivation(
    admin_context: tuple[TestClient, TestClient, Session, User],
) -> None:
    admin_client, _, session, _ = admin_context
    created = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "lifecycle@example.test",
            "full_name": "Synthetic Lifecycle User",
            "job_title": "Wakil Rektor I Bidang Akademik",
            "role_code": "WAREK",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["user"]["id"]
    user = session.get(User, UUID(user_id))
    assert user is not None
    raw_token = f"synthetic-lifecycle-session-{uuid4()}"
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    session.commit()
    user_client = TestClient(app)
    user_client.cookies.set("sitara_session", raw_token)

    deactivated = admin_client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    assert user_client.get("/api/v1/auth/me").status_code == 401

    reactivated = admin_client.patch(
        f"/api/v1/admin/users/{user_id}",
        json={"is_active": True},
    )
    assert reactivated.status_code == 200
    assert user_client.get("/api/v1/auth/me").status_code == 401
    assert session.query(UserSession).filter_by(user_id=user.id).all()[0].revoked_at is not None


def test_admin_cannot_deactivate_the_last_active_super_admin(
    admin_context: tuple[TestClient, TestClient, Session, User],
) -> None:
    admin_client, _, _, _ = admin_context
    current_admin = admin_client.get("/api/v1/auth/me").json()

    response = admin_client.patch(
        f"/api/v1/admin/users/{current_admin['id']}",
        json={"is_active": False},
    )

    assert response.status_code == 409
    assert admin_client.get("/api/v1/auth/me").status_code == 200


def test_user_creation_rolls_back_when_audit_append_fails(
    admin_context: tuple[TestClient, TestClient, Session, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_client, _, session, _ = admin_context

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise AuditEventWriteError("synthetic audit failure")

    monkeypatch.setattr("app.services.admin_users.append_user_account_event", fail_audit)
    response = admin_client.post(
        "/api/v1/admin/users",
        json={
            "email": "rollback@example.test",
            "full_name": "Synthetic Rollback User",
            "job_title": "Wakil Rektor I Bidang Akademik",
            "role_code": "WAREK",
        },
    )

    assert response.status_code == 500
    assert session.query(User).filter_by(email="rollback@example.test").first() is None
