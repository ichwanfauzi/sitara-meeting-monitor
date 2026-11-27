"""Super Admin-only account and account-audit endpoints."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_identity, require_csrf
from app.db.session import get_db
from app.models.auth import User, UserSession
from app.schemas.admin_users import (
    AdminAuditEventListResponse,
    AdminAuditEventResponse,
    AdminPasswordResetResponse,
    AdminUserCreate,
    AdminUserCreateResponse,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdate,
)
from app.services.admin_users import (
    AdminUserConflict,
    AdminUserInvalid,
    AdminUserNotFound,
    AdminUserPersistenceError,
    LastSuperAdmin,
    create_managed_user,
    list_managed_users,
    list_user_audit_events,
    reset_managed_user_password,
    update_managed_user,
)

router = APIRouter(prefix="/admin", tags=["admin-users"])
logger = logging.getLogger(__name__)
Identity = tuple[UserSession, User]
CurrentIdentity = Annotated[Identity, Depends(get_current_identity)]
DatabaseSession = Annotated[Session, Depends(get_db)]
CsrfProtection = Annotated[None, Depends(require_csrf)]


def _require_super_admin(identity: Identity) -> User:
    user = identity[1]
    if {role.role_code for role in user.roles} != {"SUPER_ADMIN"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin access required",
        )
    return user


def _serialize_user(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        job_title=user.job_title,
        roles=sorted(role.role_code for role in user.roles),
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        created_at=user.created_at,
    )


def _raise_admin_error(error: Exception) -> None:
    if isinstance(error, AdminUserNotFound):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found"
        ) from error
    if isinstance(error, AdminUserInvalid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    if isinstance(error, LastSuperAdmin):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The last active Super Admin cannot be deactivated",
        ) from error
    if isinstance(error, AdminUserConflict):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    if isinstance(error, AdminUserPersistenceError):
        logger.exception("Super Admin account change failed to commit")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Account change could not be saved",
        ) from error
    raise error


@router.get("/users", response_model=AdminUserListResponse)
def get_users(
    identity: CurrentIdentity,
    session: DatabaseSession,
) -> AdminUserListResponse:
    _require_super_admin(identity)
    users = list_managed_users(session)
    return AdminUserListResponse(items=[_serialize_user(user) for user in users], total=len(users))


@router.post(
    "/users",
    response_model=AdminUserCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: AdminUserCreate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: CsrfProtection,
) -> AdminUserCreateResponse:
    actor = _require_super_admin(identity)
    try:
        user, temporary_password = create_managed_user(
            session,
            actor=actor,
            payload=payload,
        )
    except (AdminUserInvalid, AdminUserConflict, AdminUserPersistenceError) as error:
        _raise_admin_error(error)
    return AdminUserCreateResponse(
        user=_serialize_user(user),
        temporary_password=temporary_password,
    )


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user(
    user_id: UUID,
    payload: AdminUserUpdate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: CsrfProtection,
) -> AdminUserResponse:
    actor = _require_super_admin(identity)
    try:
        user = update_managed_user(
            session,
            actor=actor,
            target_user_id=user_id,
            payload=payload,
            current_session_id=identity[0].id,
        )
    except (
        AdminUserConflict,
        AdminUserInvalid,
        AdminUserNotFound,
        AdminUserPersistenceError,
        LastSuperAdmin,
    ) as error:
        _raise_admin_error(error)
    return _serialize_user(user)


@router.post(
    "/users/{user_id}/reset-password",
    response_model=AdminPasswordResetResponse,
)
def reset_password(
    user_id: UUID,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: CsrfProtection,
) -> AdminPasswordResetResponse:
    actor = _require_super_admin(identity)
    try:
        _, temporary_password = reset_managed_user_password(
            session,
            actor=actor,
            target_user_id=user_id,
            current_session_id=identity[0].id,
        )
    except (
        AdminUserNotFound,
        AdminUserPersistenceError,
    ) as error:
        _raise_admin_error(error)
    return AdminPasswordResetResponse(temporary_password=temporary_password)


@router.get("/audit-events", response_model=AdminAuditEventListResponse)
def get_account_audit_events(
    identity: CurrentIdentity,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminAuditEventListResponse:
    _require_super_admin(identity)
    events, total = list_user_audit_events(session, limit=limit, offset=offset)
    return AdminAuditEventListResponse(
        items=[AdminAuditEventResponse.model_validate(event) for event in events],
        total=total,
    )
