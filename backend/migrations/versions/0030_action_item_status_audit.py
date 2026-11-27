"""Allow Action Item status changes in the central audit log."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_action_item_status_audit"
down_revision: str | None = "0029_minutes_supporting_pic"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEETING_ACTIONS = (
    "'meeting.status_changed', 'meeting.metadata_updated', 'meeting.agenda_changed', "
    "'meeting.participant_changed', 'meeting.notetaker_handover_requested', "
    "'meeting.notetaker_handover_approved', 'minutes.revised'"
)
_BRIEF_ACTIONS = (
    "'decision_brief.saved', 'decision_brief.submitted', 'decision_brief.withdrawn', "
    "'decision_brief.approved', 'decision_brief.rejected'"
)
_ACTION_ITEMS_WITH_STATUS = (
    "'action_item.created', 'action_item.assignment_changed', "
    "'action_item.status_changed', 'action_item.updated', 'action_item.deleted'"
)
_ACTION_ITEMS_WITHOUT_STATUS = (
    "'action_item.created', 'action_item.assignment_changed', "
    "'action_item.updated', 'action_item.deleted'"
)


def _set_audit_constraints(*, include_status_events: bool) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_audit_events_no_update")
        op.execute("DROP TRIGGER trg_audit_events_no_delete")
    action_items = (
        _ACTION_ITEMS_WITH_STATUS if include_status_events else _ACTION_ITEMS_WITHOUT_STATUS
    )
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
    if op.get_bind().dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("Action Item status audit migration requires PostgreSQL or SQLite")
    _set_audit_constraints(include_status_events=True)


def downgrade() -> None:
    connection = op.get_bind()
    status_events = connection.execute(
        sa.text("SELECT count(*) FROM audit_events WHERE action = 'action_item.status_changed'")
    ).scalar_one()
    if status_events:
        raise RuntimeError("Cannot downgrade while Action Item status audit events exist")
    _set_audit_constraints(include_status_events=False)
