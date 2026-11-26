"""Private in-app notifications for directly involved users."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationType(StrEnum):
    ACTION_ITEM_STATUS_CHANGED = "ACTION_ITEM_STATUS_CHANGED"
    DECISION_BRIEF_REVIEW_NEEDED = "DECISION_BRIEF_REVIEW_NEEDED"
    DECISION_BRIEF_REVIEW_WITHDRAWN = "DECISION_BRIEF_REVIEW_WITHDRAWN"
    DECISION_BRIEF_REVIEW_COMPLETED = "DECISION_BRIEF_REVIEW_COMPLETED"


class NotificationTargetType(StrEnum):
    ACTION_ITEM = "ACTION_ITEM"
    MEETING = "MEETING"


class NotificationEmailStatus(StrEnum):
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('ACTION_ITEM_STATUS_CHANGED', "
            "'DECISION_BRIEF_REVIEW_NEEDED', 'DECISION_BRIEF_REVIEW_WITHDRAWN', "
            "'DECISION_BRIEF_REVIEW_COMPLETED')",
            name="ck_notifications_type",
        ),
        CheckConstraint(
            "(notification_type = 'ACTION_ITEM_STATUS_CHANGED' AND target_type = 'ACTION_ITEM') "
            "OR (notification_type <> 'ACTION_ITEM_STATUS_CHANGED' AND target_type = 'MEETING')",
            name="ck_notifications_target_type",
        ),
        CheckConstraint(
            "email_status IN ('DISABLED', 'PENDING', 'SENT', 'FAILED')",
            name="ck_notifications_email_status",
        ),
        CheckConstraint("email_attempts >= 0", name="ck_notifications_email_attempts"),
        UniqueConstraint(
            "recipient_user_id",
            "event_key",
            name="uq_notifications_recipient_event",
        ),
        Index(
            "ix_notifications_recipient_unread_created",
            "recipient_user_id",
            "read_at",
            "created_at",
        ),
        Index(
            "ix_notifications_email_queue",
            "email_status",
            "email_next_attempt_at",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    recipient_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_key: Mapped[str] = mapped_column(String(150), nullable=False)
    notification_type: Mapped[NotificationType] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    target_type: Mapped[NotificationTargetType] = mapped_column(String(30), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[NotificationEmailStatus] = mapped_column(
        String(20),
        default=NotificationEmailStatus.DISABLED,
        server_default=text("'DISABLED'"),
        nullable=False,
    )
    email_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    email_next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_last_error: Mapped[str | None] = mapped_column(String(100))
