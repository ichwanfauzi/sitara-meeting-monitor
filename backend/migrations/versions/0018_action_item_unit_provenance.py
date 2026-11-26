"""Record task responsibility and PIC origin units."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_action_item_unit_provenance"
down_revision: str | None = "0017_decision_brief_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_sqlite_guards(*, include_unit_provenance: bool = False) -> None:
    op.execute("DROP TRIGGER trg_action_items_insert_guard")
    op.execute("DROP TRIGGER trg_action_items_update_guard")
    op.execute("DROP TRIGGER trg_action_items_no_delete")
    op.execute("DROP TRIGGER trg_action_items_disposition_immutable")
    op.execute("DROP TRIGGER trg_status_histories_guard")
    op.execute("DROP TRIGGER trg_assignments_update_guard")
    op.execute("DROP TRIGGER trg_assignments_no_delete")
    op.execute("DROP TRIGGER trg_progress_updates_assignment")
    if include_unit_provenance:
        op.execute("DROP TRIGGER trg_assignments_pic_origin_immutable")


def _create_sqlite_action_item_guards(*, include_responsible_unit: bool) -> None:
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
                OR NEW.disposition_id IS NOT OLD.disposition_id
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
        CREATE TRIGGER trg_action_items_disposition_immutable
        BEFORE UPDATE OF disposition_id ON action_items
        WHEN NEW.disposition_id IS NOT OLD.disposition_id
        BEGIN
            SELECT RAISE(ABORT, 'Action Item disposition is immutable');
        END
        """
    )
    if include_responsible_unit:
        op.execute(
            """
            CREATE TRIGGER trg_action_items_responsible_unit_immutable
            BEFORE UPDATE OF responsible_unit_id ON action_items
            WHEN NEW.responsible_unit_id IS NOT OLD.responsible_unit_id
            BEGIN
                SELECT RAISE(ABORT, 'Action Item responsible unit is immutable');
            END
            """
        )


def _create_sqlite_assignment_guards(*, include_pic_origin_unit: bool) -> None:
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
    if include_pic_origin_unit:
        op.execute(
            """
            CREATE TRIGGER trg_assignments_pic_origin_immutable
            BEFORE UPDATE OF pic_origin_unit_id ON assignments
            WHEN NEW.pic_origin_unit_id IS NOT OLD.pic_origin_unit_id
            BEGIN
                SELECT RAISE(ABORT, 'Assignment history is immutable');
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


def _create_sqlite_status_history_guard() -> None:
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


def _create_sqlite_progress_assignment_guard() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_progress_updates_assignment
        BEFORE INSERT ON progress_updates
        BEGIN
            SELECT CASE WHEN NEW.submitted_as = 'PIC' AND NOT EXISTS (
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


def _create_postgresql_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_action_item_responsible_unit_change() RETURNS trigger AS $$
        BEGIN
            IF NEW.responsible_unit_id IS DISTINCT FROM OLD.responsible_unit_id THEN
                RAISE EXCEPTION 'Action Item responsible unit is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_items_responsible_unit_immutable
        BEFORE UPDATE OF responsible_unit_id ON action_items
        FOR EACH ROW EXECUTE FUNCTION reject_action_item_responsible_unit_change()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_assignment_pic_origin_change() RETURNS trigger AS $$
        BEGIN
            IF NEW.pic_origin_unit_id IS DISTINCT FROM OLD.pic_origin_unit_id THEN
                RAISE EXCEPTION 'Assignment PIC origin unit is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_assignments_pic_origin_immutable
        BEFORE UPDATE OF pic_origin_unit_id ON assignments
        FOR EACH ROW EXECUTE FUNCTION reject_assignment_pic_origin_change()
        """
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Action Item unit provenance migration requires PostgreSQL or SQLite")

    if dialect == "sqlite":
        _drop_sqlite_guards()

    with op.batch_alter_table(
        "action_items",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.add_column(sa.Column("responsible_unit_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_action_items_responsible_unit",
            "organization_units",
            ["responsible_unit_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table(
        "assignments",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.add_column(sa.Column("pic_origin_unit_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_assignments_pic_origin_unit",
            "organization_units",
            ["pic_origin_unit_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_action_items_responsible_unit_id", "action_items", ["responsible_unit_id"])
    op.create_index("ix_assignments_pic_origin_unit_id", "assignments", ["pic_origin_unit_id"])

    if dialect == "sqlite":
        _create_sqlite_action_item_guards(include_responsible_unit=True)
        _create_sqlite_assignment_guards(include_pic_origin_unit=True)
        _create_sqlite_status_history_guard()
        _create_sqlite_progress_assignment_guard()
    else:
        _create_postgresql_guards()


def downgrade() -> None:
    connection = op.get_bind()
    responsible_units = connection.execute(
        sa.text("SELECT count(*) FROM action_items WHERE responsible_unit_id IS NOT NULL")
    ).scalar_one()
    pic_origin_units = connection.execute(
        sa.text("SELECT count(*) FROM assignments WHERE pic_origin_unit_id IS NOT NULL")
    ).scalar_one()
    if responsible_units or pic_origin_units:
        raise RuntimeError("Cannot downgrade while Action Item unit provenance is populated")

    dialect = connection.dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER trg_action_items_responsible_unit_immutable")
        _drop_sqlite_guards(include_unit_provenance=True)
    else:
        op.execute("DROP TRIGGER trg_action_items_responsible_unit_immutable ON action_items")
        op.execute("DROP FUNCTION reject_action_item_responsible_unit_change()")
        op.execute("DROP TRIGGER trg_assignments_pic_origin_immutable ON assignments")
        op.execute("DROP FUNCTION reject_assignment_pic_origin_change()")

    op.drop_index("ix_assignments_pic_origin_unit_id", table_name="assignments")
    op.drop_index("ix_action_items_responsible_unit_id", table_name="action_items")
    with op.batch_alter_table(
        "assignments",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("fk_assignments_pic_origin_unit", type_="foreignkey")
        batch.drop_column("pic_origin_unit_id")
    with op.batch_alter_table(
        "action_items",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("fk_action_items_responsible_unit", type_="foreignkey")
        batch.drop_column("responsible_unit_id")

    if dialect == "sqlite":
        _create_sqlite_action_item_guards(include_responsible_unit=False)
        _create_sqlite_assignment_guards(include_pic_origin_unit=False)
        _create_sqlite_status_history_guard()
        _create_sqlite_progress_assignment_guard()
