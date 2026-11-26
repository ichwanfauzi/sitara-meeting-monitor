"""Add centralized append-only audit events for meeting transitions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_audit_foundation"
down_revision: str | None = "0012_user_job_title"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Audit event migration requires PostgreSQL or SQLite")

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_roles", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("object_type", sa.String(length=50), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=True),
        sa.Column("before_values", sa.JSON(), nullable=True),
        sa.Column("after_values", sa.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action = 'meeting.status_changed'",
            name="ck_audit_events_action",
        ),
        sa.CheckConstraint("object_type = 'meeting'", name="ck_audit_events_object_type"),
        sa.CheckConstraint(
            "result IN ('SUCCEEDED', 'DENIED')",
            name="ck_audit_events_result",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_audit_events_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_object_time",
        "audit_events",
        ["object_type", "object_id", "occurred_at"],
    )
    op.create_index(
        "ix_audit_events_actor_time",
        "audit_events",
        ["actor_user_id", "occurred_at"],
    )
    op.create_index("ix_audit_events_action_time", "audit_events", ["action", "occurred_at"])

    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_audit_event_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Audit event history is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_no_truncate
            BEFORE TRUNCATE ON audit_events
            FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation()
            """
        )
    else:
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit event history is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit event history is append-only');
            END
            """
        )


def downgrade() -> None:
    event_count = op.get_bind().execute(sa.text("SELECT count(*) FROM audit_events")).scalar_one()
    if event_count:
        raise RuntimeError("Cannot downgrade while audit event history exists")

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER trg_audit_events_no_truncate ON audit_events")
        op.execute("DROP TRIGGER trg_audit_events_append_only ON audit_events")
        op.execute("DROP FUNCTION reject_audit_event_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER trg_audit_events_no_update")
        op.execute("DROP TRIGGER trg_audit_events_no_delete")

    op.drop_index("ix_audit_events_action_time", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_time", table_name="audit_events")
    op.drop_index("ix_audit_events_object_time", table_name="audit_events")
    op.drop_table("audit_events")
