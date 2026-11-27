"""Super Admin user-management request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OperationalRole = Literal["REKTOR", "WAREK", "SEKRETARIAT", "MANAGER_LEGAL"]


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    full_name: str = Field(min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    role_code: OperationalRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class AdminUserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, min_length=3, max_length=320)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    role_code: OperationalRole | None = None
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return value.strip().casefold() if value is not None else None

    @model_validator(mode="after")
    def require_at_least_one_change(self) -> "AdminUserUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one account field must be provided")
        return self


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    job_title: str | None
    roles: list[str]
    is_active: bool
    must_change_password: bool
    created_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int


class AdminUserCreateResponse(BaseModel):
    user: AdminUserResponse
    temporary_password: str


class AdminPasswordResetResponse(BaseModel):
    temporary_password: str


class AdminAuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    actor_roles: list[str]
    actor_type: Literal["USER", "SYSTEM"]
    action: str
    object_type: Literal["user"]
    object_id: UUID
    before_values: dict[str, str | None] | None
    after_values: dict[str, str | None] | None
    occurred_at: datetime


class AdminAuditEventListResponse(BaseModel):
    items: list[AdminAuditEventResponse]
    total: int
