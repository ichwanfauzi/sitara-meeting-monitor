from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.core.config import get_settings
from app.models.auth import User
from app.models.meeting import (
    DecisionBriefApprovalEvent,
    DecisionBriefVersion,
    Meeting,
    MeetingStatus,
    MinutesRevision,
)
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_alembic_revision_identifiers_fit_version_column() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())

    assert revisions
    assert all(len(revision.revision) <= 32 for revision in revisions)


def test_decision_brief_priority_migration_allows_blank_and_keeps_append_only_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "decision-brief-priority.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)

    try:
        command.upgrade(config, "0026_notification_email_delivery")
        command.upgrade(config, "head")
        constraints = inspect(engine).get_check_constraints("decision_brief_decisions")
        priority_check = next(
            item["sqltext"]
            for item in constraints
            if item["name"] == "ck_decision_brief_decisions_priority"
        )
        with engine.connect() as connection:
            guards = set(
                connection.execute(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'trigger' AND tbl_name = 'decision_brief_decisions'"
                    )
                ).scalars()
            )
        assert "priority = '' OR" in priority_check
        assert {
            "trg_decision_brief_decisions_no_update",
            "trg_decision_brief_decisions_no_delete",
        } <= guards

        command.downgrade(config, "0026_notification_email_delivery")
        downgraded_constraints = inspect(engine).get_check_constraints("decision_brief_decisions")
        downgraded_priority_check = next(
            item["sqltext"]
            for item in downgraded_constraints
            if item["name"] == "ck_decision_brief_decisions_priority"
        )
        assert "length(trim(priority)) > 0" in downgraded_priority_check
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_content_audit_migration_accepts_save_events_and_preserves_append_only_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "content-audit.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id, meeting_id, minutes_id, brief_id, source_id = (str(uuid4()) for _ in range(5))

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE users (id CHAR(32) PRIMARY KEY, email VARCHAR(320) NOT NULL, "
                    "full_name VARCHAR(200) NOT NULL, password_hash VARCHAR(255) NOT NULL, "
                    "is_active BOOLEAN NOT NULL)"
                )
            )
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            )
            connection.execute(
                text(
                    "INSERT INTO alembic_version (version_num) "
                    "VALUES ('0023_minutes_manual_target')"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE audit_events ("
                    "id CHAR(32) NOT NULL, actor_user_id CHAR(32) NOT NULL, "
                    "actor_roles JSON NOT NULL, action VARCHAR(100) NOT NULL, "
                    "object_type VARCHAR(50) NOT NULL, object_id CHAR(32) NOT NULL, "
                    "result VARCHAR(20) NOT NULL, correlation_id CHAR(32), "
                    "before_values JSON, after_values JSON, "
                    "occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                    "CONSTRAINT pk_audit_events PRIMARY KEY (id), "
                    "CONSTRAINT fk_audit_events_actor_user_id_users "
                    "FOREIGN KEY(actor_user_id) REFERENCES users (id) ON DELETE RESTRICT, "
                    "CONSTRAINT ck_audit_events_action CHECK (action IN "
                    "('meeting.status_changed', 'meeting.metadata_updated', "
                    "'meeting.agenda_changed', 'meeting.participant_changed', "
                    "'meeting.notetaker_handover_requested', "
                    "'meeting.notetaker_handover_approved', 'decision_brief.submitted', "
                    "'decision_brief.withdrawn', 'decision_brief.approved', "
                    "'decision_brief.rejected', 'disposition.created', "
                    "'action_item.created', 'action_item.assignment_changed', "
                    "'action_item.updated', 'action_item.deleted')), "
                    "CONSTRAINT ck_audit_events_object_type CHECK (object_type IN "
                    "('meeting', 'decision_brief_version', 'disposition', 'action_item')), "
                    "CONSTRAINT ck_audit_events_action_object_pair CHECK ("
                    "(action IN ('meeting.status_changed', 'meeting.metadata_updated', "
                    "'meeting.agenda_changed', 'meeting.participant_changed', "
                    "'meeting.notetaker_handover_requested', "
                    "'meeting.notetaker_handover_approved') AND object_type = 'meeting') OR "
                    "(action IN ('decision_brief.submitted', 'decision_brief.withdrawn', "
                    "'decision_brief.approved', 'decision_brief.rejected') "
                    "AND object_type = 'decision_brief_version') OR "
                    "(action = 'disposition.created' AND object_type = 'disposition') OR "
                    "(action IN ('action_item.created', 'action_item.assignment_changed', "
                    "'action_item.updated', 'action_item.deleted') "
                    "AND object_type = 'action_item')), "
                    "CONSTRAINT ck_audit_events_result CHECK "
                    "(result IN ('SUCCEEDED', 'DENIED')))"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER trg_audit_events_no_update BEFORE UPDATE ON audit_events "
                    "BEGIN SELECT RAISE(ABORT, 'Audit event history is append-only'); END"
                )
            )
            connection.execute(
                text(
                    "CREATE TRIGGER trg_audit_events_no_delete BEFORE DELETE ON audit_events "
                    "BEGIN SELECT RAISE(ABORT, 'Audit event history is append-only'); END"
                )
            )
        command.upgrade(config, "0024_content_audit_events")
        command.downgrade(config, "0023_minutes_manual_target")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0023_minutes_manual_target"
            )
        command.upgrade(config, "0024_content_audit_events")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, 'content-audit@example.test', 'Synthetic Audit User', "
                    "'synthetic-only-not-used', 1)"
                ),
                {"id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'minutes.revised', 'meeting', "
                    ":object_id, 'SUCCEEDED', :before_values, :after_values)"
                ),
                {
                    "id": str(uuid4()),
                    "actor_id": actor_id,
                    "roles": '["SEKRETARIAT"]',
                    "object_id": meeting_id,
                    "before_values": None,
                    "after_values": (
                        f'{{"revision_id":"{minutes_id}","revision_number":"1",'
                        '"format_version":"2","decision_count":"1"}'
                    ),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'decision_brief.saved', "
                    "'decision_brief_version', :object_id, 'SUCCEEDED', NULL, :after_values)"
                ),
                {
                    "id": str(uuid4()),
                    "actor_id": actor_id,
                    "roles": '["SEKRETARIAT"]',
                    "object_id": brief_id,
                    "after_values": (
                        f'{{"meeting_id":"{meeting_id}",'
                        f'"source_minutes_revision_id":"{source_id}",'
                        '"version_number":"1","decision_count":"1"}'
                    ),
                },
            )

        with engine.connect() as connection:
            content_event_count = connection.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE action IN ('minutes.revised', 'decision_brief.saved')"
                )
            ).scalar_one()
        assert content_event_count == 2
        with (
            pytest.raises(IntegrityError, match="Audit event history is append-only"),
            engine.begin() as connection,
        ):
            connection.execute(
                text("UPDATE audit_events SET result = 'DENIED' WHERE action = 'minutes.revised'")
            )
        with pytest.raises(RuntimeError, match="minutes or Decision Brief audit events exist"):
            command.downgrade(config, "0023_minutes_manual_target")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0024_content_audit_events"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_initial_migration_creates_identity_schema_and_seed_roles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    try:
        command.upgrade(config, "head")

        engine = create_engine(database_url)
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            role_codes = set(connection.execute(text("SELECT role_code FROM roles")).scalars())

        assert {
            "users",
            "roles",
            "user_roles",
            "user_sessions",
            "meetings",
            "agendas",
            "meeting_participants",
            "meeting_status_events",
            "minutes_revisions",
            "minutes_discussions",
            "minutes_decisions",
            "minutes_reviews",
            "decision_brief_versions",
            "decision_brief_decisions",
            "organization_units",
            "user_unit_memberships",
            "reporting_lines",
            "login_rate_limit_buckets",
            "action_items",
            "assignments",
            "progress_updates",
            "action_item_evidence",
            "action_item_evidence_scans",
            "completion_verifications",
            "status_histories",
            "audit_events",
            "dispositions",
            "disposition_targets",
            "meeting_notetaker_handovers",
            "decision_brief_approval_events",
            "alembic_version",
        } <= tables
        assert role_codes == {
            "SUPER_ADMIN",
            "SEKRETARIAT",
            "MANAGER_LEGAL",
            "REKTOR",
            "WAREK",
            "PIC",
        }
        review_foreign_keys = inspect(engine).get_foreign_keys("minutes_reviews")
        assert any(
            foreign_key["referred_table"] == "minutes_revisions"
            and foreign_key["constrained_columns"] == ["meeting_id", "minutes_revision_id"]
            and foreign_key["referred_columns"] == ["meeting_id", "id"]
            for foreign_key in review_foreign_keys
        )
        action_item_columns = {
            column["name"] for column in inspect(engine).get_columns("action_items")
        }
        assert {"disposition_id", "responsible_unit_id"} <= action_item_columns
        assignment_columns = {
            column["name"] for column in inspect(engine).get_columns("assignments")
        }
        assert "pic_origin_unit_id" in assignment_columns
        meeting_columns = {column["name"] for column in inspect(engine).get_columns("meetings")}
        assert "version" in meeting_columns
        handover_indexes = inspect(engine).get_indexes("meeting_notetaker_handovers")
        assert any(
            index["name"] == "uq_meeting_notetaker_handovers_pending" and index["unique"]
            for index in handover_indexes
        )
        action_item_foreign_keys = inspect(engine).get_foreign_keys("action_items")
        assert any(
            foreign_key["name"] == "fk_action_items_disposition_source"
            and foreign_key["referred_table"] == "dispositions"
            and foreign_key["constrained_columns"]
            == [
                "disposition_id",
                "meeting_id",
                "source_minutes_revision_id",
                "source_decision_id",
            ]
            for foreign_key in action_item_foreign_keys
        )
        with engine.connect() as connection:
            trigger_names = set(
                connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                ).scalars()
            )
        assert {
            "trg_minutes_revisions_no_update",
            "trg_minutes_revisions_no_delete",
            "trg_decision_brief_versions_no_update",
            "trg_decision_brief_versions_no_delete",
            "trg_progress_updates_no_update",
            "trg_progress_updates_no_delete",
            "trg_completion_verifications_no_update",
            "trg_completion_verifications_no_delete",
            "trg_status_histories_no_update",
            "trg_status_histories_no_delete",
            "trg_action_items_insert_guard",
            "trg_action_items_update_guard",
            "trg_action_items_no_delete",
            "trg_assignments_update_guard",
            "trg_progress_updates_assignment",
            "trg_action_item_evidence_limit",
            "trg_action_item_evidence_no_update",
            "trg_action_item_evidence_no_delete",
            "trg_action_item_evidence_scans_guard",
            "trg_action_item_evidence_scans_no_update",
            "trg_action_item_evidence_scans_no_delete",
            "trg_audit_events_no_update",
            "trg_audit_events_no_delete",
            "trg_meeting_notetaker_handover_approve_once",
            "trg_meeting_notetaker_handover_no_delete",
            "trg_decision_brief_approval_events_no_update",
            "trg_decision_brief_approval_events_no_delete",
        } <= trigger_names

        actor_id = uuid4()
        meeting_id = uuid4()
        revision_id = uuid4()
        with Session(engine) as session:
            session.add_all(
                [
                    User(
                        id=actor_id,
                        email="migration-minutes@example.test",
                        full_name="Synthetic Migration User",
                        password_hash="synthetic-only-not-used",
                        is_active=True,
                    ),
                    Meeting(
                        id=meeting_id,
                        meeting_number="MIGRATION-REVISION-001",
                        title="Synthetic migration test meeting",
                        meeting_date=date.today(),
                        created_by_id=actor_id,
                        status=MeetingStatus.DRAFT,
                    ),
                    MinutesRevision(
                        id=revision_id,
                        meeting_id=meeting_id,
                        revision_number=1,
                        content="Synthetic migration test minutes",
                        created_by_id=actor_id,
                    ),
                ]
            )
            session.commit()

        with engine.connect() as connection:
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(
                    text("UPDATE minutes_revisions SET content = 'silently replaced'")
                )
                connection.commit()
            connection.rollback()
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(text("DELETE FROM minutes_revisions"))
                connection.commit()
            connection.rollback()
        inspector = inspect(engine)
        email_unique_constraint = any(
            constraint.get("column_names") == ["email"]
            for constraint in inspector.get_unique_constraints("users")
        )
        session_user_index = any(
            index.get("name") == "ix_user_sessions_user_id"
            for index in inspector.get_indexes("user_sessions")
        )
        assert email_unique_constraint
        assert session_user_index

        command.downgrade(config, "base")
        assert "users" not in inspect(engine).get_table_names()
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_in_app_notification_migration_guards_nonempty_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "in-app-notifications.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE users (id CHAR(32) PRIMARY KEY, email VARCHAR(320) NOT NULL, "
                    "full_name VARCHAR(200) NOT NULL, password_hash VARCHAR(512) NOT NULL, "
                    "is_active BOOLEAN NOT NULL)"
                )
            )
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            )
            connection.execute(
                text(
                    "INSERT INTO alembic_version (version_num) VALUES ('0024_content_audit_events')"
                )
            )
        command.upgrade(config, "0026_notification_email_delivery")

        assert "notifications" in inspect(engine).get_table_names()
        command.downgrade(config, "0024_content_audit_events")
        assert "notifications" not in inspect(engine).get_table_names()
        command.upgrade(config, "0026_notification_email_delivery")

        recipient_id = uuid4().hex
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, 'notification-migration@example.test', "
                    "'Penerima Sintetis', 'synthetic-test-hash', 1)"
                ),
                {"id": recipient_id},
            )
            connection.execute(
                text(
                    "INSERT INTO notifications "
                    "(id, recipient_user_id, event_key, notification_type, message, "
                    "target_type, target_id) VALUES "
                    "(:id, :recipient_id, 'synthetic-event', 'ACTION_ITEM_STATUS_CHANGED', "
                    "'Status tindak lanjut terkait berubah.', 'ACTION_ITEM', :target_id)"
                ),
                {"id": uuid4().hex, "recipient_id": recipient_id, "target_id": uuid4().hex},
            )

        with pytest.raises(RuntimeError, match="Cannot downgrade while in-app notifications"):
            command.downgrade(config, "0024_content_audit_events")

        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM notifications")).scalar_one() == 1
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0025_in_app_notifications"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_notification_email_migration_preserves_existing_rows_and_guards_delivery_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "notification-email.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    recipient_id, notification_id, target_id = (uuid4().hex for _ in range(3))

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE users (id CHAR(32) PRIMARY KEY, email VARCHAR(320) NOT NULL, "
                    "full_name VARCHAR(200) NOT NULL, password_hash VARCHAR(512) NOT NULL, "
                    "is_active BOOLEAN NOT NULL)"
                )
            )
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            )
            connection.execute(
                text(
                    "INSERT INTO alembic_version (version_num) VALUES ('0024_content_audit_events')"
                )
            )
        command.upgrade(config, "0025_in_app_notifications")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, 'notification@example.test', 'Penerima', 'synthetic-hash', 1)"
                ),
                {"id": recipient_id},
            )
            connection.execute(
                text(
                    "INSERT INTO notifications "
                    "(id, recipient_user_id, event_key, notification_type, message, "
                    "target_type, target_id) VALUES "
                    "(:id, :recipient_id, 'legacy-event', 'ACTION_ITEM_STATUS_CHANGED', "
                    "'Status berubah.', 'ACTION_ITEM', :target_id)"
                ),
                {
                    "id": notification_id,
                    "recipient_id": recipient_id,
                    "target_id": target_id,
                },
            )

        command.upgrade(config, "0026_notification_email_delivery")
        with engine.connect() as connection:
            email_state = connection.execute(
                text("SELECT email_status, email_attempts FROM notifications WHERE id = :id"),
                {"id": notification_id},
            ).one()
        assert email_state == ("DISABLED", 0)

        command.downgrade(config, "0025_in_app_notifications")
        columns = {column["name"] for column in inspect(engine).get_columns("notifications")}
        assert "email_status" not in columns
        command.upgrade(config, "0026_notification_email_delivery")

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE notifications SET email_status = 'SENT', email_attempts = 1, "
                    "email_sent_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"id": notification_id},
            )

        with pytest.raises(RuntimeError, match="notification email delivery history"):
            command.downgrade(config, "0025_in_app_notifications")

        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM notifications")).scalar_one() == 1
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0026_notification_email_delivery"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_action_item_unit_provenance_migration_preserves_legacy_rows_and_blocks_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "action_item_unit_provenance.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id, unit_id, meeting_id, revision_id, agenda_id, discussion_id, decision_id = map(
        str, (uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
    )
    legacy_item_id, legacy_assignment_id = map(str, (uuid4(), uuid4()))
    attributed_item_id, attributed_assignment_id = map(str, (uuid4(), uuid4()))

    try:
        command.upgrade(config, "0017_decision_brief_approval")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, 'provenance-migration@example.test', 'Synthetic Actor', "
                    "'synthetic-only-not-used', 1)"
                ),
                {"id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO organization_units (id, unit_code, name, is_active) "
                    "VALUES (:id, 'PROVENANCE-UNIT', 'Synthetic Provenance Unit', 1)"
                ),
                {"id": unit_id},
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, 'PROVENANCE-001', 'Synthetic meeting', '2026-11-15', :actor)"
                ),
                {"id": meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting, 1, 2, NULL, :actor)"
                ),
                {"id": revision_id, "meeting": meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO agendas (id, meeting_id, agenda_number, title) "
                    "VALUES (:id, :meeting, 1, 'Synthetic agenda')"
                ),
                {"id": agenda_id, "meeting": meeting_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_discussions "
                    "(id, meeting_id, minutes_revision_id, agenda_id, discussion_number, content) "
                    "VALUES (:id, :meeting, :revision, :agenda, 1, 'Synthetic discussion')"
                ),
                {
                    "id": discussion_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "agenda": agenda_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_decisions "
                    "(id, meeting_id, minutes_revision_id, discussion_id, decision_number, "
                    "decision_text, is_action_item) "
                    "VALUES (:id, :meeting, :revision, :discussion, 1, 'Synthetic decision', 1)"
                ),
                {
                    "id": decision_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "discussion": discussion_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO action_items "
                    "(id, meeting_id, source_minutes_revision_id, source_decision_id, title, "
                    "description, priority, official_status, created_by_id) "
                    "VALUES (:id, :meeting, :revision, :decision, 'Legacy task', 'Synthetic task', "
                    "'Penting', 'BELUM_DIMULAI', :actor)"
                ),
                {
                    "id": legacy_item_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "decision": decision_id,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO assignments "
                    "(id, action_item_id, assignee_user_id, assigned_by_user_id, assignment_role) "
                    "VALUES (:id, :item, :actor, :actor, 'MAIN')"
                ),
                {"id": legacy_assignment_id, "item": legacy_item_id, "actor": actor_id},
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            legacy_unit_values = connection.execute(
                text(
                    "SELECT i.responsible_unit_id, a.pic_origin_unit_id "
                    "FROM action_items i JOIN assignments a ON a.action_item_id = i.id "
                    "WHERE i.id = :id"
                ),
                {"id": legacy_item_id},
            ).one()
        assert legacy_unit_values == (None, None)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO action_items "
                    "(id, meeting_id, source_minutes_revision_id, source_decision_id, title, "
                    "description, priority, official_status, created_by_id, responsible_unit_id) "
                    "VALUES (:id, :meeting, :revision, :decision, 'Attributed task', "
                    "'Synthetic task', 'Penting', 'BELUM_DIMULAI', :actor, :unit)"
                ),
                {
                    "id": attributed_item_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "decision": decision_id,
                    "actor": actor_id,
                    "unit": unit_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO assignments "
                    "(id, action_item_id, assignee_user_id, assigned_by_user_id, "
                    "assignment_role, pic_origin_unit_id) "
                    "VALUES (:id, :item, :actor, :actor, 'MAIN', :unit)"
                ),
                {
                    "id": attributed_assignment_id,
                    "item": attributed_item_id,
                    "actor": actor_id,
                    "unit": unit_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="responsible unit"):
            connection.execute(
                text("UPDATE action_items SET responsible_unit_id = NULL WHERE id = :id"),
                {"id": attributed_item_id},
            )
        with (
            engine.begin() as connection,
            pytest.raises(IntegrityError, match="Assignment history"),
        ):
            connection.execute(
                text("UPDATE assignments SET pic_origin_unit_id = NULL WHERE id = :id"),
                {"id": attributed_assignment_id},
            )
        with pytest.raises(RuntimeError, match="unit provenance is populated"):
            command.downgrade(config, "0017_decision_brief_approval")

        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0018_action_item_unit_provenance"
            )
            attributed_values = connection.execute(
                text(
                    "SELECT i.responsible_unit_id, a.pic_origin_unit_id "
                    "FROM action_items i JOIN assignments a ON a.action_item_id = i.id "
                    "WHERE i.id = :id"
                ),
                {"id": attributed_item_id},
            ).one()
        assert attributed_values == (unit_id, unit_id)
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_action_item_assignment_audit_migration_extends_constraints_and_guards_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "action_item_assignment_audit.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id = str(uuid4())
    item_id = str(uuid4())
    event_id = str(uuid4())

    try:
        command.upgrade(config, "0018_action_item_unit_provenance")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "assignment-audit-migration@example.test",
                    "full_name": "Synthetic Assignment Audit Actor",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )

        command.upgrade(config, "head")
        checks = {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("audit_events")
        }
        assert {
            "ck_audit_events_action",
            "ck_audit_events_object_type",
            "ck_audit_events_action_object_pair",
        } <= checks
        event_values = {
            "id": event_id,
            "actor_id": actor_id,
            "roles": '["SEKRETARIAT"]',
            "item_id": item_id,
            "result": "SUCCEEDED",
            "before_values": None,
            "after_values": '{"operation":"ASSIGNED","assignment_id":"'
            + str(uuid4())
            + '","assignee_user_id":"'
            + str(uuid4())
            + '","assignment_role":"SUPPORTING","pic_origin_unit_id":"'
            + str(uuid4())
            + '"}',
        }
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'action_item.assignment_changed', "
                    "'action_item', :item_id, :result, :before_values, :after_values)"
                ),
                event_values,
            )

        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'action_item.assignment_changed', "
                    "'meeting', :item_id, :result, :before_values, :after_values)"
                ),
                {**event_values, "id": str(uuid4())},
            )

        with engine.connect() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text("UPDATE audit_events SET result = 'DENIED' WHERE id = :id"),
                {"id": event_id},
            )

        with pytest.raises(RuntimeError, match="assignment audit history exists"):
            command.downgrade(config, "0018_action_item_unit_provenance")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0019_assignment_audit"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM audit_events "
                        "WHERE action = 'action_item.assignment_changed'"
                    )
                ).scalar_one()
                == 1
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_meeting_live_edit_migration_adds_scoped_handover_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "meeting_live_editing.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id = str(uuid4())
    recipient_id = str(uuid4())
    meeting_id = str(uuid4())
    handover_id = str(uuid4())

    try:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            for user_id, email in (
                (actor_id, "handover-actor@example.test"),
                (recipient_id, "handover-recipient@example.test"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                        "VALUES (:id, :email, :full_name, :password_hash, 1)"
                    ),
                    {
                        "id": user_id,
                        "email": email,
                        "full_name": "Synthetic Handover User",
                        "password_hash": "synthetic-only-not-used",
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO meetings "
                    "(id, meeting_number, title, meeting_date, created_by_id, status) "
                    "VALUES (:id, 'HANDOVER-MIGRATION-001', 'Synthetic meeting', "
                    "'2026-10-15', :actor_id, 'LIVE')"
                ),
                {"id": meeting_id, "actor_id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO meeting_notetaker_handovers "
                    "(id, meeting_id, from_notetaker_id, to_notetaker_id, "
                    "requested_by_user_id, status) "
                    "VALUES (:id, :meeting_id, :actor_id, :recipient_id, :actor_id, 'PENDING')"
                ),
                {
                    "id": handover_id,
                    "meeting_id": meeting_id,
                    "actor_id": actor_id,
                    "recipient_id": recipient_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, after_values) "
                    "VALUES (:id, :actor_id, '[]', 'meeting.agenda_changed', "
                    "'meeting', :meeting_id, 'SUCCEEDED', '{\"operation\":\"CREATED\"}')"
                ),
                {"id": str(uuid4()), "actor_id": actor_id, "meeting_id": meeting_id},
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE meeting_notetaker_handovers SET status = 'APPROVED', "
                    "approved_by_user_id = :actor_id, approved_at = CURRENT_TIMESTAMP "
                    "WHERE id = :id"
                ),
                {"actor_id": actor_id, "id": handover_id},
            )

        with engine.connect() as connection:
            with pytest.raises(IntegrityError, match="immutable"):
                connection.execute(
                    text(
                        "UPDATE meeting_notetaker_handovers "
                        "SET to_notetaker_id = :recipient_id WHERE id = :id"
                    ),
                    {"recipient_id": actor_id, "id": handover_id},
                )
                connection.commit()
            connection.rollback()
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(
                    text("DELETE FROM meeting_notetaker_handovers WHERE id = :id"),
                    {"id": handover_id},
                )
                connection.commit()
            connection.rollback()

        with pytest.raises(RuntimeError, match="meeting edit history"):
            command.downgrade(config, "0015_action_item_dispositions")
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_decision_brief_approval_migration_adds_append_only_event_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "decision_brief_approval.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id = uuid4()
    meeting_id = uuid4()
    revision_id = uuid4()
    brief_version_id = uuid4()

    try:
        command.upgrade(config, "0016_meeting_live_editing")
        with Session(engine) as session:
            actor = User(
                id=actor_id,
                email="brief-approval-migration@example.test",
                full_name="Synthetic Brief Approver",
                password_hash="synthetic-only-not-used",
                is_active=True,
            )
            meeting = Meeting(
                id=meeting_id,
                meeting_number="BRIEF-APPROVAL-MIGRATION-001",
                title="Synthetic approval migration meeting",
                meeting_date=date.today(),
                created_by_id=actor_id,
                status=MeetingStatus.DRAFT,
            )
            revision = MinutesRevision(
                id=revision_id,
                meeting_id=meeting_id,
                revision_number=1,
                content="Synthetic migration minutes",
                created_by_id=actor_id,
            )
            version = DecisionBriefVersion(
                id=brief_version_id,
                meeting_id=meeting_id,
                source_minutes_revision_id=revision_id,
                version_number=1,
                summary="Synthetic immutable Decision Brief",
                created_by_id=actor_id,
            )
            session.add_all([actor, meeting, revision, version])
            session.commit()

        command.upgrade(config, "head")
        with Session(engine) as session:
            session.add(
                DecisionBriefApprovalEvent(
                    meeting_id=meeting_id,
                    brief_version_id=brief_version_id,
                    source_minutes_revision_id=revision_id,
                    event_number=1,
                    event_type="SUBMITTED",
                    actor_user_id=actor_id,
                    actor_roles=["SEKRETARIAT"],
                )
            )
            session.commit()

        with engine.connect() as connection:
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(
                    text("UPDATE decision_brief_approval_events SET event_type = 'WITHDRAWN'")
                )
                connection.commit()
            connection.rollback()
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(text("DELETE FROM decision_brief_approval_events"))
                connection.commit()
            connection.rollback()

        assert "decision_brief_approval_events" in inspect(engine).get_table_names()
        assert any(
            index["name"] == "uq_decision_brief_approval_events_terminal" and index["unique"]
            for index in inspect(engine).get_indexes("decision_brief_approval_events")
        )
        with pytest.raises(RuntimeError, match="Decision Brief approval history"):
            command.downgrade(config, "0016_meeting_live_editing")
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_user_job_title_migration_preserves_rows_and_blocks_data_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "user_job_title.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    user_id = str(uuid4())

    try:
        command.upgrade(config, "0011_evidence_scan_quarantine")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": user_id,
                    "email": "job-title-migration@example.test",
                    "full_name": "Synthetic Existing User",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            user = connection.execute(
                text("SELECT full_name, job_title FROM users WHERE id = :id"),
                {"id": user_id},
            ).one()
            migration_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert user == ("Synthetic Existing User", None)
        assert migration_head == "0027_brief_optional_priority"

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET job_title = 'Synthetic title' WHERE id = :id"),
                {"id": user_id},
            )
        with pytest.raises(RuntimeError, match="provisioned titles"):
            command.downgrade(config, "0011_evidence_scan_quarantine")

        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0012_user_job_title"
            )
            assert (
                connection.execute(
                    text("SELECT job_title FROM users WHERE id = :id"), {"id": user_id}
                ).scalar_one()
                == "Synthetic title"
            )

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET job_title = NULL WHERE id = :id"),
                {"id": user_id},
            )
        command.downgrade(config, "0011_evidence_scan_quarantine")
        assert "job_title" not in inspect(engine).get_columns("users")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT full_name FROM users WHERE id = :id"), {"id": user_id}
                ).scalar_one()
                == "Synthetic Existing User"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_audit_event_migration_is_append_only_and_refuses_data_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "audit_events.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id = str(uuid4())
    event_id = str(uuid4())

    try:
        command.upgrade(config, "0012_user_job_title")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "audit-migration@example.test",
                    "full_name": "Synthetic Audit Actor",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0027_brief_optional_priority"
            )
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, correlation_id, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, :action, :object_type, :object_id, "
                    ":result, :correlation_id, :before_values, :after_values)"
                ),
                {
                    "id": event_id,
                    "actor_id": actor_id,
                    "roles": '["SEKRETARIAT"]',
                    "action": "meeting.status_changed",
                    "object_type": "meeting",
                    "object_id": str(uuid4()),
                    "result": "SUCCEEDED",
                    "correlation_id": str(uuid4()),
                    "before_values": '{"status":"DRAFT"}',
                    "after_values": '{"status":"LIVE"}',
                },
            )
            connection.commit()

        with engine.connect() as connection:
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(
                    text("UPDATE audit_events SET result = 'DENIED' WHERE id = :id"),
                    {"id": event_id},
                )
                connection.commit()
            connection.rollback()
            with pytest.raises(IntegrityError, match="append-only"):
                connection.execute(
                    text("DELETE FROM audit_events WHERE id = :id"), {"id": event_id}
                )
                connection.commit()
            connection.rollback()

        with pytest.raises(RuntimeError, match="audit event history exists"):
            command.downgrade(config, "0012_user_job_title")

        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0013_audit_foundation"
            )
            assert connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_disposition_migration_extends_audit_constraints_and_guards_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "disposition_migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id = str(uuid4())
    disposition_id = str(uuid4())
    event_id = str(uuid4())
    base_event = {
        "id": event_id,
        "actor_id": actor_id,
        "roles": '["SEKRETARIAT"]',
        "object_id": disposition_id,
        "result": "SUCCEEDED",
        "correlation_id": str(uuid4()),
        "before_values": None,
        "after_values": '{"target_count":"1","target_types":"USER"}',
    }

    try:
        command.upgrade(config, "0012_user_job_title")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "disposition-migration@example.test",
                    "full_name": "Synthetic Disposition Actor",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )
        command.upgrade(config, "0013_audit_foundation")
        command.upgrade(config, "head")

        assert {"dispositions", "disposition_targets"} <= set(inspect(engine).get_table_names())
        audit_checks = {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("audit_events")
        }
        assert "ck_audit_events_action_object_pair" in audit_checks
        target_checks = {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("disposition_targets")
        }
        assert "ck_disposition_targets_target_shape" in target_checks
        target_indexes = {
            index["name"] for index in inspect(engine).get_indexes("disposition_targets")
        }
        assert {
            "uq_disposition_targets_user",
            "uq_disposition_targets_unit",
            "uq_disposition_targets_role",
        } <= target_indexes
        with engine.connect() as connection:
            trigger_names = set(
                connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                ).scalars()
            )
        assert {
            "trg_audit_events_no_update",
            "trg_audit_events_no_delete",
        } <= trigger_names

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO disposition_targets "
                    "(id, disposition_id, target_type) VALUES (:id, :disposition_id, 'USER')"
                ),
                {"id": str(uuid4()), "disposition_id": str(uuid4())},
            )

        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, correlation_id, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'disposition.created', 'meeting', "
                    ":object_id, :result, :correlation_id, :before_values, :after_values)"
                ),
                base_event,
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, correlation_id, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'disposition.created', 'disposition', "
                    ":object_id, :result, :correlation_id, :before_values, :after_values)"
                ),
                base_event,
            )

        with engine.connect() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text("UPDATE audit_events SET result = 'DENIED' WHERE id = :id"),
                {"id": event_id},
            )

        with pytest.raises(RuntimeError, match="disposition history exists"):
            command.downgrade(config, "0013_audit_foundation")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0014_dispositions"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_action_item_disposition_migration_preserves_guards_and_audits_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "action_item_dispositions.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)
    actor_id = str(uuid4())
    event_id = str(uuid4())
    event_values = {
        "id": event_id,
        "actor_id": actor_id,
        "roles": '["SEKRETARIAT"]',
        "object_id": str(uuid4()),
        "result": "SUCCEEDED",
        "correlation_id": str(uuid4()),
        "before_values": None,
        "after_values": (
            f'{{"source_minutes_revision_id":"{uuid4()}","source_decision_id":"{uuid4()}"}}'
        ),
    }

    try:
        command.upgrade(config, "0014_dispositions")
        command.upgrade(config, "head")

        action_item_columns = {
            column["name"] for column in inspect(engine).get_columns("action_items")
        }
        assert "disposition_id" in action_item_columns
        action_item_foreign_keys = inspect(engine).get_foreign_keys("action_items")
        assert any(
            foreign_key["name"] == "fk_action_items_disposition_source"
            and foreign_key["referred_table"] == "dispositions"
            for foreign_key in action_item_foreign_keys
        )
        audit_checks = {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("audit_events")
        }
        assert {
            "ck_audit_events_action",
            "ck_audit_events_object_type",
            "ck_audit_events_action_object_pair",
        } <= audit_checks
        with engine.connect() as connection:
            trigger_names = set(
                connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
                ).scalars()
            )
        assert {
            "trg_action_items_insert_guard",
            "trg_action_items_update_guard",
            "trg_action_items_no_delete",
            "trg_audit_events_no_update",
            "trg_audit_events_no_delete",
        } <= trigger_names

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "action-item-audit-migration@example.test",
                    "full_name": "Synthetic Action Item Actor",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, correlation_id, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'action_item.created', 'disposition', "
                    ":object_id, :result, :correlation_id, :before_values, :after_values)"
                ),
                event_values,
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, actor_user_id, actor_roles, action, object_type, object_id, "
                    "result, correlation_id, before_values, after_values) "
                    "VALUES (:id, :actor_id, :roles, 'action_item.created', 'action_item', "
                    ":object_id, :result, :correlation_id, :before_values, :after_values)"
                ),
                event_values,
            )
        with engine.connect() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text("UPDATE audit_events SET result = 'DENIED' WHERE id = :id"),
                {"id": event_id},
            )
        with pytest.raises(RuntimeError, match="Action Item audit history exists"):
            command.downgrade(config, "0014_dispositions")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0015_action_item_dispositions"
            )
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_evidence_quarantine_migration_backfills_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "evidence-backfill.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()
    engine = create_engine(database_url)

    try:
        command.upgrade(config, "0010_action_item_evidence")
        evidence_id = uuid4().hex
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, storage_key, "
                    "original_filename, content_type, size_bytes, sha256, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'FILE', :key, 'existing.pdf', "
                    "'application/pdf', 1, :sha, :actor)"
                ),
                {
                    "id": evidence_id,
                    "item": uuid4().hex,
                    "progress": uuid4().hex,
                    "key": uuid4().hex,
                    "sha": "a" * 64,
                    "actor": uuid4().hex,
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            scan_event = connection.execute(
                text(
                    "SELECT event_number, scan_status FROM action_item_evidence_scans "
                    "WHERE evidence_id = :evidence"
                ),
                {"evidence": evidence_id},
            ).one()
            migration_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

        assert scan_event == (1, "PENDING")
        assert migration_head == "0027_brief_optional_priority"
    finally:
        engine.dispose()
        get_settings.cache_clear()


def test_organization_scope_migration_has_no_seeds_and_protects_provisioned_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "organization_scope.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0007_decision_brief")
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        with engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
            for table_name in (
                "organization_units",
                "user_unit_memberships",
                "reporting_lines",
            ):
                count = connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
                assert count == 0
        assert {"meetings", "minutes_revisions", "decision_brief_versions"} <= table_names

        command.downgrade(config, "0007_decision_brief")
        assert "organization_units" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")

        unit_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organization_units (id, unit_code, name, is_active) "
                    "VALUES (:id, 'SYNTHETIC-UNIT', 'Unit sintetis', 1)"
                ),
                {"id": unit_id},
            )

        with pytest.raises(RuntimeError, match="organization scope contains records"):
            command.downgrade(config, "0007_decision_brief")

        with engine.connect() as connection:
            unit_count = connection.execute(
                text("SELECT count(*) FROM organization_units WHERE id = :id"), {"id": unit_id}
            ).scalar_one()
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0008_organization_scope"
        assert unit_count == 1
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_action_item_migration_preserves_minutes_and_protects_task_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "action_items.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0008_organization_scope")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        old_meeting_id, old_revision_id, old_review_id = map(str, (uuid4(), uuid4(), uuid4()))
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, 'legacy-minutes@example.test', 'Historical User', 'synthetic', 1)"
                ),
                {"id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, 'ACTION-HISTORY-001', 'Historical meeting', '2026-10-15', :actor)"
                ),
                {"id": old_meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting, 1, 1, 'Original historical minutes', :actor)"
                ),
                {"id": old_revision_id, "meeting": old_meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_reviews "
                    "(id, meeting_id, minutes_revision_id, reviewer_user_id, "
                    "review_number, result) "
                    "VALUES (:id, :meeting, :revision, :actor, 1, 'VALID')"
                ),
                {
                    "id": old_review_id,
                    "meeting": old_meeting_id,
                    "revision": old_revision_id,
                    "actor": actor_id,
                },
            )

        command.upgrade(config, "head")
        meeting_id, revision_id, agenda_id, discussion_id = map(
            str, (uuid4(), uuid4(), uuid4(), uuid4())
        )
        decision_id, no_action_decision_id, item_id = map(str, (uuid4(), uuid4(), uuid4()))
        assignment_id, progress_id, status_id = map(str, (uuid4(), uuid4(), uuid4()))
        with engine.begin() as connection:
            content, review_count = connection.execute(
                text(
                    "SELECT r.content, (SELECT count(*) FROM minutes_reviews WHERE id = :review) "
                    "FROM minutes_revisions r WHERE r.id = :revision"
                ),
                {"review": old_review_id, "revision": old_revision_id},
            ).one()
            assert content == "Original historical minutes"
            assert review_count == 1
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, 'ACTION-SOURCE-001', 'Task source', '2026-10-15', :actor)"
                ),
                {"id": meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting, 1, 2, NULL, :actor)"
                ),
                {"id": revision_id, "meeting": meeting_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO agendas (id, meeting_id, agenda_number, title) "
                    "VALUES (:id, :meeting, 1, 'Synthetic agenda')"
                ),
                {"id": agenda_id, "meeting": meeting_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_discussions "
                    "(id, meeting_id, minutes_revision_id, agenda_id, discussion_number, content) "
                    "VALUES (:id, :meeting, :revision, :agenda, 1, 'Synthetic discussion')"
                ),
                {
                    "id": discussion_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "agenda": agenda_id,
                },
            )
            for source_id, is_action in ((decision_id, 1), (no_action_decision_id, 0)):
                connection.execute(
                    text(
                        "INSERT INTO minutes_decisions "
                        "(id, meeting_id, minutes_revision_id, discussion_id, decision_number, "
                        "decision_text, is_action_item) "
                        "VALUES (:id, :meeting, :revision, :discussion, :number, "
                        "'Synthetic decision', :is_action)"
                    ),
                    {
                        "id": source_id,
                        "meeting": meeting_id,
                        "revision": revision_id,
                        "discussion": discussion_id,
                        "number": 1 if is_action else 2,
                        "is_action": is_action,
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO action_items "
                    "(id, meeting_id, source_minutes_revision_id, source_decision_id, "
                    "title, description, "
                    "priority, official_status, created_by_id) "
                    "VALUES (:id, :meeting, :revision, :decision, 'Synthetic task', "
                    "'Task description', "
                    "'Penting', 'BELUM_DIMULAI', :actor)"
                ),
                {
                    "id": item_id,
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "decision": decision_id,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO assignments "
                    "(id, action_item_id, assignee_user_id, assigned_by_user_id, assignment_role) "
                    "VALUES (:id, :item, :actor, :actor, 'MAIN')"
                ),
                {"id": assignment_id, "item": item_id, "actor": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO status_histories "
                    "(id, action_item_id, event_number, old_status, new_status, changed_by_id) "
                    "VALUES (:id, :item, 1, NULL, 'BELUM_DIMULAI', :actor)"
                ),
                {"id": status_id, "item": item_id, "actor": actor_id},
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="not actionable"):
            connection.execute(
                text(
                    "INSERT INTO action_items "
                    "(id, meeting_id, source_minutes_revision_id, source_decision_id, "
                    "title, description, "
                    "priority, official_status, created_by_id) "
                    "VALUES (:id, :meeting, :revision, :decision, 'Invalid task', "
                    "'Task description', "
                    "'Penting', 'BELUM_DIMULAI', :actor)"
                ),
                {
                    "id": str(uuid4()),
                    "meeting": meeting_id,
                    "revision": revision_id,
                    "decision": no_action_decision_id,
                    "actor": actor_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "INSERT INTO progress_updates "
                    "(id, action_item_id, assignment_id, actor_user_id, report_text, "
                    "completion_requested) "
                    "VALUES (:id, :item, :assignment, :actor, 'Synthetic progress', 0)"
                ),
                {
                    "id": progress_id,
                    "item": item_id,
                    "assignment": assignment_id,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "UPDATE progress_updates SET report_text = 'Rewritten history' WHERE id = :id"
                ),
                {"id": progress_id},
            )

        with pytest.raises(RuntimeError, match="Action Item history contains records"):
            command.downgrade(config, "0008_organization_scope")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM action_items")).scalar_one() == 1
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0009_action_items"
            )

        command.upgrade(config, "head")
        leadership_progress_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO progress_updates "
                    "(id, action_item_id, assignment_id, actor_user_id, submitted_as, "
                    "report_text, completion_requested) "
                    "VALUES (:id, :item, NULL, :actor, 'LEADERSHIP', "
                    "'Leadership report', 0)"
                ),
                {"id": leadership_progress_id, "item": item_id, "actor": actor_id},
            )
            for index in range(5):
                connection.execute(
                    text(
                        "INSERT INTO action_item_evidence "
                        "(id, action_item_id, progress_update_id, evidence_kind, "
                        "external_url, uploaded_by_user_id) "
                        "VALUES (:id, :item, :progress, 'LINK', :url, :actor)"
                    ),
                    {
                        "id": str(uuid4()),
                        "item": item_id,
                        "progress": leadership_progress_id,
                        "url": f"https://example.test/evidence/{index}",
                        "actor": actor_id,
                    },
                )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="five evidence"):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, "
                    "external_url, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'LINK', "
                    "'https://example.test/evidence/overflow', :actor)"
                ),
                {
                    "id": str(uuid4()),
                    "item": item_id,
                    "progress": leadership_progress_id,
                    "actor": actor_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, "
                    "external_url, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'LINK', 'http://example.test', :actor)"
                ),
                {
                    "id": str(uuid4()),
                    "item": item_id,
                    "progress": leadership_progress_id,
                    "actor": actor_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE action_item_evidence SET link_label = 'rewritten' "
                    "WHERE progress_update_id = :progress"
                ),
                {"progress": leadership_progress_id},
            )

        scan_progress_id, file_evidence_id = map(str, (uuid4(), uuid4()))
        file_sha256 = "a" * 64
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO progress_updates "
                    "(id, action_item_id, assignment_id, actor_user_id, report_text, "
                    "completion_requested) "
                    "VALUES (:id, :item, :assignment, :actor, 'File evidence test', 0)"
                ),
                {
                    "id": scan_progress_id,
                    "item": item_id,
                    "assignment": assignment_id,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence "
                    "(id, action_item_id, progress_update_id, evidence_kind, storage_key, "
                    "original_filename, content_type, size_bytes, sha256, uploaded_by_user_id) "
                    "VALUES (:id, :item, :progress, 'FILE', :key, 'proof.pdf', "
                    "'application/pdf', 14, :sha, :actor)"
                ),
                {
                    "id": file_evidence_id,
                    "item": item_id,
                    "progress": scan_progress_id,
                    "key": uuid4().hex,
                    "sha": file_sha256,
                    "actor": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status) "
                    "VALUES (:id, :evidence, 1, 'PENDING')"
                ),
                {"id": str(uuid4()), "evidence": file_evidence_id},
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="does not match"):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status, scanner_name, "
                    "scanner_version, scanned_sha256) "
                    "VALUES (:id, :evidence, 2, 'CLEAN', 'synthetic', '1', :sha)"
                ),
                {
                    "id": str(uuid4()),
                    "evidence": file_evidence_id,
                    "sha": "b" * 64,
                },
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status, scanner_name, "
                    "scanner_version, scanned_sha256) "
                    "VALUES (:id, :evidence, 2, 'CLEAN', 'synthetic', '1', :sha)"
                ),
                {
                    "id": str(uuid4()),
                    "evidence": file_evidence_id,
                    "sha": file_sha256,
                },
            )

        with (
            engine.begin() as connection,
            pytest.raises(IntegrityError, match="transition is invalid"),
        ):
            connection.execute(
                text(
                    "INSERT INTO action_item_evidence_scans "
                    "(id, evidence_id, event_number, scan_status, scanner_name, "
                    "scanner_version, scanned_sha256) "
                    "VALUES (:id, :evidence, 3, 'REJECTED', 'synthetic', '1', :sha)"
                ),
                {
                    "id": str(uuid4()),
                    "evidence": file_evidence_id,
                    "sha": file_sha256,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE action_item_evidence_scans SET scan_status = 'REJECTED' "
                    "WHERE evidence_id = :evidence"
                ),
                {"evidence": file_evidence_id},
            )

        with pytest.raises(RuntimeError, match="scan history"):
            command.downgrade(config, "0009_action_items")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0011_evidence_scan_quarantine"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM action_item_evidence "
                        "WHERE progress_update_id = :progress"
                    ),
                    {"progress": leadership_progress_id},
                ).scalar_one()
                == 5
            )
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_versioned_minutes_migration_preserves_unbound_historical_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "historical_reviews.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0004_minutes_review")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        review_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "historical-review@example.test",
                    "full_name": "Synthetic Historical Reviewer",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, :meeting_number, :title, :meeting_date, :created_by_id)"
                ),
                {
                    "id": meeting_id,
                    "meeting_number": "HISTORICAL-REVIEW-001",
                    "title": "Synthetic historical review meeting",
                    "meeting_date": "2026-10-15",
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_reviews "
                    "(id, meeting_id, reviewer_user_id, review_number, result) "
                    "VALUES (:id, :meeting_id, :reviewer_user_id, :review_number, :result)"
                ),
                {
                    "id": review_id,
                    "meeting_id": meeting_id,
                    "reviewer_user_id": actor_id,
                    "review_number": 1,
                    "result": "VALID",
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            historical_review = connection.execute(
                text("SELECT id, minutes_revision_id FROM minutes_reviews WHERE id = :id"),
                {"id": review_id},
            ).one()
        assert historical_review.id == review_id
        assert historical_review.minutes_revision_id is None

        command.downgrade(config, "0004_minutes_review")
        with engine.connect() as connection:
            review_count = connection.execute(
                text("SELECT count(*) FROM minutes_reviews WHERE id = :id"), {"id": review_id}
            ).scalar_one()
            review_columns = {
                column["name"] for column in inspect(connection).get_columns("minutes_reviews")
            }
        assert review_count == 1
        assert "minutes_revision_id" not in review_columns

        command.downgrade(config, "base")
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_structured_minutes_migration_preserves_legacy_text_and_bound_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "structured_minutes_upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0005_versioned_minutes")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        revision_id = str(uuid4())
        review_id = str(uuid4())
        original_text = "Synthetic legacy minutes must remain byte-for-byte readable"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "structured-migration@example.test",
                    "full_name": "Synthetic Migration User",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, :meeting_number, :title, :meeting_date, :created_by_id)"
                ),
                {
                    "id": meeting_id,
                    "meeting_number": "STRUCTURED-MIGRATION-001",
                    "title": "Synthetic legacy meeting",
                    "meeting_date": "2026-10-21",
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 1, :content, :created_by_id)"
                ),
                {
                    "id": revision_id,
                    "meeting_id": meeting_id,
                    "content": original_text,
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_reviews "
                    "(id, meeting_id, minutes_revision_id, reviewer_user_id, "
                    "review_number, result) "
                    "VALUES (:id, :meeting_id, :revision_id, :reviewer_id, 1, 'VALID')"
                ),
                {
                    "id": review_id,
                    "meeting_id": meeting_id,
                    "revision_id": revision_id,
                    "reviewer_id": actor_id,
                },
            )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT format_version, content FROM minutes_revisions WHERE id = :id"),
                {"id": revision_id},
            ).one()
            review = connection.execute(
                text("SELECT minutes_revision_id, result FROM minutes_reviews WHERE id = :id"),
                {"id": review_id},
            ).one()
            migration_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()

        assert migration_head == "0027_brief_optional_priority"
        assert (revision.format_version, revision.content) == (1, original_text)
        assert (review.minutes_revision_id, review.result) == (revision_id, "VALID")
        assert {
            "minutes_discussions",
            "minutes_decisions",
        } <= set(inspect(engine).get_table_names())
        decision_columns = {
            column["name"] for column in inspect(engine).get_columns("minutes_decisions")
        }
        assert "pic_suggestion" in decision_columns
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 2, 2, 'invalid structured content', "
                    ":created_by_id)"
                ),
                {
                    "id": str(uuid4()),
                    "meeting_id": meeting_id,
                    "created_by_id": actor_id,
                },
            )
        command.downgrade(config, "0005_versioned_minutes")
        with engine.connect() as connection:
            restored_text = connection.execute(
                text("SELECT content FROM minutes_revisions WHERE id = :id"),
                {"id": revision_id},
            ).scalar_one()
            restored_review = connection.execute(
                text("SELECT minutes_revision_id FROM minutes_reviews WHERE id = :id"),
                {"id": review_id},
            ).scalar_one()
        assert restored_text == original_text
        assert restored_review == revision_id
        command.downgrade(config, "base")
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_structured_minutes_downgrade_refuses_to_drop_structured_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "structured_minutes_downgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        agenda_id = str(uuid4())
        revision_id = str(uuid4())
        discussion_id = str(uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :full_name, :password_hash, :is_active)"
                ),
                {
                    "id": actor_id,
                    "email": "structured-downgrade@example.test",
                    "full_name": "Synthetic Structured Author",
                    "password_hash": "synthetic-only-not-used",
                    "is_active": True,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, :meeting_number, :title, :meeting_date, :created_by_id)"
                ),
                {
                    "id": meeting_id,
                    "meeting_number": "STRUCTURED-DOWNGRADE-001",
                    "title": "Synthetic structured meeting",
                    "meeting_date": "2026-10-21",
                    "created_by_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agendas (id, meeting_id, agenda_number, title) "
                    "VALUES (:id, :meeting_id, 1, 'Synthetic agenda')"
                ),
                {"id": agenda_id, "meeting_id": meeting_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 1, 2, NULL, :created_by_id)"
                ),
                {"id": revision_id, "meeting_id": meeting_id, "created_by_id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_discussions "
                    "(id, meeting_id, minutes_revision_id, agenda_id, discussion_number, content) "
                    "VALUES (:id, :meeting_id, :revision_id, :agenda_id, 1, 'Synthetic discussion')"
                ),
                {
                    "id": discussion_id,
                    "meeting_id": meeting_id,
                    "revision_id": revision_id,
                    "agenda_id": agenda_id,
                },
            )

        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text("UPDATE minutes_discussions SET content = 'silently replaced' WHERE id = :id"),
                {"id": discussion_id},
            )
        with engine.begin() as connection, pytest.raises(IntegrityError):
            connection.execute(
                text("DELETE FROM minutes_discussions WHERE id = :id"),
                {"id": discussion_id},
            )

        with pytest.raises(RuntimeError, match="structured minutes"):
            command.downgrade(config, "0005_versioned_minutes")
        with engine.connect() as connection:
            migration_head = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            text_content = connection.execute(
                text("SELECT content FROM minutes_revisions WHERE id = :id"),
                {"id": revision_id},
            ).scalar_one()
            discussion_count = connection.execute(
                text("SELECT count(*) FROM minutes_discussions WHERE id = :id"),
                {"id": discussion_id},
            ).scalar_one()
        assert migration_head == "0006_structured_minutes"
        assert text_content is None
        assert discussion_count == 1
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_decision_brief_migration_preserves_minutes_and_guards_brief_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "decision_brief_upgrade.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(config, "0006_structured_minutes")
        engine = create_engine(database_url)
        actor_id = str(uuid4())
        meeting_id = str(uuid4())
        revision_id = str(uuid4())
        structured_revision_id = str(uuid4())
        agenda_id = str(uuid4())
        discussion_id = str(uuid4())
        decision_id = str(uuid4())
        original_text = "Synthetic legacy minutes for Decision Brief migration"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, full_name, password_hash, is_active) "
                    "VALUES (:id, :email, :name, :password_hash, :active)"
                ),
                {
                    "id": actor_id,
                    "email": "brief-migration@example.test",
                    "name": "Synthetic Brief User",
                    "password_hash": "synthetic-only-not-used",
                    "active": True,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO meetings (id, meeting_number, title, meeting_date, created_by_id) "
                    "VALUES (:id, :number, :title, :meeting_date, :actor_id)"
                ),
                {
                    "id": meeting_id,
                    "number": "BRIEF-MIGRATION-001",
                    "title": "Synthetic migration meeting",
                    "meeting_date": date(2026, 10, 21),
                    "actor_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 1, 1, :content, :actor_id)"
                ),
                {
                    "id": revision_id,
                    "meeting_id": meeting_id,
                    "content": original_text,
                    "actor_id": actor_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO agendas (id, meeting_id, agenda_number, title) "
                    "VALUES (:id, :meeting_id, 1, 'Synthetic structured agenda')"
                ),
                {"id": agenda_id, "meeting_id": meeting_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_revisions "
                    "(id, meeting_id, revision_number, format_version, content, created_by_id) "
                    "VALUES (:id, :meeting_id, 2, 2, NULL, :actor_id)"
                ),
                {"id": structured_revision_id, "meeting_id": meeting_id, "actor_id": actor_id},
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_discussions "
                    "(id, meeting_id, minutes_revision_id, agenda_id, discussion_number, content) "
                    "VALUES (:id, :meeting_id, :revision_id, :agenda_id, 1, 'Synthetic discussion')"
                ),
                {
                    "id": discussion_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                    "agenda_id": agenda_id,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO minutes_decisions "
                    "(id, meeting_id, minutes_revision_id, discussion_id, "
                    "decision_number, decision_text) "
                    "VALUES (:id, :meeting_id, :revision_id, :discussion_id, "
                    "1, 'Synthetic decision')"
                ),
                {
                    "id": decision_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                    "discussion_id": discussion_id,
                },
            )

        command.upgrade(config, "head")
        with engine.begin() as connection:
            version_id = str(uuid4())
            version_row = connection.execute(
                text(
                    "INSERT INTO decision_brief_versions "
                    "(id, meeting_id, source_minutes_revision_id, version_number, summary, "
                    "created_by_id) VALUES (:id, :meeting_id, :revision_id, 1, :summary, :actor_id)"
                ),
                {
                    "id": version_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                    "summary": "Synthetic editorial brief",
                    "actor_id": actor_id,
                },
            )
            entry_row = connection.execute(
                text(
                    "INSERT INTO decision_brief_decisions "
                    "(brief_version_id, source_decision_id, meeting_id, "
                    "source_minutes_revision_id, position, priority) "
                    "VALUES (:version_id, :decision_id, :meeting_id, :revision_id, 1, 'Utama')"
                ),
                {
                    "version_id": version_id,
                    "decision_id": decision_id,
                    "meeting_id": meeting_id,
                    "revision_id": structured_revision_id,
                },
            )
            stored_text = connection.execute(
                text("SELECT content FROM minutes_revisions WHERE id = :revision_id"),
                {"revision_id": revision_id},
            ).scalar_one()
            assert stored_text == original_text

        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE decision_brief_versions SET summary = 'changed' WHERE meeting_id = :id"
                ),
                {"id": meeting_id},
            )
        with engine.begin() as connection, pytest.raises(IntegrityError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE decision_brief_decisions SET priority = 'changed' "
                    "WHERE meeting_id = :id"
                ),
                {"id": meeting_id},
            )

        with pytest.raises(RuntimeError, match="Decision Brief version history"):
            command.downgrade(config, "0006_structured_minutes")

        assert version_row.rowcount == 1
        assert entry_row.rowcount == 1
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0007_decision_brief"
            )
        engine.dispose()
    finally:
        get_settings.cache_clear()
