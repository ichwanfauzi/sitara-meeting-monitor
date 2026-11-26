"""Authenticated in-app notification endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_identity, require_csrf
from app.db.session import get_db
from app.models.auth import User, UserSession
from app.schemas.notifications import NotificationPage, NotificationResponse
from app.services.notifications import (
    NotificationNotFound,
    list_notifications,
    mark_notification_read,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
Identity = tuple[UserSession, User]
CurrentIdentity = Annotated[Identity, Depends(get_current_identity)]
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=NotificationPage)
def get_notifications(
    identity: CurrentIdentity,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> NotificationPage:
    items, unread_count = list_notifications(session, identity[1].id, limit=limit)
    return NotificationPage(
        items=[NotificationResponse.model_validate(item) for item in items],
        unread_count=unread_count,
    )


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def read_notification(
    notification_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> NotificationResponse:
    try:
        notification = mark_notification_read(session, identity[1].id, notification_id)
    except NotificationNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        ) from error
    return NotificationResponse.model_validate(notification)
