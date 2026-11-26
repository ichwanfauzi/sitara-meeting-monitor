"""Add the Manager Legal role and free-text meeting/PIC fields."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0021_meeting_roster_pic"
down_revision: str | None = "0020_minutes_pic_suggestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_sqlite_assignment_triggers() -> list[str]:
    connection = op.get_bind()
    trigger_rows = connection.exec_driver_sql(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL"
    ).all()
    affected_triggers = [
        (name, sql)
        for name, table_name, sql in trigger_rows
        if table_name == "assignments" or "assignments" in sql
    ]
    for name, _ in affected_triggers:
        quoted_name = '"' + name.replace('"', '""') + '"'
        op.execute(f"DROP TRIGGER {quoted_name}")
    return [sql for _, sql in affected_triggers]


def _restore_sqlite_assignment_triggers(trigger_sql: list[str]) -> None:
    for statement in trigger_sql:
        op.execute(statement)


def upgrade() -> None:
    connection = op.get_bind()
    role_exists = connection.execute(
        sa.text("SELECT 1 FROM roles WHERE role_code = 'MANAGER_LEGAL'")
    ).first()
    if role_exists is None:
        roles = sa.table(
            "roles",
            sa.column("id", sa.Uuid()),
            sa.column("role_code", sa.String()),
            sa.column("role_name", sa.String()),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        connection.execute(
            roles.insert().values(
                id=uuid4(),
                role_code="MANAGER_LEGAL",
                role_name="Manager Legal",
                created_at=datetime.now(UTC),
            )
        )

    op.add_column("agendas", sa.Column("pic_suggestion", sa.String(length=300)))
    op.add_column("agendas", sa.Column("supporting_pic_suggestion", sa.String(length=2000)))
    op.add_column("assignments", sa.Column("assignee_display_name", sa.String(length=200)))

    dialect = connection.dialect.name
    assignment_triggers: list[str] = []
    if dialect == "sqlite":
        assignment_triggers = _drop_sqlite_assignment_triggers()
    with op.batch_alter_table(
        "assignments", recreate="always" if dialect == "sqlite" else "auto"
    ) as batch:
        batch.alter_column(
            "assignee_user_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
        batch.create_check_constraint(
            "ck_assignments_user_or_display_name",
            "(assignee_user_id IS NOT NULL AND assignee_display_name IS NULL) OR "
            "(assignee_user_id IS NULL AND assignee_display_name IS NOT NULL "
            "AND length(trim(assignee_display_name)) > 0)",
        )
    if dialect == "sqlite":
        _restore_sqlite_assignment_triggers(assignment_triggers)


def downgrade() -> None:
    connection = op.get_bind()
    role_user = connection.execute(
        sa.text(
            "SELECT count(*) FROM user_roles ur "
            "JOIN roles r ON r.id = ur.role_id "
            "WHERE r.role_code = 'MANAGER_LEGAL'"
        )
    ).scalar_one()
    if role_user:
        raise RuntimeError("Cannot downgrade while users are assigned the Manager Legal role")

    named_assignments = connection.execute(
        sa.text(
            "SELECT count(*) FROM assignments "
            "WHERE assignee_display_name IS NOT NULL OR assignee_user_id IS NULL"
        )
    ).scalar_one()
    agenda_pics = connection.execute(
        sa.text(
            "SELECT count(*) FROM agendas "
            "WHERE pic_suggestion IS NOT NULL OR supporting_pic_suggestion IS NOT NULL"
        )
    ).scalar_one()
    if named_assignments:
        raise RuntimeError("Cannot downgrade while named or userless PIC assignments exist")
    if agenda_pics:
        raise RuntimeError("Cannot downgrade while agenda PIC suggestions exist")

    dialect = connection.dialect.name
    assignment_triggers: list[str] = []
    if dialect == "sqlite":
        assignment_triggers = _drop_sqlite_assignment_triggers()
    with op.batch_alter_table(
        "assignments", recreate="always" if dialect == "sqlite" else "auto"
    ) as batch:
        batch.drop_constraint("ck_assignments_user_or_display_name", type_="check")
        batch.alter_column(
            "assignee_user_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        batch.drop_column("assignee_display_name")
    if dialect == "sqlite":
        _restore_sqlite_assignment_triggers(assignment_triggers)
    op.drop_column("agendas", "supporting_pic_suggestion")
    op.drop_column("agendas", "pic_suggestion")

    connection.execute(sa.text("DELETE FROM roles WHERE role_code = 'MANAGER_LEGAL'"))
