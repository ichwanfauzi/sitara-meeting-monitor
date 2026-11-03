"""Add meeting status events and PostgreSQL login rate-limit buckets."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_workflow_rate_limit"
down_revision: str | None = "0002_meetings_agendas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meeting_status_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(from_status = 'DRAFT' AND to_status = 'LIVE') OR "
            "(from_status = 'LIVE' AND to_status = 'FINAL') OR "
            "(from_status = 'FINAL' AND to_status = 'ARCHIVED')",
            name="ck_meeting_status_events_transition",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meeting_status_events_meeting_time",
        "meeting_status_events",
        ["meeting_id", "occurred_at"],
    )

    op.create_table(
        "login_rate_limit_buckets",
        sa.Column("bucket_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count > 0", name="ck_login_rate_limit_attempt_count_positive"),
        sa.CheckConstraint(
            "expires_at > window_started_at", name="ck_login_rate_limit_window_order"
        ),
        sa.PrimaryKeyConstraint("bucket_hash"),
    )
    op.create_index(
        "ix_login_rate_limit_buckets_expires_at",
        "login_rate_limit_buckets",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_login_rate_limit_buckets_expires_at", table_name="login_rate_limit_buckets")
    op.drop_table("login_rate_limit_buckets")
    op.drop_index("ix_meeting_status_events_meeting_time", table_name="meeting_status_events")
    op.drop_table("meeting_status_events")
