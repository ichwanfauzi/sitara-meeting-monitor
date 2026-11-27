"""Support forced password changes and audited user administration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_super_admin_account_management"
down_revision: str | None = "0030_action_item_status_audit"
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
_ACTION_ITEM_ACTIONS = (
    "'action_item.created', 'action_item.assignment_changed', 'action_item.status_changed', "
    "'action_item.updated', 'action_item.deleted'"
)
_USER_ACTIONS = (
    "'user.created', 'user.updated', 'user.deactivated', 'user.reactivated', "
    "'user.password_reset', 'user.password_changed', 'user.provisioned'"
)


def _set_audit_constraints(
    *,
    include_user_events: bool,
    restore_required_user_actor: bool = False,
) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_delete")

    user_actions = f", {_USER_ACTIONS}" if include_user_events else ""
    object_types = (
        "'meeting', 'decision_brief_version', 'disposition', 'action_item', 'user'"
        if include_user_events
        else "'meeting', 'decision_brief_version', 'disposition', 'action_item'"
    )
    user_pair = (
        f" OR (action IN ({_USER_ACTIONS}) AND object_type = 'user')" if include_user_events else ""
    )
    with op.batch_alter_table(
        "audit_events", recreate="always" if dialect == "sqlite" else "auto"
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_object_type", type_="check")
        batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
        if include_user_events:
            batch.create_check_constraint(
                "ck_audit_events_actor_type",
                "(actor_type = 'USER' AND actor_user_id IS NOT NULL) OR "
                "(actor_type = 'SYSTEM' AND actor_user_id IS NULL)",
            )
        else:
            batch.drop_constraint("ck_audit_events_actor_type", type_="check")
            if restore_required_user_actor:
                batch.alter_column("actor_user_id", existing_type=sa.Uuid(), nullable=False)
                batch.drop_column("actor_type")
        batch.create_check_constraint(
            "ck_audit_events_action",
            f"action IN ({_MEETING_ACTIONS}, {_BRIEF_ACTIONS}, "
            f"'disposition.created', {_ACTION_ITEM_ACTIONS}{user_actions})",
        )
        batch.create_check_constraint(
            "ck_audit_events_object_type",
            f"object_type IN ({object_types})",
        )
        batch.create_check_constraint(
            "ck_audit_events_action_object_pair",
            f"(action IN ({_MEETING_ACTIONS}) AND object_type = 'meeting') OR "
            f"(action IN ({_BRIEF_ACTIONS}) AND object_type = 'decision_brief_version') OR "
            "(action = 'disposition.created' AND object_type = 'disposition') OR "
            f"(action IN ({_ACTION_ITEM_ACTIONS}) AND object_type = 'action_item')"
            f"{user_pair}",
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
        raise RuntimeError("Super Admin account management migration requires PostgreSQL or SQLite")

    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    with op.batch_alter_table(
        "audit_events", recreate="always" if dialect == "sqlite" else "auto"
    ) as batch:
        batch.add_column(
            sa.Column("actor_type", sa.String(length=20), server_default="USER", nullable=False)
        )
        batch.alter_column("actor_user_id", existing_type=sa.Uuid(), nullable=True)
    _set_audit_constraints(include_user_events=True)


def downgrade() -> None:
    connection = op.get_bind()
    account_events = connection.execute(
        sa.text("SELECT count(*) FROM audit_events WHERE action LIKE 'user.%'")
    ).scalar_one()
    if account_events:
        raise RuntimeError("Cannot downgrade while user account audit events exist")
    temporary_password_users = connection.execute(
        sa.text("SELECT count(*) FROM users WHERE must_change_password IS TRUE")
    ).scalar_one()
    if temporary_password_users:
        raise RuntimeError("Cannot downgrade while accounts require a password change")

    _set_audit_constraints(
        include_user_events=False,
        restore_required_user_actor=True,
    )
    op.drop_column("users", "must_change_password")
