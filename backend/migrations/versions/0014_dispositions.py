"""Add multi-target dispositions and audit their creation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_dispositions"
down_revision: str | None = "0013_audit_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_audit_event_constraints(*, allow_dispositions: bool) -> None:
    dialect = op.get_bind().dialect.name
    with op.batch_alter_table(
        "audit_events",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_object_type", type_="check")
        if allow_dispositions:
            batch.create_check_constraint(
                "ck_audit_events_action",
                "action IN ('meeting.status_changed', 'disposition.created')",
            )
            batch.create_check_constraint(
                "ck_audit_events_object_type",
                "object_type IN ('meeting', 'disposition')",
            )
            batch.create_check_constraint(
                "ck_audit_events_action_object_pair",
                "(action = 'meeting.status_changed' AND object_type = 'meeting') OR "
                "(action = 'disposition.created' AND object_type = 'disposition')",
            )
        else:
            batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
            batch.create_check_constraint(
                "ck_audit_events_action",
                "action = 'meeting.status_changed'",
            )
            batch.create_check_constraint(
                "ck_audit_events_object_type",
                "object_type = 'meeting'",
            )

    if dialect == "sqlite":
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


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Disposition migration requires PostgreSQL or SQLite")

    _set_audit_event_constraints(allow_dispositions=True)

    op.create_table(
        "dispositions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("source_minutes_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_decision_id", sa.Uuid(), nullable=False),
        sa.Column("issued_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"],
            ["users.id"],
            name="fk_dispositions_issued_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id", "source_decision_id"],
            [
                "minutes_decisions.meeting_id",
                "minutes_decisions.minutes_revision_id",
                "minutes_decisions.id",
            ],
            name="fk_dispositions_exact_source_decision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dispositions"),
    )
    op.create_index(
        "ix_dispositions_meeting_created",
        "dispositions",
        ["meeting_id", "created_at"],
    )
    op.create_table(
        "disposition_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("disposition_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=10), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_unit_id", sa.Uuid(), nullable=True),
        sa.Column("target_role_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(target_type = 'USER' AND target_user_id IS NOT NULL "
            "AND target_unit_id IS NULL AND target_role_id IS NULL) OR "
            "(target_type = 'UNIT' AND target_user_id IS NULL "
            "AND target_unit_id IS NOT NULL AND target_role_id IS NULL) OR "
            "(target_type = 'ROLE' AND target_user_id IS NULL "
            "AND target_unit_id IS NULL AND target_role_id IS NOT NULL)",
            name="ck_disposition_targets_target_shape",
        ),
        sa.ForeignKeyConstraint(
            ["disposition_id"],
            ["dispositions.id"],
            name="fk_disposition_targets_disposition_id_dispositions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_disposition_targets_target_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_unit_id"],
            ["organization_units.id"],
            name="fk_disposition_targets_target_unit_id_organization_units",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_role_id"],
            ["roles.id"],
            name="fk_disposition_targets_target_role_id_roles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_disposition_targets"),
    )
    for target_kind, column in (
        ("user", "target_user_id"),
        ("unit", "target_unit_id"),
        ("role", "target_role_id"),
    ):
        op.create_index(
            f"uq_disposition_targets_{target_kind}",
            "disposition_targets",
            ["disposition_id", column],
            unique=True,
            postgresql_where=sa.column(column).is_not(None),
            sqlite_where=sa.column(column).is_not(None),
        )
        op.create_index(
            f"ix_disposition_targets_{target_kind}",
            "disposition_targets",
            [column],
        )


def downgrade() -> None:
    connection = op.get_bind()
    disposition_count = connection.execute(
        sa.text("SELECT count(*) FROM dispositions")
    ).scalar_one()
    disposition_events = connection.execute(
        sa.text("SELECT count(*) FROM audit_events WHERE action = 'disposition.created'")
    ).scalar_one()
    if disposition_count or disposition_events:
        raise RuntimeError("Cannot downgrade while disposition history exists")

    for target_kind in ("role", "unit", "user"):
        op.drop_index(
            f"ix_disposition_targets_{target_kind}",
            table_name="disposition_targets",
        )
        op.drop_index(
            f"uq_disposition_targets_{target_kind}",
            table_name="disposition_targets",
        )
    op.drop_table("disposition_targets")
    op.drop_index("ix_dispositions_meeting_created", table_name="dispositions")
    op.drop_table("dispositions")

    _set_audit_event_constraints(allow_dispositions=False)
