"""Response contracts for authenticated in-app notifications."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    notification_type: Literal[
        "ACTION_ITEM_STATUS_CHANGED",
        "DECISION_BRIEF_REVIEW_NEEDED",
        "DECISION_BRIEF_REVIEW_WITHDRAWN",
        "DECISION_BRIEF_REVIEW_COMPLETED",
    ]
    message: str
    target_type: Literal["ACTION_ITEM", "MEETING"]
    target_id: UUID
    created_at: datetime
    read_at: datetime | None


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    unread_count: int
