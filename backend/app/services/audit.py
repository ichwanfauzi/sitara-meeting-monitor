"""Centralized audit event writing for explicit transaction boundaries."""

from typing import Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.auth import Role, User, user_roles
from app.schemas.audit import AuditEventCreate


class AuditEventWriteError(Exception):
    """Raised when a standalone denial audit event cannot be persisted."""


def _verified_actor_roles(session: Session, actor_id: UUID) -> list[str]:
    return sorted(
        session.scalars(
            select(Role.role_code)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == actor_id)
        )
    )


def append_meeting_status_event(
    session: Session,
    *,
    actor: User,
    meeting_id: UUID,
    result: Literal["SUCCEEDED", "DENIED"],
    correlation_id: UUID | None,
    before_values: dict[str, str] | None = None,
    after_values: dict[str, str] | None = None,
) -> AuditEvent:
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action="meeting.status_changed",
        object_type="meeting",
        object_id=meeting_id,
        result=result,
        correlation_id=correlation_id,
        before_values=before_values,
        after_values=after_values,
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_meeting_change_event(
    session: Session,
    *,
    actor: User,
    meeting_id: UUID,
    action: Literal[
        "meeting.metadata_updated",
        "meeting.agenda_changed",
        "meeting.participant_changed",
        "meeting.notetaker_handover_requested",
        "meeting.notetaker_handover_approved",
    ],
    correlation_id: UUID | None,
    before_values: dict[str, str] | None,
    after_values: dict[str, str] | None,
) -> AuditEvent:
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action=action,
        object_type="meeting",
        object_id=meeting_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values=after_values,
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_minutes_revision_event(
    session: Session,
    *,
    actor: User,
    meeting_id: UUID,
    revision_id: UUID,
    revision_number: int,
    format_version: int,
    decision_count: int,
    prior_revision_id: UUID | None,
    prior_revision_number: int | None,
    correlation_id: UUID | None,
) -> AuditEvent:
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action="minutes.revised",
        object_type="meeting",
        object_id=meeting_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        before_values={
            "revision_id": str(prior_revision_id) if prior_revision_id else None,
            "revision_number": str(prior_revision_number) if prior_revision_number else None,
        },
        after_values={
            "revision_id": str(revision_id),
            "revision_number": str(revision_number),
            "format_version": str(format_version),
            "decision_count": str(decision_count),
        },
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_decision_brief_saved_event(
    session: Session,
    *,
    actor: User,
    meeting_id: UUID,
    brief_version_id: UUID,
    source_minutes_revision_id: UUID,
    version_number: int,
    decision_count: int,
    correlation_id: UUID | None,
) -> AuditEvent:
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action="decision_brief.saved",
        object_type="decision_brief_version",
        object_id=brief_version_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        after_values={
            "meeting_id": str(meeting_id),
            "source_minutes_revision_id": str(source_minutes_revision_id),
            "version_number": str(version_number),
            "decision_count": str(decision_count),
        },
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_disposition_created_event(
    session: Session,
    *,
    actor: User,
    disposition_id: UUID,
    source_minutes_revision_id: UUID,
    source_decision_id: UUID,
    target_types: set[str],
    target_count: int,
    correlation_id: UUID | None,
) -> AuditEvent:
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action="disposition.created",
        object_type="disposition",
        object_id=disposition_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        after_values={
            "source_minutes_revision_id": str(source_minutes_revision_id),
            "source_decision_id": str(source_decision_id),
            "target_count": str(target_count),
            "target_types": ",".join(sorted(target_types)),
        },
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_action_item_created_event(
    session: Session,
    *,
    actor: User,
    action_item_id: UUID,
    source_minutes_revision_id: UUID,
    source_decision_id: UUID,
    disposition_id: UUID | None,
    correlation_id: UUID | None,
) -> AuditEvent:
    after_values = {
        "source_minutes_revision_id": str(source_minutes_revision_id),
        "source_decision_id": str(source_decision_id),
    }
    if disposition_id is not None:
        after_values["disposition_id"] = str(disposition_id)
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action="action_item.created",
        object_type="action_item",
        object_id=action_item_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        after_values=after_values,
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_action_item_assignment_changed_event(
    session: Session,
    *,
    actor: User,
    action_item_id: UUID,
    operation: Literal["ASSIGNED", "REPLACED", "ENDED"],
    before_values: dict[str, str | None] | None,
    after_values: dict[str, str | None],
    correlation_id: UUID | None,
) -> AuditEvent:
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action="action_item.assignment_changed",
        object_type="action_item",
        object_id=action_item_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values={"operation": operation, **after_values},
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_action_item_edit_event(
    session: Session,
    *,
    actor: User,
    action_item_id: UUID,
    operation: Literal["UPDATED", "DELETED"],
    changed_fields: list[str],
    correlation_id: UUID | None,
) -> AuditEvent:
    action_by_operation: dict[
        Literal["UPDATED", "DELETED"], Literal["action_item.updated", "action_item.deleted"]
    ] = {
        "UPDATED": "action_item.updated",
        "DELETED": "action_item.deleted",
    }
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action=action_by_operation[operation],
        object_type="action_item",
        object_id=action_item_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        after_values={"changed_fields": ",".join(sorted(changed_fields))},
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_action_item_status_changed_event(
    session: Session,
    *,
    actor: User,
    action_item_id: UUID,
    before_status: str,
    after_status: str,
    correlation_id: UUID | None,
    verification_id: UUID | None = None,
) -> AuditEvent:
    after_values = {"official_status": after_status}
    if verification_id is not None:
        after_values["verification_id"] = str(verification_id)
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action="action_item.status_changed",
        object_type="action_item",
        object_id=action_item_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        before_values={"official_status": before_status},
        after_values=after_values,
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_user_account_event(
    session: Session,
    *,
    actor: User | None,
    action: Literal[
        "user.created",
        "user.updated",
        "user.deactivated",
        "user.reactivated",
        "user.password_reset",
        "user.password_changed",
        "user.provisioned",
    ],
    user_id: UUID,
    before_values: dict[str, str | None] | None = None,
    after_values: dict[str, str | None] | None = None,
    correlation_id: UUID | None = None,
) -> AuditEvent:
    system_actor = actor is None
    data = AuditEventCreate(
        actor_user_id=actor.id if actor is not None else None,
        actor_roles=_verified_actor_roles(session, actor.id) if actor is not None else [],
        actor_type="SYSTEM" if system_actor else "USER",
        action=action,
        object_type="user",
        object_id=user_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values=after_values,
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def append_decision_brief_workflow_event(
    session: Session,
    *,
    actor: User,
    brief_version_id: UUID,
    meeting_id: UUID,
    version_number: int,
    event_type: Literal["SUBMITTED", "WITHDRAWN", "APPROVED", "REJECTED"],
    before_state: str,
    correlation_id: UUID | None,
) -> AuditEvent:
    action_by_event: dict[
        Literal["SUBMITTED", "WITHDRAWN", "APPROVED", "REJECTED"],
        Literal[
            "decision_brief.submitted",
            "decision_brief.withdrawn",
            "decision_brief.approved",
            "decision_brief.rejected",
        ],
    ] = {
        "SUBMITTED": "decision_brief.submitted",
        "WITHDRAWN": "decision_brief.withdrawn",
        "APPROVED": "decision_brief.approved",
        "REJECTED": "decision_brief.rejected",
    }
    data = AuditEventCreate(
        actor_user_id=actor.id,
        actor_roles=_verified_actor_roles(session, actor.id),
        action=action_by_event[event_type],
        object_type="decision_brief_version",
        object_id=brief_version_id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        before_values={"state": before_state},
        after_values={
            "state": event_type,
            "meeting_id": str(meeting_id),
            "version_number": str(version_number),
        },
    )
    event = AuditEvent(**data.model_dump())
    session.add(event)
    return event


def record_denied_meeting_transition(
    session: Session,
    *,
    actor: User,
    meeting_id: UUID,
    correlation_id: UUID | None,
) -> None:
    try:
        append_meeting_status_event(
            session,
            actor=actor,
            meeting_id=meeting_id,
            result="DENIED",
            correlation_id=correlation_id,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise AuditEventWriteError from error
