"""Add immutable Decision Brief approval events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_decision_brief_approval"
down_revision: str | None = "0016_meeting_live_editing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEETING_ACTIONS = (
    "'meeting.status_changed', 'meeting.metadata_updated', 'meeting.agenda_changed', "
    "'meeting.participant_changed', 'meeting.notetaker_handover_requested', "
    "'meeting.notetaker_handover_approved'"
)
_BRIEF_ACTIONS = (
    "'decision_brief.submitted', 'decision_brief.withdrawn', "
    "'decision_brief.approved', 'decision_brief.rejected'"
)


def _set_audit_event_constraints(*, allow_brief_workflow: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_audit_events_no_update")
        op.execute("DROP TRIGGER trg_audit_events_no_delete")

    with op.batch_alter_table(
        "audit_events",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_object_type", type_="check")
        batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
        if allow_brief_workflow:
            batch.create_check_constraint(
                "ck_audit_events_action",
                f"action IN ({_MEETING_ACTIONS}, {_BRIEF_ACTIONS}, "
                "'disposition.created', 'action_item.created')",
            )
            batch.create_check_constraint(
                "ck_audit_events_object_type",
                "object_type IN ('meeting', 'decision_brief_version', "
                "'disposition', 'action_item')",
            )
            batch.create_check_constraint(
                "ck_audit_events_action_object_pair",
                f"(action IN ({_MEETING_ACTIONS}) AND object_type = 'meeting') OR "
                f"(action IN ({_BRIEF_ACTIONS}) AND object_type = 'decision_brief_version') OR "
                "(action = 'disposition.created' AND object_type = 'disposition') OR "
                "(action = 'action_item.created' AND object_type = 'action_item')",
            )
        else:
            batch.create_check_constraint(
                "ck_audit_events_action",
                f"action IN ({_MEETING_ACTIONS}, 'disposition.created', 'action_item.created')",
            )
            batch.create_check_constraint(
                "ck_audit_events_object_type",
                "object_type IN ('meeting', 'disposition', 'action_item')",
            )
            batch.create_check_constraint(
                "ck_audit_events_action_object_pair",
                f"(action IN ({_MEETING_ACTIONS}) AND object_type = 'meeting') OR "
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


def _create_approval_event_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_decision_brief_approval_event_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Decision Brief approval event history is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_decision_brief_approval_events_no_update
            BEFORE UPDATE ON decision_brief_approval_events
            FOR EACH ROW EXECUTE FUNCTION reject_decision_brief_approval_event_mutation()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_decision_brief_approval_events_no_delete
            BEFORE DELETE ON decision_brief_approval_events
            FOR EACH ROW EXECUTE FUNCTION reject_decision_brief_approval_event_mutation()
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_decision_brief_approval_events_no_truncate
            BEFORE TRUNCATE ON decision_brief_approval_events
            FOR EACH STATEMENT EXECUTE FUNCTION reject_decision_brief_approval_event_mutation()
            """
        )
    elif dialect == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            # Operation and trigger names are drawn only from this fixed tuple.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query
            # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(
                f"""
                CREATE TRIGGER trg_decision_brief_approval_events_no_{operation.lower()}
                BEFORE {operation} ON decision_brief_approval_events
                BEGIN
                    SELECT RAISE(ABORT, 'Decision Brief approval event history is append-only');
                END
                """
            )


def _drop_approval_event_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for operation in ("update", "delete", "truncate"):
            op.execute(
                f"DROP TRIGGER trg_decision_brief_approval_events_no_{operation} "
                "ON decision_brief_approval_events"
            )
        op.execute("DROP FUNCTION reject_decision_brief_approval_event_mutation()")
    elif dialect == "sqlite":
        for operation in ("update", "delete"):
            op.execute(f"DROP TRIGGER trg_decision_brief_approval_events_no_{operation}")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Decision Brief approval migration requires PostgreSQL or SQLite")

    _set_audit_event_constraints(allow_brief_workflow=True)
    op.create_table(
        "decision_brief_approval_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("brief_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_minutes_revision_id", sa.Uuid(), nullable=False),
        sa.Column("event_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_roles", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_number > 0",
            name="ck_decision_brief_approval_events_number",
        ),
        sa.CheckConstraint(
            "event_type IN ('SUBMITTED', 'WITHDRAWN', 'APPROVED', 'REJECTED')",
            name="ck_decision_brief_approval_events_type",
        ),
        sa.CheckConstraint(
            "(event_type = 'REJECTED' AND reason IS NOT NULL "
            "AND length(trim(reason)) > 0 AND length(reason) <= 4000) OR "
            "(event_type <> 'REJECTED' AND reason IS NULL)",
            name="ck_decision_brief_approval_events_reason",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "brief_version_id", "source_minutes_revision_id"],
            [
                "decision_brief_versions.meeting_id",
                "decision_brief_versions.id",
                "decision_brief_versions.source_minutes_revision_id",
            ],
            name="fk_decision_brief_approval_events_version_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_decision_brief_approval_events_actor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "brief_version_id",
            "event_number",
            name="uq_decision_brief_approval_events_number",
        ),
    )
    op.create_index(
        "ix_decision_brief_approval_events_version",
        "decision_brief_approval_events",
        ["brief_version_id", "event_number"],
    )
    op.create_index(
        "uq_decision_brief_approval_events_terminal",
        "decision_brief_approval_events",
        ["brief_version_id"],
        unique=True,
        postgresql_where=sa.text("event_type IN ('APPROVED', 'REJECTED')"),
        sqlite_where=sa.text("event_type IN ('APPROVED', 'REJECTED')"),
    )
    _create_approval_event_guards()


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM decision_brief_approval_events)")):
        raise RuntimeError(
            "Cannot downgrade while Decision Brief approval history exists; "
            "preserve the append-only events."
        )

    _drop_approval_event_guards()
    op.drop_index(
        "uq_decision_brief_approval_events_terminal",
        table_name="decision_brief_approval_events",
    )
    op.drop_index(
        "ix_decision_brief_approval_events_version",
        table_name="decision_brief_approval_events",
    )
    op.drop_table("decision_brief_approval_events")
    _set_audit_event_constraints(allow_brief_workflow=False)
