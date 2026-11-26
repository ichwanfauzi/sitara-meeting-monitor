"""Allow Decision Brief rows without an editorial priority label."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_brief_optional_priority"
down_revision: str | None = "0026_notification_email_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PRIORITY_CHECK = "priority = '' OR (length(trim(priority)) > 0 AND length(priority) <= 100)"
_PREVIOUS_PRIORITY_CHECK = "length(trim(priority)) > 0 AND length(priority) <= 100"


def _set_priority_check(expression: str) -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        op.execute("DROP TRIGGER trg_decision_brief_decisions_no_update")
        op.execute("DROP TRIGGER trg_decision_brief_decisions_no_delete")

    with op.batch_alter_table(
        "decision_brief_decisions", recreate="always" if is_sqlite else "auto"
    ) as batch_op:
        batch_op.drop_constraint("ck_decision_brief_decisions_priority", type_="check")
        batch_op.create_check_constraint(
            "ck_decision_brief_decisions_priority",
            expression,
        )

    if is_sqlite:
        op.execute(
            "CREATE TRIGGER trg_decision_brief_decisions_no_update "
            "BEFORE UPDATE ON decision_brief_decisions "
            "BEGIN SELECT RAISE(ABORT, 'decision brief versions are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_decision_brief_decisions_no_delete "
            "BEFORE DELETE ON decision_brief_decisions "
            "BEGIN SELECT RAISE(ABORT, 'decision brief versions are append-only'); END"
        )


def upgrade() -> None:
    if op.get_bind().dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("Decision Brief priority migration requires PostgreSQL or SQLite")
    _set_priority_check(_PRIORITY_CHECK)


def downgrade() -> None:
    connection = op.get_bind()
    blank_priorities = connection.execute(
        sa.text("SELECT count(*) FROM decision_brief_decisions WHERE priority = ''")
    ).scalar_one()
    if blank_priorities:
        raise RuntimeError(
            "Cannot downgrade while Decision Brief versions with blank priorities exist"
        )

    _set_priority_check(_PREVIOUS_PRIORITY_CHECK)
