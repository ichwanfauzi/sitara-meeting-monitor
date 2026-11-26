"""FastAPI application entry point."""

from fastapi import FastAPI
from starlette.middleware import Middleware

from app.api.routes.action_items import router as action_items_router
from app.api.routes.auth import router as auth_router
from app.api.routes.dispositions import router as dispositions_router
from app.api.routes.health import router as health_router
from app.api.routes.meetings import router as meetings_router
from app.api.routes.notifications import router as notifications_router
from app.core.config import get_settings
from app.middleware import EvidenceUploadSizeLimitMiddleware, RequestCorrelationIdMiddleware

settings = get_settings()
MAX_EVIDENCE_UPLOAD_REQUEST_BYTES = 11 * 1024 * 1024
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url=None,
    middleware=[
        Middleware(RequestCorrelationIdMiddleware),
        Middleware(
            EvidenceUploadSizeLimitMiddleware,
            max_request_bytes=MAX_EVIDENCE_UPLOAD_REQUEST_BYTES,
        ),
    ],
)
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(action_items_router, prefix="/api/v1")
app.include_router(dispositions_router, prefix="/api/v1")
app.include_router(meetings_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
