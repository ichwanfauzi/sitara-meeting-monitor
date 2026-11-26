from collections.abc import Iterator
from typing import NotRequired, TypedDict
from uuid import UUID, uuid4

import pytest
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditEvent
from app.models.auth import Role, User
from app.models.meeting import (
    Agenda,
    DecisionBriefApprovalEvent,
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    MeetingStatusEvent,
    MinutesDecision,
    MinutesReview,
    MinutesRevision,
)
from app.schemas.audit import AuditEventCreate
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapper, Session
from sqlalchemy.pool import StaticPool


class MeetingResponse(TypedDict):
    id: str
    status: str
    meeting_number: str
    version: NotRequired[int]
    notetaker_id: NotRequired[str | None]
    agendas: list[object]
    participants: list[object]


class DecisionPayload(TypedDict):
    decision_text: str
    output_expected: str
    target_date: str
    is_action_item: bool
    pic_suggestion: NotRequired[str]
    proposed_pic_user_id: NotRequired[str]


class DiscussionPayload(TypedDict):
    agenda_id: str
    subject: str
    content: str
    decisions: list[DecisionPayload]


class StructuredMinutesPayload(TypedDict):
    format_version: int
    content: str | None
    base_revision_id: str | None
    discussions: list[DiscussionPayload]


@pytest.fixture
def meeting_context() -> Iterator[tuple[Session, dict[str, User]]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)

    users: dict[str, User] = {}
    role_names = {
        "secretariat": ("SEKRETARIAT", "Sekretariat"),
        "manager_legal": ("MANAGER_LEGAL", "Manager Legal"),
        "rector": ("REKTOR", "Rektor"),
        "other_rector": ("REKTOR", "Rektor"),
        "warek": ("WAREK", "Wakil Rektor"),
        "pic": ("PIC", "PIC"),
        "super_admin": ("SUPER_ADMIN", "Super Admin"),
    }
    roles = {
        code: Role(role_code=code, role_name=name)
        for code, name in {value for value in role_names.values()}
    }
    session.add_all(roles.values())

    for key, (role_code, _) in role_names.items():
        user = User(
            email=f"{key}@example.test",
            full_name=key.replace("_", " ").title(),
            password_hash=hash_password("synthetic-password"),
            is_active=True,
        )
        user.roles.append(roles[role_code])
        users[key] = user
    session.add_all(users.values())
    session.commit()
    app.dependency_overrides[get_db] = lambda: session

    try:
        yield session, users
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def login(client: TestClient, user: User) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "synthetic-password"},
    )
    assert response.status_code == 200
    csrf_token = client.cookies.get("sitara_csrf")
    assert csrf_token
    client.headers.update({"X-CSRF-Token": csrf_token})


def create_meeting(
    client: TestClient,
    chairperson_id: UUID | None = None,
    meeting_number: str = "RAPIM-2026-001",
    notetaker_id: UUID | None = None,
) -> MeetingResponse:
    request_payload = {
        "meeting_number": meeting_number,
        "title": "Rapat koordinasi program",
        "meeting_date": "2026-10-15",
        "start_time": "09:00:00",
        "end_time": "10:00:00",
        "location": "Ruang rapat utama",
    }
    if notetaker_id is not None:
        request_payload["notetaker_id"] = str(notetaker_id)
    response = client.post(
        "/api/v1/meetings",
        json=request_payload,
    )
    assert response.status_code == 201
    payload: object = response.json()
    if not isinstance(payload, dict):
        pytest.fail("Meeting response must be an object", pytrace=False)
    identifier = payload.get("id")
    status = payload.get("status")
    returned_number = payload.get("meeting_number")
    agendas = payload.get("agendas")
    participants = payload.get("participants")
    if (
        not isinstance(identifier, str)
        or not isinstance(status, str)
        or not isinstance(returned_number, str)
        or not isinstance(agendas, list)
        or not isinstance(participants, list)
    ):
        pytest.fail("Meeting response has an invalid shape", pytrace=False)
    result: MeetingResponse = {
        "id": identifier,
        "status": status,
        "meeting_number": returned_number,
        "agendas": agendas,
        "participants": participants,
    }
    version = payload.get("version")
    if isinstance(version, int):
        result["version"] = version
    notetaker_id = payload.get("notetaker_id")
    if notetaker_id is None or isinstance(notetaker_id, str):
        result["notetaker_id"] = notetaker_id
    return result


def create_minutes_revision(
    client: TestClient, meeting_url: str, content: str = "Pokok bahasan rapat"
) -> dict[str, object]:
    response = client.post(
        f"{meeting_url}/minutes-revisions",
        json={"content": content, "base_revision_id": None},
    )
    assert response.status_code == 201
    payload: object = response.json()
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        pytest.fail("Minutes revision response must be an object", pytrace=False)
    return {key: value for key, value in payload.items() if isinstance(key, str)}


def test_meeting_creation_records_selected_notetaker(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(
            client,
            meeting_number="RAPIM-NOTETAKER-001",
            notetaker_id=users["warek"].id,
        )

    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.notetaker_id == users["warek"].id
    assert meeting_data["notetaker_id"] == str(users["warek"].id)


@pytest.mark.parametrize("user_key", ["pic", "super_admin"])
def test_meeting_creation_rejects_restricted_notetaker(
    meeting_context: tuple[Session, dict[str, User]], user_key: str
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        response = client.post(
            "/api/v1/meetings",
            json={
                "meeting_number": "RAPIM-RESTRICTED-NOTETAKER",
                "title": "Rapat koordinasi program",
                "meeting_date": "2026-10-15",
                "notetaker_id": str(users[user_key].id),
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Selected notetaker must be an active core user"
    assert (
        session.scalar(
            select(Meeting).where(Meeting.meeting_number == "RAPIM-RESTRICTED-NOTETAKER")
        )
        is None
    )


def test_meeting_creation_rejects_inactive_notetaker(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    users["warek"].is_active = False
    session.commit()

    with TestClient(app) as client:
        login(client, users["secretariat"])
        response = client.post(
            "/api/v1/meetings",
            json={
                "meeting_number": "RAPIM-INACTIVE-NOTETAKER",
                "title": "Rapat koordinasi program",
                "meeting_date": "2026-10-15",
                "notetaker_id": str(users["warek"].id),
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Selected notetaker must be an active core user"
    assert (
        session.scalar(select(Meeting).where(Meeting.meeting_number == "RAPIM-INACTIVE-NOTETAKER"))
        is None
    )


def test_meeting_metadata_mutations_require_csrf_and_do_not_write(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)
        client.headers.pop("X-CSRF-Token")

        unauthorized_meeting = client.post(
            "/api/v1/meetings",
            json={
                "meeting_number": "RAPIM-2026-002",
                "title": "Rapat tanpa token CSRF",
                "meeting_date": "2026-10-15",
            },
        )
        unauthorized_agenda = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/agendas",
            json={"title": "Agenda tanpa token CSRF"},
        )
        unauthorized_participant = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/participants",
            json={"user_id": str(users["warek"].id)},
        )

        assert unauthorized_meeting.status_code == 403
        assert unauthorized_agenda.status_code == 403
        assert unauthorized_participant.status_code == 403
        assert session.query(Meeting).count() == 1
        assert session.query(Agenda).count() == 0
        assert session.query(MeetingParticipant).count() == 0


def test_secretariat_can_create_and_read_meeting_agenda_and_participants(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, users["rector"].id)

        assert meeting_data["status"] == "DRAFT"
        assert meeting_data["meeting_number"] == "RAPIM-2026-001"
        assert meeting_data["agendas"] == []
        assert meeting_data["participants"] == []

        agenda_response = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/agendas",
            json={
                "title": "Evaluasi program prioritas",
                "agenda_description": "Tinjau tindak lanjut periode berjalan",
                "duration_minutes": 30,
            },
        )
        assert agenda_response.status_code == 201
        assert agenda_response.json()["agenda_number"] == 1
        next_agenda = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/agendas",
            json={"title": "Agenda berikutnya"},
        )
        assert next_agenda.status_code == 201
        assert next_agenda.json()["agenda_number"] == 2

        participant_response = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/participants",
            json={"user_id": str(users["warek"].id)},
        )
        assert participant_response.status_code == 201
        assert participant_response.json()["participant_name"] == users["warek"].full_name
        duplicate_participant = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/participants",
            json={"user_id": str(users["warek"].id)},
        )
        assert duplicate_participant.status_code == 409

        detail = client.get(f"/api/v1/meetings/{meeting_data['id']}")
        assert detail.status_code == 200
        assert detail.json()["agendas"][0]["title"] == "Evaluasi program prioritas"
        assert detail.json()["participants"][0]["user_id"] == str(users["warek"].id)
        assert session.query(Meeting).count() == 1
        assert session.query(MeetingParticipant).count() == 1


def test_authorized_meeting_metadata_update_is_versioned_and_audited(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, users["rector"].id)
        response = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={
                "expected_version": 1,
                "title": "Judul rapat diperbarui",
                "location": "Ruang rapat baru",
            },
        )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["title"] == "Judul rapat diperbarui"
    assert response.json()["location"] == "Ruang rapat baru"
    assert response.headers["x-correlation-id"]
    audit_event = session.query(AuditEvent).filter_by(action="meeting.metadata_updated").one()
    assert audit_event.actor_user_id == users["secretariat"].id
    assert audit_event.actor_roles == ["SEKRETARIAT"]
    assert str(audit_event.correlation_id) == response.headers["x-correlation-id"]
    assert audit_event.before_values == {
        "title": "Rapat koordinasi program",
        "location": "Ruang rapat utama",
    }
    assert audit_event.after_values == {
        "title": "Judul rapat diperbarui",
        "location": "Ruang rapat baru",
    }


def test_live_agenda_and_participant_changes_are_scoped_versioned_and_audited(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretary_client:
        login(secretary_client, users["secretariat"])
        meeting_data = create_meeting(secretary_client, users["rector"].id)
        live = secretary_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )
        agenda = secretary_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/agendas",
            json={"title": "Agenda LIVE"},
        )
        participant = secretary_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/participants",
            json={"user_id": str(users["warek"].id)},
        )
        assert live.status_code == 200
        assert agenda.status_code == 201
        assert participant.status_code == 201
        version = live.json()["version"] + 2

        updated_agenda = secretary_client.put(
            f"/api/v1/meetings/{meeting_data['id']}/agendas/{agenda.json()['id']}",
            json={
                "expected_version": version,
                "title": "Agenda LIVE diperbarui",
                "agenda_description": None,
                "pic_suggestion": None,
                "supporting_pic_suggestion": None,
                "duration_minutes": None,
            },
        )
        assert updated_agenda.status_code == 200
        assert updated_agenda.json()["title"] == "Agenda LIVE diperbarui"
        version += 1

        removed_participant = secretary_client.delete(
            f"/api/v1/meetings/{meeting_data['id']}/participants/{users['warek'].id}",
            params={"expected_version": version},
        )
        assert removed_participant.status_code == 204
        version += 1

        removed_agenda = secretary_client.delete(
            f"/api/v1/meetings/{meeting_data['id']}/agendas/{agenda.json()['id']}",
            params={"expected_version": version},
        )

    assert removed_agenda.status_code == 204
    assert session.query(MeetingParticipant).count() == 0
    assert session.query(Agenda).count() == 0
    change_events = (
        session.query(AuditEvent)
        .filter(AuditEvent.action.in_(("meeting.agenda_changed", "meeting.participant_changed")))
        .all()
    )
    assert len(change_events) == 5


def test_notetaker_attribution_has_no_handover_endpoint(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretary_client:
        login(secretary_client, users["secretariat"])
        meeting_data = create_meeting(
            secretary_client,
            chairperson_id=users["rector"].id,
            notetaker_id=users["secretariat"].id,
        )
        secretary_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )
        handover = secretary_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/notetaker-handovers",
            json={"new_notetaker_id": str(users["other_rector"].id)},
        )
    assert handover.status_code == 404
    updated_meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert updated_meeting is not None
    assert updated_meeting.notetaker_id == users["secretariat"].id
    actions = set(
        session.scalars(
            select(AuditEvent.action).where(AuditEvent.action.like("meeting.notetaker_handover_%"))
        )
    )
    assert actions == set()


def test_meeting_reads_are_global_but_lifecycle_changes_remain_restricted(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client, users["rector"].id)
        secretariat_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/participants",
            json={"user_id": str(users["warek"].id)},
        )

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        assert [item["id"] for item in rector_client.get("/api/v1/meetings").json()] == [
            meeting_data["id"]
        ]
        assert rector_client.get(f"/api/v1/meetings/{meeting_data['id']}").status_code == 200

    with TestClient(app) as unrelated_rector_client:
        login(unrelated_rector_client, users["other_rector"])
        assert [item["id"] for item in unrelated_rector_client.get("/api/v1/meetings").json()] == [
            meeting_data["id"]
        ]
        assert (
            unrelated_rector_client.get(f"/api/v1/meetings/{meeting_data['id']}").status_code == 200
        )
        assert (
            unrelated_rector_client.post(
                f"/api/v1/meetings/{meeting_data['id']}/transition",
                json={"to_status": "LIVE"},
            ).status_code
            == 403
        )

    with TestClient(app) as warek_client:
        login(warek_client, users["warek"])
        assert warek_client.get(f"/api/v1/meetings/{meeting_data['id']}").status_code == 200

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        agenda_response = rector_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/agendas",
            json={"title": "Tidak dibuat oleh pemilik"},
        )
        assert agenda_response.status_code == 403


def test_meeting_mutation_rolls_back_when_audit_writer_fails(
    meeting_context: tuple[Session, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, users["rector"].id)

        def fail_audit(*args: object, **kwargs: object) -> None:
            raise SQLAlchemyError("synthetic audit write failure")

        monkeypatch.setattr("app.services.meetings.append_meeting_change_event", fail_audit)
        response = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={"expected_version": 1, "title": "Tidak boleh tersimpan"},
        )

    session.expire_all()
    persisted = session.get(Meeting, UUID(meeting_data["id"]))
    assert response.status_code == 500
    assert persisted is not None
    assert persisted.title == "Rapat koordinasi program"
    assert persisted.version == 1
    assert session.query(AuditEvent).filter_by(action="meeting.metadata_updated").count() == 0


def test_meeting_metadata_rejects_stale_version_and_allows_number_changes(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, users["rector"].id)
        first_update = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={"expected_version": 1, "title": "Judul baru"},
        )
        stale_update = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={"expected_version": 1, "location": "Lokasi baru"},
        )
        number_update = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={"expected_version": 2, "meeting_number": "RAPIM-RENUMBERED"},
        )

    assert first_update.status_code == 200
    assert stale_update.status_code == 409
    assert number_update.status_code == 200
    assert number_update.json()["meeting_number"] == "RAPIM-RENUMBERED"


def test_archived_meeting_rejects_all_metadata_changes_and_keeps_audit_unchanged(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)
        meeting = session.get(Meeting, UUID(meeting_data["id"]))
        assert meeting is not None
        meeting.started_at = meeting.created_at
        meeting.finalized_at = meeting.created_at
        meeting.finalized_by_id = users["secretariat"].id
        meeting.status = MeetingStatus.ARCHIVED
        session.commit()

        number_update = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={"expected_version": meeting.version, "meeting_number": "RAPIM-RENAMED"},
        )
        title_update = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={"expected_version": meeting.version, "title": "Judul yang tidak boleh berubah"},
        )

    session.expire_all()
    persisted = session.get(Meeting, UUID(meeting_data["id"]))
    assert number_update.status_code == 409
    assert title_update.status_code == 409
    assert persisted is not None
    assert persisted.meeting_number == "RAPIM-2026-001"
    assert persisted.title == "Rapat koordinasi program"
    assert session.query(AuditEvent).filter_by(action="meeting.metadata_updated").count() == 0


def test_archived_meeting_rejects_new_decision_brief_snapshots(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(f"{meeting_url}/agendas", json={"title": "Agenda sintetis"})
        assert agenda.status_code == 201
        started = client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        assert started.status_code == 200
        minutes_payload = _structured_minutes_payload(agenda.json()["id"])
        saved_minutes = client.post(f"{meeting_url}/minutes-revisions", json=minutes_payload)
        assert saved_minutes.status_code == 201
        revision = saved_minutes.json()
        decision_id = revision["discussions"][0]["decisions"][0]["id"]
        meeting = session.get(Meeting, UUID(meeting_data["id"]))
        assert meeting is not None
        meeting.started_at = meeting.created_at
        meeting.finalized_at = meeting.created_at
        meeting.finalized_by_id = users["secretariat"].id
        meeting.status = MeetingStatus.ARCHIVED
        session.commit()

        response = client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": revision["id"],
                "summary": "Ringkasan sintetis yang tidak boleh disimpan",
                "decisions": [{"decision_id": decision_id, "priority": "Utama"}],
            },
        )
        history = client.get(f"{meeting_url}/decision-briefs")

    assert response.status_code == 409
    assert history.status_code == 200
    assert history.json() == []
    assert session.query(AuditEvent).filter_by(action="decision_brief.saved").count() == 0


def test_live_notetaker_cannot_be_changed_without_handover(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        live = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )
        response = client.patch(
            f"/api/v1/meetings/{meeting_data['id']}",
            json={
                "expected_version": live.json()["version"],
                "notetaker_id": str(users["warek"].id),
            },
        )

    session.expire_all()
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert response.status_code == 422
    assert meeting is not None
    assert meeting.notetaker_id == users["secretariat"].id


def test_agenda_referenced_by_minutes_cannot_be_removed(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(
            f"{meeting_url}/agendas",
            json={"title": "Agenda sumber"},
        )
        live = client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        revision = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda.json()["id"]),
        )
        response = client.delete(
            f"{meeting_url}/agendas/{agenda.json()['id']}",
            params={"expected_version": live.json()["version"]},
        )

    assert revision.status_code == 201
    assert response.status_code == 409
    assert session.get(Agenda, UUID(agenda.json()["id"])) is not None


def test_mixed_pic_and_secretariat_role_does_not_grant_meeting_mutation(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretary_client:
        login(secretary_client, users["secretariat"])
        meeting_data = create_meeting(secretary_client)

    pic_role = session.query(Role).filter_by(role_code="PIC").one()
    for role_code in ("SEKRETARIAT", "MANAGER_LEGAL"):
        operational_role = session.query(Role).filter_by(role_code=role_code).one()
        users["pic"].roles = [pic_role, operational_role]
        session.commit()

        with TestClient(app) as pic_client:
            login(pic_client, users["pic"])
            response = pic_client.patch(
                f"/api/v1/meetings/{meeting_data['id']}",
                json={"expected_version": 1, "title": "Tidak berizin"},
            )

        assert response.status_code == 404


@pytest.mark.parametrize("user_key", ["pic", "super_admin"])
def test_pic_and_super_admin_cannot_access_meeting_api(
    meeting_context: tuple[Session, dict[str, User]], user_key: str
) -> None:
    _, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client)

    with TestClient(app) as client:
        login(client, users[user_key])

        assert client.get("/api/v1/meetings").status_code == 403
        assert client.get(f"/api/v1/meetings/{meeting_data['id']}").status_code == 404
        assert (
            client.post(
                "/api/v1/meetings",
                json={
                    "meeting_number": "RAPIM-2026-002",
                    "title": "Tidak berizin",
                    "meeting_date": "2026-10-15",
                },
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/meetings/{meeting_data['id']}/transition",
                json={"to_status": "LIVE"},
            ).status_code
            == 404
        )


def test_super_admin_cannot_inherit_meeting_access_from_secretariat_role(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client)

    users["super_admin"].roles.append(users["secretariat"].roles[0])
    session.commit()

    with TestClient(app) as client:
        login(client, users["super_admin"])

        assert client.get("/api/v1/meetings").status_code == 403
        assert client.get(f"/api/v1/meetings/{meeting_data['id']}").status_code == 404
        assert (
            client.post(
                f"/api/v1/meetings/{meeting_data['id']}/transition",
                json={"to_status": "LIVE"},
            ).status_code
            == 404
        )


def test_meeting_create_validates_business_fields_and_rejects_status_override(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        base_payload = {
            "meeting_number": "RAPIM-2026-003",
            "title": "Rapat validasi",
            "meeting_date": "2026-10-15",
        }

        blank_title = client.post("/api/v1/meetings", json={**base_payload, "title": "  "})
        assert blank_title.status_code == 422

        invalid_time = client.post(
            "/api/v1/meetings",
            json={**base_payload, "start_time": "11:00:00", "end_time": "10:00:00"},
        )
        assert invalid_time.status_code == 422

        status_override = client.post("/api/v1/meetings", json={**base_payload, "status": "FINAL"})
        assert status_override.status_code == 422

        created = client.post("/api/v1/meetings", json=base_payload)
        assert created.status_code == 201
        duplicate = client.post("/api/v1/meetings", json=base_payload)
        assert duplicate.status_code == 409


def test_unauthenticated_cannot_list_meetings(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/meetings").status_code == 401


def test_secretariat_can_start_a_draft_meeting(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)

        response = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "LIVE"
        meeting = session.get(Meeting, UUID(meeting_data["id"]))
        assert meeting is not None
        assert meeting.started_at is not None
        event = session.query(MeetingStatusEvent).one()
        assert (event.from_status, event.to_status) == ("DRAFT", "LIVE")
        assert event.actor_user_id == users["secretariat"].id


def test_unauthenticated_user_cannot_transition_meeting(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )
    assert response.status_code == 401


def test_only_secretariat_or_manager_legal_can_transition_a_meeting_and_csrf_is_required(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client, users["rector"].id)

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        response = rector_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )
        assert response.status_code == 403

    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        secretariat_client.headers.pop("X-CSRF-Token")
        no_csrf = secretariat_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )
        assert no_csrf.status_code == 403

    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.DRAFT
    assert session.query(MeetingStatusEvent).count() == 0


def test_manager_legal_can_start_review_and_finalize_a_meeting(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["manager_legal"])
        meeting_data = create_meeting(client)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        started = client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        revision = create_minutes_revision(client, meeting_url)
        review = client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision["id"], "result": "VALID"},
        )
        finalized = client.post(f"{meeting_url}/transition", json={"to_status": "FINAL"})

    assert started.status_code == 200, started.text
    assert review.status_code == 201, review.text
    assert review.json()["reviewer_user_id"] == str(users["manager_legal"].id)
    assert finalized.status_code == 200, finalized.text
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.FINAL


def test_finalization_requires_verifiable_minutes_review_and_illegal_transitions_are_rejected(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)
        transition_url = f"/api/v1/meetings/{meeting_data['id']}/transition"

        same_status = client.post(transition_url, json={"to_status": "DRAFT"})
        illegal_skip = client.post(transition_url, json={"to_status": "ARCHIVED"})
        started = client.post(transition_url, json={"to_status": "LIVE"})
        finalization = client.post(transition_url, json={"to_status": "FINAL"})
        invalid_target = client.post(transition_url, json={"to_status": "CANCELLED"})
        extra_status = client.post(transition_url, json={"to_status": "LIVE", "status": "ARCHIVED"})

    assert same_status.status_code == 409
    assert illegal_skip.status_code == 409
    assert started.status_code == 200
    assert finalization.status_code == 409
    assert "active minutes revision" in finalization.json()["detail"].casefold()
    assert invalid_target.status_code == 422
    assert extra_status.status_code == 422
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.LIVE
    assert session.query(MeetingStatusEvent).count() == 1
    assert session.query(MinutesReview).count() == 0


def test_secretariat_minutes_review_is_attributable_and_unlocks_finalization(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        started = client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        assert started.status_code == 200
        revision = create_minutes_revision(client, meeting_url)

        review = client.post(
            f"{meeting_url}/minutes-reviews",
            json={
                "minutes_revision_id": revision["id"],
                "result": "VALID",
                "review_note": "Pemeriksaan selesai",
            },
        )
        assert review.status_code == 201
        review_data = review.json()
        assert review_data["meeting_id"] == meeting_data["id"]
        assert review_data["reviewer_user_id"] == str(users["secretariat"].id)
        assert review_data["review_number"] == 1
        assert review_data["result"] == "VALID"
        assert review_data["reviewed_at"]
        assert review_data["review_note"] == "Pemeriksaan selesai"
        review_history = client.get(f"{meeting_url}/minutes-reviews")
        assert review_history.status_code == 200
        assert review_history.json() == [review_data]

        finalized = client.post(f"{meeting_url}/transition", json={"to_status": "FINAL"})

    assert finalized.status_code == 200
    assert finalized.json()["status"] == "FINAL"
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.finalized_at is not None
    assert meeting.finalized_by_id == users["secretariat"].id
    assert session.query(MeetingStatusEvent).count() == 2


def test_latest_invalid_minutes_review_blocks_finalization_until_rechecked(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        assert (
            client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"}).status_code == 200
        )
        revision = create_minutes_revision(client, meeting_url)

        rejected = client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision["id"], "result": "INVALID"},
        )
        blocked = client.post(f"{meeting_url}/transition", json={"to_status": "FINAL"})
        assert rejected.status_code == 201
        assert blocked.status_code == 409
        assert "minutes review" in blocked.json()["detail"].casefold()

        approved = client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision["id"], "result": "VALID"},
        )
        assert approved.status_code == 201
        assert approved.json()["review_number"] == 2
        finalized = client.post(f"{meeting_url}/transition", json={"to_status": "FINAL"})

    assert finalized.status_code == 200
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.FINAL
    assert session.query(MeetingStatusEvent).count() == 2


def test_minutes_review_cannot_unlock_a_different_meeting(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        reviewed_meeting = create_meeting(client, notetaker_id=users["secretariat"].id)
        target_meeting = create_meeting(
            client,
            meeting_number="RAPIM-2026-002",
            notetaker_id=users["secretariat"].id,
        )
        reviewed_url = f"/api/v1/meetings/{reviewed_meeting['id']}"
        target_url = f"/api/v1/meetings/{target_meeting['id']}"
        assert (
            client.post(f"{reviewed_url}/transition", json={"to_status": "LIVE"}).status_code == 200
        )
        assert (
            client.post(f"{target_url}/transition", json={"to_status": "LIVE"}).status_code == 200
        )
        reviewed_revision = create_minutes_revision(client, reviewed_url)
        review = client.post(
            f"{reviewed_url}/minutes-reviews",
            json={"minutes_revision_id": reviewed_revision["id"], "result": "VALID"},
        )
        wrong_meeting_review = client.post(
            f"{target_url}/minutes-reviews",
            json={"minutes_revision_id": reviewed_revision["id"], "result": "VALID"},
        )
        finalization = client.post(f"{target_url}/transition", json={"to_status": "FINAL"})

    assert review.status_code == 201
    assert wrong_meeting_review.status_code == 409
    assert finalization.status_code == 409
    target = session.get(Meeting, UUID(target_meeting["id"]))
    assert target is not None
    assert target.status is MeetingStatus.LIVE
    assert session.query(MeetingStatusEvent).count() == 2


def test_minutes_review_requires_authentication_csrf_and_operational_authority(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client, users["rector"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "LIVE"}
            ).status_code
            == 200
        )
        secretariat_client.headers.pop("X-CSRF-Token")
        missing_csrf = secretariat_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": str(UUID(int=0)), "result": "VALID"},
        )
        assert missing_csrf.status_code == 403

    with TestClient(app) as anonymous_client:
        unauthenticated = anonymous_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": str(UUID(int=0)), "result": "VALID"},
        )
        unauthenticated_history = anonymous_client.get(f"{meeting_url}/minutes-reviews")
        assert unauthenticated.status_code == 401
        assert unauthenticated_history.status_code == 401

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        unauthorized_role = rector_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": str(UUID(int=0)), "result": "VALID"},
        )
        assert unauthorized_role.status_code == 403
        unauthorized_history = rector_client.get(f"{meeting_url}/minutes-reviews")
        assert unauthorized_history.status_code == 403

    with TestClient(app) as admin_client:
        users["super_admin"].roles.append(users["secretariat"].roles[0])
        session.commit()
        login(admin_client, users["super_admin"])
        super_admin = admin_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": str(UUID(int=0)), "result": "VALID"},
        )
        super_admin_history = admin_client.get(f"{meeting_url}/minutes-reviews")
        assert super_admin.status_code == 404
        assert super_admin_history.status_code == 404

    assert session.query(MeetingStatusEvent).count() == 1
    assert session.query(MinutesReview).count() == 0


def test_manager_legal_minutes_review_requires_live_meeting_and_valid_result(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client)

    with TestClient(app) as unrelated_rector_client:
        login(unrelated_rector_client, users["other_rector"])
        inaccessible = unrelated_rector_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/minutes-reviews",
            json={"minutes_revision_id": str(UUID(int=0)), "result": "VALID"},
        )
        assert inaccessible.status_code == 403

    with TestClient(app) as manager_client:
        login(manager_client, users["manager_legal"])
        not_live = manager_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/minutes-reviews",
            json={"minutes_revision_id": str(UUID(int=0)), "result": "VALID"},
        )
        invalid_result = manager_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/minutes-reviews",
            json={"minutes_revision_id": str(UUID(int=0)), "result": "PENDING"},
        )

    assert not_live.status_code == 409
    assert invalid_result.status_code == 422
    assert session.query(MinutesReview).count() == 0


@pytest.mark.parametrize("operator_name", ["secretariat", "manager_legal"])
def test_operational_manager_can_archive_final_meeting_and_event_is_atomic(
    meeting_context: tuple[Session, dict[str, User]],
    operator_name: str,
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users[operator_name])
        meeting_data = create_meeting(client)
        meeting = session.get(Meeting, UUID(meeting_data["id"]))
        assert meeting is not None
        meeting.status = MeetingStatus.FINAL
        meeting.finalized_at = meeting.created_at
        meeting.finalized_by_id = users[operator_name].id
        session.commit()

        response = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "ARCHIVED"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ARCHIVED"
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.ARCHIVED
    event = session.query(MeetingStatusEvent).one()
    assert (event.from_status, event.to_status) == ("FINAL", "ARCHIVED")


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        (MeetingStatus.DRAFT, MeetingStatus.FINAL),
        (MeetingStatus.DRAFT, MeetingStatus.ARCHIVED),
        (MeetingStatus.LIVE, MeetingStatus.DRAFT),
        (MeetingStatus.LIVE, MeetingStatus.ARCHIVED),
        (MeetingStatus.FINAL, MeetingStatus.DRAFT),
        (MeetingStatus.FINAL, MeetingStatus.LIVE),
        (MeetingStatus.ARCHIVED, MeetingStatus.DRAFT),
        (MeetingStatus.ARCHIVED, MeetingStatus.LIVE),
        (MeetingStatus.ARCHIVED, MeetingStatus.FINAL),
    ],
)
def test_all_other_status_transitions_are_rejected(
    meeting_context: tuple[Session, dict[str, User]],
    from_status: MeetingStatus,
    to_status: MeetingStatus,
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)
        meeting = session.get(Meeting, UUID(meeting_data["id"]))
        assert meeting is not None
        meeting.status = from_status
        if from_status in {MeetingStatus.LIVE, MeetingStatus.FINAL, MeetingStatus.ARCHIVED}:
            meeting.started_at = meeting.created_at
        if from_status in {MeetingStatus.FINAL, MeetingStatus.ARCHIVED}:
            meeting.finalized_at = meeting.created_at
            meeting.finalized_by_id = users["secretariat"].id
        session.commit()

        response = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": to_status.value},
        )

    assert response.status_code == 409
    assert meeting.status is from_status
    assert session.query(MeetingStatusEvent).count() == 0


def test_core_user_appends_revision_and_stale_base_is_rejected(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as secretariat_client, TestClient(app) as notetaker_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(
            secretariat_client,
            meeting_number="RAPIM-REV-001",
            notetaker_id=users["rector"].id,
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "LIVE"}
            ).status_code
            == 200
        )

        login(notetaker_client, users["rector"])
        revision_url = f"{meeting_url}/minutes-revisions"
        first = notetaker_client.post(
            revision_url,
            json={"content": "Pokok bahasan versi pertama", "base_revision_id": None},
        )
        assert first.status_code == 201
        first_data = first.json()
        assert first_data["revision_number"] == 1
        assert first_data["created_by_id"] == str(users["rector"].id)

        second = notetaker_client.post(
            revision_url,
            json={
                "content": "Pokok bahasan versi kedua",
                "base_revision_id": first_data["id"],
            },
        )
        assert second.status_code == 201
        assert second.json()["revision_number"] == 2

        stale = notetaker_client.post(
            revision_url,
            json={
                "content": "Perubahan dari versi lama",
                "base_revision_id": first_data["id"],
            },
        )
        history = notetaker_client.get(revision_url)

    assert stale.status_code == 409
    assert history.status_code == 200
    assert [revision["content"] for revision in history.json()] == [
        "Pokok bahasan versi pertama",
        "Pokok bahasan versi kedua",
    ]


def test_revision_change_makes_review_stale_until_latest_revision_is_reviewed(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with (
        TestClient(app) as secretariat_client,
        TestClient(app) as notetaker_client,
    ):
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(
            secretariat_client,
            meeting_number="RAPIM-REV-002",
            notetaker_id=users["rector"].id,
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "LIVE"}
            ).status_code
            == 200
        )

        login(notetaker_client, users["rector"])
        revision_url = f"{meeting_url}/minutes-revisions"
        revision_one = notetaker_client.post(
            revision_url,
            json={"content": "Notulen awal", "base_revision_id": None},
        )
        assert revision_one.status_code == 201
        revision_one_id = revision_one.json()["id"]

        first_review = secretariat_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision_one_id, "result": "VALID"},
        )
        assert first_review.status_code == 201

        revision_two = notetaker_client.post(
            revision_url,
            json={"content": "Notulen diperbarui", "base_revision_id": revision_one_id},
        )
        assert revision_two.status_code == 201
        stale_review = secretariat_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision_one_id, "result": "VALID"},
        )
        blocked = secretariat_client.post(f"{meeting_url}/transition", json={"to_status": "FINAL"})
        meeting = session.get(Meeting, UUID(str(meeting_data["id"])))
        status_before_valid_review = meeting.status if meeting is not None else None
        event_count_before_valid_review = session.query(MeetingStatusEvent).count()

        second_review = secretariat_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision_two.json()["id"], "result": "VALID"},
        )
        finalized = secretariat_client.post(
            f"{meeting_url}/transition", json={"to_status": "FINAL"}
        )

    assert stale_review.status_code == 409
    assert blocked.status_code == 409
    assert status_before_valid_review is MeetingStatus.LIVE
    assert event_count_before_valid_review == 1
    assert second_review.status_code == 201
    assert second_review.json()["minutes_revision_id"] == revision_two.json()["id"]
    assert finalized.status_code == 200
    assert session.query(MeetingStatusEvent).count() == 2


def test_minutes_revision_access_excludes_restricted_roles_and_validates_input(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    users["pic"].roles.append(next(role for role in users["rector"].roles))
    session.commit()

    with (
        TestClient(app) as secretariat_client,
        TestClient(app) as notetaker_client,
        TestClient(app) as other_client,
        TestClient(app) as pic_client,
        TestClient(app) as admin_client,
        TestClient(app) as anonymous_client,
    ):
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(
            secretariat_client,
            meeting_number="RAPIM-REV-003",
            notetaker_id=users["rector"].id,
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        assert (
            secretariat_client.post(
                f"{meeting_url}/participants", json={"user_id": str(users["pic"].id)}
            ).status_code
            == 201
        )
        assert (
            secretariat_client.post(
                f"{meeting_url}/participants",
                json={"user_id": str(users["other_rector"].id)},
            ).status_code
            == 201
        )
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "LIVE"}
            ).status_code
            == 200
        )
        revision_url = f"{meeting_url}/minutes-revisions"

        login(notetaker_client, users["rector"])
        blank = notetaker_client.post(
            revision_url,
            json={"content": "  \n", "base_revision_id": None},
        )
        created = notetaker_client.post(
            revision_url,
            json={"content": "Notulen privat", "base_revision_id": None},
        )
        assert created.status_code == 201
        missing_base = notetaker_client.post(revision_url, json={"content": "Tanpa base"})
        notetaker_client.headers.pop("X-CSRF-Token")
        missing_csrf = notetaker_client.post(
            revision_url,
            json={
                "content": "Perubahan tanpa CSRF",
                "base_revision_id": created.json()["id"],
            },
        )

        login(other_client, users["other_rector"])
        other_core_editor = other_client.post(
            revision_url,
            json={
                "content": "Revisi pengguna inti lain",
                "base_revision_id": created.json()["id"],
            },
        )
        login(pic_client, users["pic"])
        pic_read = pic_client.get(revision_url)
        login(admin_client, users["super_admin"])
        admin_read = admin_client.get(revision_url)
        anonymous_read = anonymous_client.get(revision_url)

    assert blank.status_code == 422
    assert missing_base.status_code == 422
    assert missing_csrf.status_code == 403
    assert other_core_editor.status_code == 201
    assert pic_read.status_code == 404
    assert admin_read.status_code == 404
    assert anonymous_read.status_code == 401
    assert session.query(MinutesReview).count() == 0


def _structured_minutes_payload(
    agenda_id: str, base_revision_id: str | None = None, text_value: str = "Pembahasan sintetis"
) -> StructuredMinutesPayload:
    return {
        "format_version": 2,
        "content": None,
        "base_revision_id": base_revision_id,
        "discussions": [
            {
                "agenda_id": agenda_id,
                "subject": "Evaluasi program",
                "content": text_value,
                "decisions": [
                    {
                        "decision_text": "Perbaiki pelaporan triwulan",
                        "output_expected": "Laporan revisi",
                        "target_date": "2026-11-30",
                        "is_action_item": True,
                    }
                ],
            }
        ],
    }


def test_structured_minutes_revision_round_trips_agenda_discussion_and_decision(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda_response = client.post(
            f"{meeting_url}/agendas",
            json={"title": "Evaluasi program"},
        )
        assert agenda_response.status_code == 201
        agenda_id = agenda_response.json()["id"]
        assert (
            client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"}).status_code == 200
        )

        structured_payload = _structured_minutes_payload(agenda_id)
        structured_payload["discussions"][0]["decisions"][0]["pic_suggestion"] = (
            "Warek bidang akademik"
        )
        saved = client.post(f"{meeting_url}/minutes-revisions", json=structured_payload)
        history = client.get(f"{meeting_url}/minutes-revisions")

    assert saved.status_code == 201
    revision = saved.json()
    assert revision["format_version"] == 2
    assert revision["content"] is None
    assert revision["discussions"][0]["agenda_id"] == agenda_id
    assert revision["discussions"][0]["content"] == "Pembahasan sintetis"
    decision = revision["discussions"][0]["decisions"][0]
    assert decision["discussion_id"] == revision["discussions"][0]["id"]
    assert decision["decision_text"] == "Perbaiki pelaporan triwulan"
    assert decision["pic_suggestion"] == "Warek bidang akademik"
    assert decision["target_date"] == "2026-11-30"
    assert decision["is_action_item"] is True
    assert history.status_code == 200
    assert history.json() == [revision]


def test_minutes_and_decision_brief_saves_write_content_free_database_audit_events(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda_response = client.post(f"{meeting_url}/agendas", json={"title": "Agenda audit"})
        assert agenda_response.status_code == 201
        agenda = agenda_response.json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        saved_minutes = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        )
        revision = saved_minutes.json()
        decision = revision["discussions"][0]["decisions"][0]
        saved_brief = client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": revision["id"],
                "summary": "Ringkasan sintetis untuk uji audit.",
                "decisions": [{"decision_id": decision["id"], "priority": "Utama"}],
            },
        )

    assert saved_minutes.status_code == 201
    assert saved_brief.status_code == 201
    minutes_event = session.query(AuditEvent).filter_by(action="minutes.revised").one()
    brief_event = session.query(AuditEvent).filter_by(action="decision_brief.saved").one()
    assert minutes_event.object_id == UUID(str(meeting_data["id"]))
    assert minutes_event.after_values == {
        "revision_id": revision["id"],
        "revision_number": "1",
        "format_version": "2",
        "decision_count": "1",
    }
    assert brief_event.object_id == UUID(saved_brief.json()["id"])
    assert brief_event.after_values == {
        "meeting_id": meeting_data["id"],
        "source_minutes_revision_id": revision["id"],
        "version_number": "1",
        "decision_count": "1",
    }
    audit_payload = str(minutes_event.after_values) + str(brief_event.after_values)
    assert "Perbaiki pelaporan triwulan" not in audit_payload
    assert "Laporan revisi" not in audit_payload


def test_structured_minutes_rejects_agenda_from_another_meeting_without_partial_rows(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        other_meeting = create_meeting(
            client,
            notetaker_id=users["secretariat"].id,
            meeting_number="RAPIM-2026-002",
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        other_agenda = client.post(
            f"/api/v1/meetings/{other_meeting['id']}/agendas",
            json={"title": "Agenda rapat lain"},
        ).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})

        response = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(other_agenda["id"]),
        )

    assert response.status_code == 422
    assert (
        session.query(MinutesRevision).filter_by(meeting_id=UUID(str(meeting_data["id"]))).count()
        == 0
    )
    assert session.execute(text("SELECT count(*) FROM minutes_discussions")).scalar_one() == 0
    assert session.execute(text("SELECT count(*) FROM minutes_decisions")).scalar_one() == 0


def test_structured_minutes_rejects_an_empty_snapshot(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        response = client.post(
            f"{meeting_url}/minutes-revisions",
            json={
                "format_version": 2,
                "content": None,
                "base_revision_id": None,
                "discussions": [],
            },
        )

    assert response.status_code == 422
    assert (
        session.query(MinutesRevision).filter_by(meeting_id=UUID(str(meeting_data["id"]))).count()
        == 0
    )


def test_structured_minutes_does_not_accept_pic_assignment_fields(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(f"{meeting_url}/agendas", json={"title": "Agenda"}).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        payload = _structured_minutes_payload(agenda["id"])
        decisions = payload["discussions"][0]["decisions"]
        decisions[0]["proposed_pic_user_id"] = str(users["rector"].id)

        response = client.post(f"{meeting_url}/minutes-revisions", json=payload)

    assert response.status_code == 422
    assert (
        session.query(MinutesRevision).filter_by(meeting_id=UUID(str(meeting_data["id"]))).count()
        == 0
    )


def test_database_rejects_decision_link_to_discussion_from_another_revision(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(f"{meeting_url}/agendas", json={"title": "Agenda"}).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        first = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        second_response = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"], base_revision_id=first["id"]),
        )

    assert second_response.status_code == 201
    first_discussion_id = UUID(first["discussions"][0]["id"])
    second_revision_id = UUID(second_response.json()["id"])
    with pytest.raises(IntegrityError):
        session.add(
            MinutesDecision(
                meeting_id=UUID(str(meeting_data["id"])),
                minutes_revision_id=second_revision_id,
                discussion_id=first_discussion_id,
                decision_number=99,
                decision_text="Synthetic cross-revision decision",
            )
        )
        session.commit()
    session.rollback()
    assert session.execute(text("SELECT count(*) FROM minutes_decisions")).scalar_one() == 2


def test_stale_structured_revision_rolls_back_root_and_all_children(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(f"{meeting_url}/agendas", json={"title": "Agenda"}).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        first = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        )
        assert first.status_code == 201
        stale_payload = _structured_minutes_payload(
            agenda["id"], text_value="Draf konflik sintetis"
        )
        stale = client.post(f"{meeting_url}/minutes-revisions", json=stale_payload)

    assert stale.status_code == 409
    assert (
        session.query(MinutesRevision).filter_by(meeting_id=UUID(str(meeting_data["id"]))).count()
        == 1
    )
    assert session.execute(text("SELECT count(*) FROM minutes_discussions")).scalar_one() == 1
    assert session.execute(text("SELECT count(*) FROM minutes_decisions")).scalar_one() == 1


def test_structured_minutes_keep_csrf_and_live_core_role_authorization(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        live_meeting = create_meeting(
            client,
            chairperson_id=users["rector"].id,
            notetaker_id=users["secretariat"].id,
        )
        live_url = f"/api/v1/meetings/{live_meeting['id']}"
        agenda = client.post(f"{live_url}/agendas", json={"title": "Agenda"}).json()
        client.post(f"{live_url}/transition", json={"to_status": "LIVE"})
        client.headers.pop("X-CSRF-Token")
        missing_csrf = client.post(
            f"{live_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        )

    with TestClient(app) as rector_client:
        login(rector_client, users["other_rector"])
        other_core_editor = rector_client.post(
            f"{live_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        )

    with TestClient(app) as draft_client:
        login(draft_client, users["secretariat"])
        draft_meeting = create_meeting(
            draft_client,
            notetaker_id=users["secretariat"].id,
            meeting_number="RAPIM-2026-002",
        )
        draft_url = f"/api/v1/meetings/{draft_meeting['id']}"
        draft_agenda = draft_client.post(f"{draft_url}/agendas", json={"title": "Agenda"}).json()
        not_live = draft_client.post(
            f"{draft_url}/minutes-revisions",
            json=_structured_minutes_payload(draft_agenda["id"]),
        )

    assert missing_csrf.status_code == 403
    assert other_core_editor.status_code == 201
    assert not_live.status_code == 409


def test_structured_review_and_finalization_remain_bound_to_the_active_revision(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client, TestClient(app) as notetaker_client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["rector"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(f"{meeting_url}/agendas", json={"title": "Agenda"}).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        login(notetaker_client, users["rector"])
        first = notetaker_client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        )
        assert first.status_code == 201
        first_id = first.json()["id"]
        review = client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": first_id, "result": "VALID"},
        )
        assert review.status_code == 201
        second = notetaker_client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(
                agenda["id"], base_revision_id=first_id, text_value="Revisi baru sintetis"
            ),
        )
        finalization = client.post(f"{meeting_url}/transition", json={"to_status": "FINAL"})

    assert second.status_code == 201
    assert finalization.status_code == 409
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.LIVE


def test_decision_brief_versions_keep_editorial_data_and_traceable_source(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app, raise_server_exceptions=False) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, notetaker_id=users["secretariat"].id)
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(f"{meeting_url}/agendas", json={"title": "Agenda sumber"}).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        first_revision = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        first_decision = first_revision["discussions"][0]["decisions"][0]
        brief_request = {
            "source_minutes_revision_id": first_revision["id"],
            "summary": "Prioritaskan perbaikan pelaporan.",
            "notes": "Ringkasan editorial sintetis.",
            "decisions": [
                {
                    "decision_id": first_decision["id"],
                    "brief_text": "Prioritaskan pelaporan triwulan.",
                    "priority": "",
                    "editorial_note": None,
                }
            ],
        }
        created = client.post(f"{meeting_url}/decision-briefs", json=brief_request)
        history_before = client.get(f"{meeting_url}/decision-briefs")
        second_revision = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(
                agenda["id"],
                base_revision_id=first_revision["id"],
                text_value="Pembahasan dan keputusan terbaru sintetis",
            ),
        ).json()
        stale_create = client.post(f"{meeting_url}/decision-briefs", json=brief_request)
        history_after = client.get(f"{meeting_url}/decision-briefs")

    assert created.status_code == 201, created.text
    brief = created.json()
    assert brief["version_number"] == 1
    assert brief["source_minutes_revision_id"] == first_revision["id"]
    assert brief["is_stale"] is False
    assert brief["summary"] == brief_request["summary"]
    assert brief["notes"] == brief_request["notes"]
    assert brief["decisions"][0]["decision_id"] == first_decision["id"]
    assert brief["decisions"][0]["source_decision_text"] == first_decision["decision_text"]
    assert brief["decisions"][0]["brief_text"] == "Prioritaskan pelaporan triwulan."
    assert brief["decisions"][0]["priority"] == ""
    assert brief["decisions"][0]["editorial_note"] is None
    assert history_before.status_code == 200
    assert history_before.json() == [brief]
    assert history_after.status_code == 200
    assert history_after.json()[0]["id"] == brief["id"]
    assert history_after.json()[0]["source_minutes_revision_id"] == first_revision["id"]
    assert history_after.json()[0]["is_stale"] is True
    assert stale_create.status_code == 409
    assert second_revision["id"] != first_revision["id"]


def test_decision_brief_rejects_source_decisions_from_other_meetings_or_revisions(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(
            client, notetaker_id=users["secretariat"].id, meeting_number="BRIEF-SOURCE-001"
        )
        other_meeting = create_meeting(
            client, notetaker_id=users["secretariat"].id, meeting_number="BRIEF-SOURCE-002"
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        other_url = f"/api/v1/meetings/{other_meeting['id']}"
        agenda = client.post(f"{meeting_url}/agendas", json={"title": "Agenda utama"}).json()
        other_agenda = client.post(f"{other_url}/agendas", json={"title": "Agenda lain"}).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        client.post(f"{other_url}/transition", json={"to_status": "LIVE"})
        first = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        other = client.post(
            f"{other_url}/minutes-revisions",
            json=_structured_minutes_payload(other_agenda["id"]),
        ).json()
        latest = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(
                agenda["id"], base_revision_id=first["id"], text_value="Revisi sintetis terbaru"
            ),
        ).json()
        other_decision_id = other["discussions"][0]["decisions"][0]["id"]
        old_decision_id = first["discussions"][0]["decisions"][0]["id"]
        cross_meeting = client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": latest["id"],
                "summary": "Ringkasan sintetis.",
                "decisions": [{"decision_id": other_decision_id, "priority": "Utama"}],
            },
        )
        cross_revision = client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": latest["id"],
                "summary": "Ringkasan sintetis.",
                "decisions": [{"decision_id": old_decision_id, "priority": "Utama"}],
            },
        )

    assert cross_meeting.status_code == 422
    assert cross_revision.status_code == 422
    assert session.execute(text("SELECT count(*) FROM decision_brief_versions")).scalar_one() == 0
    assert session.execute(text("SELECT count(*) FROM decision_brief_decisions")).scalar_one() == 0


def test_decision_brief_requires_csrf_and_denies_rektor_creation(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(
            secretariat_client,
            chairperson_id=users["rector"].id,
            notetaker_id=users["secretariat"].id,
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = secretariat_client.post(
            f"{meeting_url}/agendas", json={"title": "Agenda uji"}
        ).json()
        secretariat_client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        revision = secretariat_client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        decision = revision["discussions"][0]["decisions"][0]
        missing_csrf_payload = {
            "source_minutes_revision_id": revision["id"],
            "summary": "Ringkasan sintetis.",
            "decisions": [{"decision_id": decision["id"], "priority": "Utama"}],
        }
        secretariat_client.headers.pop("X-CSRF-Token")
        missing_csrf = secretariat_client.post(
            f"{meeting_url}/decision-briefs", json=missing_csrf_payload
        )

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        read_history = rector_client.get(f"{meeting_url}/decision-briefs")
        leadership_create = rector_client.post(
            f"{meeting_url}/decision-briefs", json=missing_csrf_payload
        )

    with TestClient(app) as pic_client:
        login(pic_client, users["pic"])
        hidden_history = pic_client.get(f"{meeting_url}/decision-briefs")

    with TestClient(app) as out_of_scope_client:
        login(out_of_scope_client, users["other_rector"])
        out_of_scope_history = out_of_scope_client.get(f"{meeting_url}/decision-briefs")

    users["super_admin"].roles.append(users["secretariat"].roles[0])
    with TestClient(app) as admin_client:
        login(admin_client, users["super_admin"])
        hidden_admin_create = admin_client.post(
            f"{meeting_url}/decision-briefs", json=missing_csrf_payload
        )

    assert missing_csrf.status_code == 403
    assert read_history.status_code == 200
    assert leadership_create.status_code == 403
    assert hidden_history.status_code == 404
    assert out_of_scope_history.status_code == 200
    assert hidden_admin_create.status_code == 404


def test_decision_brief_approval_requires_final_valid_and_records_one_approver(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(
            secretariat_client,
            chairperson_id=users["rector"].id,
            notetaker_id=users["secretariat"].id,
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = secretariat_client.post(
            f"{meeting_url}/agendas",
            json={"title": "Agenda approval sintetis"},
        ).json()
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "LIVE"}
            ).status_code
            == 200
        )
        revision = secretariat_client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        decision = revision["discussions"][0]["decisions"][0]
        brief = secretariat_client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": revision["id"],
                "summary": "Ringkasan approval sintetis.",
                "decisions": [{"decision_id": decision["id"], "priority": "Utama"}],
            },
        ).json()
        brief_url = f"{meeting_url}/decision-briefs/{brief['id']}"
        before_final = secretariat_client.post(f"{brief_url}/submit")
        invalid_review = secretariat_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision["id"], "result": "INVALID"},
        )
        invalid_review_submit = secretariat_client.post(f"{brief_url}/submit")
        valid_review = secretariat_client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision["id"], "result": "VALID"},
        )
        finalized = secretariat_client.post(
            f"{meeting_url}/transition", json={"to_status": "FINAL"}
        )

    with TestClient(app) as rector_submitter_client:
        login(rector_submitter_client, users["rector"])
        submitted = rector_submitter_client.post(f"{brief_url}/submit")

    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        self_approval = secretariat_client.post(f"{brief_url}/approve")
        self_rejection = secretariat_client.post(
            f"{brief_url}/reject",
            json={"reason": "Pengaju tidak dapat meninjau versinya sendiri."},
        )

    with TestClient(app) as pic_client:
        login(pic_client, users["pic"])
        unauthorized_submit = pic_client.post(f"{brief_url}/submit")

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        blank_rejection = rector_client.post(f"{brief_url}/reject", json={"reason": "  "})
        rejected = rector_client.post(
            f"{brief_url}/reject", json={"reason": "Perlu perbaikan data sumber."}
        )

    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        second_brief_response = secretariat_client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": revision["id"],
                "summary": "Ringkasan approval sintetis versi baru.",
                "decisions": [{"decision_id": decision["id"], "priority": "Utama"}],
            },
        )
        second_brief = second_brief_response.json()
        second_brief_url = f"{meeting_url}/decision-briefs/{second_brief['id']}"
        second_submit = secretariat_client.post(f"{second_brief_url}/submit")
        withdrawn = secretariat_client.post(f"{second_brief_url}/withdraw")
        resubmitted = secretariat_client.post(f"{second_brief_url}/submit")

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        approved = rector_client.post(f"{second_brief_url}/approve")
        history = rector_client.get(f"{meeting_url}/decision-briefs")

    assert before_final.status_code == 409
    assert invalid_review.status_code == 201
    assert invalid_review_submit.status_code == 409
    assert valid_review.status_code == 201
    assert finalized.status_code == 200
    assert submitted.status_code == 200
    assert self_approval.status_code == 403
    assert self_rejection.status_code == 403
    assert unauthorized_submit.status_code == 404
    assert blank_rejection.status_code == 422
    assert rejected.status_code == 200
    assert second_brief_response.status_code == 201
    assert second_submit.status_code == 200
    assert withdrawn.status_code == 200
    assert resubmitted.status_code == 200
    assert approved.status_code == 200
    rejected_brief, approved_brief = history.json()
    assert rejected_brief["id"] == brief["id"]
    assert rejected_brief["approval_state"] == "REJECTED"
    assert [event["event_type"] for event in rejected_brief["approval_events"]] == [
        "SUBMITTED",
        "REJECTED",
    ]
    assert rejected_brief["approval_events"][0]["actor_user_id"] == str(users["rector"].id)
    assert rejected_brief["approval_events"][0]["actor_roles"] == ["REKTOR"]
    assert rejected_brief["approval_events"][-1]["reason"] == "Perlu perbaikan data sumber."
    assert approved_brief["id"] == second_brief["id"]
    assert approved_brief["version_number"] == 2
    assert approved_brief["approval_state"] == "APPROVED"
    assert [event["event_type"] for event in approved_brief["approval_events"]] == [
        "SUBMITTED",
        "WITHDRAWN",
        "SUBMITTED",
        "APPROVED",
    ]
    assert approved_brief["approval_events"][-1]["actor_user_id"] == str(users["rector"].id)
    assert approved_brief["approval_events"][-1]["actor_roles"] == ["REKTOR"]
    rejected_audits = (
        session.query(AuditEvent)
        .filter(AuditEvent.object_id == UUID(brief["id"]))
        .order_by(AuditEvent.occurred_at)
        .all()
    )
    approved_audits = (
        session.query(AuditEvent)
        .filter(AuditEvent.object_id == UUID(second_brief["id"]))
        .order_by(AuditEvent.occurred_at)
        .all()
    )
    assert [
        event.action for event in rejected_audits if event.action != "decision_brief.saved"
    ] == [
        "decision_brief.submitted",
        "decision_brief.rejected",
    ]
    assert [
        event.action for event in approved_audits if event.action != "decision_brief.saved"
    ] == [
        "decision_brief.submitted",
        "decision_brief.withdrawn",
        "decision_brief.submitted",
        "decision_brief.approved",
    ]
    assert all(
        sum(event.action == "decision_brief.saved" for event in events) == 1
        for events in (rejected_audits, approved_audits)
    )
    assert all(
        "Ringkasan approval sintetis" not in str(event.after_values)
        for event in rejected_audits + approved_audits
    )


def test_manager_legal_can_approve_pending_decision_brief(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(
            secretariat_client,
            notetaker_id=users["secretariat"].id,
        )
        meeting = session.get(Meeting, UUID(meeting_data["id"]))
        assert meeting is not None
        meeting.chairperson_id = users["manager_legal"].id
        session.commit()
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = secretariat_client.post(
            f"{meeting_url}/agendas",
            json={"title": "Agenda persetujuan Manager Legal sintetis"},
        ).json()
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "LIVE"}
            ).status_code
            == 200
        )
        revision = secretariat_client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        decision = revision["discussions"][0]["decisions"][0]
        assert (
            secretariat_client.post(
                f"{meeting_url}/minutes-reviews",
                json={"minutes_revision_id": revision["id"], "result": "VALID"},
            ).status_code
            == 201
        )
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "FINAL"}
            ).status_code
            == 200
        )
        brief = secretariat_client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": revision["id"],
                "summary": "Ringkasan untuk persetujuan Manager Legal.",
                "decisions": [{"decision_id": decision["id"], "priority": "Utama"}],
            },
        ).json()
        brief_url = f"{meeting_url}/decision-briefs/{brief['id']}"
        submitted = secretariat_client.post(f"{brief_url}/submit")

    with TestClient(app) as manager_legal_client:
        login(manager_legal_client, users["manager_legal"])
        manager_legal_notifications = manager_legal_client.get("/api/v1/notifications").json()
        approved = manager_legal_client.post(f"{brief_url}/approve")
        history = manager_legal_client.get(f"{meeting_url}/decision-briefs")

    assert submitted.status_code == 200
    assert approved.status_code == 200
    assert manager_legal_notifications["unread_count"] == 1
    assert (
        manager_legal_notifications["items"][0]["notification_type"]
        == "DECISION_BRIEF_REVIEW_NEEDED"
    )
    approved_brief = history.json()[0]
    assert approved_brief["approval_state"] == "APPROVED"
    approval_event = approved_brief["approval_events"][-1]
    assert approval_event["event_type"] == "APPROVED"
    assert approval_event["actor_user_id"] == str(users["manager_legal"].id)
    assert approval_event["actor_roles"] == ["MANAGER_LEGAL"]


def test_decision_brief_workflow_notifies_direct_reviewer_and_author_only(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(
            secretariat_client,
        )
        meeting = session.get(Meeting, UUID(meeting_data["id"]))
        assert meeting is not None
        meeting.chairperson_id = users["rector"].id
        meeting.notetaker_id = users["secretariat"].id
        session.commit()
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda_response = secretariat_client.post(
            f"{meeting_url}/agendas",
            json={"title": "Agenda notification sintetis"},
        )
        assert agenda_response.status_code == 201, agenda_response.text
        agenda = agenda_response.json()
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "LIVE"}
            ).status_code
            == 200
        )
        revision = secretariat_client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        decision = revision["discussions"][0]["decisions"][0]
        assert (
            secretariat_client.post(
                f"{meeting_url}/minutes-reviews",
                json={"minutes_revision_id": revision["id"], "result": "VALID"},
            ).status_code
            == 201
        )
        assert (
            secretariat_client.post(
                f"{meeting_url}/transition", json={"to_status": "FINAL"}
            ).status_code
            == 200
        )
        brief = secretariat_client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": revision["id"],
                "summary": "Confidential brief body stays out of notification.",
                "decisions": [{"decision_id": decision["id"], "priority": "Utama"}],
            },
        ).json()
        brief_url = f"{meeting_url}/decision-briefs/{brief['id']}"
        submitted = secretariat_client.post(f"{brief_url}/submit")

    with TestClient(app) as reviewer_client:
        login(reviewer_client, users["rector"])
        reviewer_page = reviewer_client.get("/api/v1/notifications").json()
        approved = reviewer_client.post(f"{brief_url}/approve")

    with TestClient(app) as author_client:
        login(author_client, users["secretariat"])
        author_page = author_client.get("/api/v1/notifications").json()

    assert submitted.status_code == 200
    assert approved.status_code == 200
    assert len(reviewer_page["items"]) == 1
    reviewer_notification = reviewer_page["items"][0]
    assert reviewer_notification["notification_type"] == "DECISION_BRIEF_REVIEW_NEEDED"
    assert reviewer_notification["target_type"] == "MEETING"
    assert reviewer_notification["target_id"] == meeting_data["id"]
    assert "Confidential brief body" not in reviewer_notification["message"]
    assert meeting_data["meeting_number"] not in reviewer_notification["message"]
    assert len(author_page["items"]) == 1
    assert author_page["items"][0]["notification_type"] == "DECISION_BRIEF_REVIEW_COMPLETED"


def test_decision_brief_audit_failure_rolls_back_workflow_event(
    meeting_context: tuple[Session, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(
            client,
            chairperson_id=users["rector"].id,
            notetaker_id=users["secretariat"].id,
        )
        meeting_url = f"/api/v1/meetings/{meeting_data['id']}"
        agenda = client.post(
            f"{meeting_url}/agendas",
            json={"title": "Agenda rollback sintetis"},
        ).json()
        client.post(f"{meeting_url}/transition", json={"to_status": "LIVE"})
        revision = client.post(
            f"{meeting_url}/minutes-revisions",
            json=_structured_minutes_payload(agenda["id"]),
        ).json()
        decision = revision["discussions"][0]["decisions"][0]
        brief = client.post(
            f"{meeting_url}/decision-briefs",
            json={
                "source_minutes_revision_id": revision["id"],
                "summary": "Ringkasan rollback sintetis.",
                "decisions": [{"decision_id": decision["id"], "priority": "Utama"}],
            },
        ).json()
        client.post(
            f"{meeting_url}/minutes-reviews",
            json={"minutes_revision_id": revision["id"], "result": "VALID"},
        )
        client.post(f"{meeting_url}/transition", json={"to_status": "FINAL"})

    original_commit = Session.commit

    def fail_after_flush(target_session: Session) -> None:
        if any(
            isinstance(item, DecisionBriefApprovalEvent)
            for item in target_session.identity_map.values()
        ):
            target_session.flush()
            raise SQLAlchemyError("Synthetic approval transaction failure")
        original_commit(target_session)

    monkeypatch.setattr(Session, "commit", fail_after_flush)
    with TestClient(app) as client:
        login(client, users["secretariat"])
        response = client.post(f"{meeting_url}/decision-briefs/{brief['id']}/submit")

    assert response.status_code == 500
    assert response.json()["detail"] == "Decision Brief workflow could not be recorded"
    assert response.headers["X-Correlation-ID"]
    assert session.query(DecisionBriefApprovalEvent).count() == 0
    assert (
        session.query(AuditEvent)
        .filter_by(action="decision_brief.submitted", object_id=UUID(brief["id"]))
        .count()
        == 0
    )


def test_meeting_transition_writes_redacted_audit_event_with_server_role_snapshot(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client, users["rector"].id)
        response = client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
            headers={"X-Correlation-ID": "caller-controlled-value"},
        )

    assert response.status_code == 200
    correlation_id = response.headers["X-Correlation-ID"]
    assert UUID(correlation_id)
    assert correlation_id != "caller-controlled-value"
    audit_event = session.query(AuditEvent).one()
    assert audit_event.actor_user_id == users["secretariat"].id
    assert audit_event.actor_roles == ["SEKRETARIAT"]
    assert audit_event.action == "meeting.status_changed"
    assert audit_event.object_type == "meeting"
    assert audit_event.object_id == UUID(meeting_data["id"])
    assert audit_event.result == "SUCCEEDED"
    assert audit_event.correlation_id == UUID(correlation_id)
    assert audit_event.before_values == {"status": "DRAFT"}
    assert audit_event.after_values == {"status": "LIVE"}
    assert audit_event.occurred_at is not None
    assert session.query(MeetingStatusEvent).count() == 1


def test_unauthorized_meeting_transition_is_audited_without_business_change(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context
    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client, users["rector"].id)

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        response = rector_client.post(
            f"/api/v1/meetings/{meeting_data['id']}/transition",
            json={"to_status": "LIVE"},
        )

    assert response.status_code == 403
    audit_event = session.query(AuditEvent).one()
    assert audit_event.actor_user_id == users["rector"].id
    assert audit_event.actor_roles == ["REKTOR"]
    assert audit_event.action == "meeting.status_changed"
    assert audit_event.result == "DENIED"
    assert audit_event.before_values is None
    assert audit_event.after_values is None
    assert audit_event.correlation_id == UUID(response.headers["X-Correlation-ID"])
    assert session.query(MeetingStatusEvent).count() == 0
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.DRAFT


def test_audit_insert_failure_rolls_back_meeting_transition(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    session, users = meeting_context

    def fail_audit_insert(
        _mapper: Mapper[AuditEvent], _connection: Connection, _target: AuditEvent
    ) -> None:
        raise SQLAlchemyError("synthetic audit storage failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        login(client, users["secretariat"])
        meeting_data = create_meeting(client)
        event.listen(AuditEvent, "before_insert", fail_audit_insert)
        try:
            response = client.post(
                f"/api/v1/meetings/{meeting_data['id']}/transition",
                json={"to_status": "LIVE"},
            )
        finally:
            event.remove(AuditEvent, "before_insert", fail_audit_insert)

    assert response.status_code == 500
    assert UUID(response.headers["X-Correlation-ID"])
    session.rollback()
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.DRAFT
    assert session.query(MeetingStatusEvent).count() == 0
    assert session.query(AuditEvent).count() == 0


def test_audit_event_payload_rejects_fields_outside_status_allowlist(
    meeting_context: tuple[Session, dict[str, User]],
) -> None:
    _, users = meeting_context
    with pytest.raises(ValidationError):
        AuditEventCreate.model_validate(
            {
                "actor_user_id": users["secretariat"].id,
                "actor_roles": ["SEKRETARIAT"],
                "action": "meeting.status_changed",
                "object_type": "meeting",
                "object_id": uuid4(),
                "result": "SUCCEEDED",
                "before_values": {"status": "DRAFT", "title": "Sensitive meeting title"},
            }
        )


def test_denial_audit_failure_preserves_forbidden_response_and_alerts(
    meeting_context: tuple[Session, dict[str, User]], caplog: pytest.LogCaptureFixture
) -> None:
    session, users = meeting_context

    def fail_audit_insert(
        _mapper: Mapper[AuditEvent], _connection: Connection, _target: AuditEvent
    ) -> None:
        raise SQLAlchemyError("synthetic audit storage failure")

    with TestClient(app) as secretariat_client:
        login(secretariat_client, users["secretariat"])
        meeting_data = create_meeting(secretariat_client, users["rector"].id)

    with TestClient(app) as rector_client:
        login(rector_client, users["rector"])
        event.listen(AuditEvent, "before_insert", fail_audit_insert)
        try:
            response = rector_client.post(
                f"/api/v1/meetings/{meeting_data['id']}/transition",
                json={"to_status": "LIVE"},
            )
        finally:
            event.remove(AuditEvent, "before_insert", fail_audit_insert)

    assert response.status_code == 403
    assert "Denied meeting transition could not be recorded" in caplog.text
    session.rollback()
    meeting = session.get(Meeting, UUID(meeting_data["id"]))
    assert meeting is not None
    assert meeting.status is MeetingStatus.DRAFT
    assert session.query(MeetingStatusEvent).count() == 0
    assert session.query(AuditEvent).count() == 0
