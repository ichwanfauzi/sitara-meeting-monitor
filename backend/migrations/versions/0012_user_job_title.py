"""Store user job titles separately from organization units."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_user_job_title"
down_revision: str | None = "0011_evidence_scan_quarantine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("job_title", sa.String(length=200), nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    populated_titles = connection.execute(
        sa.text("SELECT count(*) FROM users WHERE job_title IS NOT NULL")
    ).scalar_one()
    if populated_titles:
        raise RuntimeError("Cannot downgrade user job titles while provisioned titles exist")
    op.drop_column("users", "job_title")
