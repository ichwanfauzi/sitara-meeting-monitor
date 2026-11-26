"""Transactional Action Item use cases and server-side object authorization."""

import hashlib
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import get_settings
from app.core.roles import (
    MEETING_LEADER_ROLES,
    PIC_ROLE,
    SECRETARIAT_ROLE,
    SUPER_ADMIN_ROLE,
)
from app.models.action_item import (
    ActionItem,
    ActionItemAssignment,
    ActionItemEvidence,
    ActionItemEvidenceKind,
    ActionItemEvidenceScan,
    ActionItemEvidenceScanStatus,
    ActionItemStatus,
    ActionItemStatusHistory,
    AssignmentRole,
    CompletionReviewOutcome,
    CompletionVerification,
    ProgressSubmitterKind,
    ProgressUpdate,
)
from app.models.auth import Role, User, user_roles
from app.models.disposition import Disposition
from app.models.meeting import Meeting, MeetingParticipant, MinutesDecision, MinutesRevision
from app.models.organization import OrganizationUnit, UserUnitMembership
from app.schemas.action_items import (
    ActionItemAssignmentCreate,
    ActionItemAssignmentEnd,
    ActionItemCreate,
    ActionItemEvidenceLinkCreate,
    ActionItemStatusChange,
    ActionItemUpdate,
    AssignablePicDirectoryResponse,
    AssignablePicDirectoryUser,
    CompletionReviewCreate,
    OrganizationUnitDirectoryResponse,
    OrganizationUnitReference,
    ProgressUpdateCreate,
)
from app.services.action_item_evidence_storage import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceStorageError,
    detect_evidence_file_type,
    evidence_file_path,
    remove_evidence_file,
    safe_display_filename,
    store_evidence_file,
)
from app.services.audit import (
    append_action_item_assignment_changed_event,
    append_action_item_created_event,
    append_action_item_edit_event,
)
from app.services.notifications import notify_active_action_item_assignees
from app.services.organization import (
    assignable_pic_user_ids,
    can_access_task_scope,
    can_assign_pic,
    has_active_unit_membership,
    is_active_action_manager,
)


class ActionItemNotFound(Exception):
    """Raised when an Action Item is absent or outside the caller's visible scope."""


class ActionItemPermissionDenied(Exception):
    """Raised when an actor cannot perform an Action Item operation."""


class ActionItemSourceInvalid(Exception):
    """Raised when the source is not an actionable decision from the exact revision."""


class ActionItemSourceNotActive(Exception):
    """Raised when a task is requested from a superseded minutes revision."""


class ActionItemPersistenceError(Exception):
    """Raised when a task and its required audit event cannot be saved."""


class ActionItemAssignmentConflict(Exception):
    """Raised when an assignment would violate active PIC cardinality."""


class ActionItemAssigneeInvalid(Exception):
    """Raised when a target account is not eligible to be assigned as a PIC."""


class ActionItemUnitInvalid(Exception):
    """Raised when a selected unit is inactive or not valid for the PIC."""


class ActionItemPicSearchInvalid(Exception):
    """Raised when a PIC directory search is too short."""


class ActionItemConcurrencyConflict(Exception):
    """Raised when a caller writes against an older task version."""


class ActionItemEditConflict(Exception):
    """Raised when a completed task cannot be edited or deleted."""


class ActionItemStatusTransitionInvalid(Exception):
    """Raised when a requested status does not change the current official status."""


class ActionItemVerificationRequired(Exception):
    """Raised when completion is requested outside a verified progress report."""


class ActionItemProgressDenied(Exception):
    """Raised when the actor is not an active PIC assigned to the task."""


class ActionItemVerificationInvalid(Exception):
    """Raised when a completion review does not reference an eligible report."""


class ActionItemEvidenceDenied(Exception):
    """Raised when an actor cannot add or read evidence for a progress update."""


class ActionItemEvidenceLimitExceeded(Exception):
    """Raised when a progress update already has the maximum evidence count."""


class ActionItemEvidenceStorageNotConfigured(Exception):
    """Raised when private evidence storage has not been configured."""


class ActionItemEvidenceQuarantined(Exception):
    """Raised when evidence does not have a trusted clean scan result."""


class ActionItemEvidenceScanResultInvalid(Exception):
    """Raised when a scanner result does not match a pending file."""


def _role_codes(session: Session, user_id: UUID) -> set[str]:
    return set(
        session.scalars(
            select(Role.role_code)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user_id)
        )
    )


def _active_pic(session: Session, user: User) -> bool:
    roles = _role_codes(session, user.id)
    return (
        session.scalar(select(User.is_active).where(User.id == user.id)) is True
        and PIC_ROLE in roles
        and SUPER_ADMIN_ROLE not in roles
        and has_active_unit_membership(session, user.id)
    )


def _active_assignments(session: Session, action_item_id: UUID) -> list[ActionItemAssignment]:
    return list(
        session.scalars(
            select(ActionItemAssignment)
            .where(
                ActionItemAssignment.action_item_id == action_item_id,
                ActionItemAssignment.ended_at.is_(None),
            )
            .order_by(ActionItemAssignment.assignment_role, ActionItemAssignment.started_at)
        )
    )


def _assignment_audit_values(assignment: ActionItemAssignment) -> dict[str, str | None]:
    values = {
        "assignment_id": str(assignment.id),
        "assignee_user_id": (
            str(assignment.assignee_user_id) if assignment.assignee_user_id else None
        ),
        "assignment_role": AssignmentRole(assignment.assignment_role).value,
        "pic_origin_unit_id": (
            str(assignment.pic_origin_unit_id) if assignment.pic_origin_unit_id else None
        ),
    }
    if assignment.assignee_display_name is not None:
        values["assignee_display_name"] = assignment.assignee_display_name
    return values


def _can_read_item(
    session: Session,
    actor: User,
    assignments: list[ActionItemAssignment],
) -> bool:
    if is_active_action_manager(session, actor):
        return True
    main = next(
        (
            assignment
            for assignment in assignments
            if assignment.assignment_role == AssignmentRole.MAIN
        ),
        None,
    )
    if main is None:
        return False
    supporting_ids = {
        assignment.assignee_user_id
        for assignment in assignments
        if assignment.assignment_role == AssignmentRole.SUPPORTING
        and assignment.assignee_user_id is not None
    }
    return can_access_task_scope(
        session,
        actor,
        main_pic_user_id=main.assignee_user_id,
        supporting_pic_user_ids=supporting_ids,
    )


def get_action_item_for_actor(session: Session, actor: User, action_item_id: UUID) -> ActionItem:
    action_item = session.get(ActionItem, action_item_id)
    if (
        action_item is None
        or action_item.deleted_at is not None
        or not _can_read_item(session, actor, _active_assignments(session, action_item_id))
    ):
        raise ActionItemNotFound
    return action_item


def list_action_items(
    session: Session,
    actor: User,
    *,
    limit: int,
    offset: int,
    meeting_id: UUID | None = None,
    official_status: ActionItemStatus | None = None,
    include_deleted: bool = False,
) -> list[ActionItem]:
    if session.scalar(select(User.is_active).where(User.id == actor.id)) is not True:
        return []
    roles = _role_codes(session, actor.id)
    if SUPER_ADMIN_ROLE in roles:
        return []

    statement = select(ActionItem)
    if not include_deleted:
        statement = statement.where(ActionItem.deleted_at.is_(None))
    if meeting_id is not None:
        statement = statement.where(ActionItem.meeting_id == meeting_id)
    if official_status is not None:
        statement = statement.where(ActionItem.official_status == official_status.value)

    if not is_active_action_manager(session, actor):
        if not roles.intersection({PIC_ROLE, *MEETING_LEADER_ROLES}):
            return []
        assignment_filters: list[ColumnElement[bool]] = [ActionItemAssignment.ended_at.is_(None)]
        if not roles.intersection(MEETING_LEADER_ROLES):
            assignment_filters.append(ActionItemAssignment.assignee_user_id == actor.id)
        candidate_assignments = select(ActionItemAssignment.action_item_id).where(
            *assignment_filters
        )
        statement = statement.where(ActionItem.id.in_(candidate_assignments))

    candidates = list(
        session.scalars(statement.order_by(ActionItem.created_at.desc(), ActionItem.id).distinct())
    )
    visible = [
        item
        for item in candidates
        if _can_read_item(session, actor, _active_assignments(session, item.id))
    ]
    return visible[offset : offset + limit]


def source_revision_is_stale(session: Session, action_item: ActionItem) -> bool:
    active_revision_id = session.scalar(
        select(MinutesRevision.id)
        .where(MinutesRevision.meeting_id == action_item.meeting_id)
        .order_by(MinutesRevision.revision_number.desc())
        .limit(1)
    )
    return active_revision_id != action_item.source_minutes_revision_id


def list_action_item_assignments(
    session: Session, action_item_id: UUID
) -> list[ActionItemAssignment]:
    return list(
        session.scalars(
            select(ActionItemAssignment)
            .where(ActionItemAssignment.action_item_id == action_item_id)
            .order_by(ActionItemAssignment.started_at, ActionItemAssignment.id)
        )
    )


def list_progress_updates(session: Session, action_item_id: UUID) -> list[ProgressUpdate]:
    return list(
        session.scalars(
            select(ProgressUpdate)
            .where(ProgressUpdate.action_item_id == action_item_id)
            .order_by(ProgressUpdate.submitted_at, ProgressUpdate.id)
        )
    )


def list_status_history(session: Session, action_item_id: UUID) -> list[ActionItemStatusHistory]:
    return list(
        session.scalars(
            select(ActionItemStatusHistory)
            .where(ActionItemStatusHistory.action_item_id == action_item_id)
            .order_by(ActionItemStatusHistory.event_number)
        )
    )


def list_completion_verifications(
    session: Session, action_item_id: UUID
) -> list[CompletionVerification]:
    return list(
        session.scalars(
            select(CompletionVerification)
            .where(CompletionVerification.action_item_id == action_item_id)
            .order_by(CompletionVerification.reviewed_at, CompletionVerification.id)
        )
    )


def _has_action_item_management_role(session: Session, actor: User) -> bool:
    return is_active_action_manager(session, actor)


def can_manage_action_items(session: Session, actor: User, meeting: Meeting) -> bool:
    return _has_action_item_management_role(session, actor)


def can_access_action_item_pic_directory(session: Session, actor: User, meeting: Meeting) -> bool:
    if _has_action_item_management_role(session, actor):
        return True
    roles = _role_codes(session, actor.id)
    if (
        session.scalar(select(User.is_active).where(User.id == actor.id)) is not True
        or roles.intersection({SUPER_ADMIN_ROLE, PIC_ROLE})
        or not roles.intersection(MEETING_LEADER_ROLES)
    ):
        return False
    return (
        actor.id in {meeting.created_by_id, meeting.chairperson_id, meeting.notetaker_id}
        or session.scalar(
            select(MeetingParticipant.meeting_id).where(
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.user_id == actor.id,
            )
        )
        is not None
    )


def can_manage_action_item_pic_directory(session: Session, actor: User) -> bool:
    return _has_action_item_management_role(session, actor)


def search_assignable_pics(
    session: Session,
    actor: User,
    meeting_id: UUID,
    *,
    query: str,
    limit: int,
) -> AssignablePicDirectoryResponse:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise ActionItemNotFound
    if not can_manage_action_item_pic_directory(session, actor):
        raise ActionItemPermissionDenied

    normalized_query = query.strip()
    if query and len(normalized_query) < 2:
        raise ActionItemPicSearchInvalid
    pattern = None
    if normalized_query:
        escaped_query = (
            normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped_query}%"
    now = datetime.now(UTC)
    assignable_ids = assignable_pic_user_ids(session, actor, at=now)
    pic_filters: list[ColumnElement[bool]] = [User.id.in_(assignable_ids)]
    if pattern is not None:
        pic_filters.append(
            or_(
                User.full_name.ilike(pattern, escape="\\"),
                User.job_title.ilike(pattern, escape="\\"),
            )
        )
    pics = list(
        session.scalars(
            select(User).where(*pic_filters).order_by(User.full_name, User.id).limit(limit + 1)
        ).all()
    )
    memberships = session.execute(
        select(UserUnitMembership.user_id, OrganizationUnit)
        .join(OrganizationUnit, OrganizationUnit.id == UserUnitMembership.unit_id)
        .join(User, User.id == UserUnitMembership.user_id)
        .where(
            UserUnitMembership.user_id.in_(pic.id for pic in pics),
            UserUnitMembership.valid_from <= now,
            (UserUnitMembership.valid_until.is_(None)) | (UserUnitMembership.valid_until > now),
            OrganizationUnit.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(OrganizationUnit.unit_code, OrganizationUnit.name)
    ).all()
    memberships_by_user: dict[UUID, list[OrganizationUnitReference]] = {}
    for user_id, unit in memberships:
        memberships_by_user.setdefault(user_id, []).append(
            OrganizationUnitReference(id=unit.id, unit_code=unit.unit_code, name=unit.name)
        )
    return AssignablePicDirectoryResponse(
        query=normalized_query,
        pics=[
            AssignablePicDirectoryUser(
                id=pic.id,
                full_name=pic.full_name,
                job_title=pic.job_title,
                active_units=memberships_by_user.get(pic.id, []),
            )
            for pic in pics[:limit]
        ],
        units=[
            OrganizationUnitReference(id=unit.id, unit_code=unit.unit_code, name=unit.name)
            for unit in session.scalars(
                select(OrganizationUnit)
                .where(OrganizationUnit.is_active.is_(True))
                .order_by(OrganizationUnit.unit_code, OrganizationUnit.name)
            )
        ],
        more_pics=len(pics) > limit,
    )


def list_active_action_item_units(
    session: Session,
    actor: User,
    meeting_id: UUID,
) -> OrganizationUnitDirectoryResponse:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise ActionItemNotFound
    if not can_manage_action_item_pic_directory(session, actor):
        raise ActionItemPermissionDenied
    units = session.scalars(
        select(OrganizationUnit)
        .where(OrganizationUnit.is_active.is_(True))
        .order_by(OrganizationUnit.unit_code, OrganizationUnit.name)
    ).all()
    return OrganizationUnitDirectoryResponse(
        units=[
            OrganizationUnitReference(id=unit.id, unit_code=unit.unit_code, name=unit.name)
            for unit in units
        ]
    )


def create_action_item(
    session: Session,
    actor: User,
    data: ActionItemCreate,
    *,
    correlation_id: UUID | None = None,
) -> ActionItem:
    if not _has_action_item_management_role(session, actor):
        raise ActionItemPermissionDenied
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == data.meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise ActionItemSourceInvalid
    if not can_manage_action_items(session, actor, meeting):
        session.rollback()
        raise ActionItemPermissionDenied

    source_revision = session.scalar(
        select(MinutesRevision).where(
            MinutesRevision.meeting_id == data.meeting_id,
            MinutesRevision.id == data.source_minutes_revision_id,
            MinutesRevision.format_version == 2,
        )
    )
    decision = session.scalar(
        select(MinutesDecision).where(
            MinutesDecision.meeting_id == data.meeting_id,
            MinutesDecision.minutes_revision_id == data.source_minutes_revision_id,
            MinutesDecision.id == data.source_decision_id,
        )
    )
    if source_revision is None or decision is None or not decision.is_action_item:
        session.rollback()
        raise ActionItemSourceInvalid
    disposition = (
        session.get(Disposition, data.disposition_id) if data.disposition_id is not None else None
    )
    if data.disposition_id is not None and (
        disposition is None
        or disposition.meeting_id != data.meeting_id
        or disposition.source_minutes_revision_id != data.source_minutes_revision_id
        or disposition.source_decision_id != data.source_decision_id
    ):
        session.rollback()
        raise ActionItemSourceInvalid

    active_revision_id = session.scalar(
        select(MinutesRevision.id)
        .where(MinutesRevision.meeting_id == data.meeting_id)
        .order_by(MinutesRevision.revision_number.desc())
        .limit(1)
    )
    if active_revision_id != source_revision.id:
        session.rollback()
        raise ActionItemSourceNotActive
    now = datetime.now(UTC)
    responsible_unit_is_active = session.scalar(
        select(OrganizationUnit.id).where(
            OrganizationUnit.id == data.responsible_unit_id,
            OrganizationUnit.is_active.is_(True),
        )
    )
    if responsible_unit_is_active is None:
        session.rollback()
        raise ActionItemUnitInvalid
    if data.main_pic_user_id is not None and not can_assign_pic(
        session, actor, data.main_pic_user_id, at=now
    ):
        session.rollback()
        raise ActionItemAssigneeInvalid
    if data.main_pic_user_id is not None and not has_active_unit_membership(
        session, data.main_pic_user_id, data.main_pic_origin_unit_id, at=now
    ):
        session.rollback()
        raise ActionItemUnitInvalid

    action_item = ActionItem(
        meeting_id=data.meeting_id,
        disposition_id=data.disposition_id,
        responsible_unit_id=data.responsible_unit_id,
        source_minutes_revision_id=source_revision.id,
        source_decision_id=decision.id,
        title=data.title,
        description=data.description,
        output_expected=data.output_expected,
        due_date=data.due_date,
        priority=data.priority,
        official_status=ActionItemStatus.BELUM_DIMULAI,
        created_by_id=actor.id,
        version=1,
        created_at=now,
        updated_at=now,
    )
    assignment = ActionItemAssignment(
        action_item=action_item,
        assignee_user_id=data.main_pic_user_id,
        assignee_display_name=data.main_pic_display_name,
        assigned_by_user_id=actor.id,
        pic_origin_unit_id=data.main_pic_origin_unit_id,
        assignment_role=AssignmentRole.MAIN,
        started_at=now,
    )
    initial_status = ActionItemStatusHistory(
        action_item=action_item,
        event_number=1,
        old_status=None,
        new_status=ActionItemStatus.BELUM_DIMULAI,
        changed_by_id=actor.id,
        changed_at=now,
        change_note="Action Item dibuat",
    )
    session.add_all([action_item, assignment, initial_status])
    try:
        session.flush()
        append_action_item_created_event(
            session,
            actor=actor,
            action_item_id=action_item.id,
            source_minutes_revision_id=source_revision.id,
            source_decision_id=decision.id,
            disposition_id=data.disposition_id,
            correlation_id=correlation_id,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise ActionItemPersistenceError from error
    session.refresh(action_item)
    return action_item


def update_action_item(
    session: Session,
    actor: User,
    action_item_id: UUID,
    data: ActionItemUpdate,
    *,
    correlation_id: UUID | None = None,
) -> ActionItem:
    if not is_active_action_manager(session, actor):
        raise ActionItemPermissionDenied
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None or action_item.deleted_at is not None:
        raise ActionItemNotFound
    if action_item.version != data.expected_version:
        session.rollback()
        raise ActionItemConcurrencyConflict
    if action_item.official_status == ActionItemStatus.SELESAI:
        session.rollback()
        raise ActionItemEditConflict

    changed_fields = [
        field
        for field in ("title", "description", "output_expected", "due_date", "priority")
        if getattr(action_item, field) != getattr(data, field)
    ]
    if not changed_fields:
        session.rollback()
        return action_item

    for field in changed_fields:
        setattr(action_item, field, getattr(data, field))
    now = datetime.now(UTC)
    action_item.version += 1
    action_item.updated_at = now
    try:
        append_action_item_edit_event(
            session,
            actor=actor,
            action_item_id=action_item.id,
            operation="UPDATED",
            changed_fields=changed_fields,
            correlation_id=correlation_id,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise ActionItemPersistenceError from error
    session.refresh(action_item)
    return action_item


def delete_action_item(
    session: Session,
    actor: User,
    action_item_id: UUID,
    *,
    expected_version: int,
    correlation_id: UUID | None = None,
) -> ActionItem:
    if not is_active_action_manager(session, actor):
        raise ActionItemPermissionDenied
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None or action_item.deleted_at is not None:
        raise ActionItemNotFound
    if action_item.version != expected_version:
        session.rollback()
        raise ActionItemConcurrencyConflict
    if action_item.official_status == ActionItemStatus.SELESAI:
        session.rollback()
        raise ActionItemEditConflict

    now = datetime.now(UTC)
    action_item.deleted_at = now
    action_item.deleted_by_id = actor.id
    action_item.version += 1
    action_item.updated_at = now
    try:
        append_action_item_edit_event(
            session,
            actor=actor,
            action_item_id=action_item.id,
            operation="DELETED",
            changed_fields=["deleted_at"],
            correlation_id=correlation_id,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise ActionItemPersistenceError from error
    session.refresh(action_item)
    return action_item


def create_assignment(
    session: Session,
    actor: User,
    action_item_id: UUID,
    data: ActionItemAssignmentCreate,
    expected_version: int,
    *,
    correlation_id: UUID | None = None,
) -> ActionItemAssignment:
    if not _has_action_item_management_role(session, actor):
        raise ActionItemPermissionDenied
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None:
        raise ActionItemNotFound
    meeting = session.get(Meeting, action_item.meeting_id)
    if meeting is None or not can_manage_action_items(session, actor, meeting):
        session.rollback()
        raise ActionItemPermissionDenied
    if action_item.version != expected_version:
        session.rollback()
        raise ActionItemConcurrencyConflict
    now = datetime.now(UTC)
    if data.assignee_user_id is not None and not can_assign_pic(
        session, actor, data.assignee_user_id, at=now
    ):
        session.rollback()
        raise ActionItemAssigneeInvalid
    if data.assignee_user_id is not None and not has_active_unit_membership(
        session, data.assignee_user_id, data.pic_origin_unit_id, at=now
    ):
        session.rollback()
        raise ActionItemUnitInvalid

    current = _active_assignments(session, action_item_id)
    existing_for_user = next(
        (
            assignment
            for assignment in current
            if (
                data.assignee_user_id is not None
                and assignment.assignee_user_id == data.assignee_user_id
            )
            or (
                data.assignee_display_name is not None
                and assignment.assignee_display_name is not None
                and assignment.assignee_display_name.casefold()
                == data.assignee_display_name.casefold()
            )
        ),
        None,
    )
    if existing_for_user is not None:
        session.rollback()
        raise ActionItemAssignmentConflict

    before_values: dict[str, str | None] | None = None
    operation: Literal["ASSIGNED", "REPLACED"] = "ASSIGNED"
    if data.assignment_role is AssignmentRole.MAIN:
        old_main = next(
            (
                assignment
                for assignment in current
                if assignment.assignment_role == AssignmentRole.MAIN
            ),
            None,
        )
        if old_main is None:
            session.rollback()
            raise ActionItemAssignmentConflict
        before_values = _assignment_audit_values(old_main)
        operation = "REPLACED"
        old_main.ended_at = now
        old_main.ended_by_user_id = actor.id
        old_main.end_reason = data.reason or "PIC utama diganti"
        # The partial unique index permits only one active MAIN row. Close the
        # previous row before inserting its replacement in this transaction.
        session.flush()

    assignment = ActionItemAssignment(
        action_item_id=action_item.id,
        assignee_user_id=data.assignee_user_id,
        assignee_display_name=data.assignee_display_name,
        assigned_by_user_id=actor.id,
        pic_origin_unit_id=data.pic_origin_unit_id,
        assignment_role=data.assignment_role,
        started_at=now,
        assignment_reason=data.reason,
    )
    action_item.version += 1
    action_item.updated_at = now
    session.add(assignment)
    try:
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise ActionItemAssignmentConflict from error
    except SQLAlchemyError as error:
        session.rollback()
        raise ActionItemPersistenceError from error
    try:
        append_action_item_assignment_changed_event(
            session,
            actor=actor,
            action_item_id=action_item.id,
            operation=operation,
            before_values=before_values,
            after_values=_assignment_audit_values(assignment),
            correlation_id=correlation_id,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise ActionItemPersistenceError from error
    session.refresh(assignment)
    return assignment


def end_assignment(
    session: Session,
    actor: User,
    action_item_id: UUID,
    assignment_id: UUID,
    data: ActionItemAssignmentEnd,
    *,
    correlation_id: UUID | None = None,
) -> ActionItemAssignment:
    if not _has_action_item_management_role(session, actor):
        raise ActionItemPermissionDenied
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None:
        raise ActionItemNotFound
    meeting = session.get(Meeting, action_item.meeting_id)
    if meeting is None or not can_manage_action_items(session, actor, meeting):
        session.rollback()
        raise ActionItemPermissionDenied
    if action_item.version != data.expected_version:
        session.rollback()
        raise ActionItemConcurrencyConflict
    assignment = session.scalar(
        select(ActionItemAssignment).where(
            ActionItemAssignment.action_item_id == action_item_id,
            ActionItemAssignment.id == assignment_id,
            ActionItemAssignment.ended_at.is_(None),
        )
    )
    if assignment is None:
        session.rollback()
        raise ActionItemNotFound
    if assignment.assignment_role == AssignmentRole.MAIN:
        session.rollback()
        raise ActionItemAssignmentConflict

    now = datetime.now(UTC)
    before_values = _assignment_audit_values(assignment)
    assignment.ended_at = now
    assignment.ended_by_user_id = actor.id
    assignment.end_reason = data.reason or "PIC pendukung diakhiri"
    action_item.version += 1
    action_item.updated_at = now
    try:
        session.flush()
        append_action_item_assignment_changed_event(
            session,
            actor=actor,
            action_item_id=action_item.id,
            operation="ENDED",
            before_values=before_values,
            after_values={
                "assignment_id": str(assignment.id),
                "ended_by_user_id": str(actor.id),
            },
            correlation_id=correlation_id,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise ActionItemPersistenceError from error
    session.refresh(assignment)
    return assignment


def create_progress_update(
    session: Session,
    actor: User,
    action_item_id: UUID,
    data: ProgressUpdateCreate,
) -> ProgressUpdate:
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None:
        raise ActionItemNotFound
    assignments = _active_assignments(session, action_item_id)
    if not _can_read_item(session, actor, assignments):
        raise ActionItemNotFound
    submitter_kind, active_assignment = _progress_submitter_context(session, actor, assignments)
    if data.assignment_id is not None and (
        active_assignment is None or data.assignment_id != active_assignment.id
    ):
        raise ActionItemProgressDenied

    update = ProgressUpdate(
        action_item_id=action_item.id,
        assignment_id=active_assignment.id if active_assignment is not None else None,
        actor_user_id=actor.id,
        submitted_as=submitter_kind,
        report_text=data.report_text,
        blocker_text=data.blocker_text,
        progress_percent=data.progress_percent,
        completion_requested=data.completion_requested,
        submitted_at=datetime.now(UTC),
    )
    session.add(update)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(update)
    return update


def _progress_submitter_context(
    session: Session,
    actor: User,
    assignments: list[ActionItemAssignment],
) -> tuple[ProgressSubmitterKind, ActionItemAssignment | None]:
    roles = _role_codes(session, actor.id)
    if (
        SUPER_ADMIN_ROLE in roles
        or session.scalar(select(User.is_active).where(User.id == actor.id)) is not True
    ):
        raise ActionItemProgressDenied

    active_assignment = next(
        (assignment for assignment in assignments if assignment.assignee_user_id == actor.id),
        None,
    )
    if active_assignment is not None and _active_pic(session, actor):
        return ProgressSubmitterKind.PIC, active_assignment

    if (
        roles.intersection(MEETING_LEADER_ROLES)
        and SECRETARIAT_ROLE not in roles
        and has_active_unit_membership(session, actor.id)
    ):
        return ProgressSubmitterKind.LEADERSHIP, None
    raise ActionItemProgressDenied


def _lock_progress_for_evidence(
    session: Session,
    actor: User,
    action_item_id: UUID,
    progress_update_id: UUID,
) -> ProgressUpdate:
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None:
        raise ActionItemNotFound
    progress_update = session.scalar(
        select(ProgressUpdate)
        .where(
            ProgressUpdate.action_item_id == action_item_id,
            ProgressUpdate.id == progress_update_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if progress_update is None:
        raise ActionItemNotFound
    assignments = _active_assignments(session, action_item_id)
    if not _can_read_item(session, actor, assignments):
        raise ActionItemNotFound
    try:
        _progress_submitter_context(session, actor, assignments)
    except ActionItemProgressDenied as error:
        raise ActionItemEvidenceDenied from error
    if progress_update.actor_user_id != actor.id:
        raise ActionItemEvidenceDenied

    evidence_count = session.scalar(
        select(func.count())
        .select_from(ActionItemEvidence)
        .where(ActionItemEvidence.progress_update_id == progress_update_id)
    )
    if evidence_count is not None and evidence_count >= 5:
        raise ActionItemEvidenceLimitExceeded
    return progress_update


def create_file_evidence(
    session: Session,
    actor: User,
    action_item_id: UUID,
    progress_update_id: UUID,
    filename: str,
    content: bytes,
) -> ActionItemEvidence:
    progress_update = _lock_progress_for_evidence(
        session, actor, action_item_id, progress_update_id
    )
    safe_filename = safe_display_filename(filename)
    content_type = detect_evidence_file_type(safe_filename, content)
    storage_root = get_settings().action_item_evidence_storage_path
    if storage_root is None:
        raise ActionItemEvidenceStorageNotConfigured
    storage_key, digest = store_evidence_file(storage_root, content)
    evidence = ActionItemEvidence(
        action_item_id=action_item_id,
        progress_update_id=progress_update.id,
        evidence_kind=ActionItemEvidenceKind.FILE,
        storage_key=storage_key,
        original_filename=safe_filename,
        content_type=content_type,
        size_bytes=len(content),
        sha256=digest,
        uploaded_by_user_id=actor.id,
    )
    session.add(evidence)
    try:
        session.flush()
        session.add(
            ActionItemEvidenceScan(
                evidence_id=evidence.id,
                event_number=1,
                scan_status=ActionItemEvidenceScanStatus.PENDING,
            )
        )
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        try:
            remove_evidence_file(storage_root, storage_key)
        except EvidenceStorageError as cleanup_error:
            raise cleanup_error from error
        raise
    session.refresh(evidence)
    return evidence


def record_evidence_scan_result(
    session: Session,
    evidence_id: UUID,
    *,
    clean: bool,
    scanner_name: str,
    scanner_version: str,
    scanned_sha256: str,
) -> ActionItemEvidenceScan:
    """Record a trusted scanner result; no public endpoint invokes this operation."""
    if (
        not scanner_name.strip()
        or len(scanner_name) > 100
        or not scanner_version.strip()
        or len(scanner_version) > 100
    ):
        raise ActionItemEvidenceScanResultInvalid
    evidence = session.scalar(
        select(ActionItemEvidence)
        .where(
            ActionItemEvidence.id == evidence_id,
            ActionItemEvidence.evidence_kind == ActionItemEvidenceKind.FILE,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if evidence is None or evidence.sha256 != scanned_sha256:
        raise ActionItemEvidenceScanResultInvalid
    previous_scan = session.scalar(
        select(ActionItemEvidenceScan)
        .where(ActionItemEvidenceScan.evidence_id == evidence_id)
        .order_by(ActionItemEvidenceScan.event_number.desc())
        .limit(1)
    )
    if previous_scan is None or previous_scan.scan_status != ActionItemEvidenceScanStatus.PENDING:
        raise ActionItemEvidenceScanResultInvalid

    scan = ActionItemEvidenceScan(
        evidence_id=evidence_id,
        event_number=previous_scan.event_number + 1,
        scan_status=(
            ActionItemEvidenceScanStatus.CLEAN if clean else ActionItemEvidenceScanStatus.REJECTED
        ),
        scanner_name=scanner_name,
        scanner_version=scanner_version,
        scanned_sha256=scanned_sha256,
    )
    session.add(scan)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(scan)
    return scan


def create_link_evidence(
    session: Session,
    actor: User,
    action_item_id: UUID,
    progress_update_id: UUID,
    data: ActionItemEvidenceLinkCreate,
) -> ActionItemEvidence:
    progress_update = _lock_progress_for_evidence(
        session, actor, action_item_id, progress_update_id
    )
    evidence = ActionItemEvidence(
        action_item_id=action_item_id,
        progress_update_id=progress_update.id,
        evidence_kind=ActionItemEvidenceKind.LINK,
        external_url=str(data.url),
        link_label=data.label,
        uploaded_by_user_id=actor.id,
    )
    session.add(evidence)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(evidence)
    return evidence


def _read_integrity_checked_evidence(
    evidence: ActionItemEvidence,
    storage_root: Path,
) -> bytes:
    if evidence.storage_key is None or evidence.sha256 is None:
        raise EvidenceStorageError("Evidence storage metadata is unavailable")
    path = evidence_file_path(storage_root, evidence.storage_key)
    try:
        with path.open("rb") as evidence_file:
            before = os.fstat(evidence_file.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size != evidence.size_bytes
                or before.st_size > MAX_EVIDENCE_FILE_BYTES
            ):
                raise EvidenceStorageError("Evidence file integrity check failed")
            content = evidence_file.read(MAX_EVIDENCE_FILE_BYTES + 1)
            after = os.fstat(evidence_file.fileno())
    except OSError as error:
        raise EvidenceStorageError("Evidence storage file is unavailable") from error

    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
        or len(content) != evidence.size_bytes
        or hashlib.sha256(content).hexdigest() != evidence.sha256
    ):
        raise EvidenceStorageError("Evidence file integrity check failed")
    return content


def get_evidence_file_for_actor(
    session: Session,
    actor: User,
    action_item_id: UUID,
    evidence_id: UUID,
) -> tuple[ActionItemEvidence, bytes]:
    evidence = session.scalar(
        select(ActionItemEvidence).where(
            ActionItemEvidence.action_item_id == action_item_id,
            ActionItemEvidence.id == evidence_id,
            ActionItemEvidence.evidence_kind == ActionItemEvidenceKind.FILE,
        )
    )
    if evidence is None or evidence.storage_key is None:
        raise ActionItemNotFound
    assignments = _active_assignments(session, action_item_id)
    if not _can_read_item(session, actor, assignments):
        raise ActionItemNotFound
    storage_root = get_settings().action_item_evidence_storage_path
    if storage_root is None:
        raise ActionItemEvidenceStorageNotConfigured
    scan = session.scalar(
        select(ActionItemEvidenceScan)
        .where(ActionItemEvidenceScan.evidence_id == evidence_id)
        .order_by(ActionItemEvidenceScan.event_number.desc())
        .limit(1)
    )
    if (
        scan is None
        or scan.scan_status != ActionItemEvidenceScanStatus.CLEAN
        or evidence.sha256 is None
        or scan.scanned_sha256 != evidence.sha256
    ):
        raise ActionItemEvidenceQuarantined
    return evidence, _read_integrity_checked_evidence(evidence, storage_root)


def change_action_item_status(
    session: Session,
    actor: User,
    action_item_id: UUID,
    data: ActionItemStatusChange,
) -> ActionItem:
    if not is_active_action_manager(session, actor):
        raise ActionItemPermissionDenied
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None:
        raise ActionItemNotFound
    if action_item.version != data.expected_version:
        session.rollback()
        raise ActionItemConcurrencyConflict
    if action_item.official_status == data.to_status:
        session.rollback()
        raise ActionItemStatusTransitionInvalid
    if data.to_status is ActionItemStatus.SELESAI:
        session.rollback()
        raise ActionItemVerificationRequired

    old_status = ActionItemStatus(action_item.official_status)
    now = datetime.now(UTC)
    event_number = (
        session.scalar(
            select(func.coalesce(func.max(ActionItemStatusHistory.event_number), 0)).where(
                ActionItemStatusHistory.action_item_id == action_item.id
            )
        )
        or 0
    ) + 1
    status_event = ActionItemStatusHistory(
        action_item_id=action_item.id,
        event_number=event_number,
        old_status=old_status,
        new_status=data.to_status,
        changed_by_id=actor.id,
        change_note=data.note,
        changed_at=now,
    )
    session.add(status_event)
    # History must be written first so the database guard can validate that
    # every official status change has a matching immutable history event.
    session.flush()
    action_item.official_status = data.to_status
    action_item.completed_at = None
    action_item.version += 1
    action_item.updated_at = now
    notify_active_action_item_assignees(
        session,
        action_item,
        event_id=status_event.id,
        actor_id=actor.id,
    )
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(action_item)
    return action_item


def review_completion(
    session: Session,
    actor: User,
    action_item_id: UUID,
    data: CompletionReviewCreate,
) -> tuple[ActionItem, CompletionVerification]:
    if not is_active_action_manager(session, actor):
        raise ActionItemPermissionDenied
    action_item = session.scalar(
        select(ActionItem)
        .where(ActionItem.id == action_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if action_item is None:
        raise ActionItemNotFound
    if action_item.version != data.expected_version:
        session.rollback()
        raise ActionItemConcurrencyConflict
    if action_item.official_status == ActionItemStatus.SELESAI:
        session.rollback()
        raise ActionItemVerificationInvalid

    report = session.scalar(
        select(ProgressUpdate).where(
            ProgressUpdate.action_item_id == action_item.id,
            ProgressUpdate.id == data.progress_update_id,
            ProgressUpdate.completion_requested.is_(True),
        )
    )
    if report is None:
        session.rollback()
        raise ActionItemVerificationInvalid
    active_pic_assignment = session.scalar(
        select(ActionItemAssignment.id)
        .where(
            ActionItemAssignment.action_item_id == action_item.id,
            ActionItemAssignment.assignee_user_id == actor.id,
            ActionItemAssignment.ended_at.is_(None),
        )
        .limit(1)
    )
    if report.actor_user_id == actor.id or active_pic_assignment is not None:
        session.rollback()
        raise ActionItemPermissionDenied
    prior_review = session.scalar(
        select(CompletionVerification.id).where(
            CompletionVerification.action_item_id == action_item.id,
            CompletionVerification.progress_update_id == report.id,
        )
    )
    if prior_review is not None:
        session.rollback()
        raise ActionItemVerificationInvalid
    if data.outcome is CompletionReviewOutcome.VERIFIED:
        latest_scan_number = (
            select(func.max(ActionItemEvidenceScan.event_number))
            .where(ActionItemEvidenceScan.evidence_id == ActionItemEvidence.id)
            .correlate(ActionItemEvidence)
            .scalar_subquery()
        )
        clean_evidence = session.scalar(
            select(ActionItemEvidence)
            .join(
                ActionItemEvidenceScan,
                ActionItemEvidenceScan.evidence_id == ActionItemEvidence.id,
            )
            .where(
                ActionItemEvidence.action_item_id == action_item.id,
                ActionItemEvidence.evidence_kind == ActionItemEvidenceKind.FILE,
                ActionItemEvidenceScan.event_number == latest_scan_number,
                ActionItemEvidenceScan.scan_status == ActionItemEvidenceScanStatus.CLEAN,
                ActionItemEvidence.sha256.is_not(None),
                ActionItemEvidenceScan.scanned_sha256 == ActionItemEvidence.sha256,
            )
            .limit(1)
        )
        storage_root = get_settings().action_item_evidence_storage_path
        if clean_evidence is None or storage_root is None:
            session.rollback()
            raise ActionItemVerificationInvalid
        try:
            _read_integrity_checked_evidence(clean_evidence, storage_root)
        except EvidenceStorageError as error:
            session.rollback()
            raise ActionItemVerificationInvalid from error

    now = datetime.now(UTC)
    verification = CompletionVerification(
        action_item_id=action_item.id,
        progress_update_id=report.id,
        reviewer_user_id=actor.id,
        outcome=data.outcome,
        review_note=data.review_note,
        reviewed_at=now,
    )
    session.add(verification)
    try:
        session.flush()
        if data.outcome is CompletionReviewOutcome.VERIFIED:
            event_number = (
                session.scalar(
                    select(func.coalesce(func.max(ActionItemStatusHistory.event_number), 0)).where(
                        ActionItemStatusHistory.action_item_id == action_item.id
                    )
                )
                or 0
            ) + 1
            session.add(
                ActionItemStatusHistory(
                    action_item_id=action_item.id,
                    event_number=event_number,
                    old_status=ActionItemStatus(action_item.official_status),
                    new_status=ActionItemStatus.SELESAI,
                    changed_by_id=actor.id,
                    verification_id=verification.id,
                    change_note=data.review_note,
                    changed_at=now,
                )
            )
            session.flush()
            action_item.official_status = ActionItemStatus.SELESAI
            action_item.completed_at = now
        action_item.version += 1
        action_item.updated_at = now
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ActionItemVerificationInvalid from error
    except SQLAlchemyError:
        session.rollback()
        raise
    session.refresh(action_item)
    session.refresh(verification)
    return action_item, verification
