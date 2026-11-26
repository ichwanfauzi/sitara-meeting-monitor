"""Deliver queued notification emails through the configured SMTP relay."""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.models import meeting as _meeting_models  # noqa: F401
from app.models.auth import User
from app.models.notification import (
    Notification,
    NotificationEmailStatus,
    NotificationType,
)

LOGGER = logging.getLogger("sitara.notification_email")
_EMAIL_COPY: dict[NotificationType, str] = {
    NotificationType.ACTION_ITEM_STATUS_CHANGED: (
        "Status tindak lanjut yang Anda ikuti telah berubah."
    ),
    NotificationType.DECISION_BRIEF_REVIEW_NEEDED: (
        "Ada Decision Brief yang menunggu tinjauan Anda."
    ),
    NotificationType.DECISION_BRIEF_REVIEW_WITHDRAWN: (
        "Permintaan tinjauan Decision Brief telah ditarik."
    ),
    NotificationType.DECISION_BRIEF_REVIEW_COMPLETED: (
        "Tinjauan Decision Brief telah diselesaikan."
    ),
}


def _validate_smtp_settings(settings: Settings) -> None:
    if not settings.notification_email_enabled:
        raise RuntimeError("NOTIFICATION_EMAIL_ENABLED must be true for the email worker")
    if (
        not settings.smtp_username
        or settings.smtp_password is None
        or not settings.smtp_password.get_secret_value()
        or not settings.smtp_from_email
    ):
        raise RuntimeError("SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL must be configured")
    if settings.notification_email_test_recipient and settings.app_env.casefold() not in {
        "development",
        "testing",
    }:
        raise RuntimeError("Test email recipient override is not allowed outside nonproduction")


def _send_notification_email(
    notification_type: NotificationType,
    recipient_email: str,
    settings: Settings,
) -> None:
    _validate_smtp_settings(settings)
    if settings.smtp_password is None or settings.smtp_username is None:
        raise RuntimeError("SMTP credentials are not configured")
    if settings.smtp_from_email is None:
        raise RuntimeError("SMTP_FROM_EMAIL is not configured")

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = recipient_email
    message["Subject"] = "SITARA - Notifikasi"
    message.set_content(
        "Anda memiliki notifikasi baru di SITARA.\n\n"
        f"{_EMAIL_COPY[notification_type]}\n\n"
        "Silakan masuk ke SITARA untuk melihat detail sesuai hak akses akun Anda."
    )

    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout_seconds,
    ) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


def process_pending_notifications(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    """Deliver one bounded batch; SMTP failures remain durable and retryable."""
    if not settings.notification_email_enabled:
        return 0
    _validate_smtp_settings(settings)
    current_time = now or datetime.now(UTC)
    due_email = or_(
        Notification.email_next_attempt_at.is_(None),
        Notification.email_next_attempt_at <= current_time,
    )
    rows = session.execute(
        select(Notification, User.email)
        .join(User, User.id == Notification.recipient_user_id)
        .where(
            Notification.email_status == NotificationEmailStatus.PENDING,
            due_email,
        )
        .order_by(Notification.created_at, Notification.id)
        .limit(25)
        .with_for_update(of=Notification, skip_locked=True)
    ).all()

    for notification, account_email in rows:
        recipient_email = settings.notification_email_test_recipient or account_email
        try:
            _send_notification_email(notification.notification_type, recipient_email, settings)
        except (OSError, smtplib.SMTPException) as error:
            notification.email_attempts += 1
            notification.email_last_error = type(error).__name__
            if notification.email_attempts >= settings.notification_email_max_attempts:
                notification.email_status = NotificationEmailStatus.FAILED
                notification.email_next_attempt_at = None
            else:
                delay = min(
                    settings.notification_email_retry_base_seconds
                    * (2 ** (notification.email_attempts - 1)),
                    86_400,
                )
                notification.email_next_attempt_at = current_time + timedelta(seconds=delay)
            session.commit()
            LOGGER.error(
                "Notification email failed; notification_id=%s attempt=%s error_type=%s",
                notification.id,
                notification.email_attempts,
                type(error).__name__,
            )
        else:
            notification.email_attempts += 1
            notification.email_status = NotificationEmailStatus.SENT
            notification.email_last_error = None
            notification.email_next_attempt_at = None
            notification.email_sent_at = current_time
            session.commit()
            LOGGER.info("Notification email sent; notification_id=%s", notification.id)
    return len(rows)


def run_worker() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the notification email worker")
    _validate_smtp_settings(settings)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    session_factory: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)
    LOGGER.info("SITARA notification email worker started")
    try:
        while True:
            try:
                with session_factory() as session:
                    process_pending_notifications(session, settings)
            except Exception:
                LOGGER.exception("Notification email worker failed; retrying after delay")
            time.sleep(settings.notification_email_poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=get_settings().log_level.upper())
    run_worker()
