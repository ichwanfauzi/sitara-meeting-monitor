"""Audit Action Item assignment changes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_assignment_audit"
down_revision: str | None = "0018_action_item_unit_provenance"
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
_ACTION_ITEM_ACTIONS = "'action_item.created', 'action_item.assignment_changed'"


def _set_assignment_audit_constraint(*, include_assignment_changes: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_audit_events_no_update")
        op.execute("DROP TRIGGER trg_audit_events_no_delete")

    action_item_actions = (
        _ACTION_ITEM_ACTIONS if include_assignment_changes else "'action_item.created'"
    )
    with op.batch_alter_table(
        "audit_events",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_object_type", type_="check")
        batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_action",
            f"action IN ({_MEETING_ACTIONS}, {_BRIEF_ACTIONS}, "
            "'disposition.created', "
            f"{action_item_actions})",
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
            f"(action IN ({action_item_actions}) AND object_type = 'action_item')",
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


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Action Item assignment audit migration requires PostgreSQL or SQLite")
    _set_assignment_audit_constraint(include_assignment_changes=True)


def downgrade() -> None:
    assignment_events = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM audit_events WHERE action = 'action_item.assignment_changed'"
            )
        )
        .scalar_one()
    )
    if assignment_events:
        raise RuntimeError("Cannot downgrade while Action Item assignment audit history exists")
    _set_assignment_audit_constraint(include_assignment_changes=False)
