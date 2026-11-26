"""Store an optional PIC suggestion with each source decision."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_minutes_pic_suggestion"
down_revision: str | None = "0019_assignment_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "minutes_decisions",
        sa.Column("pic_suggestion", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    suggestion_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM minutes_decisions WHERE pic_suggestion IS NOT NULL"))
        .scalar_one()
    )
    if suggestion_count:
        raise RuntimeError("Cannot downgrade while minutes decisions have PIC suggestions")
    op.drop_column("minutes_decisions", "pic_suggestion")
