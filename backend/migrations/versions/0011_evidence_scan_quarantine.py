"""Quarantine uploaded evidence until a trusted scanner records a clean result."""

from collections.abc import Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0011_evidence_scan_quarantine"
down_revision: str | None = "0010_action_item_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_item_evidence_scans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("event_number", sa.Integer(), nullable=False),
        sa.Column("scan_status", sa.String(length=10), nullable=False),
        sa.Column("scanner_name", sa.String(length=100), nullable=True),
        sa.Column("scanner_version", sa.String(length=100), nullable=True),
        sa.Column("scanned_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "scanned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scan_status IN ('PENDING', 'CLEAN', 'REJECTED')",
            name="ck_action_item_evidence_scans_status",
        ),
        sa.CheckConstraint("event_number > 0", name="ck_action_item_evidence_scans_event_number"),
        sa.CheckConstraint(
            "(scan_status = 'PENDING' AND scanner_name IS NULL "
            "AND scanner_version IS NULL AND scanned_sha256 IS NULL) OR "
            "(scan_status IN ('CLEAN', 'REJECTED') AND scanner_name IS NOT NULL "
            "AND length(trim(scanner_name)) > 0 AND scanner_version IS NOT NULL "
            "AND length(trim(scanner_version)) > 0 AND scanned_sha256 IS NOT NULL "
            "AND length(scanned_sha256) = 64)",
            name="ck_action_item_evidence_scans_result",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["action_item_evidence.id"],
            name="fk_action_item_evidence_scans_evidence_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "evidence_id",
            "event_number",
            name="uq_action_item_evidence_scans_event_number",
        ),
    )
    op.create_index(
        "ix_action_item_evidence_scans_latest",
        "action_item_evidence_scans",
        ["evidence_id", "event_number"],
    )

    scan_event_table = sa.table(
        "action_item_evidence_scans",
        sa.Column("id", sa.Uuid()),
        sa.Column("evidence_id", sa.Uuid()),
        sa.Column("event_number", sa.Integer()),
        sa.Column("scan_status", sa.String(length=10)),
    )
    existing_file_ids = (
        op.get_bind()
        .execute(
            sa.text("SELECT id FROM action_item_evidence WHERE evidence_kind = 'FILE' ORDER BY id")
        )
        .scalars()
    )
    pending_events = [
        {
            "id": uuid4(),
            "evidence_id": UUID(str(evidence_id)),
            "event_number": 1,
            "scan_status": "PENDING",
        }
        for evidence_id in existing_file_ids
    ]
    if pending_events:
        op.get_bind().execute(sa.insert(scan_event_table), pending_events)

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _create_postgresql_guards()
    elif dialect == "sqlite":
        _create_sqlite_guards()


def _create_postgresql_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_action_item_evidence_scan_event()
        RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            expected_event integer;
            previous_status text;
            evidence_sha256 text;
        BEGIN
            PERFORM 1
            FROM action_item_evidence
            WHERE id = NEW.evidence_id
            FOR UPDATE;
            SELECT COALESCE(MAX(event_number), 0) + 1
            INTO expected_event
            FROM action_item_evidence_scans
            WHERE evidence_id = NEW.evidence_id;
            IF NEW.event_number <> expected_event THEN
                RAISE EXCEPTION 'Evidence scan event sequence is invalid';
            END IF;

            IF NEW.event_number = 1 THEN
                IF NEW.scan_status <> 'PENDING' THEN
                    RAISE EXCEPTION 'Evidence must start in PENDING quarantine';
                END IF;
            ELSE
                SELECT scan_status INTO previous_status
                FROM action_item_evidence_scans
                WHERE evidence_id = NEW.evidence_id
                  AND event_number = NEW.event_number - 1;
                IF previous_status <> 'PENDING'
                   OR NEW.scan_status NOT IN ('CLEAN', 'REJECTED') THEN
                    RAISE EXCEPTION 'Evidence scan transition is invalid';
                END IF;
            END IF;

            IF NEW.scan_status IN ('CLEAN', 'REJECTED') THEN
                SELECT sha256 INTO evidence_sha256
                FROM action_item_evidence
                WHERE id = NEW.evidence_id
                  AND evidence_kind = 'FILE';
                IF evidence_sha256 IS NULL OR NEW.scanned_sha256 <> evidence_sha256 THEN
                    RAISE EXCEPTION 'Scanner result does not match the stored evidence';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_scans_guard
        BEFORE INSERT ON action_item_evidence_scans
        FOR EACH ROW EXECUTE FUNCTION guard_action_item_evidence_scan_event()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_scans_append_only
        BEFORE UPDATE OR DELETE ON action_item_evidence_scans
        FOR EACH ROW EXECUTE FUNCTION reject_action_item_history_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_scans_no_truncate
        BEFORE TRUNCATE ON action_item_evidence_scans
        FOR EACH STATEMENT EXECUTE FUNCTION reject_action_item_history_mutation()
        """
    )


def _create_sqlite_guards() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_action_item_evidence_scans_guard
        BEFORE INSERT ON action_item_evidence_scans
        BEGIN
            SELECT CASE WHEN NEW.event_number <> COALESCE((
                SELECT MAX(event_number) + 1
                FROM action_item_evidence_scans
                WHERE evidence_id = NEW.evidence_id
            ), 1) THEN RAISE(ABORT, 'Evidence scan event sequence is invalid') END;
            SELECT CASE
                WHEN NEW.event_number = 1 AND NEW.scan_status <> 'PENDING'
                    THEN RAISE(ABORT, 'Evidence must start in PENDING quarantine')
                WHEN NEW.event_number > 1 AND NOT EXISTS (
                    SELECT 1
                    FROM action_item_evidence_scans
                    WHERE evidence_id = NEW.evidence_id
                      AND event_number = NEW.event_number - 1
                      AND scan_status = 'PENDING'
                ) THEN RAISE(ABORT, 'Evidence scan transition is invalid')
                WHEN NEW.event_number > 1 AND NEW.scan_status NOT IN ('CLEAN', 'REJECTED')
                    THEN RAISE(ABORT, 'Evidence scan transition is invalid')
                WHEN NEW.scan_status IN ('CLEAN', 'REJECTED') AND NOT EXISTS (
                    SELECT 1
                    FROM action_item_evidence e
                    WHERE e.id = NEW.evidence_id
                      AND e.evidence_kind = 'FILE'
                      AND e.sha256 = NEW.scanned_sha256
                ) THEN RAISE(ABORT, 'Scanner result does not match the stored evidence')
            END;
        END
        """
    )
    for operation in ("UPDATE", "DELETE"):
        # The operation comes only from this fixed migration tuple.
        # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
        op.execute(
            f"""
            CREATE TRIGGER trg_action_item_evidence_scans_no_{operation.lower()}
            BEFORE {operation} ON action_item_evidence_scans
            BEGIN
                SELECT RAISE(ABORT, 'Evidence scan history is append-only');
            END
            """
        )


def downgrade() -> None:
    event_count = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM action_item_evidence_scans"))
        .scalar_one()
    )
    if event_count:
        raise RuntimeError("Cannot downgrade while Action Item evidence scan history exists")

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER trg_action_item_evidence_scans_no_truncate ON action_item_evidence_scans"
        )
        op.execute(
            "DROP TRIGGER trg_action_item_evidence_scans_append_only ON action_item_evidence_scans"
        )
        op.execute(
            "DROP TRIGGER trg_action_item_evidence_scans_guard ON action_item_evidence_scans"
        )
        op.execute("DROP FUNCTION guard_action_item_evidence_scan_event()")
    elif dialect == "sqlite":
        for trigger_name in (
            "trg_action_item_evidence_scans_no_update",
            "trg_action_item_evidence_scans_no_delete",
            "trg_action_item_evidence_scans_guard",
        ):
            # The trigger name comes only from the fixed migration tuple above.
            # nosemgrep: python.lang.security.audit.formatted-sql-query.formatted-sql-query, python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query  # noqa: E501
            op.execute(f"DROP TRIGGER {trigger_name}")

    op.drop_index("ix_action_item_evidence_scans_latest", table_name="action_item_evidence_scans")
    op.drop_table("action_item_evidence_scans")
