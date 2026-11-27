"""Super Admin account-management operations."""

import secrets
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.roles import (
    SUPER_ADMIN_ROLE,
)
from app.core.security import hash_password
from app.models.audit import AuditEvent
from app.models.auth import Role, User, UserSession, user_roles
from app.schemas.admin_users import AdminUserCreate, AdminUserUpdate
from app.services.audit import AuditEventWriteError, append_user_account_event

OPERATIONAL_ROLE_LIMITS = {
    "REKTOR": 1,
    "WAREK": 4,
    "SEKRETARIAT": 1,
    "MANAGER_LEGAL": 1,
}
WAREK_POSITION_TITLES = frozenset(
    {
        "Wakil Rektor I Bidang Akademik",
        "Wakil Rektor II Bidang Sumber Daya",
        "Wakil Rektor III Bidang Kemahasiswaan",
        "Wakil Rektor IV Bidang Kerjasama",
    }
)
MANAGED_ROLE_CODES = frozenset(OPERATIONAL_ROLE_LIMITS)


class AdminUserNotFound(LookupError):
    """Raised when an account is outside the managed roster."""


class AdminUserInvalid(ValueError):
    """Raised when an account request conflicts with the managed roster."""


class AdminUserConflict(ValueError):
    """Raised when an account violates a uniqueness or roster constraint."""


class LastSuperAdmin(ValueError):
    """Raised when an operation would leave no active Super Admin."""


class AdminUserPersistenceError(RuntimeError):
    """Raised when an account change and its audit event cannot be committed."""


def _role_codes(user: User) -> set[str]:
    return {role.role_code for role in user.roles}


def _managed_user(session: Session, user_id: UUID) -> User:
    user = session.scalar(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    if user is None:
        raise AdminUserNotFound
    roles = _role_codes(user)
    if roles == {SUPER_ADMIN_ROLE} or len(roles) == 1 and roles <= MANAGED_ROLE_CODES:
        return user
    raise AdminUserNotFound


def _get_role(session: Session, role_code: str) -> Role:
    role = session.scalar(select(Role).where(Role.role_code == role_code))
    if role is None:
        raise AdminUserInvalid("Requested role is not configured")
    return role


def _validate_roster_slot(
    session: Session,
    *,
    role_code: str,
    job_title: str | None,
    excluding_user_id: UUID | None = None,
) -> None:
    if role_code not in MANAGED_ROLE_CODES:
        raise AdminUserInvalid("Only approved operational roles can be assigned")
    if role_code == "WAREK" and job_title not in WAREK_POSITION_TITLES:
        raise AdminUserInvalid("A WAREK account must use one of the four approved positions")
    if session.scalar(select(Role.id).where(Role.role_code == role_code).with_for_update()) is None:
        raise AdminUserInvalid("Requested role is not configured")

    active_role_users = (
        select(User.id)
        .join(user_roles, user_roles.c.user_id == User.id)
        .join(Role, Role.id == user_roles.c.role_id)
        .where(User.is_active.is_(True), Role.role_code == role_code)
    )
    if excluding_user_id is not None:
        active_role_users = active_role_users.where(User.id != excluding_user_id)
    active_user_ids = list(session.scalars(active_role_users.with_for_update()))
    if len(active_user_ids) >= OPERATIONAL_ROLE_LIMITS[role_code]:
        raise AdminUserConflict(f"The active {role_code} roster is full")

    if role_code == "WAREK" and job_title is not None:
        occupied_position = (
            select(User.id)
            .join(user_roles, user_roles.c.user_id == User.id)
            .join(Role, Role.id == user_roles.c.role_id)
            .where(
                User.is_active.is_(True),
                Role.role_code == "WAREK",
                User.job_title == job_title,
            )
        )
        if excluding_user_id is not None:
            occupied_position = occupied_position.where(User.id != excluding_user_id)
        if session.scalar(occupied_position.with_for_update()) is not None:
            raise AdminUserConflict("That WAREK position is already assigned")


def _snapshot(user: User) -> dict[str, str | None]:
    roles = sorted(_role_codes(user))
    return {
        "email": user.email,
        "full_name": user.full_name,
        "job_title": user.job_title,
        "role_code": roles[0] if roles else None,
    }


def _revoke_sessions(
    session: Session,
    *,
    user_id: UUID,
    except_session_id: UUID | None = None,
) -> None:
    statement = update(UserSession).where(
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    )
    if except_session_id is not None:
        statement = statement.where(UserSession.id != except_session_id)
    session.execute(statement.values(revoked_at=datetime.now(UTC)))


def _commit_account_change(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise AdminUserConflict("Account data conflicts with an existing user") from error
    except (SQLAlchemyError, ValidationError) as error:
        session.rollback()
        raise AdminUserPersistenceError from error


def list_managed_users(session: Session) -> list[User]:
    statement = (
        select(User)
        .options(selectinload(User.roles))
        .where(
            User.id.in_(
                select(user_roles.c.user_id)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(Role.role_code.in_(MANAGED_ROLE_CODES | {SUPER_ADMIN_ROLE}))
            )
        )
        .order_by(User.created_at, User.email)
    )
    users = list(session.scalars(statement))
    return [
        item
        for item in users
        if (
            _role_codes(item) == {SUPER_ADMIN_ROLE}
            or len(_role_codes(item)) == 1
            and _role_codes(item) <= MANAGED_ROLE_CODES
        )
    ]


def list_user_audit_events(
    session: Session, *, limit: int, offset: int
) -> tuple[list[AuditEvent], int]:
    base = select(AuditEvent).where(AuditEvent.action.like("user.%"))
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    events = list(
        session.scalars(
            base.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return events, total


def create_managed_user(
    session: Session,
    *,
    actor: User,
    payload: AdminUserCreate,
) -> tuple[User, str]:
    if payload.role_code not in MANAGED_ROLE_CODES:
        raise AdminUserInvalid("Only approved operational roles can be assigned")
    _validate_roster_slot(
        session,
        role_code=payload.role_code,
        job_title=payload.job_title,
    )
    role = _get_role(session, payload.role_code)
    temporary_password = secrets.token_urlsafe(24)
    user = User(
        email=payload.email,
        full_name=payload.full_name.strip(),
        job_title=payload.job_title.strip() if payload.job_title else None,
        password_hash=hash_password(temporary_password),
        is_active=True,
        must_change_password=True,
        roles=[role],
    )
    session.add(user)
    try:
        session.flush()
        append_user_account_event(
            session,
            actor=actor,
            action="user.created",
            user_id=user.id,
            after_values=_snapshot(user),
        )
    except (SQLAlchemyError, ValidationError, AuditEventWriteError) as error:
        session.rollback()
        if isinstance(error, IntegrityError):
            raise AdminUserConflict("An account already uses that email address") from error
        raise AdminUserPersistenceError from error
    _commit_account_change(session)
    return user, temporary_password


def update_managed_user(
    session: Session,
    *,
    actor: User,
    target_user_id: UUID,
    payload: AdminUserUpdate,
    current_session_id: UUID | None,
) -> User:
    user = _managed_user(session, target_user_id)
    role_codes = _role_codes(user)
    target_is_super_admin = role_codes == {SUPER_ADMIN_ROLE}
    fields = payload.model_fields_set
    if any(
        field in fields and getattr(payload, field) is None
        for field in {"email", "full_name", "role_code", "is_active"}
    ):
        raise AdminUserInvalid("Required account fields cannot be null")
    if target_is_super_admin and "role_code" in fields:
        raise AdminUserInvalid(
            "Super Admin roles are managed only by the local provisioning command"
        )

    prior_active = user.is_active
    prior_snapshot = _snapshot(user)
    role_changed = "role_code" in fields and payload.role_code not in role_codes
    next_role_code = (
        payload.role_code
        if "role_code" in fields and payload.role_code is not None
        else next(iter(role_codes))
    )
    next_job_title = payload.job_title if "job_title" in fields else user.job_title
    next_active = payload.is_active if "is_active" in fields else user.is_active

    if not target_is_super_admin and (
        role_changed
        or (not prior_active and next_active)
        or ("job_title" in fields and next_role_code == "WAREK")
    ):
        _validate_roster_slot(
            session,
            role_code=next_role_code,
            job_title=next_job_title,
            excluding_user_id=user.id,
        )
    if next_role_code == "WAREK" and next_job_title not in WAREK_POSITION_TITLES:
        raise AdminUserInvalid("A WAREK account must use one of the four approved positions")

    if target_is_super_admin and prior_active and not next_active:
        active_admin_ids = list(
            session.scalars(
                select(User.id)
                .join(user_roles, user_roles.c.user_id == User.id)
                .join(Role, Role.id == user_roles.c.role_id)
                .where(User.is_active.is_(True), Role.role_code == SUPER_ADMIN_ROLE)
                .with_for_update()
            )
        )
        if len(set(active_admin_ids)) <= 1:
            raise LastSuperAdmin

    if "email" in fields:
        user.email = payload.email
    if "full_name" in fields:
        user.full_name = payload.full_name.strip()
    if "job_title" in fields:
        user.job_title = payload.job_title.strip() if payload.job_title else None
    if role_changed:
        user.roles[:] = [_get_role(session, next_role_code)]
    if "is_active" in fields:
        user.is_active = next_active
    next_snapshot = _snapshot(user)
    changed_snapshot = {
        field: (prior_snapshot[field], next_snapshot[field])
        for field in prior_snapshot
        if prior_snapshot[field] != next_snapshot[field]
    }
    try:
        session.flush()
        if changed_snapshot:
            append_user_account_event(
                session,
                actor=actor,
                action="user.updated",
                user_id=user.id,
                before_values={field: before for field, (before, _) in changed_snapshot.items()},
                after_values={field: after for field, (_, after) in changed_snapshot.items()},
            )
        if prior_active != user.is_active:
            append_user_account_event(
                session,
                actor=actor,
                action="user.reactivated" if user.is_active else "user.deactivated",
                user_id=user.id,
                before_values={"is_active": str(prior_active).lower()},
                after_values={"is_active": str(user.is_active).lower()},
            )
        if prior_active != user.is_active or role_changed:
            _revoke_sessions(
                session,
                user_id=user.id,
                except_session_id=(current_session_id if user.id == actor.id else None),
            )
    except (SQLAlchemyError, ValidationError, AuditEventWriteError) as error:
        session.rollback()
        raise AdminUserPersistenceError from error

    _commit_account_change(session)
    return user


def reset_managed_user_password(
    session: Session,
    *,
    actor: User,
    target_user_id: UUID,
    current_session_id: UUID | None,
) -> tuple[User, str]:
    user = _managed_user(session, target_user_id)
    temporary_password = secrets.token_urlsafe(24)
    user.password_hash = hash_password(temporary_password)
    user.must_change_password = True
    _revoke_sessions(
        session,
        user_id=user.id,
        except_session_id=current_session_id if user.id == actor.id else None,
    )
    try:
        append_user_account_event(
            session,
            actor=actor,
            action="user.password_reset",
            user_id=user.id,
            after_values={"must_change_password": "true"},
        )
    except (SQLAlchemyError, ValidationError, AuditEventWriteError) as error:
        session.rollback()
        raise AdminUserPersistenceError from error
    _commit_account_change(session)
    return user, temporary_password
