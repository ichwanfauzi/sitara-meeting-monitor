"""Allow leadership progress and add private Action Item evidence metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_action_item_evidence"
down_revision: str | None = "0009_action_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVIDENCE_TYPES = (
    "'application/pdf', 'image/jpeg', 'image/png', 'image/heic', 'image/heif', "
    "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', "
    "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', "
    "'application/vnd.openxmlformats-officedocument.presentationml.presentation', "
    "'text/csv', 'text/plain'"
)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER trg_progress_updates_assignment ON progress_updates")
        op.execute("DROP FUNCTION guard_progress_assignment()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER trg_completion_verifications_report")

    with op.batch_alter_table("progress_updates") as batch_op:
        batch_op.drop_constraint("fk_progress_updates_current_assignment_actor", type_="foreignkey")
        batch_op.alter_column(
            "assignment_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("submitted_as", sa.String(length=20), server_default="PIC", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_progress_updates_submission_context",
            "(submitted_as = 'PIC' AND assignment_id IS NOT NULL) OR "
            "(submitted_as = 'LEADERSHIP' AND assignment_id IS NULL)",
        )
        batch_op.create_foreign_key(
            "fk_progress_updates_assignment_same_task",
            "assignments",
            ["action_item_id", "assignment_id"],
            ["action_item_id", "id"],
            ondelete="RESTRICT",
        )

    op.create_table(
        "action_item_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("progress_update_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_kind", sa.String(length=10), nullable=False),
        sa.Column("storage_key", sa.String(length=32), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("link_label", sa.String(length=200), nullable=True),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('FILE', 'LINK')", name="ck_action_item_evidence_kind"
        ),
        sa.CheckConstraint(
            "(evidence_kind = 'FILE' AND storage_key IS NOT NULL AND length(storage_key) = 32 "
            "AND original_filename IS NOT NULL AND content_type IS NOT NULL "
            "AND content_type IN ("
            + _EVIDENCE_TYPES
            + ") AND size_bytes IS NOT NULL AND size_bytes BETWEEN 1 AND 10485760 "
            "AND sha256 IS NOT NULL AND length(sha256) = 64 AND external_url IS NULL) OR "
            "(evidence_kind = 'LINK' AND storage_key IS NULL "
            "AND original_filename IS NULL AND content_type IS NULL "
            "AND size_bytes IS NULL AND sha256 IS NULL "
            "AND external_url IS NOT NULL AND substr(external_url, 1, 8) = 'https://')",
            name="ck_action_item_evidence_payload",
        ),
        sa.CheckConstraint(
            "link_label IS NULL OR length(link_label) BETWEEN 1 AND 200",
            name="ck_action_item_evidence_link_label",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id", "progress_update_id"],
            ["progress_updates.action_item_id", "progress_updates.id"],
            name="fk_action_item_evidence_progress_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name="fk_action_item_evidence_uploaded_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_action_item_evidence_storage_key"),
    )
    op.create_index(
        "ix_action_item_evidence_progress_time",
        "action_item_evidence",
        ["progress_update_id", "created_at"],
    )

    if dialect == "postgresql":
        _create_postgresql_guards()
    elif dialect == "sqlite":
        _create_sqlite_guards()
        _create_sqlite_completion_guard()


def _create_postgresql_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_progress_assignment()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.submitted_as = 'PIC' THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM assignments a
                    WHERE a.action_item_id = NEW.action_item_id
                      AND a.id = NEW.assignment_id
                      AND a.assignee_user_id = NEW.actor_user_id
                      AND a.ended_at IS NULL
                ) THEN
                    RAISE EXCEPTION 'PIC progress requires an active assignment';
                END IF;
            ELSIF NEW.submitted_as = 'LEADERSHIP' THEN
                IF NEW.assignment_id IS NOT NULL THEN
                    RAISE EXCEPTION 'Leadership progress cannot reference a PIC assignment';
                END IF;
            ELSE
                RAISE EXCEPTION 'Progress submitter kind is invalid';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_assignment
        BEFORE INSERT ON progress_updates
        FOR EACH ROW EXECUTE FUNCTION guard_progress_assignment()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_action_item_evidence_limit()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE evidence_count integer;
        BEGIN
            PERFORM 1
            FROM progress_updates
            WHERE id = NEW.progress_update_id
            FOR UPDATE;
            SELECT count(*) INTO evidence_count
            FROM action_item_evidence
            WHERE progress_update_id = NEW.progress_update_id;
            IF evidence_count >= 5 THEN
                RAISE EXCEPTION 'A progress update can have at most five evidence items';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_limit
        BEFORE INSERT ON action_item_evidence
        FOR EACH ROW EXECUTE FUNCTION guard_action_item_evidence_limit()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_append_only
        BEFORE UPDATE OR DELETE ON action_item_evidence
        FOR EACH ROW EXECUTE FUNCTION reject_action_item_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_no_truncate
        BEFORE TRUNCATE ON action_item_evidence
        FOR EACH STATEMENT EXECUTE FUNCTION reject_action_item_history_mutation()
        """
    )


def _create_sqlite_guards() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_assignment
        BEFORE INSERT ON progress_updates
        BEGIN
            SELECT CASE
                WHEN NEW.submitted_as = 'PIC' AND NOT EXISTS (
                    SELECT 1
                    FROM assignments a
                    WHERE a.action_item_id = NEW.action_item_id
                      AND a.id = NEW.assignment_id
                      AND a.assignee_user_id = NEW.actor_user_id
                      AND a.ended_at IS NULL
                ) THEN RAISE(ABORT, 'PIC progress requires an active assignment')
                WHEN NEW.submitted_as = 'LEADERSHIP' AND NEW.assignment_id IS NOT NULL
                    THEN RAISE(ABORT, 'Leadership progress cannot reference a PIC assignment')
                WHEN NEW.submitted_as NOT IN ('PIC', 'LEADERSHIP')
                    THEN RAISE(ABORT, 'Progress submitter kind is invalid')
            END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_no_update
        BEFORE UPDATE ON progress_updates
        BEGIN
            SELECT RAISE(ABORT, 'Action Item history is append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_no_delete
        BEFORE DELETE ON progress_updates
        BEGIN
            SELECT RAISE(ABORT, 'Action Item history is append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_limit
        BEFORE INSERT ON action_item_evidence
        BEGIN
            SELECT CASE WHEN (
                SELECT count(*)
                FROM action_item_evidence
                WHERE progress_update_id = NEW.progress_update_id
            ) >= 5 THEN RAISE(ABORT, 'A progress update can have at most five evidence items') END;
        END
        """
    )
    for operation in ("UPDATE", "DELETE"):
        # The operation comes only from this fixed migration tuple.
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
        op.execute(
            f"""
            CREATE TRIGGER trg_action_item_evidence_no_{operation.lower()}
            BEFORE {operation} ON action_item_evidence
            BEGIN
                SELECT RAISE(ABORT, 'Action Item evidence is append-only');
            END
            """
        )


def _create_sqlite_completion_guard() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_completion_verifications_report
        BEFORE INSERT ON completion_verifications
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1
                FROM progress_updates p
                WHERE p.action_item_id = NEW.action_item_id
                  AND p.id = NEW.progress_update_id
                  AND p.completion_requested = 1
            ) THEN RAISE(ABORT, 'Completion review requires a completion request') END;
        END
        """
    )


def downgrade() -> None:
    connection = op.get_bind()
    evidence_count = connection.execute(
        sa.text("SELECT count(*) FROM action_item_evidence")
    ).scalar_one()
    leadership_progress_count = connection.execute(
        sa.text("SELECT count(*) FROM progress_updates WHERE submitted_as = 'LEADERSHIP'")
    ).scalar_one()
    if evidence_count or leadership_progress_count:
        raise RuntimeError(
            "Cannot downgrade while Action Item evidence or leadership progress exists"
        )

    dialect = connection.dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER trg_action_item_evidence_no_truncate ON action_item_evidence")
        op.execute("DROP TRIGGER trg_action_item_evidence_append_only ON action_item_evidence")
        op.execute("DROP TRIGGER trg_action_item_evidence_limit ON action_item_evidence")
        op.execute("DROP FUNCTION guard_action_item_evidence_limit()")
    elif dialect == "sqlite":
        for trigger_name in (
            "trg_action_item_evidence_no_update",
            "trg_action_item_evidence_no_delete",
            "trg_action_item_evidence_limit",
        ):
            # The trigger name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER {trigger_name}")

    op.drop_index("ix_action_item_evidence_progress_time", table_name="action_item_evidence")
    op.drop_table("action_item_evidence")

    if dialect == "postgresql":
        op.execute("DROP TRIGGER trg_progress_updates_assignment ON progress_updates")
        op.execute("DROP FUNCTION guard_progress_assignment()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER trg_progress_updates_assignment")
        op.execute("DROP TRIGGER trg_completion_verifications_report")

    with op.batch_alter_table("progress_updates") as batch_op:
        batch_op.drop_constraint("fk_progress_updates_assignment_same_task", type_="foreignkey")
        batch_op.drop_constraint("ck_progress_updates_submission_context", type_="check")
        batch_op.drop_column("submitted_as")
        batch_op.alter_column(
            "assignment_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_progress_updates_current_assignment_actor",
            "assignments",
            ["action_item_id", "assignment_id", "actor_user_id"],
            ["action_item_id", "id", "assignee_user_id"],
            ondelete="RESTRICT",
        )

    if dialect == "postgresql":
        _restore_postgresql_progress_guard()
    elif dialect == "sqlite":
        _restore_sqlite_progress_guard()
        _create_sqlite_completion_guard()


def _restore_postgresql_progress_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_progress_assignment()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM assignments a
                WHERE a.action_item_id = NEW.action_item_id
                  AND a.id = NEW.assignment_id
                  AND a.assignee_user_id = NEW.actor_user_id
                  AND a.ended_at IS NULL
            ) THEN
                RAISE EXCEPTION 'Progress report requires an active assignment';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_assignment
        BEFORE INSERT ON progress_updates
        FOR EACH ROW EXECUTE FUNCTION guard_progress_assignment()
        """
    )


def _restore_sqlite_progress_guard() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_assignment
        BEFORE INSERT ON progress_updates
        BEGIN
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1
                FROM assignments a
                WHERE a.action_item_id = NEW.action_item_id
                  AND a.id = NEW.assignment_id
                  AND a.assignee_user_id = NEW.actor_user_id
                  AND a.ended_at IS NULL
            ) THEN RAISE(ABORT, 'Progress report requires an active assignment') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_no_update
        BEFORE UPDATE ON progress_updates
        BEGIN
            SELECT RAISE(ABORT, 'Action Item history is append-only');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_no_delete
        BEFORE DELETE ON progress_updates
        BEGIN
            SELECT RAISE(ABORT, 'Action Item history is append-only');
        END
        """
    )
