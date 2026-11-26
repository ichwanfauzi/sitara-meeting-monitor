"""Add versioned meeting edits and formal notetaker handovers."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_meeting_live_editing"
down_revision: str | None = "0015_action_item_dispositions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEETING_AUDIT_ACTIONS = (
    "'meeting.status_changed', 'meeting.metadata_updated', 'meeting.agenda_changed', "
    "'meeting.participant_changed', 'meeting.notetaker_handover_requested', "
    "'meeting.notetaker_handover_approved'"
)


def _set_audit_event_constraints(*, allow_meeting_edits: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_audit_events_no_update")
        op.execute("DROP TRIGGER trg_audit_events_no_delete")

    with op.batch_alter_table(
        "audit_events",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
        if allow_meeting_edits:
            batch.create_check_constraint(
                "ck_audit_events_action",
                f"action IN ({_MEETING_AUDIT_ACTIONS}, 'disposition.created', "
                "'action_item.created')",
            )
            batch.create_check_constraint(
                "ck_audit_events_action_object_pair",
                "(action IN (" + _MEETING_AUDIT_ACTIONS + ") AND object_type = 'meeting') OR "
                "(action = 'disposition.created' AND object_type = 'disposition') OR "
                "(action = 'action_item.created' AND object_type = 'action_item')",
            )
        else:
            batch.create_check_constraint(
                "ck_audit_events_action",
                "action IN ('meeting.status_changed', 'disposition.created', "
                "'action_item.created')",
            )
            batch.create_check_constraint(
                "ck_audit_events_action_object_pair",
                "(action = 'meeting.status_changed' AND object_type = 'meeting') OR "
                "(action = 'disposition.created' AND object_type = 'disposition') OR "
                "(action = 'action_item.created' AND object_type = 'action_item')",
            )

    if dialect == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            # Operation and trigger names are drawn only from this fixed tuple.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(
                f"""
                CREATE TRIGGER trg_audit_events_no_{operation.lower()}
                BEFORE {operation} ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'Audit event history is append-only');
                END
                """
            )


def _create_handover_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION guard_meeting_notetaker_handover() RETURNS trigger AS $$
            BEGIN
                IF OLD.id IS DISTINCT FROM NEW.id
                   OR OLD.meeting_id IS DISTINCT FROM NEW.meeting_id
                   OR OLD.from_notetaker_id IS DISTINCT FROM NEW.from_notetaker_id
                   OR OLD.to_notetaker_id IS DISTINCT FROM NEW.to_notetaker_id
                   OR OLD.requested_by_user_id IS DISTINCT FROM NEW.requested_by_user_id
                   OR OLD.requested_at IS DISTINCT FROM NEW.requested_at
                   OR OLD.status <> 'PENDING'
                   OR NEW.status <> 'APPROVED'
                   OR NEW.approved_by_user_id IS NULL
                   OR NEW.approved_at IS NULL THEN
                    RAISE EXCEPTION 'Notetaker handover requests are immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_meeting_notetaker_handover_approve_once
            BEFORE UPDATE ON meeting_notetaker_handovers
            FOR EACH ROW EXECUTE FUNCTION guard_meeting_notetaker_handover()
            """
        )
        op.execute(
            """
            CREATE FUNCTION reject_meeting_notetaker_handover_delete() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Notetaker handover history is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_meeting_notetaker_handover_no_delete
            BEFORE DELETE ON meeting_notetaker_handovers
            FOR EACH ROW EXECUTE FUNCTION reject_meeting_notetaker_handover_delete()
            """
        )
        op.execute(
            """
            CREATE FUNCTION reject_meeting_notetaker_handover_truncate() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Notetaker handover history is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_meeting_notetaker_handover_no_truncate
            BEFORE TRUNCATE ON meeting_notetaker_handovers
            FOR EACH STATEMENT EXECUTE FUNCTION reject_meeting_notetaker_handover_truncate()
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_meeting_notetaker_handover_approve_once
            BEFORE UPDATE ON meeting_notetaker_handovers
            BEGIN
                SELECT CASE WHEN
                    NEW.id IS NOT OLD.id
                    OR NEW.meeting_id IS NOT OLD.meeting_id
                    OR NEW.from_notetaker_id IS NOT OLD.from_notetaker_id
                    OR NEW.to_notetaker_id IS NOT OLD.to_notetaker_id
                    OR NEW.requested_by_user_id IS NOT OLD.requested_by_user_id
                    OR NEW.requested_at IS NOT OLD.requested_at
                    OR OLD.status <> 'PENDING'
                    OR NEW.status <> 'APPROVED'
                    OR NEW.approved_by_user_id IS NULL
                    OR NEW.approved_at IS NULL
                    THEN RAISE(ABORT, 'Notetaker handover requests are immutable')
                END;
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_meeting_notetaker_handover_no_delete
            BEFORE DELETE ON meeting_notetaker_handovers
            BEGIN
                SELECT RAISE(ABORT, 'Notetaker handover history is append-only');
            END
            """
        )


def _drop_handover_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER trg_meeting_notetaker_handover_no_delete ON meeting_notetaker_handovers"
        )
        op.execute(
            "DROP TRIGGER trg_meeting_notetaker_handover_no_truncate ON meeting_notetaker_handovers"
        )
        op.execute(
            "DROP TRIGGER trg_meeting_notetaker_handover_approve_once "
            "ON meeting_notetaker_handovers"
        )
        op.execute("DROP FUNCTION reject_meeting_notetaker_handover_delete()")
        op.execute("DROP FUNCTION reject_meeting_notetaker_handover_truncate()")
        op.execute("DROP FUNCTION guard_meeting_notetaker_handover()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER trg_meeting_notetaker_handover_no_delete")
        op.execute("DROP TRIGGER trg_meeting_notetaker_handover_approve_once")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Meeting live-edit migration requires PostgreSQL or SQLite")

    _set_audit_event_constraints(allow_meeting_edits=True)
    with op.batch_alter_table("meetings") as batch:
        batch.add_column(
            sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False)
        )
        batch.create_check_constraint("ck_meetings_version_positive", "version > 0")
    op.create_table(
        "meeting_notetaker_handovers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("from_notetaker_id", sa.Uuid(), nullable=True),
        sa.Column("to_notetaker_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED')",
            name="ck_meeting_notetaker_handovers_status",
        ),
        sa.CheckConstraint(
            "from_notetaker_id IS NULL OR from_notetaker_id <> to_notetaker_id",
            name="ck_meeting_notetaker_handovers_distinct_users",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND approved_by_user_id IS NULL AND approved_at IS NULL) OR "
            "(status = 'APPROVED' AND approved_by_user_id IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_meeting_notetaker_handovers_approval_state",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["meetings.id"],
            name="fk_meeting_notetaker_handovers_meeting_id_meetings",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_notetaker_id"],
            ["users.id"],
            name="fk_meeting_notetaker_handovers_from_notetaker_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_notetaker_id"],
            ["users.id"],
            name="fk_meeting_notetaker_handovers_to_notetaker_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_meeting_notetaker_handovers_requested_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name="fk_meeting_notetaker_handovers_approved_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_meeting_notetaker_handovers"),
    )
    op.create_index(
        "ix_meeting_notetaker_handovers_meeting_requested",
        "meeting_notetaker_handovers",
        ["meeting_id", "requested_at"],
    )
    op.create_index(
        "uq_meeting_notetaker_handovers_pending",
        "meeting_notetaker_handovers",
        ["meeting_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
        sqlite_where=sa.text("status = 'PENDING'"),
    )
    _create_handover_guards()


def downgrade() -> None:
    connection = op.get_bind()
    handover_count = connection.execute(
        sa.text("SELECT count(*) FROM meeting_notetaker_handovers")
    ).scalar_one()
    handover_events = connection.execute(
        sa.text(
            "SELECT count(*) FROM audit_events WHERE action IN "
            "('meeting.metadata_updated', 'meeting.agenda_changed', "
            "'meeting.participant_changed', 'meeting.notetaker_handover_requested', "
            "'meeting.notetaker_handover_approved')"
        )
    ).scalar_one()
    changed_meetings = connection.execute(
        sa.text("SELECT count(*) FROM meetings WHERE version > 1")
    ).scalar_one()
    if handover_count or handover_events or changed_meetings:
        raise RuntimeError("Cannot downgrade while meeting edit history exists")

    _drop_handover_guards()
    op.drop_index(
        "ix_meeting_notetaker_handovers_meeting_requested",
        table_name="meeting_notetaker_handovers",
    )
    op.drop_index(
        "uq_meeting_notetaker_handovers_pending",
        table_name="meeting_notetaker_handovers",
    )
    op.drop_table("meeting_notetaker_handovers")
    with op.batch_alter_table("meetings") as batch:
        batch.drop_constraint("ck_meetings_version_positive", type_="check")
        batch.drop_column("version")
    _set_audit_event_constraints(allow_meeting_edits=False)
