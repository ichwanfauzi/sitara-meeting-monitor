"""Request and response contracts for dispositions."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.disposition import DispositionTargetType


class _DispositionTargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserDispositionTargetInput(_DispositionTargetInput):
    target_type: Literal["USER"]
    user_id: UUID


class UnitDispositionTargetInput(_DispositionTargetInput):
    target_type: Literal["UNIT"]
    unit_id: UUID


class RoleDispositionTargetInput(_DispositionTargetInput):
    target_type: Literal["ROLE"]
    role_id: UUID


DispositionTargetInput = Annotated[
    UserDispositionTargetInput | UnitDispositionTargetInput | RoleDispositionTargetInput,
    Field(discriminator="target_type"),
]


class DispositionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_minutes_revision_id: UUID
    source_decision_id: UUID
    instruction: str = Field(min_length=1, max_length=20_000)
    targets: list[DispositionTargetInput] = Field(min_length=1, max_length=100)

    @field_validator("instruction")
    @classmethod
    def trim_instruction(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Instruction cannot be blank")
        return value

    @model_validator(mode="after")
    def reject_duplicate_targets(self) -> "DispositionCreate":
        seen: set[tuple[str, UUID]] = set()
        for target in self.targets:
            target_id = (
                target.user_id
                if isinstance(target, UserDispositionTargetInput)
                else target.unit_id
                if isinstance(target, UnitDispositionTargetInput)
                else target.role_id
            )
            key = (target.target_type, target_id)
            if key in seen:
                raise ValueError("Disposition targets must be unique")
            seen.add(key)
        return self


class DispositionTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_type: DispositionTargetType
    target_user_id: UUID | None
    target_unit_id: UUID | None
    target_role_id: UUID | None
    target_label: str


class DispositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    meeting_id: UUID
    source_minutes_revision_id: UUID
    source_decision_id: UUID
    issued_by_user_id: UUID
    instruction: str
    created_at: datetime
    targets: list[DispositionTargetResponse]


class DispositionDirectoryUser(BaseModel):
    id: UUID
    full_name: str
    job_title: str | None


class DispositionDirectoryUnit(BaseModel):
    id: UUID
    unit_code: str
    name: str


class DispositionDirectoryRole(BaseModel):
    id: UUID
    role_code: str
    role_name: str


class DispositionTargetDirectoryResponse(BaseModel):
    query: str
    users: list[DispositionDirectoryUser]
    units: list[DispositionDirectoryUnit]
    roles: list[DispositionDirectoryRole]
    more_users: bool
    more_units: bool
    more_roles: bool
