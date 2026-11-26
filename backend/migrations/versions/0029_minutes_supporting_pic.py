"""Add an optional supporting PIC suggestion to each minutes decision."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_minutes_supporting_pic"
down_revision: str | None = "0028_meeting_external_attendees"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Minutes supporting PIC migration requires PostgreSQL or SQLite")

    op.add_column(
        "minutes_decisions",
        sa.Column("supporting_pic_suggestion", sa.String(length=2_000), nullable=True),
    )
    if dialect == "postgresql":
        op.create_check_constraint(
            "ck_minutes_decisions_supporting_pic_suggestion_length",
            "minutes_decisions",
            "supporting_pic_suggestion IS NULL OR length(supporting_pic_suggestion) <= 2000",
        )
    else:
        op.execute(
            """
            CREATE TRIGGER trg_minutes_decisions_supporting_pic_length_insert
            BEFORE INSERT ON minutes_decisions
            WHEN NEW.supporting_pic_suggestion IS NOT NULL
              AND length(NEW.supporting_pic_suggestion) > 2000
            BEGIN
                SELECT RAISE(ABORT, 'Supporting PIC suggestion exceeds 2000 characters');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_minutes_decisions_supporting_pic_length_update
            BEFORE UPDATE ON minutes_decisions
            WHEN NEW.supporting_pic_suggestion IS NOT NULL
              AND length(NEW.supporting_pic_suggestion) > 2000
            BEGIN
                SELECT RAISE(ABORT, 'Supporting PIC suggestion exceeds 2000 characters');
            END
            """
        )


def downgrade() -> None:
    connection = op.get_bind()
    populated_values = connection.execute(
        sa.text(
            "SELECT count(*) FROM minutes_decisions WHERE supporting_pic_suggestion IS NOT NULL"
        )
    ).scalar_one()
    if populated_values:
        raise RuntimeError("Cannot downgrade while supporting PIC suggestions are stored")

    if connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER trg_minutes_decisions_supporting_pic_length_insert")
        op.execute("DROP TRIGGER trg_minutes_decisions_supporting_pic_length_update")
    else:
        op.drop_constraint(
            "ck_minutes_decisions_supporting_pic_suggestion_length",
            "minutes_decisions",
            type_="check",
        )
    op.drop_column("minutes_decisions", "supporting_pic_suggestion")
