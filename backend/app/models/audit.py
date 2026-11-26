"""Append-only centralized audit event records."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('meeting.status_changed', 'meeting.metadata_updated', "
            "'meeting.agenda_changed', 'meeting.participant_changed', "
            "'meeting.notetaker_handover_requested', 'meeting.notetaker_handover_approved', "
            "'minutes.revised', 'decision_brief.saved', "
            "'decision_brief.submitted', 'decision_brief.withdrawn', "
            "'decision_brief.approved', 'decision_brief.rejected', "
            "'disposition.created', 'action_item.created', 'action_item.assignment_changed', "
            "'action_item.updated', 'action_item.deleted')",
            name="ck_audit_events_action",
        ),
        CheckConstraint(
            "object_type IN ('meeting', 'decision_brief_version', 'disposition', 'action_item')",
            name="ck_audit_events_object_type",
        ),
        CheckConstraint(
            "(action = 'meeting.status_changed' AND object_type = 'meeting') OR "
            "(action IN ('meeting.metadata_updated', 'meeting.agenda_changed', "
            "'meeting.participant_changed', 'meeting.notetaker_handover_requested', "
            "'meeting.notetaker_handover_approved') AND object_type = 'meeting') OR "
            "(action = 'minutes.revised' AND object_type = 'meeting') OR "
            "(action IN ('decision_brief.saved', 'decision_brief.submitted', "
            "'decision_brief.withdrawn', "
            "'decision_brief.approved', 'decision_brief.rejected') "
            "AND object_type = 'decision_brief_version') OR "
            "(action = 'disposition.created' AND object_type = 'disposition') OR "
            "(action IN ('action_item.created', 'action_item.assignment_changed', "
            "'action_item.updated', 'action_item.deleted') "
            "AND object_type = 'action_item')",
            name="ck_audit_events_action_object_pair",
        ),
        CheckConstraint(
            "result IN ('SUCCEEDED', 'DENIED')",
            name="ck_audit_events_result",
        ),
        Index("ix_audit_events_object_time", "object_type", "object_id", "occurred_at"),
        Index("ix_audit_events_actor_time", "actor_user_id", "occurred_at"),
        Index("ix_audit_events_action_time", "action", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_roles: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    before_values: Mapped[dict[str, str | None] | None] = mapped_column(JSON)
    after_values: Mapped[dict[str, str | None] | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
