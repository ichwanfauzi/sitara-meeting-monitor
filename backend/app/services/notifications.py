"""Persistence helpers for private, in-app notifications."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.action_item import ActionItem, ActionItemAssignment
from app.models.auth import User
from app.models.notification import (
    Notification,
    NotificationEmailStatus,
    NotificationTargetType,
    NotificationType,
)


class NotificationNotFound(Exception):
    """Raised when a notification is not owned by the requesting user."""


def add_notifications(
    session: Session,
    *,
    recipient_ids: set[UUID],
    event_key: str,
    notification_type: NotificationType,
    message: str,
    target_type: NotificationTargetType,
    target_id: UUID,
) -> None:
    email_status = (
        NotificationEmailStatus.PENDING
        if get_settings().notification_email_enabled
        else NotificationEmailStatus.DISABLED
    )
    for recipient_id in recipient_ids:
        session.add(
            Notification(
                recipient_user_id=recipient_id,
                event_key=event_key,
                notification_type=notification_type,
                message=message,
                target_type=target_type,
                target_id=target_id,
                email_status=email_status,
            )
        )


def notify_active_action_item_assignees(
    session: Session,
    action_item: ActionItem,
    *,
    event_id: UUID,
    actor_id: UUID,
) -> None:
    assigned_user_ids = set(
        session.scalars(
            select(ActionItemAssignment.assignee_user_id)
            .where(
                ActionItemAssignment.action_item_id == action_item.id,
                ActionItemAssignment.ended_at.is_(None),
                ActionItemAssignment.assignee_user_id.is_not(None),
            )
            .distinct()
        )
    )
    assigned_user_ids.discard(actor_id)
    if not assigned_user_ids:
        return
    active_user_ids = set(
        session.scalars(
            select(User.id).where(
                User.id.in_(assigned_user_ids),
                User.is_active.is_(True),
            )
        )
    )
    add_notifications(
        session,
        recipient_ids=active_user_ids,
        event_key=f"action_item_status:{event_id}",
        notification_type=NotificationType.ACTION_ITEM_STATUS_CHANGED,
        message="Status tindak lanjut yang Anda ikuti telah berubah.",
        target_type=NotificationTargetType.ACTION_ITEM,
        target_id=action_item.id,
    )


def list_notifications(
    session: Session,
    recipient_id: UUID,
    *,
    limit: int,
) -> tuple[list[Notification], int]:
    items = list(
        session.scalars(
            select(Notification)
            .where(Notification.recipient_user_id == recipient_id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        )
    )
    unread_count = session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_user_id == recipient_id,
            Notification.read_at.is_(None),
        )
    )
    return items, int(unread_count or 0)


def mark_notification_read(
    session: Session,
    recipient_id: UUID,
    notification_id: UUID,
) -> Notification:
    notification = session.scalar(
        select(Notification)
        .where(
            Notification.id == notification_id,
            Notification.recipient_user_id == recipient_id,
        )
        .with_for_update()
    )
    if notification is None:
        raise NotificationNotFound
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        session.commit()
        session.refresh(notification)
    return notification
