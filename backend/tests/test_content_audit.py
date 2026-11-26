from uuid import uuid4

import pytest
from app.schemas.audit import AuditEventCreate
from pydantic import ValidationError


def test_minutes_revision_audit_event_records_metadata_without_content() -> None:
    meeting_id = uuid4()
    revision_id = uuid4()
    event = AuditEventCreate(
        actor_user_id=uuid4(),
        actor_roles=["SEKRETARIAT"],
        action="minutes.revised",
        object_type="meeting",
        object_id=meeting_id,
        result="SUCCEEDED",
        before_values={"revision_id": None, "revision_number": None},
        after_values={
            "revision_id": str(revision_id),
            "revision_number": "1",
            "format_version": "2",
            "decision_count": "3",
        },
    )

    assert event.object_id == meeting_id
    assert "content" not in (event.before_values or {}) | (event.after_values or {})


def test_decision_brief_save_audit_event_records_source_and_version() -> None:
    version_id = uuid4()
    event = AuditEventCreate(
        actor_user_id=uuid4(),
        actor_roles=["MANAGER_LEGAL"],
        action="decision_brief.saved",
        object_type="decision_brief_version",
        object_id=version_id,
        result="SUCCEEDED",
        after_values={
            "meeting_id": str(uuid4()),
            "source_minutes_revision_id": str(uuid4()),
            "version_number": "2",
            "decision_count": "3",
        },
    )

    assert event.object_id == version_id
    assert event.action == "decision_brief.saved"


def test_content_audit_rejects_meeting_text_or_unallowlisted_fields() -> None:
    with pytest.raises(ValidationError):
        AuditEventCreate(
            actor_user_id=uuid4(),
            actor_roles=["SEKRETARIAT"],
            action="minutes.revised",
            object_type="meeting",
            object_id=uuid4(),
            result="SUCCEEDED",
            after_values={
                "revision_id": str(uuid4()),
                "revision_number": "1",
                "format_version": "2",
                "decision_count": "3",
                "content": "Isi rapat rahasia",
            },
        )
