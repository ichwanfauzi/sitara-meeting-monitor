"""Add recoverable Action Item deletion and Decision Brief editorial text."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_repository_action_edits"
down_revision: str | None = "0021_meeting_roster_pic"
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
_BASE_ACTION_ITEMS = "'action_item.created', 'action_item.assignment_changed'"
_EDIT_ACTION_ITEMS = (
    "'action_item.created', 'action_item.assignment_changed', "
    "'action_item.updated', 'action_item.deleted'"
)


def _set_audit_constraints(*, include_edit_events: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_audit_events_no_update")
        op.execute("DROP TRIGGER trg_audit_events_no_delete")
    action_items = _EDIT_ACTION_ITEMS if include_edit_events else _BASE_ACTION_ITEMS
    with op.batch_alter_table(
        "audit_events", recreate="always" if dialect == "sqlite" else "auto"
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_object_type", type_="check")
        batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_action",
            f"action IN ({_MEETING_ACTIONS}, {_BRIEF_ACTIONS}, "
            f"'disposition.created', {action_items})",
        )
        batch.create_check_constraint(
            "ck_audit_events_object_type",
            "object_type IN ('meeting', 'decision_brief_version', 'disposition', 'action_item')",
        )
        batch.create_check_constraint(
            "ck_audit_events_action_object_pair",
            f"(action IN ({_MEETING_ACTIONS}) AND object_type = 'meeting') OR "
            f"(action IN ({_BRIEF_ACTIONS}) AND object_type = 'decision_brief_version') OR "
            "(action = 'disposition.created' AND object_type = 'disposition') OR "
            f"(action IN ({action_items}) AND object_type = 'action_item')",
        )
    if dialect == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            # Operation and trigger names are drawn from this fixed tuple.
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


def _drop_sqlite_action_item_triggers() -> list[str]:
    connection = op.get_bind()
    trigger_rows = connection.exec_driver_sql(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' AND sql IS NOT NULL"
    ).all()
    affected_triggers = [
        (name, sql)
        for name, table_name, sql in trigger_rows
        if table_name in {"action_items", "status_histories"} or "action_items" in sql
    ]
    for name, _ in affected_triggers:
        quoted_name = '"' + name.replace('"', '""') + '"'
        op.execute(f"DROP TRIGGER {quoted_name}")
    return [sql for _, sql in affected_triggers]


def _restore_sqlite_action_item_triggers(trigger_sql: list[str]) -> None:
    for statement in trigger_sql:
        op.execute(statement)


def upgrade() -> None:
    connection = op.get_bind()
    dialect = connection.dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Repository/action-item edit migration requires PostgreSQL or SQLite")

    existing_action_item_triggers: list[str] = []
    if dialect == "sqlite":
        existing_action_item_triggers = _drop_sqlite_action_item_triggers()
    with op.batch_alter_table(
        "action_items",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("deleted_by_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_action_items_deleted_by_user",
            "users",
            ["deleted_by_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if dialect == "postgresql":
        op.create_check_constraint(
            "ck_action_items_deleted_actor_pair",
            "action_items",
            "(deleted_at IS NULL AND deleted_by_id IS NULL) OR "
            "(deleted_at IS NOT NULL AND deleted_by_id IS NOT NULL)",
        )
    else:
        op.execute(
            """
            CREATE TRIGGER trg_action_items_deleted_actor_insert
            BEFORE INSERT ON action_items
            WHEN (NEW.deleted_at IS NULL) <> (NEW.deleted_by_id IS NULL)
            BEGIN
                SELECT RAISE(ABORT, 'Deleted time and actor must be set together');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_action_items_deleted_actor_update
            BEFORE UPDATE ON action_items
            WHEN (NEW.deleted_at IS NULL) <> (NEW.deleted_by_id IS NULL)
            BEGIN
                SELECT RAISE(ABORT, 'Deleted time and actor must be set together');
            END
            """
        )
        _restore_sqlite_action_item_triggers(existing_action_item_triggers)

    op.add_column(
        "decision_brief_decisions",
        sa.Column("brief_text", sa.Text(), nullable=True),
    )
    _set_audit_constraints(include_edit_events=True)


def downgrade() -> None:
    connection = op.get_bind()
    deleted_items = connection.execute(
        sa.text("SELECT count(*) FROM action_items WHERE deleted_at IS NOT NULL")
    ).scalar_one()
    brief_texts = connection.execute(
        sa.text("SELECT count(*) FROM decision_brief_decisions WHERE brief_text IS NOT NULL")
    ).scalar_one()
    edit_events = connection.execute(
        sa.text(
            "SELECT count(*) FROM audit_events "
            "WHERE action IN ('action_item.updated', 'action_item.deleted')"
        )
    ).scalar_one()
    if deleted_items or brief_texts or edit_events:
        raise RuntimeError(
            "Cannot downgrade while deleted Action Items, Decision Brief text, "
            "or edit audit events exist"
        )

    dialect = connection.dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_action_items_deleted_actor_insert")
        op.execute("DROP TRIGGER trg_action_items_deleted_actor_update")
        existing_action_item_triggers = _drop_sqlite_action_item_triggers()
    else:
        op.drop_constraint("ck_action_items_deleted_actor_pair", "action_items", type_="check")
    _set_audit_constraints(include_edit_events=False)
    op.drop_column("decision_brief_decisions", "brief_text")
    with op.batch_alter_table(
        "action_items",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("fk_action_items_deleted_by_user", type_="foreignkey")
        batch.drop_column("deleted_by_id")
        batch.drop_column("deleted_at")
    if dialect == "sqlite":
        _restore_sqlite_action_item_triggers(existing_action_item_triggers)
