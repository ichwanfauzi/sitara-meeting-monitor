"""Add a durable email delivery queue to in-app notifications."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_notification_email_delivery"
down_revision: str | None = "0025_in_app_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("Notification email migration requires PostgreSQL or SQLite")

    with op.batch_alter_table("notifications") as batch_op:
        batch_op.add_column(
            sa.Column(
                "email_status",
                sa.String(length=20),
                server_default=sa.text("'DISABLED'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "email_attempts",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("email_next_attempt_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("email_sent_at", sa.DateTime(timezone=True)))
        batch_op.add_column(sa.Column("email_last_error", sa.String(length=100)))
        batch_op.create_check_constraint(
            "ck_notifications_email_status",
            "email_status IN ('DISABLED', 'PENDING', 'SENT', 'FAILED')",
        )
        batch_op.create_check_constraint(
            "ck_notifications_email_attempts",
            "email_attempts >= 0",
        )

    op.create_index(
        "ix_notifications_email_queue",
        "notifications",
        ["email_status", "email_next_attempt_at", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    existing_email_delivery_history = connection.execute(
        sa.text("SELECT count(*) FROM notifications WHERE email_status <> 'DISABLED'")
    ).scalar_one()
    if existing_email_delivery_history:
        raise RuntimeError("Cannot downgrade while notification email delivery history exists")

    op.drop_index("ix_notifications_email_queue", table_name="notifications")
    with op.batch_alter_table("notifications") as batch_op:
        batch_op.drop_constraint("ck_notifications_email_attempts", type_="check")
        batch_op.drop_constraint("ck_notifications_email_status", type_="check")
        batch_op.drop_column("email_last_error")
        batch_op.drop_column("email_sent_at")
        batch_op.drop_column("email_next_attempt_at")
        batch_op.drop_column("email_attempts")
        batch_op.drop_column("email_status")
