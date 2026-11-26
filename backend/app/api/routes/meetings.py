"""Rapim metadata and agenda endpoints with role and object authorization."""

import logging
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import get_current_identity, require_csrf
from app.db.session import get_db
from app.models.auth import User, UserSession
from app.models.meeting import (
    Agenda,
    DecisionBriefApprovalEventType,
    DecisionBriefDecision,
    DecisionBriefVersion,
    Meeting,
    MeetingExternalParticipant,
    MeetingParticipant,
    MinutesDecision,
    MinutesDiscussion,
    MinutesReview,
    MinutesRevision,
)
from app.schemas.meetings import (
    AgendaCreate,
    AgendaResponse,
    AgendaUpdate,
    DecisionBriefDecisionResponse,
    DecisionBriefRejectionRequest,
    DecisionBriefVersionCreate,
    DecisionBriefVersionResponse,
    MeetingCreate,
    MeetingExternalParticipantCreate,
    MeetingExternalParticipantResponse,
    MeetingMetadataUpdate,
    MeetingParticipantCreate,
    MeetingParticipantOptionResponse,
    MeetingParticipantResponse,
    MeetingResponse,
    MeetingTransitionRequest,
    MinutesDecisionResponse,
    MinutesDiscussionResponse,
    MinutesReviewCreate,
    MinutesReviewResponse,
    MinutesRevisionCreate,
    MinutesRevisionResponse,
)
from app.services.audit import AuditEventWriteError, record_denied_meeting_transition
from app.services.meetings import (
    DecisionBriefSourceRevisionConflict,
    DecisionBriefSubmissionIneligible,
    DecisionBriefVersionNotFound,
    DecisionBriefWorkflowConflict,
    DecisionBriefWorkflowDenied,
    DecisionBriefWorkflowPersistenceError,
    DuplicateMeetingRecord,
    InvalidDecisionBriefSource,
    InvalidMeetingMetadata,
    InvalidMeetingReference,
    InvalidMeetingTransition,
    InvalidMinutesRevisionStructure,
    MeetingAgendaNotFound,
    MeetingAgendaReferenced,
    MeetingMutationDenied,
    MeetingMutationPersistenceError,
    MeetingNotEditable,
    MeetingNotLiveForMinutesReview,
    MeetingNotLiveForMinutesRevision,
    MeetingParticipantNotFound,
    MinutesReviewRequired,
    MinutesRevisionConflict,
    MinutesRevisionEditDenied,
    StaleMeetingVersion,
    add_external_meeting_participant,
    add_meeting_participant,
    can_create_decision_brief,
    can_create_meeting,
    can_edit_minutes,
    can_read_meeting,
    can_read_meetings,
    can_read_minutes,
    can_review_meeting_minutes,
    can_transition_meeting,
    create_agenda,
    create_decision_brief_version,
    create_meeting,
    create_minutes_revision,
    decision_brief_approval_state,
    delete_agenda,
    delete_external_meeting_participant,
    delete_meeting_participant,
    get_meeting,
    list_decision_brief_approval_events,
    list_decision_brief_versions,
    list_meetings,
    list_minutes_reviews,
    list_minutes_revisions,
    record_minutes_review,
    transition_decision_brief_workflow,
    transition_meeting,
    update_agenda,
    update_meeting_metadata,
    user_role_codes,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])
logger = logging.getLogger(__name__)
Identity = tuple[UserSession, User]
CurrentIdentity = Annotated[Identity, Depends(get_current_identity)]
DatabaseSession = Annotated[Session, Depends(get_db)]


def _serialize_agenda(agenda: Agenda) -> AgendaResponse:
    return AgendaResponse(
        id=agenda.id,
        meeting_id=agenda.meeting_id,
        agenda_number=agenda.agenda_number,
        title=agenda.title,
        agenda_description=agenda.agenda_description,
        pic_suggestion=agenda.pic_suggestion,
        supporting_pic_suggestion=agenda.supporting_pic_suggestion,
        duration_minutes=agenda.duration_minutes,
        sort_order=agenda.sort_order,
    )


def _serialize_participant(participant: MeetingParticipant) -> MeetingParticipantResponse:
    return MeetingParticipantResponse(
        user_id=participant.user_id,
        participant_name=participant.user.full_name,
        participant_title=participant.participant_title or participant.user.job_title,
    )


def _serialize_external_participant(
    participant: MeetingExternalParticipant,
) -> MeetingExternalParticipantResponse:
    return MeetingExternalParticipantResponse(
        id=participant.id,
        participant_name=participant.participant_name,
    )


def _serialize_meeting(meeting: Meeting) -> MeetingResponse:
    return MeetingResponse(
        id=meeting.id,
        meeting_number=meeting.meeting_number,
        title=meeting.title,
        meeting_type=meeting.meeting_type,
        meeting_date=meeting.meeting_date,
        start_time=meeting.start_time,
        end_time=meeting.end_time,
        location=meeting.location,
        created_by_id=meeting.created_by_id,
        notetaker_id=meeting.notetaker_id,
        status=meeting.status,
        version=meeting.version,
        created_at=meeting.created_at,
        updated_at=meeting.updated_at,
        agendas=[_serialize_agenda(agenda) for agenda in meeting.agendas],
        participants=[_serialize_participant(item) for item in meeting.participants],
        external_participants=[
            _serialize_external_participant(item) for item in meeting.external_participants
        ],
    )


def _serialize_minutes_review(review: MinutesReview) -> MinutesReviewResponse:
    return MinutesReviewResponse(
        id=review.id,
        meeting_id=review.meeting_id,
        minutes_revision_id=review.minutes_revision_id,
        reviewer_user_id=review.reviewer_user_id,
        review_number=review.review_number,
        result=review.result,
        review_note=review.review_note,
        reviewed_at=review.reviewed_at,
    )


def _serialize_minutes_revision(
    session: Session, revision: MinutesRevision
) -> MinutesRevisionResponse:
    return _serialize_minutes_revisions(session, [revision])[0]


def _serialize_minutes_revisions(
    session: Session, revisions: list[MinutesRevision]
) -> list[MinutesRevisionResponse]:
    if not revisions:
        return []

    revision_ids = [revision.id for revision in revisions]
    discussion_rows = list(
        session.scalars(
            select(MinutesDiscussion)
            .where(MinutesDiscussion.minutes_revision_id.in_(revision_ids))
            .order_by(
                MinutesDiscussion.minutes_revision_id,
                MinutesDiscussion.agenda_id,
                MinutesDiscussion.discussion_number,
            )
        )
    )
    decision_rows = list(
        session.scalars(
            select(MinutesDecision)
            .where(MinutesDecision.minutes_revision_id.in_(revision_ids))
            .order_by(
                MinutesDecision.minutes_revision_id,
                MinutesDecision.discussion_id,
                MinutesDecision.decision_number,
            )
        )
    )
    decisions_by_discussion: dict[UUID, list[MinutesDecisionResponse]] = {}
    for decision in decision_rows:
        decisions_by_discussion.setdefault(decision.discussion_id, []).append(
            MinutesDecisionResponse(
                id=decision.id,
                discussion_id=decision.discussion_id,
                decision_number=decision.decision_number,
                decision_text=decision.decision_text,
                pic_suggestion=decision.pic_suggestion,
                supporting_pic_suggestion=decision.supporting_pic_suggestion,
                output_expected=decision.output_expected,
                target_date=decision.target_date,
                target_text=decision.target_text,
                is_action_item=decision.is_action_item,
            )
        )
    discussions_by_revision: dict[UUID, list[MinutesDiscussionResponse]] = {}
    for discussion in discussion_rows:
        discussions_by_revision.setdefault(discussion.minutes_revision_id, []).append(
            MinutesDiscussionResponse(
                id=discussion.id,
                agenda_id=discussion.agenda_id,
                discussion_number=discussion.discussion_number,
                subject=discussion.subject,
                content=discussion.content,
                decisions=decisions_by_discussion.get(discussion.id, []),
            )
        )
    return [
        MinutesRevisionResponse(
            id=revision.id,
            meeting_id=revision.meeting_id,
            revision_number=revision.revision_number,
            format_version=cast(Literal[1, 2], revision.format_version),
            content=revision.content,
            discussions=discussions_by_revision.get(revision.id, []),
            created_by_id=revision.created_by_id,
            created_at=revision.created_at,
        )
        for revision in revisions
    ]


def _require_manager(user: User) -> None:
    if not can_read_meetings(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Meeting access denied")


def _require_meeting_editor(user: User) -> None:
    if not can_create_meeting(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Meeting edit denied")


def _load_visible_meeting(session: Session, meeting_id: UUID, user: User) -> Meeting:
    meeting = get_meeting(session, meeting_id)
    if meeting is None or not can_read_meeting(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting


def _raise_create_error(error: Exception) -> None:
    if isinstance(error, DuplicateMeetingRecord):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Meeting number, agenda number, or participant already exists",
        ) from error
    if isinstance(error, InvalidMeetingReference):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected notetaker must be an active core user",
        ) from error
    raise error


def _raise_meeting_mutation_error(error: Exception, correlation_id: UUID | None) -> None:
    if isinstance(error, MeetingMutationDenied):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Meeting update denied"
        ) from error
    if isinstance(error, MeetingNotEditable):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only draft or live meetings can be changed",
        ) from error
    if isinstance(error, StaleMeetingVersion):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Meeting was updated by another user"
        ) from error
    if isinstance(error, InvalidMeetingMetadata):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Meeting metadata is invalid for its current status",
        ) from error
    if isinstance(error, DuplicateMeetingRecord):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Meeting number, agenda number, or participant already exists",
        ) from error
    if isinstance(error, InvalidMeetingReference):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Referenced user is missing or inactive",
        ) from error
    if isinstance(error, MeetingAgendaNotFound | MeetingParticipantNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting item not found"
        ) from error
    if isinstance(error, MeetingAgendaReferenced):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agenda is referenced by immutable minutes and cannot be removed",
        ) from error
    if isinstance(error, MeetingMutationPersistenceError):
        logger.exception("Meeting mutation failed; correlation_id=%s", correlation_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Meeting change and audit event could not be saved",
        ) from error
    raise error


@router.get("", response_model=list[MeetingResponse])
def get_meetings(
    identity: CurrentIdentity,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> list[MeetingResponse]:
    user = identity[1]
    _require_manager(user)
    return [
        _serialize_meeting(meeting)
        for meeting in list_meetings(session, user, limit=limit, offset=offset, query=query)
    ]


@router.get("/participant-options", response_model=list[MeetingParticipantOptionResponse])
def get_participant_options(
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> list[MeetingParticipantOptionResponse]:
    user = identity[1]
    _require_meeting_editor(user)
    candidates = session.scalars(
        select(User).where(User.is_active.is_(True)).options(selectinload(User.roles))
    ).all()
    return [
        MeetingParticipantOptionResponse(
            id=candidate.id,
            full_name=candidate.full_name,
            job_title=candidate.job_title,
            roles=sorted(user_role_codes(candidate)),
        )
        for candidate in candidates
        if can_read_meetings(candidate)
    ]


@router.post("", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
def post_meeting(
    data: MeetingCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingResponse:
    user = identity[1]
    _require_meeting_editor(user)
    try:
        meeting = create_meeting(session, user, data)
    except (DuplicateMeetingRecord, InvalidMeetingReference) as error:
        _raise_create_error(error)
    return _serialize_meeting(meeting)


@router.get("/{meeting_id}", response_model=MeetingResponse)
def get_meeting_detail(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> MeetingResponse:
    meeting = _load_visible_meeting(session, meeting_id, identity[1])
    return _serialize_meeting(meeting)


@router.patch("/{meeting_id}", response_model=MeetingResponse)
def patch_meeting_metadata(
    meeting_id: UUID,
    data: MeetingMetadataUpdate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        meeting = update_meeting_metadata(
            session,
            meeting_id,
            user,
            data,
            correlation_id=request.state.correlation_id,
        )
    except (
        DuplicateMeetingRecord,
        InvalidMeetingMetadata,
        InvalidMeetingReference,
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return _serialize_meeting(meeting)


@router.post(
    "/{meeting_id}/agendas",
    response_model=AgendaResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_agenda(
    meeting_id: UUID,
    data: AgendaCreate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> AgendaResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        agenda = create_agenda(
            session,
            meeting_id,
            user,
            data,
            correlation_id=request.state.correlation_id,
        )
    except (
        DuplicateMeetingRecord,
        InvalidMeetingReference,
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return _serialize_agenda(agenda)


@router.put(
    "/{meeting_id}/agendas/{agenda_id}",
    response_model=AgendaResponse,
)
def put_agenda(
    meeting_id: UUID,
    agenda_id: UUID,
    data: AgendaUpdate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> AgendaResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        agenda = update_agenda(
            session,
            meeting_id,
            agenda_id,
            user,
            data,
            correlation_id=request.state.correlation_id,
        )
    except (
        DuplicateMeetingRecord,
        InvalidMeetingReference,
        MeetingAgendaNotFound,
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return _serialize_agenda(agenda)


@router.delete(
    "/{meeting_id}/agendas/{agenda_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_agenda_route(
    meeting_id: UUID,
    agenda_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    expected_version: Annotated[int, Query(gt=0)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        delete_agenda(
            session,
            meeting_id,
            agenda_id,
            user,
            expected_version=expected_version,
            correlation_id=request.state.correlation_id,
        )
    except (
        MeetingAgendaNotFound,
        MeetingAgendaReferenced,
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{meeting_id}/participants",
    response_model=MeetingParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_participant(
    meeting_id: UUID,
    data: MeetingParticipantCreate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingParticipantResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        participant = add_meeting_participant(
            session,
            meeting_id,
            user,
            data,
            correlation_id=request.state.correlation_id,
        )
    except (
        DuplicateMeetingRecord,
        InvalidMeetingReference,
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return _serialize_participant(participant)


@router.delete(
    "/{meeting_id}/participants/{participant_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_participant_route(
    meeting_id: UUID,
    participant_user_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    expected_version: Annotated[int, Query(gt=0)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        delete_meeting_participant(
            session,
            meeting_id,
            participant_user_id,
            user,
            expected_version=expected_version,
            correlation_id=request.state.correlation_id,
        )
    except (
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        MeetingParticipantNotFound,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{meeting_id}/participants/external",
    response_model=MeetingExternalParticipantResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_external_participant(
    meeting_id: UUID,
    data: MeetingExternalParticipantCreate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingExternalParticipantResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        participant = add_external_meeting_participant(
            session,
            meeting_id,
            user,
            data,
            correlation_id=request.state.correlation_id,
        )
    except (
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return _serialize_external_participant(participant)


@router.delete(
    "/{meeting_id}/participants/external/{external_participant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_external_participant_route(
    meeting_id: UUID,
    external_participant_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    expected_version: Annotated[int, Query(gt=0)],
    _csrf: Annotated[None, Depends(require_csrf)],
) -> Response:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    try:
        delete_external_meeting_participant(
            session,
            meeting_id,
            external_participant_id,
            user,
            expected_version=expected_version,
            correlation_id=request.state.correlation_id,
        )
    except (
        MeetingMutationDenied,
        MeetingMutationPersistenceError,
        MeetingNotEditable,
        MeetingParticipantNotFound,
        StaleMeetingVersion,
    ) as error:
        _raise_meeting_mutation_error(error, request.state.correlation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{meeting_id}/transition", response_model=MeetingResponse)
def post_meeting_transition(
    meeting_id: UUID,
    data: MeetingTransitionRequest,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MeetingResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    if not can_transition_meeting(user):
        correlation_id = request.state.correlation_id
        try:
            record_denied_meeting_transition(
                session,
                actor=user,
                meeting_id=meeting_id,
                correlation_id=correlation_id,
            )
        except AuditEventWriteError:
            logger.critical(
                "Denied meeting transition could not be recorded; correlation_id=%s object_id=%s",
                correlation_id,
                meeting_id,
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Meeting transition denied"
        )
    try:
        meeting = transition_meeting(
            session,
            meeting_id,
            user,
            data.to_status,
            correlation_id=request.state.correlation_id,
        )
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except MinutesReviewRequired as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Meeting cannot be finalized until the active minutes revision "
                "has a valid minutes review"
            ),
        ) from error
    except InvalidMeetingTransition as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Meeting status transition is not allowed",
        ) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Meeting transition could not be recorded",
            headers={"X-Correlation-ID": str(request.state.correlation_id)},
        ) from error
    return _serialize_meeting(meeting)


@router.post(
    "/{meeting_id}/minutes-reviews",
    response_model=MinutesReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_minutes_review(
    meeting_id: UUID,
    data: MinutesReviewCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MinutesReviewResponse:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    if not can_review_meeting_minutes(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Minutes review denied")
    try:
        review = record_minutes_review(session, meeting_id, user, data)
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except MeetingNotLiveForMinutesReview as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes can only be reviewed while the meeting is LIVE",
        ) from error
    except MinutesRevisionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes review must reference the active revision",
        ) from error
    return _serialize_minutes_review(review)


@router.get("/{meeting_id}/minutes-reviews", response_model=list[MinutesReviewResponse])
def get_minutes_reviews(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> list[MinutesReviewResponse]:
    user = identity[1]
    _load_visible_meeting(session, meeting_id, user)
    if not can_review_meeting_minutes(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Minutes review access denied"
        )
    return [
        _serialize_minutes_review(review) for review in list_minutes_reviews(session, meeting_id)
    ]


@router.post(
    "/{meeting_id}/minutes-revisions",
    response_model=MinutesRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_minutes_revision(
    meeting_id: UUID,
    data: MinutesRevisionCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> MinutesRevisionResponse:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    if not can_read_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    if not can_edit_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Minutes edit denied")
    try:
        revision = create_minutes_revision(session, meeting_id, user, data)
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except MinutesRevisionEditDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Minutes edit denied"
        ) from error
    except MeetingNotLiveForMinutesRevision as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes can only be edited while the meeting is LIVE",
        ) from error
    except MinutesRevisionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Minutes changed since the supplied base revision",
        ) from error
    except InvalidMinutesRevisionStructure as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Structured minutes reference an agenda outside the meeting scope",
        ) from error
    return _serialize_minutes_revision(session, revision)


@router.get("/{meeting_id}/minutes-revisions", response_model=list[MinutesRevisionResponse])
def get_minutes_revisions(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> list[MinutesRevisionResponse]:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    if not can_read_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return _serialize_minutes_revisions(session, list_minutes_revisions(session, meeting_id))


def _serialize_decision_brief_versions(
    session: Session,
    versions: list[DecisionBriefVersion],
    active_revision_id: UUID | None,
) -> list[DecisionBriefVersionResponse]:
    if not versions:
        return []

    version_ids = [version.id for version in versions]
    approval_events = list_decision_brief_approval_events(session, version_ids)
    entries = list(
        session.scalars(
            select(DecisionBriefDecision)
            .where(DecisionBriefDecision.brief_version_id.in_(version_ids))
            .order_by(DecisionBriefDecision.brief_version_id, DecisionBriefDecision.position)
        )
    )
    decision_ids = {entry.source_decision_id for entry in entries}
    source_context: dict[UUID, tuple[MinutesDecision, MinutesDiscussion, Agenda]] = {}
    if decision_ids:
        source_rows = session.execute(
            select(MinutesDecision, MinutesDiscussion, Agenda)
            .join(
                MinutesDiscussion,
                and_(
                    MinutesDiscussion.id == MinutesDecision.discussion_id,
                    MinutesDiscussion.meeting_id == MinutesDecision.meeting_id,
                    MinutesDiscussion.minutes_revision_id == MinutesDecision.minutes_revision_id,
                ),
            )
            .join(
                Agenda,
                and_(
                    Agenda.id == MinutesDiscussion.agenda_id,
                    Agenda.meeting_id == MinutesDiscussion.meeting_id,
                ),
            )
            .where(MinutesDecision.id.in_(decision_ids))
        )
        source_context = {
            decision.id: (decision, discussion, agenda)
            for decision, discussion, agenda in source_rows
        }

    entries_by_version: dict[UUID, list[DecisionBriefDecisionResponse]] = {}
    for entry in entries:
        source_decision, source_discussion, source_agenda = source_context[entry.source_decision_id]
        entries_by_version.setdefault(entry.brief_version_id, []).append(
            DecisionBriefDecisionResponse(
                decision_id=source_decision.id,
                source_decision_text=source_decision.decision_text,
                source_agenda_id=source_agenda.id,
                source_agenda_title=source_agenda.title,
                source_discussion_id=source_discussion.id,
                source_discussion_subject=source_discussion.subject,
                brief_text=entry.brief_text,
                priority=entry.priority,
                editorial_note=entry.editorial_note,
                position=entry.position,
            )
        )
    return [
        DecisionBriefVersionResponse(
            id=version.id,
            meeting_id=version.meeting_id,
            source_minutes_revision_id=version.source_minutes_revision_id,
            version_number=version.version_number,
            summary=version.summary,
            notes=version.notes,
            created_by_id=version.created_by_id,
            created_at=version.created_at,
            is_stale=version.source_minutes_revision_id != active_revision_id,
            approval_state=decision_brief_approval_state(approval_events.get(version.id, [])),
            approval_events=approval_events.get(version.id, []),
            decisions=entries_by_version.get(version.id, []),
        )
        for version in versions
    ]


@router.post(
    "/{meeting_id}/decision-briefs",
    response_model=DecisionBriefVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_decision_brief_version(
    meeting_id: UUID,
    data: DecisionBriefVersionCreate,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> DecisionBriefVersionResponse:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    if not can_read_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    if not can_create_decision_brief(user, meeting):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Decision Brief access denied"
        )
    try:
        version = create_decision_brief_version(session, meeting_id, user, data)
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except MinutesRevisionEditDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Decision Brief access denied"
        ) from error
    except MeetingNotEditable as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived meetings are read-only",
        ) from error
    except InvalidDecisionBriefSource as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Decision Brief source must reference decisions in the supplied meeting revision"
            ),
        ) from error
    except DecisionBriefSourceRevisionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Decision Brief source must be the active minutes revision",
        ) from error
    _, active_revision_id = list_decision_brief_versions(session, meeting_id)
    return _serialize_decision_brief_versions(session, [version], active_revision_id)[0]


@router.get("/{meeting_id}/decision-briefs", response_model=list[DecisionBriefVersionResponse])
def get_decision_brief_history(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> list[DecisionBriefVersionResponse]:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    if not can_read_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    versions, active_revision_id = list_decision_brief_versions(session, meeting_id)
    return _serialize_decision_brief_versions(session, versions, active_revision_id)


def _apply_decision_brief_workflow_event(
    meeting_id: UUID,
    brief_version_id: UUID,
    event_type: DecisionBriefApprovalEventType,
    request: Request,
    identity: Identity,
    session: Session,
    *,
    reason: str | None = None,
) -> DecisionBriefVersionResponse:
    user = identity[1]
    meeting = _load_visible_meeting(session, meeting_id, user)
    if not can_read_minutes(user, meeting):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    try:
        transition_decision_brief_workflow(
            session,
            meeting_id,
            brief_version_id,
            user,
            event_type,
            correlation_id=request.state.correlation_id,
            reason=reason,
        )
    except InvalidMeetingReference as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found"
        ) from error
    except DecisionBriefVersionNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Decision Brief version not found"
        ) from error
    except DecisionBriefWorkflowDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Decision Brief action denied"
        ) from error
    except (DecisionBriefWorkflowConflict, DecisionBriefSubmissionIneligible) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Decision Brief action is not allowed in its current state",
        ) from error
    except DecisionBriefWorkflowPersistenceError as error:
        correlation_id = request.state.correlation_id
        logger.error(
            "Decision Brief workflow event could not be recorded; correlation_id=%s object_id=%s",
            correlation_id,
            brief_version_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Decision Brief workflow could not be recorded",
            headers={"X-Correlation-ID": str(correlation_id)},
        ) from error

    versions, active_revision_id = list_decision_brief_versions(session, meeting_id)
    version = next((item for item in versions if item.id == brief_version_id), None)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Decision Brief version not found"
        )
    return _serialize_decision_brief_versions(session, [version], active_revision_id)[0]


@router.post(
    "/{meeting_id}/decision-briefs/{brief_version_id}/submit",
    response_model=DecisionBriefVersionResponse,
)
def submit_decision_brief_version(
    meeting_id: UUID,
    brief_version_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> DecisionBriefVersionResponse:
    return _apply_decision_brief_workflow_event(
        meeting_id,
        brief_version_id,
        DecisionBriefApprovalEventType.SUBMITTED,
        request,
        identity,
        session,
    )


@router.post(
    "/{meeting_id}/decision-briefs/{brief_version_id}/approve",
    response_model=DecisionBriefVersionResponse,
)
def approve_decision_brief_version(
    meeting_id: UUID,
    brief_version_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> DecisionBriefVersionResponse:
    return _apply_decision_brief_workflow_event(
        meeting_id,
        brief_version_id,
        DecisionBriefApprovalEventType.APPROVED,
        request,
        identity,
        session,
    )


@router.post(
    "/{meeting_id}/decision-briefs/{brief_version_id}/reject",
    response_model=DecisionBriefVersionResponse,
)
def reject_decision_brief_version(
    meeting_id: UUID,
    brief_version_id: UUID,
    data: DecisionBriefRejectionRequest,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> DecisionBriefVersionResponse:
    return _apply_decision_brief_workflow_event(
        meeting_id,
        brief_version_id,
        DecisionBriefApprovalEventType.REJECTED,
        request,
        identity,
        session,
        reason=data.reason,
    )


@router.post(
    "/{meeting_id}/decision-briefs/{brief_version_id}/withdraw",
    response_model=DecisionBriefVersionResponse,
)
def withdraw_decision_brief_version(
    meeting_id: UUID,
    brief_version_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> DecisionBriefVersionResponse:
    return _apply_decision_brief_workflow_event(
        meeting_id,
        brief_version_id,
        DecisionBriefApprovalEventType.WITHDRAWN,
        request,
        identity,
        session,
    )
