"""Link action items to their source disposition and audit task creation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_action_item_dispositions"
down_revision: str | None = "0014_dispositions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _set_audit_event_constraints(*, allow_action_items: bool) -> None:
    dialect = op.get_bind().dialect.name
    with op.batch_alter_table(
        "audit_events",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("ck_audit_events_action", type_="check")
        batch.drop_constraint("ck_audit_events_object_type", type_="check")
        batch.drop_constraint("ck_audit_events_action_object_pair", type_="check")
        if allow_action_items:
            batch.create_check_constraint(
                "ck_audit_events_action",
                "action IN ('meeting.status_changed', 'disposition.created', "
                "'action_item.created')",
            )
            batch.create_check_constraint(
                "ck_audit_events_object_type",
                "object_type IN ('meeting', 'disposition', 'action_item')",
            )
            batch.create_check_constraint(
                "ck_audit_events_action_object_pair",
                "(action = 'meeting.status_changed' AND object_type = 'meeting') OR "
                "(action = 'disposition.created' AND object_type = 'disposition') OR "
                "(action = 'action_item.created' AND object_type = 'action_item')",
            )
        else:
            batch.create_check_constraint(
                "ck_audit_events_action",
                "action IN ('meeting.status_changed', 'disposition.created')",
            )
            batch.create_check_constraint(
                "ck_audit_events_object_type",
                "object_type IN ('meeting', 'disposition')",
            )
            batch.create_check_constraint(
                "ck_audit_events_action_object_pair",
                "(action = 'meeting.status_changed' AND object_type = 'meeting') OR "
                "(action = 'disposition.created' AND object_type = 'disposition')",
            )

    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit event history is append-only');
            END
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'Audit event history is append-only');
            END
            """
        )


def _create_sqlite_action_item_triggers(*, include_disposition: bool) -> None:
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
    if include_disposition:
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
    op.execute(
        """
        CREATE TRIGGER trg_action_items_no_delete
        BEFORE DELETE ON action_items
        BEGIN
            SELECT RAISE(ABORT, 'Action Items cannot be deleted');
        END
        """
    )


def _create_sqlite_status_history_trigger() -> None:
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


def _drop_sqlite_action_item_triggers(*, include_disposition: bool) -> None:
    op.execute("DROP TRIGGER trg_action_items_insert_guard")
    op.execute("DROP TRIGGER trg_action_items_update_guard")
    op.execute("DROP TRIGGER trg_action_items_no_delete")
    if include_disposition:
        op.execute("DROP TRIGGER trg_action_items_disposition_immutable")


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect not in {"postgresql", "sqlite"}:
        raise RuntimeError("Action Item disposition migration requires PostgreSQL or SQLite")

    _set_audit_event_constraints(allow_action_items=True)
    op.create_index(
        "uq_dispositions_source_binding",
        "dispositions",
        ["id", "meeting_id", "source_minutes_revision_id", "source_decision_id"],
        unique=True,
    )
    if dialect == "sqlite":
        _drop_sqlite_action_item_triggers(include_disposition=False)
        op.execute("DROP TRIGGER trg_status_histories_guard")
    with op.batch_alter_table(
        "action_items",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.add_column(sa.Column("disposition_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_action_items_disposition_source",
            "dispositions",
            [
                "disposition_id",
                "meeting_id",
                "source_minutes_revision_id",
                "source_decision_id",
            ],
            [
                "id",
                "meeting_id",
                "source_minutes_revision_id",
                "source_decision_id",
            ],
            ondelete="RESTRICT",
        )
    op.create_index("ix_action_items_disposition_id", "action_items", ["disposition_id"])

    if dialect == "sqlite":
        _create_sqlite_action_item_triggers(include_disposition=True)
        _create_sqlite_status_history_trigger()
    else:
        op.execute(
            """
            CREATE FUNCTION reject_action_item_disposition_change() RETURNS trigger AS $$
            BEGIN
                IF NEW.disposition_id IS DISTINCT FROM OLD.disposition_id THEN
                    RAISE EXCEPTION 'Action Item disposition is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_action_items_disposition_immutable
            BEFORE UPDATE OF disposition_id ON action_items
            FOR EACH ROW EXECUTE FUNCTION reject_action_item_disposition_change()
            """
        )


def downgrade() -> None:
    connection = op.get_bind()
    linked_items = connection.execute(
        sa.text("SELECT count(*) FROM action_items WHERE disposition_id IS NOT NULL")
    ).scalar_one()
    audit_events = connection.execute(
        sa.text("SELECT count(*) FROM audit_events WHERE action = 'action_item.created'")
    ).scalar_one()
    if linked_items or audit_events:
        raise RuntimeError("Cannot downgrade while Action Item audit history exists")

    dialect = connection.dialect.name
    if dialect == "sqlite":
        _drop_sqlite_action_item_triggers(include_disposition=True)
        op.execute("DROP TRIGGER trg_status_histories_guard")
        _set_audit_event_constraints(allow_action_items=False)
    if dialect == "postgresql":
        op.execute("DROP TRIGGER trg_action_items_disposition_immutable ON action_items")
        op.execute("DROP FUNCTION reject_action_item_disposition_change()")
    op.drop_index("ix_action_items_disposition_id", table_name="action_items")
    with op.batch_alter_table(
        "action_items",
        recreate="always" if dialect == "sqlite" else "auto",
    ) as batch:
        batch.drop_constraint("fk_action_items_disposition_source", type_="foreignkey")
        batch.drop_column("disposition_id")
    if dialect == "sqlite":
        _create_sqlite_action_item_triggers(include_disposition=False)
        _create_sqlite_status_history_trigger()
    op.drop_index("uq_dispositions_source_binding", table_name="dispositions")
    if dialect != "sqlite":
        _set_audit_event_constraints(allow_action_items=False)
