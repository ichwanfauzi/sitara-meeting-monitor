"""Add immutable agenda-structured minutes snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_structured_minutes"
down_revision: str | None = "0005_versioned_minutes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _drop_legacy_minutes_revision_guards()

    with op.batch_alter_table("minutes_revisions") as batch_op:
        batch_op.drop_constraint("ck_minutes_revisions_content_not_blank", type_="check")
        batch_op.drop_constraint("ck_minutes_revisions_content_size", type_="check")
        batch_op.add_column(
            sa.Column("format_version", sa.Integer(), server_default=sa.text("1"), nullable=False)
        )
        batch_op.alter_column("content", existing_type=sa.Text(), nullable=True)
        batch_op.create_check_constraint(
            "ck_minutes_revisions_format_version", "format_version IN (1, 2)"
        )
        batch_op.create_check_constraint(
            "ck_minutes_revisions_content_by_format",
            "(format_version = 1 AND content IS NOT NULL AND length(trim(content)) > 0 "
            "AND length(content) <= 1000000) OR "
            "(format_version = 2 AND content IS NULL)",
        )

    with op.batch_alter_table("agendas") as batch_op:
        batch_op.create_unique_constraint("uq_agendas_meeting_id", ["meeting_id", "id"])

    op.create_table(
        "minutes_discussions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("minutes_revision_id", sa.Uuid(), nullable=False),
        sa.Column("agenda_id", sa.Uuid(), nullable=False),
        sa.Column("discussion_number", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint("discussion_number > 0", name="ck_minutes_discussions_number_positive"),
        sa.CheckConstraint(
            "length(trim(content)) > 0 AND length(content) <= 100000",
            name="ck_minutes_discussions_content",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "minutes_revision_id"],
            ["minutes_revisions.meeting_id", "minutes_revisions.id"],
            name="fk_minutes_discussions_revision_same_meeting",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "agenda_id"],
            ["agendas.meeting_id", "agendas.id"],
            name="fk_minutes_discussions_agenda_same_meeting",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "minutes_revision_id",
            "agenda_id",
            "discussion_number",
            name="uq_minutes_discussions_revision_agenda_number",
        ),
        sa.UniqueConstraint(
            "meeting_id",
            "minutes_revision_id",
            "id",
            name="uq_minutes_discussions_revision_id",
        ),
    )
    op.create_table(
        "minutes_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("minutes_revision_id", sa.Uuid(), nullable=False),
        sa.Column("discussion_id", sa.Uuid(), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("decision_text", sa.Text(), nullable=False),
        sa.Column("output_expected", sa.Text(), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("is_action_item", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint("decision_number > 0", name="ck_minutes_decisions_number_positive"),
        sa.CheckConstraint(
            "length(trim(decision_text)) > 0 AND length(decision_text) <= 20000",
            name="ck_minutes_decisions_text",
        ),
        sa.CheckConstraint(
            "output_expected IS NULL OR length(output_expected) <= 20000",
            name="ck_minutes_decisions_output_expected",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "minutes_revision_id", "discussion_id"],
            [
                "minutes_discussions.meeting_id",
                "minutes_discussions.minutes_revision_id",
                "minutes_discussions.id",
            ],
            name="fk_minutes_decisions_discussion_same_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "minutes_revision_id",
            "discussion_id",
            "decision_number",
            name="uq_minutes_decisions_discussion_number",
        ),
    )

    _create_minutes_snapshot_guards()


def downgrade() -> None:
    structured_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM minutes_revisions WHERE format_version = 2"))
        .scalar_one()
    )
    if structured_count:
        raise RuntimeError(
            "Cannot downgrade structured minutes while format_version=2 snapshots exist"
        )

    _drop_minutes_snapshot_guards()
    op.drop_table("minutes_decisions")
    op.drop_table("minutes_discussions")

    with op.batch_alter_table("agendas") as batch_op:
        batch_op.drop_constraint("uq_agendas_meeting_id", type_="unique")

    with op.batch_alter_table("minutes_revisions") as batch_op:
        batch_op.drop_constraint("ck_minutes_revisions_content_by_format", type_="check")
        batch_op.drop_constraint("ck_minutes_revisions_format_version", type_="check")
        batch_op.drop_column("format_version")
        batch_op.alter_column("content", existing_type=sa.Text(), nullable=False)
        batch_op.create_check_constraint(
            "ck_minutes_revisions_content_not_blank", "length(trim(content)) > 0"
        )
        batch_op.create_check_constraint(
            "ck_minutes_revisions_content_size", "length(content) <= 1000000"
        )

    _create_legacy_minutes_revision_guards()


def _create_minutes_snapshot_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    table_names = ("minutes_revisions", "minutes_discussions", "minutes_decisions")
    if dialect_name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_minutes_snapshot_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'minutes snapshots are append-only';
            END;
            $$
            """
        )
        for table_name in table_names:
            op.execute(
                f"CREATE TRIGGER trg_{table_name}_append_only "
                f"BEFORE UPDATE OR DELETE ON {table_name} "
                "FOR EACH ROW EXECUTE FUNCTION reject_minutes_snapshot_mutation()"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table_name}_no_truncate "
                f"BEFORE TRUNCATE ON {table_name} "
                "FOR EACH STATEMENT EXECUTE FUNCTION reject_minutes_snapshot_mutation()"
            )
    elif dialect_name == "sqlite":
        for table_name in table_names:
            op.execute(
                f"CREATE TRIGGER trg_{table_name}_no_update BEFORE UPDATE ON {table_name} "
                "BEGIN SELECT RAISE(ABORT, 'minutes snapshots are append-only'); END"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table_name}_no_delete BEFORE DELETE ON {table_name} "
                "BEGIN SELECT RAISE(ABORT, 'minutes snapshots are append-only'); END"
            )
    else:
        raise RuntimeError(f"Unsupported database dialect for minutes snapshots: {dialect_name}")


def _drop_minutes_snapshot_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    table_names = ("minutes_revisions", "minutes_discussions", "minutes_decisions")
    if dialect_name == "postgresql":
        for table_name in table_names:
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_no_truncate ON {table_name}")
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
        op.execute("DROP FUNCTION reject_minutes_snapshot_mutation()")
    elif dialect_name == "sqlite":
        for table_name in table_names:
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_no_update")
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_no_delete")


def _drop_legacy_minutes_revision_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute("DROP TRIGGER trg_minutes_revisions_no_truncate ON minutes_revisions")
        op.execute("DROP TRIGGER trg_minutes_revisions_append_only ON minutes_revisions")
        op.execute("DROP FUNCTION reject_minutes_revision_mutation()")
    elif dialect_name == "sqlite":
        op.execute("DROP TRIGGER trg_minutes_revisions_no_update")
        op.execute("DROP TRIGGER trg_minutes_revisions_no_delete")


def _create_legacy_minutes_revision_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_minutes_revision_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'minutes revisions are append-only';
            END;
            $$
            """
        )
        op.execute(
            "CREATE TRIGGER trg_minutes_revisions_append_only "
            "BEFORE UPDATE OR DELETE ON minutes_revisions "
            "FOR EACH ROW EXECUTE FUNCTION reject_minutes_revision_mutation()"
        )
        op.execute(
            "CREATE TRIGGER trg_minutes_revisions_no_truncate "
            "BEFORE TRUNCATE ON minutes_revisions "
            "FOR EACH STATEMENT EXECUTE FUNCTION reject_minutes_revision_mutation()"
        )
    elif dialect_name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_minutes_revisions_no_update BEFORE UPDATE ON minutes_revisions "
            "BEGIN SELECT RAISE(ABORT, 'minutes revisions are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_minutes_revisions_no_delete BEFORE DELETE ON minutes_revisions "
            "BEGIN SELECT RAISE(ABORT, 'minutes revisions are append-only'); END"
        )
