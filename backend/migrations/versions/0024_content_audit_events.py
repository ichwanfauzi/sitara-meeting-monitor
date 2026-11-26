"""Audit structured minutes and Decision Brief saves."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_content_audit_events"
down_revision: str | None = "0023_minutes_manual_target"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEETING_ACTIONS = (
    "'meeting.status_changed', 'meeting.metadata_updated', 'meeting.agenda_changed', "
    "'meeting.participant_changed', 'meeting.notetaker_handover_requested', "
    "'meeting.notetaker_handover_approved'"
)
_BRIEF_WORKFLOW_ACTIONS = (
    "'decision_brief.submitted', 'decision_brief.withdrawn', "
    "'decision_brief.approved', 'decision_brief.rejected'"
)
_ACTION_ITEM_ACTIONS = (
    "'action_item.created', 'action_item.assignment_changed', "
    "'action_item.updated', 'action_item.deleted'"
)


def _set_audit_constraints(*, include_content_events: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_audit_events_no_update")
        op.execute("DROP TRIGGER trg_audit_events_no_delete")

    content_actions = (
        "'minutes.revised', 'decision_brief.saved', " if include_content_events else ""
    )
    with op.batch_alter_table(
        "audit_events", recreate="always" if dialect == "sqlite" else "auto"
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_object_type", type_="check")
        batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
        batch.create_check_constraint(
            "ck_audit_events_action",
            f"action IN ({_MEETING_ACTIONS}, {content_actions}{_BRIEF_WORKFLOW_ACTIONS}, "
            "'disposition.created', "
            f"{_ACTION_ITEM_ACTIONS})",
        )
        batch.create_check_constraint(
            "ck_audit_events_object_type",
            "object_type IN ('meeting', 'decision_brief_version', 'disposition', 'action_item')",
        )
        minutes_pair = (
            "(action = 'minutes.revised' AND object_type = 'meeting') OR "
            if include_content_events
            else ""
        )
        brief_actions = (
            f"'decision_brief.saved', {_BRIEF_WORKFLOW_ACTIONS}"
            if include_content_events
            else _BRIEF_WORKFLOW_ACTIONS
        )
        batch.create_check_constraint(
            "ck_audit_events_action_object_pair",
            f"(action IN ({_MEETING_ACTIONS}) AND object_type = 'meeting') OR "
            f"{minutes_pair}"
            f"(action IN ({brief_actions}) AND object_type = 'decision_brief_version') OR "
            "(action = 'disposition.created' AND object_type = 'disposition') OR "
            f"(action IN ({_ACTION_ITEM_ACTIONS}) AND object_type = 'action_item')",
        )

    if dialect == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            # Operation values are selected from this fixed tuple.
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
    if op.get_bind().dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("Content audit migration requires PostgreSQL or SQLite")
    _set_audit_constraints(include_content_events=True)


def downgrade() -> None:
    connection = op.get_bind()
    content_events = connection.execute(
        sa.text(
            "SELECT count(*) FROM audit_events "
            "WHERE action IN ('minutes.revised', 'decision_brief.saved')"
        )
    ).scalar_one()
    if content_events:
        raise RuntimeError("Cannot downgrade while minutes or Decision Brief audit events exist")

    _set_audit_constraints(include_content_events=False)
