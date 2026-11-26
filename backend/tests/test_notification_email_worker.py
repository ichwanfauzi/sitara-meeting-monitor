import subprocess
import sys
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

import pytest
from app.core.config import Settings, get_settings
from app.models import meeting as meeting_models
from app.models.auth import User
from app.models.notification import Notification, NotificationEmailStatus, NotificationType
from app.notification_email_worker import process_pending_notifications
from app.services.notifications import add_notifications
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


class FakeSMTP:
    def __init__(self) -> None:
        self.started_tls = False
        self.credentials: tuple[str, str] | None = None
        self.messages: list[EmailMessage] = []

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.messages.append(message)


def test_email_worker_registers_models_before_mapper_configuration() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from sqlalchemy.orm import configure_mappers; "
                "import app.notification_email_worker; configure_mappers()"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "testing",
        "notification_email_enabled": True,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "sender@example.test",
        "smtp_password": "synthetic-app-password",
        "smtp_from_email": "sender@example.test",
        "notification_email_test_recipient": "test-inbox@example.test",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _notification_session() -> tuple[Session, User, Notification]:
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    meeting_models.Meeting.__table__.create(engine)
    Notification.__table__.create(engine)
    session = Session(engine)
    recipient = User(
        id=uuid4(),
        email="assigned-pic@example.test",
        full_name="PIC Sintetis",
        password_hash="synthetic-hash",
        is_active=True,
    )
    notification = Notification(
        id=uuid4(),
        recipient_user_id=recipient.id,
        event_key="synthetic-event",
        notification_type=NotificationType.ACTION_ITEM_STATUS_CHANGED,
        message="CONFIDENTIAL RAPIM TITLE MUST NOT BE EMAILED",
        target_type="ACTION_ITEM",
        target_id=uuid4(),
        email_status=NotificationEmailStatus.PENDING,
    )
    session.add_all([recipient, notification])
    session.commit()
    return session, recipient, notification


def test_email_worker_sends_generic_message_to_test_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import notification_email_worker as worker

    session, _, notification = _notification_session()
    smtp = FakeSMTP()
    monkeypatch.setattr(worker.smtplib, "SMTP", lambda *_args, **_kwargs: smtp)

    processed = process_pending_notifications(
        session,
        _settings(),
        now=datetime(2026, 11, 26, tzinfo=UTC),
    )

    assert processed == 1
    assert smtp.started_tls
    assert smtp.credentials == ("sender@example.test", "synthetic-app-password")
    assert len(smtp.messages) == 1
    email = smtp.messages[0]
    assert email["To"] == "test-inbox@example.test"
    assert email["From"] == "sender@example.test"
    assert email["Subject"] == "SITARA - Notifikasi"
    body = email.get_body(preferencelist=("plain",))
    assert body is not None
    text = body.get_content()
    assert "Status tindak lanjut yang Anda ikuti telah berubah." in text
    assert "CONFIDENTIAL RAPIM TITLE" not in text
    session.refresh(notification)
    assert notification.email_status == NotificationEmailStatus.SENT
    assert notification.email_sent_at is not None
    assert notification.email_attempts == 1
    engine = session.get_bind()
    session.close()
    engine.dispose()


def test_email_worker_uses_account_email_when_no_test_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import notification_email_worker as worker

    session, recipient, _ = _notification_session()
    smtp = FakeSMTP()
    monkeypatch.setattr(worker.smtplib, "SMTP", lambda *_args, **_kwargs: smtp)

    process_pending_notifications(
        session,
        _settings(notification_email_test_recipient=None),
        now=datetime(2026, 11, 26, tzinfo=UTC),
    )

    assert smtp.messages[0]["To"] == recipient.email
    engine = session.get_bind()
    session.close()
    engine.dispose()


def test_email_worker_retries_smtp_failure_without_storing_server_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import smtplib

    from app import notification_email_worker as worker

    session, _, notification = _notification_session()

    def fail_sending(*_args: object, **_kwargs: object) -> FakeSMTP:
        raise smtplib.SMTPAuthenticationError(535, b"private SMTP diagnostic")

    monkeypatch.setattr(worker.smtplib, "SMTP", fail_sending)

    processed = process_pending_notifications(
        session,
        _settings(notification_email_retry_base_seconds=30),
        now=datetime(2026, 11, 26, tzinfo=UTC),
    )

    assert processed == 1
    session.refresh(notification)
    assert notification.email_status == NotificationEmailStatus.PENDING
    assert notification.email_attempts == 1
    assert notification.email_last_error == "SMTPAuthenticationError"
    assert notification.email_next_attempt_at is not None
    assert "private SMTP diagnostic" not in str(notification.email_last_error)
    engine = session.get_bind()
    session.close()
    engine.dispose()


def test_email_worker_stops_after_maximum_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    import smtplib

    from app import notification_email_worker as worker

    session, _, notification = _notification_session()

    def fail_sending(*_args: object, **_kwargs: object) -> FakeSMTP:
        raise smtplib.SMTPAuthenticationError(535, b"private SMTP diagnostic")

    monkeypatch.setattr(worker.smtplib, "SMTP", fail_sending)

    process_pending_notifications(
        session,
        _settings(notification_email_max_attempts=1),
        now=datetime(2026, 11, 26, tzinfo=UTC),
    )

    session.refresh(notification)
    assert notification.email_status == NotificationEmailStatus.FAILED
    assert notification.email_attempts == 1
    assert notification.email_next_attempt_at is None
    engine = session.get_bind()
    session.close()
    engine.dispose()


def test_notification_email_queue_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATION_EMAIL_ENABLED", "false")
    get_settings.cache_clear()
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    meeting_models.Meeting.__table__.create(engine)
    Notification.__table__.create(engine)
    user = User(
        id=uuid4(),
        email="assigned-pic@example.test",
        full_name="PIC Sintetis",
        password_hash="synthetic-hash",
        is_active=True,
    )
    with Session(engine) as session:
        session.add(user)
        session.flush()
        add_notifications(
            session,
            recipient_ids={user.id},
            event_key="synthetic-event",
            notification_type=NotificationType.ACTION_ITEM_STATUS_CHANGED,
            message="Status tindak lanjut yang Anda ikuti telah berubah.",
            target_type="ACTION_ITEM",
            target_id=uuid4(),
        )
        session.flush()
        notification = session.query(Notification).one()
        assert notification.email_status == NotificationEmailStatus.DISABLED

    monkeypatch.setenv("NOTIFICATION_EMAIL_ENABLED", "true")
    get_settings.cache_clear()
    try:
        with Session(engine) as session:
            add_notifications(
                session,
                recipient_ids={user.id},
                event_key="second-synthetic-event",
                notification_type=NotificationType.ACTION_ITEM_STATUS_CHANGED,
                message="Status tindak lanjut yang Anda ikuti telah berubah.",
                target_type="ACTION_ITEM",
                target_id=uuid4(),
            )
            session.flush()
            queued = session.query(Notification).filter_by(event_key="second-synthetic-event").one()
            assert queued.email_status == NotificationEmailStatus.PENDING
    finally:
        get_settings.cache_clear()
        engine.dispose()


def test_test_recipient_override_is_rejected_outside_nonproduction() -> None:
    with pytest.raises(ValidationError, match="development or testing"):
        Settings(
            _env_file=None,
            app_env="production",
            notification_email_test_recipient="test-inbox@example.test",
        )
