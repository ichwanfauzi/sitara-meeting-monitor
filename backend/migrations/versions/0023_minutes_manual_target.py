"""Allow structured minutes targets to use dates or manual text."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_minutes_manual_target"
down_revision: str | None = "0022_repository_action_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Minutes manual-target migration requires PostgreSQL or SQLite")

    op.add_column("minutes_decisions", sa.Column("target_text", sa.Text(), nullable=True))
    if dialect == "postgresql":
        op.create_check_constraint(
            "ck_minutes_decisions_single_target_value",
            "minutes_decisions",
            "target_date IS NULL OR target_text IS NULL",
        )
        op.create_check_constraint(
            "ck_minutes_decisions_target_text_length",
            "minutes_decisions",
            "target_text IS NULL OR length(target_text) <= 500",
        )
    else:
        op.execute(
            """
            CREATE TRIGGER trg_minutes_decisions_target_value_insert
            BEFORE INSERT ON minutes_decisions
            WHEN (NEW.target_date IS NOT NULL AND NEW.target_text IS NOT NULL)
              OR (NEW.target_text IS NOT NULL AND length(NEW.target_text) > 500)
            BEGIN
                SELECT RAISE(ABORT, 'Invalid target value (maximum 500 characters)');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_minutes_decisions_target_value_update
            BEFORE UPDATE ON minutes_decisions
            WHEN (NEW.target_date IS NOT NULL AND NEW.target_text IS NOT NULL)
              OR (NEW.target_text IS NOT NULL AND length(NEW.target_text) > 500)
            BEGIN
                SELECT RAISE(ABORT, 'Invalid target value (maximum 500 characters)');
            END
            """
        )


def downgrade() -> None:
    connection = op.get_bind()
    populated_targets = connection.execute(
        sa.text("SELECT count(*) FROM minutes_decisions WHERE target_text IS NOT NULL")
    ).scalar_one()
    if populated_targets:
        raise RuntimeError("Cannot downgrade while manual minutes targets are stored")

    if connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER trg_minutes_decisions_target_value_insert")
        op.execute("DROP TRIGGER trg_minutes_decisions_target_value_update")
    else:
        op.drop_constraint(
            "ck_minutes_decisions_single_target_value", "minutes_decisions", type_="check"
        )
        op.drop_constraint(
            "ck_minutes_decisions_target_text_length", "minutes_decisions", type_="check"
        )
    op.drop_column("minutes_decisions", "target_text")
