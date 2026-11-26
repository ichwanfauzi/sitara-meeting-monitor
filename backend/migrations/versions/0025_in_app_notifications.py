"""Persist private in-app notifications for directly involved users."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_in_app_notifications"
down_revision: str | None = "0024_content_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("In-app notification migration requires PostgreSQL or SQLite")

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(length=150), nullable=False),
        sa.Column("notification_type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "notification_type IN ('ACTION_ITEM_STATUS_CHANGED', "
            "'DECISION_BRIEF_REVIEW_NEEDED', 'DECISION_BRIEF_REVIEW_WITHDRAWN', "
            "'DECISION_BRIEF_REVIEW_COMPLETED')",
            name="ck_notifications_type",
        ),
        sa.CheckConstraint(
            "(notification_type = 'ACTION_ITEM_STATUS_CHANGED' AND target_type = 'ACTION_ITEM') "
            "OR (notification_type <> 'ACTION_ITEM_STATUS_CHANGED' AND target_type = 'MEETING')",
            name="ck_notifications_target_type",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="fk_notifications_recipient_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.UniqueConstraint(
            "recipient_user_id",
            "event_key",
            name="uq_notifications_recipient_event",
        ),
    )
    op.create_index(
        "ix_notifications_recipient_unread_created",
        "notifications",
        ["recipient_user_id", "read_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    existing_notifications = connection.execute(
        sa.text("SELECT count(*) FROM notifications")
    ).scalar_one()
    if existing_notifications:
        raise RuntimeError("Cannot downgrade while in-app notifications are stored")
    op.drop_index("ix_notifications_recipient_unread_created", table_name="notifications")
    op.drop_table("notifications")
