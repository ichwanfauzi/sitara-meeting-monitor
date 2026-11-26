"""Meeting access policies and database use cases."""

from datetime import UTC, date, datetime, time
from typing import Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.roles import (
    MANAGER_LEGAL_ROLE,
    MEETING_EDITOR_ROLES,
    MEETING_MANAGER_ROLES,
    PIC_ROLE,
    RECTOR_ROLE,
    SECRETARIAT_OPERATOR_ROLES,
    SECRETARIAT_ROLE,
    SUPER_ADMIN_ROLE,
    VICE_RECTOR_ROLE,
)
from app.models.auth import User
from app.models.meeting import (
    Agenda,
    DecisionBriefApprovalEvent,
    DecisionBriefApprovalEventType,
    DecisionBriefDecision,
    DecisionBriefVersion,
    Meeting,
    MeetingNotetakerHandover,
    MeetingParticipant,
    MeetingStatus,
    MeetingStatusEvent,
    MinutesDecision,
    MinutesDiscussion,
    MinutesReview,
    MinutesReviewResult,
    MinutesRevision,
    NotetakerHandoverStatus,
)
from app.models.notification import NotificationTargetType, NotificationType
from app.schemas.meetings import (
    AgendaCreate,
    AgendaUpdate,
    DecisionBriefApprovalEventName,
    DecisionBriefApprovalEventResponse,
    DecisionBriefApprovalState,
    DecisionBriefVersionCreate,
    MeetingCreate,
    MeetingMetadataUpdate,
    MeetingParticipantCreate,
    MinutesReviewCreate,
    MinutesRevisionCreate,
    NotetakerHandoverCreate,
)
from app.services.audit import (
    append_decision_brief_saved_event,
    append_decision_brief_workflow_event,
    append_meeting_change_event,
    append_meeting_status_event,
    append_minutes_revision_event,
)
from app.services.notifications import add_notifications


class DuplicateMeetingRecord(Exception):
    """Raised when a unique meeting, agenda, or participant record conflicts."""


class InvalidMeetingReference(Exception):
    """Raised when a meeting references a missing or inactive user."""


class InvalidMeetingTransition(Exception):
    """Raised when the requested status transition is not permitted."""


class MinutesReviewRequired(Exception):
    """Raised when the latest minutes review is missing or invalid."""


class MeetingNotLiveForMinutesReview(Exception):
    """Raised when minutes are submitted for review outside the live state."""


class MeetingNotLiveForMinutesRevision(Exception):
    """Raised when minutes are edited outside the live state."""


class MinutesRevisionConflict(Exception):
    """Raised when a minutes write is based on a revision that is no longer active."""


class MinutesRevisionEditDenied(Exception):
    """Raised when a user cannot edit minutes under the core-role policy."""


class InvalidMinutesRevisionStructure(Exception):
    """Raised when a structured snapshot references an agenda outside its meeting."""


class InvalidDecisionBriefSource(Exception):
    """Raised when a brief references a decision outside its exact source snapshot."""


class DecisionBriefSourceRevisionConflict(Exception):
    """Raised when a brief is created from a revision that is no longer active."""


class DecisionBriefVersionNotFound(Exception):
    """Raised when a version does not belong to the requested meeting."""


class DecisionBriefWorkflowDenied(Exception):
    """Raised when an actor is not authorized for a brief workflow action."""


class DecisionBriefWorkflowConflict(Exception):
    """Raised when a brief workflow action is invalid for its current state."""


class DecisionBriefSubmissionIneligible(Exception):
    """Raised when meeting or minutes state does not permit brief submission."""


class DecisionBriefWorkflowPersistenceError(Exception):
    """Raised when a required approval event or audit event cannot be saved."""


class MeetingMutationDenied(Exception):
    """Raised when an actor cannot mutate a meeting in the requested scope."""


class MeetingNotEditable(Exception):
    """Raised when a meeting is no longer in DRAFT or LIVE."""


class StaleMeetingVersion(Exception):
    """Raised when a meeting update is based on an outdated version."""


class InvalidMeetingMetadata(Exception):
    """Raised when a metadata update violates a lifecycle or field rule."""


class MeetingAgendaNotFound(Exception):
    """Raised when an agenda is not part of the selected meeting."""


class MeetingAgendaReferenced(Exception):
    """Raised when an agenda is already referenced by immutable minutes."""


class MeetingParticipantNotFound(Exception):
    """Raised when a participant is not part of the selected meeting."""


class MeetingMutationPersistenceError(Exception):
    """Raised when a meeting mutation or its required audit event cannot be saved."""


class NotetakerHandoverNotLive(Exception):
    """Raised when a handover is requested or approved outside LIVE."""


class NotetakerHandoverNotFound(Exception):
    """Raised when a handover does not belong to the selected meeting."""


class NotetakerHandoverConflict(Exception):
    """Raised when a handover is no longer pending or its source is stale."""


def user_role_codes(user: User) -> set[str]:
    return {role.role_code for role in user.roles}


def can_read_meetings(user: User) -> bool:
    roles = user_role_codes(user)
    return roles.isdisjoint({SUPER_ADMIN_ROLE, PIC_ROLE}) and bool(roles & MEETING_MANAGER_ROLES)


def _is_meeting_associate(user: User, meeting: Meeting) -> bool:
    return user.id in {
        meeting.created_by_id,
        meeting.chairperson_id,
        meeting.notetaker_id,
    } or any(participant.user_id == user.id for participant in meeting.participants)


def can_read_meeting(user: User, meeting: Meeting) -> bool:
    roles = user_role_codes(user)
    return roles.isdisjoint({SUPER_ADMIN_ROLE, PIC_ROLE}) and bool(roles & MEETING_MANAGER_ROLES)


def can_manage_meeting(user: User, meeting: Meeting) -> bool:
    roles = user_role_codes(user)
    if roles & {SUPER_ADMIN_ROLE, PIC_ROLE}:
        return False
    return bool(roles & {SECRETARIAT_ROLE, MANAGER_LEGAL_ROLE, VICE_RECTOR_ROLE})


def can_create_meeting(user: User) -> bool:
    roles = user_role_codes(user)
    return roles.isdisjoint({SUPER_ADMIN_ROLE, PIC_ROLE}) and bool(
        roles & {SECRETARIAT_ROLE, MANAGER_LEGAL_ROLE, VICE_RECTOR_ROLE}
    )


def can_transition_meeting(user: User) -> bool:
    roles = user_role_codes(user)
    return roles.isdisjoint({SUPER_ADMIN_ROLE, PIC_ROLE}) and bool(
        roles & SECRETARIAT_OPERATOR_ROLES
    )


def can_review_meeting_minutes(user: User) -> bool:
    """Operational Secretariat and Manager Legal users may review minutes."""
    roles = user_role_codes(user)
    return roles.isdisjoint({SUPER_ADMIN_ROLE, PIC_ROLE}) and bool(
        roles & SECRETARIAT_OPERATOR_ROLES
    )


def can_read_minutes(user: User, meeting: Meeting) -> bool:
    """PIC and Super Admin never receive full restricted minutes content."""
    roles = user_role_codes(user)
    if roles & {SUPER_ADMIN_ROLE, PIC_ROLE}:
        return False
    return can_read_meeting(user, meeting)


def can_edit_minutes(user: User, meeting: Meeting) -> bool:
    """Any authorized core user may append a minutes revision while the meeting is LIVE."""
    roles = user_role_codes(user)
    if roles & {SUPER_ADMIN_ROLE, PIC_ROLE}:
        return False
    return can_read_minutes(user, meeting) and bool(roles & MEETING_EDITOR_ROLES)


def can_create_decision_brief(user: User, meeting: Meeting) -> bool:
    """Secretariat, Manager Legal, and in-scope Warek users may create draft briefs."""
    roles = user_role_codes(user)
    if roles & {SUPER_ADMIN_ROLE, PIC_ROLE}:
        return False
    return bool(roles & {SECRETARIAT_ROLE, MANAGER_LEGAL_ROLE, VICE_RECTOR_ROLE})


def can_review_decision_brief(user: User, meeting: Meeting) -> bool:
    """Active Secretariat, Manager Legal, Rektor, or Warek users may review in-scope briefs."""
    roles = user_role_codes(user)
    if not user.is_active or roles & {SUPER_ADMIN_ROLE, PIC_ROLE}:
        return False
    return can_read_meeting(user, meeting) and bool(
        roles
        & {
            SECRETARIAT_ROLE,
            MANAGER_LEGAL_ROLE,
            RECTOR_ROLE,
            VICE_RECTOR_ROLE,
        }
    )


def _decision_brief_event_name(value: str) -> DecisionBriefApprovalEventName:
    if value == "SUBMITTED":
        return "SUBMITTED"
    if value == "WITHDRAWN":
        return "WITHDRAWN"
    if value == "APPROVED":
        return "APPROVED"
    if value == "REJECTED":
        return "REJECTED"
    raise ValueError(f"Unknown Decision Brief approval event type: {value}")


def list_meetings(
    session: Session, user: User, limit: int, offset: int, query: str | None = None
) -> list[Meeting]:
    if not can_read_meetings(user):
        return []
    statement = select(Meeting).options(
        selectinload(Meeting.agendas),
        selectinload(Meeting.participants).selectinload(MeetingParticipant.user),
    )
    normalized_query = (query or "").strip()
    if normalized_query:
        escaped_query = (
            normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
        statement = statement.where(
            or_(
                Meeting.meeting_number.ilike(pattern, escape="\\"),
                Meeting.title.ilike(pattern, escape="\\"),
            )
        )
    statement = statement.order_by(Meeting.meeting_date.desc(), Meeting.meeting_number)
    statement = statement.offset(offset).limit(limit)
    return list(session.scalars(statement).unique().all())


def get_meeting(session: Session, meeting_id: UUID) -> Meeting | None:
    statement = (
        select(Meeting)
        .options(
            selectinload(Meeting.agendas),
            selectinload(Meeting.participants).selectinload(MeetingParticipant.user),
        )
        .where(Meeting.id == meeting_id)
    )
    return session.scalar(statement)


def _require_active_users(session: Session, user_ids: set[UUID]) -> None:
    if not user_ids:
        return
    active_ids = set(
        session.scalars(select(User.id).where(User.id.in_(user_ids), User.is_active.is_(True)))
    )
    if active_ids != user_ids:
        raise InvalidMeetingReference


def _lock_editable_meeting(
    session: Session,
    actor: User,
    meeting_id: UUID,
    *,
    expected_version: int | None = None,
) -> Meeting:
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if not can_manage_meeting(actor, meeting):
        session.rollback()
        raise MeetingMutationDenied
    if meeting.status not in {MeetingStatus.DRAFT, MeetingStatus.LIVE}:
        session.rollback()
        raise MeetingNotEditable
    if expected_version is not None and meeting.version != expected_version:
        session.rollback()
        raise StaleMeetingVersion
    return meeting


def _audit_value(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _commit_meeting_mutation(
    session: Session,
    *,
    meeting: Meeting,
    actor: User,
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
) -> None:
    meeting.version += 1
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise DuplicateMeetingRecord from error
    except SQLAlchemyError as error:
        session.rollback()
        raise MeetingMutationPersistenceError from error

    try:
        append_meeting_change_event(
            session,
            actor=actor,
            meeting_id=meeting.id,
            action=action,
            correlation_id=correlation_id,
            before_values=before_values,
            after_values=after_values,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise MeetingMutationPersistenceError from error


def create_meeting(session: Session, creator: User, data: MeetingCreate) -> Meeting:
    if data.notetaker_id is not None:
        notetaker = session.scalar(
            select(User)
            .where(User.id == data.notetaker_id, User.is_active.is_(True))
            .options(selectinload(User.roles))
        )
        if notetaker is None or not can_read_meetings(notetaker):
            session.rollback()
            raise InvalidMeetingReference

    meeting = Meeting(
        meeting_number=data.meeting_number,
        title=data.title,
        meeting_type=data.meeting_type,
        meeting_date=data.meeting_date,
        start_time=data.start_time,
        end_time=data.end_time,
        location=data.location,
        created_by_id=creator.id,
        notetaker_id=data.notetaker_id,
        status=MeetingStatus.DRAFT,
    )
    session.add(meeting)
    _commit_or_raise_duplicate(session)
    return get_meeting(session, meeting.id)  # type: ignore[return-value]


def update_meeting_metadata(
    session: Session,
    meeting_id: UUID,
    actor: User,
    data: MeetingMetadataUpdate,
    *,
    correlation_id: UUID | None,
) -> Meeting:
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if not can_manage_meeting(actor, meeting):
        session.rollback()
        raise MeetingMutationDenied
    if meeting.version != data.expected_version:
        session.rollback()
        raise StaleMeetingVersion
    changes = data.model_fields_set - {"expected_version"}
    if meeting.status is MeetingStatus.ARCHIVED or (
        changes != {"meeting_number"}
        and meeting.status not in {MeetingStatus.DRAFT, MeetingStatus.LIVE}
    ):
        session.rollback()
        raise MeetingNotEditable
    candidate_start = data.start_time if "start_time" in changes else meeting.start_time
    candidate_end = data.end_time if "end_time" in changes else meeting.end_time
    if (
        candidate_start is not None
        and candidate_end is not None
        and candidate_end < candidate_start
    ):
        session.rollback()
        raise InvalidMeetingMetadata

    before_values: dict[str, str] = {}
    after_values: dict[str, str] = {}
    for field in sorted(changes):
        previous = getattr(meeting, field)
        updated = getattr(data, field)
        if previous == updated:
            continue
        before_values[field] = _audit_value(previous)
        after_values[field] = _audit_value(updated)
        setattr(meeting, field, updated)

    if not after_values:
        session.rollback()
        result = get_meeting(session, meeting_id)
        if result is None:
            raise InvalidMeetingReference
        return result

    _commit_meeting_mutation(
        session,
        meeting=meeting,
        actor=actor,
        action="meeting.metadata_updated",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values=after_values,
    )
    result = get_meeting(session, meeting_id)
    if result is None:
        raise InvalidMeetingReference
    return result


def create_agenda(
    session: Session,
    meeting_id: UUID,
    actor: User,
    data: AgendaCreate,
    *,
    correlation_id: UUID | None,
) -> Agenda:
    meeting = _lock_editable_meeting(
        session, actor, meeting_id, expected_version=data.expected_version
    )
    last_agenda_number = session.scalar(
        select(func.max(Agenda.agenda_number)).where(Agenda.meeting_id == meeting.id)
    )
    last_sort_order = session.scalar(
        select(func.max(Agenda.sort_order)).where(Agenda.meeting_id == meeting.id)
    )
    agenda = Agenda(
        meeting_id=meeting.id,
        agenda_number=(last_agenda_number or 0) + 1,
        title=data.title,
        agenda_description=data.agenda_description,
        pic_suggestion=data.pic_suggestion,
        supporting_pic_suggestion=data.supporting_pic_suggestion,
        duration_minutes=data.duration_minutes,
        sort_order=(last_sort_order or -1) + 1,
    )
    session.add(agenda)
    try:
        session.flush()
        _commit_meeting_mutation(
            session,
            meeting=meeting,
            actor=actor,
            action="meeting.agenda_changed",
            correlation_id=correlation_id,
            before_values=None,
            after_values={
                "agenda_id": str(agenda.id),
                "operation": "CREATED",
                "agenda_number": str(agenda.agenda_number),
                "title": agenda.title,
                "pic_suggestion": _audit_value(agenda.pic_suggestion),
                "supporting_pic_suggestion": _audit_value(agenda.supporting_pic_suggestion),
                "duration_minutes": _audit_value(agenda.duration_minutes),
                "sort_order": str(agenda.sort_order),
            },
        )
    except DuplicateMeetingRecord:
        raise
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        if isinstance(error, IntegrityError):
            raise DuplicateMeetingRecord from error
        raise MeetingMutationPersistenceError from error
    result = session.get(Agenda, agenda.id)
    if result is None:
        raise MeetingAgendaNotFound
    return result


def add_meeting_participant(
    session: Session,
    meeting_id: UUID,
    actor: User,
    data: MeetingParticipantCreate,
    *,
    correlation_id: UUID | None,
) -> MeetingParticipant:
    meeting = _lock_editable_meeting(
        session, actor, meeting_id, expected_version=data.expected_version
    )
    _require_active_users(session, {data.user_id})
    if session.get(MeetingParticipant, (meeting.id, data.user_id)) is not None:
        session.rollback()
        raise DuplicateMeetingRecord
    participant_user = session.get(User, data.user_id)
    if participant_user is None:
        session.rollback()
        raise InvalidMeetingReference
    participant = MeetingParticipant(
        meeting_id=meeting.id,
        user_id=data.user_id,
        participant_title=participant_user.job_title,
    )
    meeting.participants.append(participant)
    session.add(participant)
    try:
        session.flush()
        _commit_meeting_mutation(
            session,
            meeting=meeting,
            actor=actor,
            action="meeting.participant_changed",
            correlation_id=correlation_id,
            before_values=None,
            after_values={
                "participant_user_id": str(participant.user_id),
                "operation": "ADDED",
                "changed_fields": "user_id",
            },
        )
    except DuplicateMeetingRecord:
        raise
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        if isinstance(error, IntegrityError):
            raise DuplicateMeetingRecord from error
        raise MeetingMutationPersistenceError from error
    result = session.get(MeetingParticipant, (meeting.id, data.user_id))
    if result is None:
        raise MeetingParticipantNotFound
    session.refresh(result)
    return result


def _agenda_audit_snapshot(
    agenda: Agenda, *, operation: str, changed_fields: set[str]
) -> dict[str, str]:
    return {
        "agenda_id": str(agenda.id),
        "operation": operation,
        "agenda_number": str(agenda.agenda_number),
        "title": agenda.title,
        "pic_suggestion": _audit_value(agenda.pic_suggestion),
        "supporting_pic_suggestion": _audit_value(agenda.supporting_pic_suggestion),
        "duration_minutes": _audit_value(agenda.duration_minutes),
        "sort_order": str(agenda.sort_order),
        "changed_fields": ",".join(sorted(changed_fields)),
    }


def update_agenda(
    session: Session,
    meeting_id: UUID,
    agenda_id: UUID,
    actor: User,
    data: AgendaUpdate,
    *,
    correlation_id: UUID | None,
) -> Agenda:
    meeting = _lock_editable_meeting(
        session, actor, meeting_id, expected_version=data.expected_version
    )
    agenda = session.scalar(
        select(Agenda).where(Agenda.id == agenda_id, Agenda.meeting_id == meeting.id)
    )
    if agenda is None:
        session.rollback()
        raise MeetingAgendaNotFound
    fields = {
        "title",
        "agenda_description",
        "pic_suggestion",
        "supporting_pic_suggestion",
        "duration_minutes",
    }
    changed_fields = {field for field in fields if getattr(agenda, field) != getattr(data, field)}
    if not changed_fields:
        session.rollback()
        result = session.get(Agenda, agenda_id)
        if result is None:
            raise MeetingAgendaNotFound
        return result

    before_values = _agenda_audit_snapshot(
        agenda, operation="UPDATED", changed_fields=changed_fields
    )
    for field in changed_fields:
        setattr(agenda, field, getattr(data, field))
    after_values = _agenda_audit_snapshot(
        agenda, operation="UPDATED", changed_fields=changed_fields
    )
    _commit_meeting_mutation(
        session,
        meeting=meeting,
        actor=actor,
        action="meeting.agenda_changed",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values=after_values,
    )
    result = session.get(Agenda, agenda_id)
    if result is None:
        raise MeetingAgendaNotFound
    return result


def delete_agenda(
    session: Session,
    meeting_id: UUID,
    agenda_id: UUID,
    actor: User,
    *,
    expected_version: int,
    correlation_id: UUID | None,
) -> None:
    meeting = _lock_editable_meeting(session, actor, meeting_id, expected_version=expected_version)
    agenda = session.scalar(
        select(Agenda).where(Agenda.id == agenda_id, Agenda.meeting_id == meeting.id)
    )
    if agenda is None:
        session.rollback()
        raise MeetingAgendaNotFound
    if session.scalar(
        select(MinutesDiscussion.id).where(MinutesDiscussion.agenda_id == agenda.id).limit(1)
    ):
        session.rollback()
        raise MeetingAgendaReferenced

    before_values = _agenda_audit_snapshot(
        agenda,
        operation="DELETED",
        changed_fields={
            "agenda_number",
            "title",
            "lead_user_id",
            "duration_minutes",
            "sort_order",
        },
    )
    session.delete(agenda)
    _commit_meeting_mutation(
        session,
        meeting=meeting,
        actor=actor,
        action="meeting.agenda_changed",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values=None,
    )


def _participant_audit_snapshot(
    participant: MeetingParticipant, *, operation: str, changed_fields: set[str]
) -> dict[str, str]:
    return {
        "participant_user_id": str(participant.user_id),
        "operation": operation,
        "changed_fields": ",".join(sorted(changed_fields)),
    }


def delete_meeting_participant(
    session: Session,
    meeting_id: UUID,
    participant_user_id: UUID,
    actor: User,
    *,
    expected_version: int,
    correlation_id: UUID | None,
) -> None:
    meeting = _lock_editable_meeting(session, actor, meeting_id, expected_version=expected_version)
    participant = session.get(MeetingParticipant, (meeting.id, participant_user_id))
    if participant is None:
        session.rollback()
        raise MeetingParticipantNotFound

    before_values = _participant_audit_snapshot(
        participant,
        operation="REMOVED",
        changed_fields={"user_id"},
    )
    session.delete(participant)
    _commit_meeting_mutation(
        session,
        meeting=meeting,
        actor=actor,
        action="meeting.participant_changed",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values=None,
    )


def list_notetaker_handovers(session: Session, meeting_id: UUID) -> list[MeetingNotetakerHandover]:
    return list(
        session.scalars(
            select(MeetingNotetakerHandover)
            .where(MeetingNotetakerHandover.meeting_id == meeting_id)
            .order_by(MeetingNotetakerHandover.requested_at, MeetingNotetakerHandover.id)
        ).all()
    )


def create_notetaker_handover(
    session: Session,
    meeting_id: UUID,
    actor: User,
    data: NotetakerHandoverCreate,
    *,
    correlation_id: UUID | None,
) -> MeetingNotetakerHandover:
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    roles = user_role_codes(actor)
    operational_secretariat = bool(roles & SECRETARIAT_OPERATOR_ROLES) and not roles & {
        SUPER_ADMIN_ROLE,
        PIC_ROLE,
    }
    current_notetaker = meeting.notetaker_id == actor.id and can_read_minutes(actor, meeting)
    if not operational_secretariat and not current_notetaker:
        session.rollback()
        raise MeetingMutationDenied
    if meeting.status is not MeetingStatus.LIVE:
        session.rollback()
        raise NotetakerHandoverNotLive
    if meeting.version != data.expected_version:
        session.rollback()
        raise StaleMeetingVersion
    if meeting.notetaker_id == data.new_notetaker_id:
        session.rollback()
        raise InvalidMeetingMetadata
    pending_handover = session.scalar(
        select(MeetingNotetakerHandover.id)
        .where(
            MeetingNotetakerHandover.meeting_id == meeting.id,
            MeetingNotetakerHandover.status == NotetakerHandoverStatus.PENDING.value,
        )
        .limit(1)
    )
    if pending_handover is not None:
        session.rollback()
        raise NotetakerHandoverConflict
    _require_active_users(session, {data.new_notetaker_id})

    handover = MeetingNotetakerHandover(
        meeting_id=meeting.id,
        from_notetaker_id=meeting.notetaker_id,
        to_notetaker_id=data.new_notetaker_id,
        requested_by_user_id=actor.id,
        status=NotetakerHandoverStatus.PENDING.value,
    )
    session.add(handover)
    try:
        session.flush()
        _commit_meeting_mutation(
            session,
            meeting=meeting,
            actor=actor,
            action="meeting.notetaker_handover_requested",
            correlation_id=correlation_id,
            before_values=None,
            after_values={
                "handover_id": str(handover.id),
                "from_notetaker_id": _audit_value(handover.from_notetaker_id),
                "to_notetaker_id": str(handover.to_notetaker_id),
                "status": handover.status,
            },
        )
    except MeetingMutationPersistenceError:
        raise
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise MeetingMutationPersistenceError from error
    result = session.get(MeetingNotetakerHandover, handover.id)
    if result is None:
        raise NotetakerHandoverNotFound
    return result


def approve_notetaker_handover(
    session: Session,
    meeting_id: UUID,
    handover_id: UUID,
    actor: User,
    *,
    correlation_id: UUID | None,
) -> MeetingNotetakerHandover:
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if not can_manage_meeting(actor, meeting):
        session.rollback()
        raise MeetingMutationDenied
    if meeting.status is not MeetingStatus.LIVE:
        session.rollback()
        raise NotetakerHandoverNotLive
    handover = session.scalar(
        select(MeetingNotetakerHandover)
        .where(
            MeetingNotetakerHandover.id == handover_id,
            MeetingNotetakerHandover.meeting_id == meeting.id,
        )
        .with_for_update()
    )
    if handover is None:
        session.rollback()
        raise NotetakerHandoverNotFound
    if (
        handover.status != NotetakerHandoverStatus.PENDING.value
        or handover.from_notetaker_id != meeting.notetaker_id
    ):
        session.rollback()
        raise NotetakerHandoverConflict
    _require_active_users(session, {handover.to_notetaker_id})

    before_values = {
        "handover_id": str(handover.id),
        "from_notetaker_id": _audit_value(handover.from_notetaker_id),
        "to_notetaker_id": str(handover.to_notetaker_id),
        "status": handover.status,
    }
    now = datetime.now(UTC)
    meeting.notetaker_id = handover.to_notetaker_id
    handover.status = NotetakerHandoverStatus.APPROVED.value
    handover.approved_by_user_id = actor.id
    handover.approved_at = now
    _commit_meeting_mutation(
        session,
        meeting=meeting,
        actor=actor,
        action="meeting.notetaker_handover_approved",
        correlation_id=correlation_id,
        before_values=before_values,
        after_values={**before_values, "status": handover.status},
    )
    result = session.get(MeetingNotetakerHandover, handover.id)
    if result is None:
        raise NotetakerHandoverNotFound
    return result


def create_minutes_revision(
    session: Session,
    meeting_id: UUID,
    author: User,
    data: MinutesRevisionCreate,
) -> MinutesRevision:
    """Append a revision using a locked meeting row and an optimistic base revision."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if not can_edit_minutes(author, meeting):
        session.rollback()
        raise MinutesRevisionEditDenied
    if meeting.status is not MeetingStatus.LIVE:
        session.rollback()
        raise MeetingNotLiveForMinutesRevision

    latest_revision = _latest_minutes_revision(session, meeting_id)
    latest_id = latest_revision.id if latest_revision is not None else None
    if data.base_revision_id != latest_id:
        session.rollback()
        raise MinutesRevisionConflict

    if data.format_version == 2:
        agenda_ids = {discussion.agenda_id for discussion in data.discussions}
        if agenda_ids:
            matching_agenda_ids = set(
                session.scalars(
                    select(Agenda.id).where(
                        Agenda.meeting_id == meeting_id, Agenda.id.in_(agenda_ids)
                    )
                )
            )
            if matching_agenda_ids != agenda_ids:
                session.rollback()
                raise InvalidMinutesRevisionStructure

    revision_id = uuid4()
    revision = MinutesRevision(
        id=revision_id,
        meeting_id=meeting_id,
        revision_number=(latest_revision.revision_number if latest_revision else 0) + 1,
        format_version=data.format_version,
        content=data.content,
        created_by_id=author.id,
        created_at=datetime.now(UTC),
    )
    discussion_rows: list[MinutesDiscussion] = []
    decision_rows: list[MinutesDecision] = []
    if data.format_version == 2:
        discussion_numbers: dict[UUID, int] = {}
        for discussion in data.discussions:
            discussion_number = discussion_numbers.get(discussion.agenda_id, 0) + 1
            discussion_numbers[discussion.agenda_id] = discussion_number
            discussion_id = uuid4()
            discussion_rows.append(
                MinutesDiscussion(
                    id=discussion_id,
                    meeting_id=meeting_id,
                    minutes_revision_id=revision_id,
                    agenda_id=discussion.agenda_id,
                    discussion_number=discussion_number,
                    subject=discussion.subject,
                    content=discussion.content,
                )
            )
            decision_rows.extend(
                MinutesDecision(
                    id=uuid4(),
                    meeting_id=meeting_id,
                    minutes_revision_id=revision_id,
                    discussion_id=discussion_id,
                    decision_number=decision_number,
                    decision_text=decision.decision_text,
                    pic_suggestion=decision.pic_suggestion,
                    output_expected=decision.output_expected,
                    target_date=decision.target_date,
                    target_text=decision.target_text,
                    is_action_item=decision.is_action_item,
                )
                for decision_number, decision in enumerate(discussion.decisions, start=1)
            )
    session.add(revision)
    try:
        session.flush()
        session.add_all(discussion_rows)
        session.flush()
        session.add_all(decision_rows)
        append_minutes_revision_event(
            session,
            actor=author,
            meeting_id=meeting_id,
            revision_id=revision.id,
            revision_number=revision.revision_number,
            format_version=revision.format_version,
            decision_count=len(decision_rows),
            prior_revision_id=latest_revision.id if latest_revision else None,
            prior_revision_number=latest_revision.revision_number if latest_revision else None,
            correlation_id=None,
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(revision)
    return revision


def list_minutes_revisions(session: Session, meeting_id: UUID) -> list[MinutesRevision]:
    """Return immutable snapshots in their per-meeting revision order."""
    statement = (
        select(MinutesRevision)
        .where(MinutesRevision.meeting_id == meeting_id)
        .order_by(MinutesRevision.revision_number)
    )
    return list(session.scalars(statement).all())


def create_decision_brief_version(
    session: Session,
    meeting_id: UUID,
    author: User,
    data: DecisionBriefVersionCreate,
) -> DecisionBriefVersion:
    """Append one editorial snapshot tied to the active structured minutes revision."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if meeting.status is MeetingStatus.ARCHIVED:
        session.rollback()
        raise MeetingNotEditable
    if not can_create_decision_brief(author, meeting):
        session.rollback()
        raise MinutesRevisionEditDenied

    source_revision = session.scalar(
        select(MinutesRevision).where(
            MinutesRevision.meeting_id == meeting_id,
            MinutesRevision.id == data.source_minutes_revision_id,
        )
    )
    if source_revision is None:
        session.rollback()
        raise InvalidDecisionBriefSource
    active_revision = _latest_minutes_revision(session, meeting_id)
    if active_revision is None or source_revision.id != active_revision.id:
        session.rollback()
        raise DecisionBriefSourceRevisionConflict

    source_decision_ids = {item.decision_id for item in data.decisions}
    all_source_decision_ids = set(
        session.scalars(
            select(MinutesDecision.id).where(
                MinutesDecision.meeting_id == meeting_id,
                MinutesDecision.minutes_revision_id == source_revision.id,
            )
        )
    )
    matched_ids = set(
        session.scalars(
            select(MinutesDecision.id).where(
                MinutesDecision.meeting_id == meeting_id,
                MinutesDecision.minutes_revision_id == source_revision.id,
                MinutesDecision.id.in_(source_decision_ids),
            )
        )
    )
    if matched_ids != source_decision_ids or source_decision_ids != all_source_decision_ids:
        session.rollback()
        raise InvalidDecisionBriefSource

    previous_version = session.scalar(
        select(func.coalesce(func.max(DecisionBriefVersion.version_number), 0)).where(
            DecisionBriefVersion.meeting_id == meeting_id
        )
    )
    version = DecisionBriefVersion(
        meeting_id=meeting_id,
        source_minutes_revision_id=source_revision.id,
        version_number=(previous_version or 0) + 1,
        summary=data.summary,
        notes=data.notes,
        created_by_id=author.id,
        created_at=datetime.now(UTC),
    )
    entries = [
        DecisionBriefDecision(
            meeting_id=meeting_id,
            source_minutes_revision_id=source_revision.id,
            source_decision_id=item.decision_id,
            position=position,
            brief_text=item.brief_text,
            priority=item.priority,
            editorial_note=item.editorial_note,
        )
        for position, item in enumerate(data.decisions, start=1)
    ]
    session.add(version)
    try:
        session.flush()
        for entry in entries:
            entry.brief_version_id = version.id
        session.add_all(entries)
        append_decision_brief_saved_event(
            session,
            actor=author,
            meeting_id=meeting_id,
            brief_version_id=version.id,
            source_minutes_revision_id=source_revision.id,
            version_number=version.version_number,
            decision_count=len(entries),
            correlation_id=None,
        )
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(version)
    return version


def list_decision_brief_versions(
    session: Session, meeting_id: UUID
) -> tuple[list[DecisionBriefVersion], UUID | None]:
    """Return immutable brief history and the active minutes revision for stale calculation."""
    versions = list(
        session.scalars(
            select(DecisionBriefVersion)
            .where(DecisionBriefVersion.meeting_id == meeting_id)
            .order_by(DecisionBriefVersion.version_number)
        ).all()
    )
    active_revision = _latest_minutes_revision(session, meeting_id)
    return versions, active_revision.id if active_revision is not None else None


def list_decision_brief_approval_events(
    session: Session, brief_version_ids: list[UUID]
) -> dict[UUID, list[DecisionBriefApprovalEventResponse]]:
    if not brief_version_ids:
        return {}
    rows = session.scalars(
        select(DecisionBriefApprovalEvent)
        .where(DecisionBriefApprovalEvent.brief_version_id.in_(brief_version_ids))
        .order_by(
            DecisionBriefApprovalEvent.brief_version_id,
            DecisionBriefApprovalEvent.event_number,
        )
    )
    result: dict[UUID, list[DecisionBriefApprovalEventResponse]] = {
        version_id: [] for version_id in brief_version_ids
    }
    for row in rows:
        result[row.brief_version_id].append(
            DecisionBriefApprovalEventResponse(
                id=row.id,
                event_number=row.event_number,
                event_type=_decision_brief_event_name(row.event_type),
                actor_user_id=row.actor_user_id,
                actor_roles=row.actor_roles,
                reason=row.reason,
                correlation_id=row.correlation_id,
                occurred_at=row.occurred_at,
            )
        )
    return result


def decision_brief_approval_state(
    events: list[DecisionBriefApprovalEventResponse],
) -> DecisionBriefApprovalState:
    if not events:
        return "DRAFT"
    state_by_event: dict[str, DecisionBriefApprovalState] = {
        "SUBMITTED": "PENDING_APPROVAL",
        "WITHDRAWN": "WITHDRAWN",
        "APPROVED": "APPROVED",
        "REJECTED": "REJECTED",
    }
    return state_by_event[events[-1].event_type]


def _notify_decision_brief_workflow_event(
    session: Session,
    *,
    meeting: Meeting,
    version: DecisionBriefVersion,
    event: DecisionBriefApprovalEvent,
    actor_id: UUID,
    event_type: DecisionBriefApprovalEventType,
) -> None:
    if event_type in {
        DecisionBriefApprovalEventType.SUBMITTED,
        DecisionBriefApprovalEventType.WITHDRAWN,
    }:
        candidate_ids = {
            user_id
            for user_id in (meeting.chairperson_id, meeting.notetaker_id)
            if user_id is not None
        }
        candidate_ids.update(
            session.scalars(
                select(MeetingParticipant.user_id).where(
                    MeetingParticipant.meeting_id == meeting.id
                )
            )
        )
        candidate_ids.discard(actor_id)
        candidates = (
            session.scalars(
                select(User)
                .options(selectinload(User.roles))
                .where(User.id.in_(candidate_ids), User.is_active.is_(True))
            ).all()
            if candidate_ids
            else []
        )
        reviewer_ids = {
            candidate.id
            for candidate in candidates
            if can_review_decision_brief(candidate, meeting)
        }
        author_is_active = session.scalar(
            select(User.is_active).where(User.id == version.created_by_id)
        )
        if version.created_by_id != actor_id and author_is_active is True:
            reviewer_ids.add(version.created_by_id)
        notification_type = (
            NotificationType.DECISION_BRIEF_REVIEW_NEEDED
            if event_type is DecisionBriefApprovalEventType.SUBMITTED
            else NotificationType.DECISION_BRIEF_REVIEW_WITHDRAWN
        )
        message = (
            "Decision Brief menunggu review."
            if event_type is DecisionBriefApprovalEventType.SUBMITTED
            else "Pengajuan Decision Brief telah ditarik."
        )
    else:
        author_is_active = session.scalar(
            select(User.is_active).where(User.id == version.created_by_id)
        )
        reviewer_ids = (
            {version.created_by_id}
            if version.created_by_id != actor_id and author_is_active is True
            else set()
        )
        notification_type = NotificationType.DECISION_BRIEF_REVIEW_COMPLETED
        message = "Review Decision Brief telah selesai."

    add_notifications(
        session,
        recipient_ids=reviewer_ids,
        event_key=f"decision_brief_workflow:{event.id}",
        notification_type=notification_type,
        message=message,
        target_type=NotificationTargetType.MEETING,
        target_id=meeting.id,
    )


def transition_decision_brief_workflow(
    session: Session,
    meeting_id: UUID,
    brief_version_id: UUID,
    actor: User,
    event_type: DecisionBriefApprovalEventType,
    *,
    correlation_id: UUID | None,
    reason: str | None = None,
) -> DecisionBriefApprovalEvent:
    """Append one authorized workflow event with its central audit record."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if not actor.is_active or user_role_codes(actor) & {SUPER_ADMIN_ROLE, PIC_ROLE}:
        session.rollback()
        raise DecisionBriefWorkflowDenied
    if meeting.status is MeetingStatus.ARCHIVED:
        session.rollback()
        raise DecisionBriefWorkflowConflict

    version = session.scalar(
        select(DecisionBriefVersion).where(
            DecisionBriefVersion.meeting_id == meeting_id,
            DecisionBriefVersion.id == brief_version_id,
        )
    )
    if version is None:
        session.rollback()
        raise DecisionBriefVersionNotFound

    authorized_approver = can_review_decision_brief(actor, meeting)
    authorized_author = actor.id == version.created_by_id and can_create_decision_brief(
        actor, meeting
    )
    if event_type is DecisionBriefApprovalEventType.SUBMITTED:
        if not authorized_author and not authorized_approver:
            session.rollback()
            raise DecisionBriefWorkflowDenied
    elif event_type is DecisionBriefApprovalEventType.WITHDRAWN:
        if not authorized_author:
            session.rollback()
            raise DecisionBriefWorkflowDenied
    elif not authorized_approver:
        session.rollback()
        raise DecisionBriefWorkflowDenied

    history = list(
        session.scalars(
            select(DecisionBriefApprovalEvent)
            .where(DecisionBriefApprovalEvent.brief_version_id == version.id)
            .order_by(DecisionBriefApprovalEvent.event_number)
        ).all()
    )
    current_state = decision_brief_approval_state(
        [
            DecisionBriefApprovalEventResponse(
                id=item.id,
                event_number=item.event_number,
                event_type=_decision_brief_event_name(item.event_type),
                actor_user_id=item.actor_user_id,
                actor_roles=item.actor_roles,
                reason=item.reason,
                correlation_id=item.correlation_id,
                occurred_at=item.occurred_at,
            )
            for item in history
        ]
    )

    if event_type is DecisionBriefApprovalEventType.SUBMITTED:
        if current_state not in {"DRAFT", "WITHDRAWN"}:
            session.rollback()
            raise DecisionBriefWorkflowConflict
        latest_review = session.scalar(
            select(MinutesReview)
            .where(MinutesReview.meeting_id == meeting_id)
            .order_by(MinutesReview.review_number.desc())
            .limit(1)
        )
        active_revision = _latest_minutes_revision(session, meeting_id)
        if (
            meeting.status is not MeetingStatus.FINAL
            or active_revision is None
            or active_revision.id != version.source_minutes_revision_id
            or latest_review is None
            or latest_review.result is not MinutesReviewResult.VALID
            or latest_review.minutes_revision_id != version.source_minutes_revision_id
        ):
            session.rollback()
            raise DecisionBriefSubmissionIneligible
    elif event_type is DecisionBriefApprovalEventType.WITHDRAWN:
        if actor.id != version.created_by_id:
            session.rollback()
            raise DecisionBriefWorkflowDenied
        if current_state != "PENDING_APPROVAL":
            session.rollback()
            raise DecisionBriefWorkflowConflict
    else:
        if current_state != "PENDING_APPROVAL":
            session.rollback()
            raise DecisionBriefWorkflowConflict
        if actor.id == version.created_by_id:
            session.rollback()
            raise DecisionBriefWorkflowDenied
        if event_type is DecisionBriefApprovalEventType.REJECTED:
            if reason is None or not reason.strip():
                session.rollback()
                raise DecisionBriefWorkflowConflict
            reason = reason.strip()

    before_state = current_state
    action_by_event: dict[
        DecisionBriefApprovalEventType,
        Literal["SUBMITTED", "WITHDRAWN", "APPROVED", "REJECTED"],
    ] = {
        DecisionBriefApprovalEventType.SUBMITTED: "SUBMITTED",
        DecisionBriefApprovalEventType.WITHDRAWN: "WITHDRAWN",
        DecisionBriefApprovalEventType.APPROVED: "APPROVED",
        DecisionBriefApprovalEventType.REJECTED: "REJECTED",
    }
    try:
        audit_event = append_decision_brief_workflow_event(
            session,
            actor=actor,
            brief_version_id=version.id,
            meeting_id=meeting_id,
            version_number=version.version_number,
            event_type=action_by_event[event_type],
            before_state=before_state,
            correlation_id=correlation_id,
        )
        event = DecisionBriefApprovalEvent(
            meeting_id=meeting_id,
            brief_version_id=version.id,
            source_minutes_revision_id=version.source_minutes_revision_id,
            event_number=len(history) + 1,
            event_type=event_type.value,
            actor_user_id=actor.id,
            actor_roles=audit_event.actor_roles,
            reason=reason if event_type is DecisionBriefApprovalEventType.REJECTED else None,
            correlation_id=correlation_id,
            occurred_at=datetime.now(UTC),
        )
        session.add(event)
        session.flush()
        _notify_decision_brief_workflow_event(
            session,
            meeting=meeting,
            version=version,
            event=event,
            actor_id=actor.id,
            event_type=event_type,
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DecisionBriefWorkflowConflict from error
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise DecisionBriefWorkflowPersistenceError from error
    session.refresh(event)
    return event


def record_minutes_review(
    session: Session,
    meeting_id: UUID,
    reviewer: User,
    data: MinutesReviewCreate,
) -> MinutesReview:
    """Record a review attestation, serialized with the meeting lifecycle."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference
    if meeting.status is not MeetingStatus.LIVE:
        session.rollback()
        raise MeetingNotLiveForMinutesReview

    latest_revision = _latest_minutes_revision(session, meeting_id)
    if latest_revision is None or data.minutes_revision_id != latest_revision.id:
        session.rollback()
        raise MinutesRevisionConflict

    previous_number = session.scalar(
        select(func.coalesce(func.max(MinutesReview.review_number), 0)).where(
            MinutesReview.meeting_id == meeting_id
        )
    )
    review = MinutesReview(
        meeting_id=meeting_id,
        reviewer_user_id=reviewer.id,
        minutes_revision_id=latest_revision.id,
        review_number=(previous_number or 0) + 1,
        result=data.result,
        review_note=data.review_note,
        reviewed_at=datetime.now(UTC),
    )
    session.add(review)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(review)
    return review


def list_minutes_reviews(session: Session, meeting_id: UUID) -> list[MinutesReview]:
    """Return the ordered review history for an already-authorized meeting."""
    statement = (
        select(MinutesReview)
        .where(MinutesReview.meeting_id == meeting_id)
        .order_by(MinutesReview.review_number)
    )
    return list(session.scalars(statement).all())


def transition_meeting(
    session: Session,
    meeting_id: UUID,
    actor: User,
    to_status: MeetingStatus,
    correlation_id: UUID | None = None,
) -> Meeting:
    """Apply one allowed transition and write both histories in one transaction."""
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise InvalidMeetingReference

    from_status = meeting.status
    if from_status is to_status:
        session.rollback()
        raise InvalidMeetingTransition

    if from_status is MeetingStatus.DRAFT and to_status is MeetingStatus.LIVE:
        meeting.started_at = datetime.now(UTC)
    elif from_status is MeetingStatus.LIVE and to_status is MeetingStatus.FINAL:
        latest_revision = _latest_minutes_revision(session, meeting_id)
        latest_review = session.scalar(
            select(MinutesReview)
            .where(MinutesReview.meeting_id == meeting_id)
            .order_by(MinutesReview.review_number.desc())
            .limit(1)
        )
        if (
            latest_revision is None
            or latest_review is None
            or latest_review.result is not MinutesReviewResult.VALID
            or latest_review.minutes_revision_id != latest_revision.id
        ):
            session.rollback()
            raise MinutesReviewRequired
        meeting.finalized_at = datetime.now(UTC)
        meeting.finalized_by_id = actor.id
    elif from_status is MeetingStatus.FINAL and to_status is MeetingStatus.ARCHIVED:
        pass
    else:
        session.rollback()
        raise InvalidMeetingTransition

    meeting.status = to_status
    meeting.version += 1
    session.add(
        MeetingStatusEvent(
            meeting_id=meeting.id,
            actor_user_id=actor.id,
            from_status=from_status.value,
            to_status=to_status.value,
        )
    )
    append_meeting_status_event(
        session,
        actor=actor,
        meeting_id=meeting.id,
        result="SUCCEEDED",
        correlation_id=correlation_id,
        before_values={"status": from_status.value},
        after_values={"status": to_status.value},
    )
    try:
        session.commit()
    except (SQLAlchemyError, ValidationError):
        session.rollback()
        raise
    return get_meeting(session, meeting_id)  # type: ignore[return-value]


def _commit_or_raise_duplicate(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise DuplicateMeetingRecord from error


def _latest_minutes_revision(session: Session, meeting_id: UUID) -> MinutesRevision | None:
    return session.scalar(
        select(MinutesRevision)
        .where(MinutesRevision.meeting_id == meeting_id)
        .order_by(MinutesRevision.revision_number.desc())
        .limit(1)
    )
