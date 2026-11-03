"""Add provenance-bound Action Items and auditable task histories."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_action_items"
down_revision: str | None = "0008_organization_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_VALUES = "'BELUM_DIMULAI', 'BERPROSES', 'TERKENDALA', 'MENUNGGU_ACC', 'SELESAI'"


def upgrade() -> None:
    op.create_table(
        "action_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("meeting_id", sa.Uuid(), nullable=False),
        sa.Column("source_minutes_revision_id", sa.Uuid(), nullable=False),
        sa.Column("source_decision_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("output_expected", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("priority", sa.String(length=100), nullable=False),
        sa.Column("official_status", sa.String(length=30), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"official_status IN ({_STATUS_VALUES})", name="ck_action_items_official_status"
        ),
        sa.CheckConstraint("version > 0", name="ck_action_items_version_positive"),
        sa.CheckConstraint(
            "(official_status = 'SELESAI' AND completed_at IS NOT NULL) OR "
            "(official_status <> 'SELESAI' AND completed_at IS NULL)",
            name="ck_action_items_completed_at_status",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0 AND length(title) <= 300", name="ck_action_items_title"
        ),
        sa.CheckConstraint(
            "length(trim(description)) > 0 AND length(description) <= 20000",
            name="ck_action_items_description",
        ),
        sa.CheckConstraint(
            "output_expected IS NULL OR length(output_expected) <= 20000",
            name="ck_action_items_output_expected",
        ),
        sa.CheckConstraint(
            "length(trim(priority)) > 0 AND length(priority) <= 100",
            name="ck_action_items_priority",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id", "source_decision_id"],
            [
                "minutes_decisions.meeting_id",
                "minutes_decisions.minutes_revision_id",
                "minutes_decisions.id",
            ],
            name="fk_action_items_exact_source_decision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_action_items_created_by_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_action_items_meeting_status", "action_items", ["meeting_id", "official_status"]
    )
    op.create_index(
        "ix_action_items_source_revision",
        "action_items",
        ["meeting_id", "source_minutes_revision_id"],
    )

    op.create_table(
        "assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_role", sa.String(length=20), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("assignment_reason", sa.Text(), nullable=True),
        sa.Column("end_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("assignment_role IN ('MAIN', 'SUPPORTING')", name="ck_assignments_role"),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ck_assignments_end_after_start"
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL AND ended_by_user_id IS NULL AND end_reason IS NULL) OR "
            "(ended_at IS NOT NULL AND ended_by_user_id IS NOT NULL AND end_reason IS NOT NULL "
            "AND length(trim(end_reason)) > 0)",
            name="ck_assignments_end_metadata",
        ),
        sa.CheckConstraint(
            "assignment_reason IS NULL OR length(assignment_reason) <= 4000",
            name="ck_assignments_reason_length",
        ),
        sa.CheckConstraint(
            "end_reason IS NULL OR length(end_reason) <= 4000",
            name="ck_assignments_end_reason_length",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_assignments_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["users.id"],
            name="fk_assignments_assignee_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["users.id"],
            name="fk_assignments_assigned_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ended_by_user_id"],
            ["users.id"],
            name="fk_assignments_ended_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_item_id", "id", name="uq_assignments_action_item_id"),
        sa.UniqueConstraint(
            "action_item_id", "id", "assignee_user_id", name="uq_assignments_actor_reference"
        ),
    )
    op.create_index(
        "uq_assignments_one_active_main",
        "assignments",
        ["action_item_id"],
        unique=True,
        postgresql_where=sa.text("assignment_role = 'MAIN' AND ended_at IS NULL"),
        sqlite_where=sa.text("assignment_role = 'MAIN' AND ended_at IS NULL"),
    )
    op.create_index(
        "uq_assignments_one_active_role_per_user",
        "assignments",
        ["action_item_id", "assignee_user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
        sqlite_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "ix_assignments_assignee_active", "assignments", ["assignee_user_id", "ended_at"]
    )

    op.create_table(
        "progress_updates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("report_text", sa.Text(), nullable=True),
        sa.Column("blocker_text", sa.Text(), nullable=True),
        sa.Column("progress_percent", sa.SmallInteger(), nullable=True),
        sa.Column("completion_requested", sa.Boolean(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100",
            name="ck_progress_updates_percent",
        ),
        sa.CheckConstraint(
            "(report_text IS NOT NULL AND length(trim(report_text)) > 0) OR "
            "(blocker_text IS NOT NULL AND length(trim(blocker_text)) > 0) OR "
            "progress_percent IS NOT NULL OR completion_requested",
            name="ck_progress_updates_has_report",
        ),
        sa.CheckConstraint(
            "report_text IS NULL OR length(report_text) <= 20000",
            name="ck_progress_updates_report_length",
        ),
        sa.CheckConstraint(
            "blocker_text IS NULL OR length(blocker_text) <= 20000",
            name="ck_progress_updates_blocker_length",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_progress_updates_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id", "assignment_id", "actor_user_id"],
            ["assignments.action_item_id", "assignments.id", "assignments.assignee_user_id"],
            name="fk_progress_updates_current_assignment_actor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_progress_updates_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_item_id", "id", name="uq_progress_updates_action_item_id"),
    )
    op.create_index(
        "ix_progress_updates_action_item_time",
        "progress_updates",
        ["action_item_id", "submitted_at"],
    )

    op.create_table(
        "completion_verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("progress_update_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('VERIFIED', 'NEEDS_REVISION')", name="ck_completion_verifications_outcome"
        ),
        sa.CheckConstraint(
            "review_note IS NULL OR length(review_note) <= 4000",
            name="ck_completion_verifications_note_length",
        ),
        sa.CheckConstraint(
            "outcome <> 'NEEDS_REVISION' OR "
            "(review_note IS NOT NULL AND length(trim(review_note)) > 0)",
            name="ck_completion_verifications_revision_note",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_completion_verifications_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id", "progress_update_id"],
            ["progress_updates.action_item_id", "progress_updates.id"],
            name="fk_completion_verifications_progress_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name="fk_completion_verifications_reviewer_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "action_item_id", "id", name="uq_completion_verifications_action_item_id"
        ),
        sa.UniqueConstraint(
            "action_item_id", "progress_update_id", name="uq_completion_verifications_report"
        ),
    )
    op.create_index(
        "ix_completion_verifications_task_time",
        "completion_verifications",
        ["action_item_id", "reviewed_at"],
    )

    op.create_table(
        "status_histories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("action_item_id", sa.Uuid(), nullable=False),
        sa.Column("event_number", sa.Integer(), nullable=False),
        sa.Column("old_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("changed_by_id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("event_number > 0", name="ck_status_histories_event_number_positive"),
        sa.CheckConstraint(
            f"old_status IS NULL OR old_status IN ({_STATUS_VALUES})",
            name="ck_status_histories_old_status",
        ),
        sa.CheckConstraint(
            f"new_status IN ({_STATUS_VALUES})", name="ck_status_histories_new_status"
        ),
        sa.CheckConstraint(
            "old_status IS NULL OR old_status <> new_status",
            name="ck_status_histories_status_changed",
        ),
        sa.CheckConstraint(
            "old_status IS NOT NULL OR new_status = 'BELUM_DIMULAI'",
            name="ck_status_histories_initial_status",
        ),
        sa.CheckConstraint(
            "new_status <> 'SELESAI' OR verification_id IS NOT NULL",
            name="ck_status_histories_completion_verification_required",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_status_histories_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id", "verification_id"],
            ["completion_verifications.action_item_id", "completion_verifications.id"],
            name="fk_status_histories_verification_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_id"],
            ["users.id"],
            name="fk_status_histories_changed_by_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "action_item_id", "event_number", name="uq_status_histories_task_event"
        ),
    )
    op.create_index(
        "ix_status_histories_task_time", "status_histories", ["action_item_id", "changed_at"]
    )

    _create_integrity_guards()


def downgrade() -> None:
    connection = op.get_bind()
    table_names = (
        "action_items",
        "assignments",
        "progress_updates",
        "completion_verifications",
        "status_histories",
    )
    populated = [
        name
        for name in table_names
        # The table name comes only from the fixed migration tuple above.
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        if connection.execute(sa.text(f"SELECT count(*) FROM {name}")).scalar_one()
    ]
    if populated:
        raise RuntimeError(
            "Cannot downgrade while Action Item history contains records: " + ", ".join(populated)
        )

    _drop_integrity_guards()
    op.drop_index("ix_status_histories_task_time", table_name="status_histories")
    op.drop_table("status_histories")
    op.drop_index("ix_completion_verifications_task_time", table_name="completion_verifications")
    op.drop_table("completion_verifications")
    op.drop_index("ix_progress_updates_action_item_time", table_name="progress_updates")
    op.drop_table("progress_updates")
    op.drop_index("ix_assignments_assignee_active", table_name="assignments")
    op.drop_index("uq_assignments_one_active_role_per_user", table_name="assignments")
    op.drop_index("uq_assignments_one_active_main", table_name="assignments")
    op.drop_table("assignments")
    op.drop_index("ix_action_items_source_revision", table_name="action_items")
    op.drop_index("ix_action_items_meeting_status", table_name="action_items")
    op.drop_table("action_items")


def _create_integrity_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_action_item_history_mutation()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Action Item history is append-only';
            END;
            $$
            """
        )
        for table in ("progress_updates", "completion_verifications", "status_histories"):
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_action_item_history_mutation()
                """
            )
        op.execute(
            """
            CREATE FUNCTION guard_action_item_write()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE actionable boolean;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Action Items cannot be deleted';
                END IF;
                IF TG_OP = 'INSERT' THEN
                    IF NEW.official_status <> 'BELUM_DIMULAI' THEN
                        RAISE EXCEPTION 'Action Items must start at BELUM_DIMULAI';
                    END IF;
                    SELECT is_action_item INTO actionable
                    FROM minutes_decisions
                    WHERE meeting_id = NEW.meeting_id
                      AND minutes_revision_id = NEW.source_minutes_revision_id
                      AND id = NEW.source_decision_id;
                    IF actionable IS DISTINCT FROM TRUE THEN
                        RAISE EXCEPTION 'Source decision is not actionable';
                    END IF;
                    RETURN NEW;
                END IF;
                IF NEW.meeting_id IS DISTINCT FROM OLD.meeting_id
                   OR NEW.source_minutes_revision_id IS DISTINCT FROM OLD.source_minutes_revision_id
                   OR NEW.source_decision_id IS DISTINCT FROM OLD.source_decision_id
                   OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'Action Item source and creation provenance are immutable';
                END IF;
                IF NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION 'Action Item version must advance by one';
                END IF;
                IF NEW.official_status IS DISTINCT FROM OLD.official_status THEN
                    IF NEW.completed_at IS NULL AND NEW.official_status = 'SELESAI' THEN
                        RAISE EXCEPTION 'SELESAI requires a verified completion';
                    END IF;
                    IF NEW.official_status <> 'SELESAI' AND NEW.completed_at IS NOT NULL THEN
                        RAISE EXCEPTION 'completed_at must be cleared when task is reopened';
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1
                        FROM status_histories h
                        WHERE h.action_item_id = OLD.id
                          AND h.old_status = OLD.official_status
                          AND h.new_status = NEW.official_status
                          AND h.event_number = (
                              SELECT max(event_number)
                              FROM status_histories
                              WHERE action_item_id = OLD.id
                          )
                    ) THEN
                        RAISE EXCEPTION 'Status change requires a matching status history record';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_action_items_guard
            BEFORE INSERT OR UPDATE OR DELETE ON action_items
            FOR EACH ROW EXECUTE FUNCTION guard_action_item_write()
            """
        )
        op.execute(
            """
            CREATE FUNCTION guard_assignment_history()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'Assignment history cannot be deleted';
                END IF;
                IF OLD.ended_at IS NOT NULL
                   OR NEW.action_item_id IS DISTINCT FROM OLD.action_item_id
                   OR NEW.assignee_user_id IS DISTINCT FROM OLD.assignee_user_id
                   OR NEW.assigned_by_user_id IS DISTINCT FROM OLD.assigned_by_user_id
                   OR NEW.assignment_role IS DISTINCT FROM OLD.assignment_role
                   OR NEW.started_at IS DISTINCT FROM OLD.started_at
                   OR NEW.assignment_reason IS DISTINCT FROM OLD.assignment_reason
                   OR NEW.ended_at IS NULL
                   OR NEW.ended_by_user_id IS NULL
                   OR NEW.end_reason IS NULL
                   OR length(trim(NEW.end_reason)) = 0 THEN
                    RAISE EXCEPTION 'Assignment history is immutable';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_assignments_history_guard
            BEFORE UPDATE OR DELETE ON assignments
            FOR EACH ROW EXECUTE FUNCTION guard_assignment_history()
            """
        )
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
        op.execute(
            """
            CREATE FUNCTION guard_completion_verification()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM progress_updates p
                    WHERE p.action_item_id = NEW.action_item_id
                      AND p.id = NEW.progress_update_id
                      AND p.completion_requested
                ) THEN
                    RAISE EXCEPTION 'Completion review requires a completion request';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_completion_verifications_report
            BEFORE INSERT ON completion_verifications
            FOR EACH ROW EXECUTE FUNCTION guard_completion_verification()
            """
        )
        op.execute(
            """
            CREATE FUNCTION guard_status_history()
            RETURNS trigger
            LANGUAGE plpgsql AS $$
            DECLARE
                current_status text;
                last_event integer;
                verified boolean;
            BEGIN
                SELECT official_status INTO current_status
                FROM action_items
                WHERE id = NEW.action_item_id
                FOR UPDATE;
                SELECT coalesce(max(event_number), 0) INTO last_event
                FROM status_histories
                WHERE action_item_id = NEW.action_item_id;
                IF NEW.event_number <> last_event + 1 THEN
                    RAISE EXCEPTION 'Status history event sequence is invalid';
                END IF;
                IF last_event = 0 THEN
                    IF NEW.old_status IS NOT NULL OR NEW.new_status <> 'BELUM_DIMULAI' THEN
                        RAISE EXCEPTION 'First Action Item status must be BELUM_DIMULAI';
                    END IF;
                ELSIF NEW.old_status IS DISTINCT FROM current_status THEN
                    RAISE EXCEPTION 'Status history does not match current Action Item status';
                END IF;
                IF NEW.new_status = 'SELESAI' THEN
                    SELECT outcome = 'VERIFIED' INTO verified
                    FROM completion_verifications
                    WHERE action_item_id = NEW.action_item_id
                      AND id = NEW.verification_id;
                    IF verified IS DISTINCT FROM TRUE THEN
                        RAISE EXCEPTION 'SELESAI requires verified completion';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_status_histories_guard
            BEFORE INSERT ON status_histories
            FOR EACH ROW EXECUTE FUNCTION guard_status_history()
            """
        )
        for table in (
            "action_items",
            "assignments",
            "progress_updates",
            "completion_verifications",
            "status_histories",
        ):
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_truncate
                BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION reject_action_item_history_mutation()
                """
            )
    elif dialect == "sqlite":
        for table in ("progress_updates", "completion_verifications", "status_histories"):
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'Action Item history is append-only');
                END
                """
            )
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_no_delete
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'Action Item history is append-only');
                END
                """
            )
        op.execute(
            """
            CREATE TRIGGER trg_action_items_insert_guard
            BEFORE INSERT ON action_items
            BEGIN
                SELECT CASE WHEN NEW.official_status <> 'BELUM_DIMULAI'
                    THEN RAISE(ABORT, 'Action Items must start at BELUM_DIMULAI') END;
                SELECT CASE WHEN COALESCE((
                    SELECT is_action_item
                    FROM minutes_decisions
                    WHERE meeting_id = NEW.meeting_id
                      AND minutes_revision_id = NEW.source_minutes_revision_id
                      AND id = NEW.source_decision_id
                ), 0) <> 1
                    THEN RAISE(ABORT, 'Source decision is not actionable') END;
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_action_items_update_guard
            BEFORE UPDATE ON action_items
            BEGIN
                SELECT CASE WHEN NEW.meeting_id IS NOT OLD.meeting_id
                    OR NEW.source_minutes_revision_id IS NOT OLD.source_minutes_revision_id
                    OR NEW.source_decision_id IS NOT OLD.source_decision_id
                    OR NEW.created_by_id IS NOT OLD.created_by_id
                    OR NEW.created_at IS NOT OLD.created_at
                    THEN RAISE(
                        ABORT, 'Action Item source and creation provenance are immutable'
                    ) END;
                SELECT CASE WHEN NEW.version <> OLD.version + 1
                    THEN RAISE(ABORT, 'Action Item version must advance by one') END;
                SELECT CASE WHEN NEW.official_status IS NOT OLD.official_status AND NOT EXISTS (
                    SELECT 1
                    FROM status_histories h
                    WHERE h.action_item_id = OLD.id
                      AND h.old_status IS OLD.official_status
                      AND h.new_status = NEW.official_status
                      AND h.event_number = (
                          SELECT max(event_number)
                          FROM status_histories
                          WHERE action_item_id = OLD.id
                      )
                )
                    THEN RAISE(
                        ABORT, 'Status change requires a matching status history record'
                    ) END;
                SELECT CASE WHEN NEW.official_status = 'SELESAI' AND NEW.completed_at IS NULL
                    THEN RAISE(ABORT, 'SELESAI requires a verified completion') END;
                SELECT CASE WHEN NEW.official_status <> 'SELESAI' AND NEW.completed_at IS NOT NULL
                    THEN RAISE(ABORT, 'completed_at must be cleared when task is reopened') END;
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_action_items_no_delete
            BEFORE DELETE ON action_items
            BEGIN
                SELECT RAISE(ABORT, 'Action Items cannot be deleted');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_assignments_update_guard
            BEFORE UPDATE ON assignments
            BEGIN
                SELECT CASE WHEN OLD.ended_at IS NOT NULL
                    OR NEW.action_item_id IS NOT OLD.action_item_id
                    OR NEW.assignee_user_id IS NOT OLD.assignee_user_id
                    OR NEW.assigned_by_user_id IS NOT OLD.assigned_by_user_id
                    OR NEW.assignment_role IS NOT OLD.assignment_role
                    OR NEW.started_at IS NOT OLD.started_at
                    OR NEW.assignment_reason IS NOT OLD.assignment_reason
                    OR NEW.ended_at IS NULL
                    OR NEW.ended_by_user_id IS NULL
                    OR NEW.end_reason IS NULL
                    OR length(trim(NEW.end_reason)) = 0
                    THEN RAISE(ABORT, 'Assignment history is immutable') END;
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_assignments_no_delete
            BEFORE DELETE ON assignments
            BEGIN
                SELECT RAISE(ABORT, 'Assignment history cannot be deleted');
            END
            """
        )
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
        op.execute(
            """
            CREATE TRIGGER trg_status_histories_guard
            BEFORE INSERT ON status_histories
            BEGIN
                SELECT CASE WHEN NEW.event_number <> COALESCE((
                    SELECT max(event_number) + 1
                    FROM status_histories
                    WHERE action_item_id = NEW.action_item_id
                ), 1) THEN RAISE(ABORT, 'Status history event sequence is invalid') END;
                SELECT CASE WHEN NEW.old_status IS NULL AND NEW.new_status <> 'BELUM_DIMULAI'
                    THEN RAISE(ABORT, 'First Action Item status must be BELUM_DIMULAI') END;
                SELECT CASE WHEN NEW.old_status IS NOT NULL AND NEW.old_status IS NOT (
                    SELECT official_status
                    FROM action_items
                    WHERE id = NEW.action_item_id
                ) THEN RAISE(ABORT, 'Status history does not match current Action Item status') END;
                SELECT CASE WHEN NEW.new_status = 'SELESAI' AND COALESCE((
                    SELECT outcome
                    FROM completion_verifications
                    WHERE action_item_id = NEW.action_item_id
                      AND id = NEW.verification_id
                ), '') <> 'VERIFIED'
                    THEN RAISE(ABORT, 'SELESAI requires verified completion') END;
            END
            """
        )
    else:
        raise RuntimeError(f"Unsupported database dialect for Action Items: {dialect}")


def _drop_integrity_guards() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in (
            "action_items",
            "assignments",
            "progress_updates",
            "completion_verifications",
            "status_histories",
        ):
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table}_no_truncate ON {table}")
        op.execute("DROP TRIGGER trg_status_histories_guard ON status_histories")
        op.execute("DROP TRIGGER trg_completion_verifications_report ON completion_verifications")
        op.execute("DROP TRIGGER trg_progress_updates_assignment ON progress_updates")
        op.execute("DROP TRIGGER trg_assignments_history_guard ON assignments")
        op.execute("DROP TRIGGER trg_action_items_guard ON action_items")
        op.execute("DROP FUNCTION guard_status_history()")
        op.execute("DROP FUNCTION guard_completion_verification()")
        op.execute("DROP FUNCTION guard_progress_assignment()")
        op.execute("DROP FUNCTION guard_assignment_history()")
        op.execute("DROP FUNCTION guard_action_item_write()")
        for table in ("progress_updates", "completion_verifications", "status_histories"):
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table}_append_only ON {table}")
        op.execute("DROP FUNCTION reject_action_item_history_mutation()")
    elif dialect == "sqlite":
        for trigger in (
            "trg_status_histories_guard",
            "trg_completion_verifications_report",
            "trg_progress_updates_assignment",
            "trg_assignments_no_delete",
            "trg_assignments_update_guard",
            "trg_action_items_no_delete",
            "trg_action_items_update_guard",
            "trg_action_items_insert_guard",
        ):
            # The trigger name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER {trigger}")
        for table in ("progress_updates", "completion_verifications", "status_histories"):
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table}_no_delete")
            # The table name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER trg_{table}_no_update")
