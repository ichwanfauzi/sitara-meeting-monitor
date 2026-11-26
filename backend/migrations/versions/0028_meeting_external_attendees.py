"""Store named external meeting attendees."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_meeting_external_attendees"
down_revision: str | None = "0027_brief_optional_priority"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meeting_external_participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("participant_name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(trim(participant_name)) > 0",
            name="ck_meeting_external_participants_name_not_blank",
        ),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_meeting_external_participants"),
    )
    op.create_index(
        "ix_meeting_external_participants_meeting_id",
        "meeting_external_participants",
        ["meeting_id"],
    )


def downgrade() -> None:
    attendee_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM meeting_external_participants"))
        .scalar_one()
    )
    if attendee_count:
        raise RuntimeError("Cannot downgrade while external meeting participants are recorded")

    op.drop_index(
        "ix_meeting_external_participants_meeting_id",
        table_name="meeting_external_participants",
    )
    op.drop_table("meeting_external_participants")
