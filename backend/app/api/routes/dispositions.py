"""Disposition endpoints for authorized meeting participants and officials."""

import logging
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_identity, require_csrf
from app.db.session import get_db
from app.models.auth import User, UserSession
from app.schemas.dispositions import (
    DispositionCreate,
    DispositionResponse,
    DispositionTargetDirectoryResponse,
)
from app.services.dispositions import (
    DispositionNotFound,
    DispositionPermissionDenied,
    DispositionPersistenceError,
    DispositionSearchQueryInvalid,
    DispositionSourceInvalid,
    DispositionSourceNotActive,
    DispositionTargetInvalid,
    create_disposition,
    list_dispositions,
    search_disposition_targets,
)

router = APIRouter(prefix="/meetings", tags=["dispositions"])
logger = logging.getLogger(__name__)
Identity = tuple[UserSession, User]
CurrentIdentity = Annotated[Identity, Depends(get_current_identity)]
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get(
    "/{meeting_id}/dispositions",
    response_model=list[DispositionResponse],
)
def get_meeting_dispositions(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DispositionResponse]:
    try:
        dispositions = list_dispositions(
            session,
            identity[1],
            meeting_id,
            limit=limit,
            offset=offset,
        )
    except DispositionNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        ) from error
    except DispositionPermissionDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Disposition access denied",
        ) from error
    return [DispositionResponse.model_validate(item) for item in dispositions]


@router.get(
    "/{meeting_id}/disposition-targets",
    response_model=DispositionTargetDirectoryResponse,
)
def get_meeting_disposition_targets(
    meeting_id: UUID,
    identity: CurrentIdentity,
    session: DatabaseSession,
    query: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DispositionTargetDirectoryResponse:
    try:
        return search_disposition_targets(
            session,
            identity[1],
            meeting_id,
            query=query,
            limit=limit,
        )
    except DispositionNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        ) from error
    except DispositionPermissionDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Disposition access denied",
        ) from error
    except DispositionSearchQueryInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Target search must contain at least two non-whitespace characters",
        ) from error


@router.post(
    "/{meeting_id}/dispositions",
    response_model=DispositionResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_disposition(
    meeting_id: UUID,
    data: DispositionCreate,
    request: Request,
    identity: CurrentIdentity,
    session: DatabaseSession,
    _csrf: Annotated[None, Depends(require_csrf)],
) -> DispositionResponse:
    correlation_id = cast(UUID | None, getattr(request.state, "correlation_id", None))
    try:
        disposition = create_disposition(
            session,
            identity[1],
            meeting_id,
            data,
            correlation_id=correlation_id,
        )
    except DispositionNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meeting not found",
        ) from error
    except DispositionPermissionDenied as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Disposition access denied",
        ) from error
    except DispositionSourceInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Disposition source must belong to this meeting and revision",
        ) from error
    except DispositionSourceNotActive as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Disposition source minutes revision is no longer active",
        ) from error
    except DispositionTargetInvalid as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Disposition targets must reference active users/units or existing roles",
        ) from error
    except DispositionPersistenceError as error:
        logger.exception("Disposition transaction failed; correlation_id=%s", correlation_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Disposition and audit event could not be saved",
        ) from error
    return DispositionResponse.model_validate(disposition)
