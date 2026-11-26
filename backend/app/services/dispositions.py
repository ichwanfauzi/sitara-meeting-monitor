"""Disposition creation with source, target, authorization, and audit checks."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models.auth import Role, User
from app.models.disposition import Disposition, DispositionTarget
from app.models.meeting import Meeting, MinutesDecision, MinutesRevision
from app.models.organization import OrganizationUnit
from app.schemas.dispositions import (
    DispositionCreate,
    DispositionDirectoryRole,
    DispositionDirectoryUnit,
    DispositionDirectoryUser,
    DispositionTargetDirectoryResponse,
    RoleDispositionTargetInput,
    UnitDispositionTargetInput,
    UserDispositionTargetInput,
)
from app.services.action_items import (
    can_access_action_item_pic_directory,
    can_manage_action_items,
)
from app.services.audit import append_disposition_created_event


class DispositionNotFound(Exception):
    """Raised when a meeting does not exist."""


class DispositionPermissionDenied(Exception):
    """Raised when an actor cannot issue a disposition in the meeting scope."""


class DispositionSourceInvalid(Exception):
    """Raised when a disposition source does not belong to the meeting."""


class DispositionSourceNotActive(Exception):
    """Raised when a disposition refers to a superseded minutes revision."""


class DispositionTargetInvalid(Exception):
    """Raised when a target is missing, inactive, or unknown."""


class DispositionPersistenceError(Exception):
    """Raised when the disposition and its required audit event cannot be saved."""


class DispositionSearchQueryInvalid(Exception):
    """Raised when a target search contains fewer than two visible characters."""


def _require_meeting_access(session: Session, actor: User, meeting_id: UUID) -> Meeting:
    meeting = session.get(Meeting, meeting_id)
    if meeting is None:
        raise DispositionNotFound
    if not can_access_action_item_pic_directory(session, actor, meeting):
        raise DispositionPermissionDenied
    return meeting


def list_dispositions(
    session: Session,
    actor: User,
    meeting_id: UUID,
    *,
    limit: int,
    offset: int,
) -> list[Disposition]:
    meeting = _require_meeting_access(session, actor, meeting_id)
    statement = (
        select(Disposition)
        .options(
            selectinload(Disposition.targets).selectinload(DispositionTarget.target_user),
            selectinload(Disposition.targets).selectinload(DispositionTarget.target_unit),
            selectinload(Disposition.targets).selectinload(DispositionTarget.target_role),
        )
        .where(Disposition.meeting_id == meeting.id)
        .order_by(Disposition.created_at.desc(), Disposition.id)
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement).unique().all())


def search_disposition_targets(
    session: Session,
    actor: User,
    meeting_id: UUID,
    *,
    query: str,
    limit: int,
) -> DispositionTargetDirectoryResponse:
    _require_meeting_access(session, actor, meeting_id)
    normalized_query = query.strip()
    if len(normalized_query) < 2:
        raise DispositionSearchQueryInvalid
    escaped_query = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped_query}%"
    users = list(
        session.scalars(
            select(User)
            .where(
                User.is_active.is_(True),
                or_(
                    User.full_name.ilike(pattern, escape="\\"),
                    User.job_title.ilike(pattern, escape="\\"),
                ),
            )
            .order_by(User.full_name, User.id)
            .limit(limit + 1)
        ).all()
    )
    units = list(
        session.scalars(
            select(OrganizationUnit)
            .where(
                OrganizationUnit.is_active.is_(True),
                or_(
                    OrganizationUnit.unit_code.ilike(pattern, escape="\\"),
                    OrganizationUnit.name.ilike(pattern, escape="\\"),
                ),
            )
            .order_by(OrganizationUnit.unit_code, OrganizationUnit.id)
            .limit(limit + 1)
        ).all()
    )
    roles = list(
        session.scalars(
            select(Role)
            .where(
                or_(
                    Role.role_code.ilike(pattern, escape="\\"),
                    Role.role_name.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Role.role_code, Role.id)
            .limit(limit + 1)
        ).all()
    )
    return DispositionTargetDirectoryResponse(
        query=normalized_query,
        users=[
            DispositionDirectoryUser(
                id=user.id,
                full_name=user.full_name,
                job_title=user.job_title,
            )
            for user in users[:limit]
        ],
        units=[
            DispositionDirectoryUnit(
                id=unit.id,
                unit_code=unit.unit_code,
                name=unit.name,
            )
            for unit in units[:limit]
        ],
        roles=[
            DispositionDirectoryRole(
                id=role.id,
                role_code=role.role_code,
                role_name=role.role_name,
            )
            for role in roles[:limit]
        ],
        more_users=len(users) > limit,
        more_units=len(units) > limit,
        more_roles=len(roles) > limit,
    )


def _validate_target(session: Session, target: object) -> DispositionTarget:
    if isinstance(target, UserDispositionTargetInput):
        target_exists = (
            session.scalar(
                select(User.id).where(
                    User.id == target.user_id,
                    User.is_active.is_(True),
                )
            )
            is not None
        )
        if not target_exists:
            raise DispositionTargetInvalid
        return DispositionTarget(target_type=target.target_type, target_user_id=target.user_id)

    if isinstance(target, UnitDispositionTargetInput):
        target_exists = (
            session.scalar(
                select(OrganizationUnit.id).where(
                    OrganizationUnit.id == target.unit_id,
                    OrganizationUnit.is_active.is_(True),
                )
            )
            is not None
        )
        if not target_exists:
            raise DispositionTargetInvalid
        return DispositionTarget(target_type=target.target_type, target_unit_id=target.unit_id)

    if isinstance(target, RoleDispositionTargetInput):
        if session.get(Role, target.role_id) is None:
            raise DispositionTargetInvalid
        return DispositionTarget(target_type=target.target_type, target_role_id=target.role_id)

    raise DispositionTargetInvalid


def create_disposition(
    session: Session,
    actor: User,
    meeting_id: UUID,
    data: DispositionCreate,
    *,
    correlation_id: UUID | None,
) -> Disposition:
    meeting = session.scalar(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if meeting is None:
        raise DispositionNotFound
    if not can_manage_action_items(session, actor, meeting):
        session.rollback()
        raise DispositionPermissionDenied

    active_revision_id = session.scalar(
        select(MinutesRevision.id)
        .where(MinutesRevision.meeting_id == meeting_id)
        .order_by(MinutesRevision.revision_number.desc())
        .limit(1)
    )
    if active_revision_id != data.source_minutes_revision_id:
        session.rollback()
        raise DispositionSourceNotActive

    decision_exists = (
        session.scalar(
            select(MinutesDecision.id).where(
                MinutesDecision.meeting_id == meeting_id,
                MinutesDecision.minutes_revision_id == data.source_minutes_revision_id,
                MinutesDecision.id == data.source_decision_id,
            )
        )
        is not None
    )
    if not decision_exists:
        session.rollback()
        raise DispositionSourceInvalid

    targets = [_validate_target(session, target) for target in data.targets]
    disposition = Disposition(
        meeting_id=meeting_id,
        source_minutes_revision_id=data.source_minutes_revision_id,
        source_decision_id=data.source_decision_id,
        issued_by_user_id=actor.id,
        instruction=data.instruction,
        targets=targets,
    )
    session.add(disposition)
    try:
        session.flush()
        append_disposition_created_event(
            session,
            actor=actor,
            disposition_id=disposition.id,
            source_minutes_revision_id=disposition.source_minutes_revision_id,
            source_decision_id=disposition.source_decision_id,
            target_types={target.target_type for target in targets},
            target_count=len(targets),
            correlation_id=correlation_id,
        )
        session.commit()
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise DispositionPersistenceError from error

    session.refresh(disposition)
    return disposition
