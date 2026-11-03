"""Add immutable, revision-bound Decision Brief versions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_decision_brief"
down_revision: str | None = "0006_structured_minutes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _drop_minutes_decision_guards_for_sqlite_batch()
    with op.batch_alter_table("minutes_decisions") as batch_op:
        batch_op.create_unique_constraint(
            "uq_minutes_decisions_revision_id",
            ["meeting_id", "minutes_revision_id", "id"],
        )
    _restore_minutes_decision_guards_for_sqlite_batch()
    op.create_table(
        "decision_brief_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("source_minutes_revision_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("version_number > 0", name="ck_decision_brief_versions_number_positive"),
        sa.CheckConstraint(
            "length(trim(summary)) > 0 AND length(summary) <= 100000",
            name="ck_decision_brief_versions_summary",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(notes) <= 20000",
            name="ck_decision_brief_versions_notes",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id"],
            ["minutes_revisions.meeting_id", "minutes_revisions.id"],
            name="fk_decision_brief_versions_source_revision_same_meeting",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_decision_brief_versions_created_by_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meeting_id", "version_number", name="uq_decision_brief_versions_meeting_number"
        ),
        sa.UniqueConstraint(
            "meeting_id",
            "id",
            "source_minutes_revision_id",
            name="uq_decision_brief_versions_meeting_id_source",
        ),
    )
    op.create_index(
        "ix_decision_brief_versions_meeting_created",
        "decision_brief_versions",
        ["meeting_id", "version_number"],
    )
    op.create_table(
        "decision_brief_decisions",
        sa.Column("brief_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_decision_id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("source_minutes_revision_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(length=100), nullable=False),
        sa.Column("editorial_note", sa.Text(), nullable=True),
        sa.CheckConstraint("position > 0", name="ck_decision_brief_decisions_position_positive"),
        sa.CheckConstraint(
            "length(trim(priority)) > 0 AND length(priority) <= 100",
            name="ck_decision_brief_decisions_priority",
        ),
        sa.CheckConstraint(
            "editorial_note IS NULL OR length(editorial_note) <= 4000",
            name="ck_decision_brief_decisions_editorial_note",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "brief_version_id", "source_minutes_revision_id"],
            [
                "decision_brief_versions.meeting_id",
                "decision_brief_versions.id",
                "decision_brief_versions.source_minutes_revision_id",
            ],
            name="fk_decision_brief_decisions_version_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id", "source_decision_id"],
            [
                "minutes_decisions.meeting_id",
                "minutes_decisions.minutes_revision_id",
                "minutes_decisions.id",
            ],
            name="fk_decision_brief_decisions_exact_source_decision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("brief_version_id", "source_decision_id"),
        sa.UniqueConstraint(
            "brief_version_id", "position", name="uq_decision_brief_decisions_position"
        ),
    )
    _create_immutability_guards()


def downgrade() -> None:
    connection = op.get_bind()
    version_count = connection.execute(
        sa.text("SELECT count(*) FROM decision_brief_versions")
    ).scalar_one()
    if version_count:
        raise RuntimeError("Cannot downgrade while Decision Brief version history contains records")

    _drop_immutability_guards()
    op.drop_table("decision_brief_decisions")
    op.drop_index(
        "ix_decision_brief_versions_meeting_created", table_name="decision_brief_versions"
    )
    op.drop_table("decision_brief_versions")
    _drop_minutes_decision_guards_for_sqlite_batch()
    with op.batch_alter_table("minutes_decisions") as batch_op:
        batch_op.drop_constraint("uq_minutes_decisions_revision_id", type_="unique")
    _restore_minutes_decision_guards_for_sqlite_batch()


def _create_immutability_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    table_names = ("decision_brief_versions", "decision_brief_decisions")
    if dialect_name == "postgresql":
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
                "BEGIN SELECT RAISE(ABORT, 'decision brief versions are append-only'); END"
            )
            op.execute(
                f"CREATE TRIGGER trg_{table_name}_no_delete BEFORE DELETE ON {table_name} "
                "BEGIN SELECT RAISE(ABORT, 'decision brief versions are append-only'); END"
            )
    else:
        raise RuntimeError(f"Unsupported database dialect for Decision Briefs: {dialect_name}")


def _drop_immutability_guards() -> None:
    dialect_name = op.get_bind().dialect.name
    table_names = ("decision_brief_versions", "decision_brief_decisions")
    if dialect_name == "postgresql":
        for table_name in table_names:
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_no_truncate ON {table_name}")
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_append_only ON {table_name}")
    elif dialect_name == "sqlite":
        for table_name in table_names:
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_no_update")
            # The identifiers come only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table_name}_no_delete")


def _drop_minutes_decision_guards_for_sqlite_batch() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER trg_minutes_decisions_no_update")
        op.execute("DROP TRIGGER trg_minutes_decisions_no_delete")


def _restore_minutes_decision_guards_for_sqlite_batch() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_minutes_decisions_no_update BEFORE UPDATE ON minutes_decisions "
            "BEGIN SELECT RAISE(ABORT, 'minutes snapshots are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_minutes_decisions_no_delete BEFORE DELETE ON minutes_decisions "
            "BEGIN SELECT RAISE(ABORT, 'minutes snapshots are append-only'); END"
        )
