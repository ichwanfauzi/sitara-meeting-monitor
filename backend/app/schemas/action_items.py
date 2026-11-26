"""Validated Action Item request and response schemas."""

from datetime import date, datetime
from uuid import UUID

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.action_item import (
    ActionItemEvidenceKind,
    ActionItemEvidenceScanStatus,
    ActionItemStatus,
    AssignmentRole,
    CompletionReviewOutcome,
    ProgressSubmitterKind,
)


class OrganizationUnitReference(BaseModel):
    id: UUID
    unit_code: str
    name: str


def _trim_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Value cannot be blank")
    return value


def _trim_optional(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class ActionItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: UUID
    source_minutes_revision_id: UUID
    source_decision_id: UUID
    disposition_id: UUID | None = None
    responsible_unit_id: UUID
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20_000)
    output_expected: str | None = Field(default=None, max_length=20_000)
    due_date: date | None = None
    priority: str = Field(min_length=1, max_length=100)
    main_pic_user_id: UUID | None = None
    main_pic_display_name: str | None = Field(default=None, max_length=200)
    main_pic_origin_unit_id: UUID | None = None

    _strip_title = field_validator("title")(_trim_required)
    _strip_description = field_validator("description")(_trim_required)
    _strip_output = field_validator("output_expected")(_trim_optional)
    _strip_priority = field_validator("priority")(_trim_required)
    _strip_main_pic_display_name = field_validator("main_pic_display_name")(_trim_optional)

    @model_validator(mode="after")
    def require_main_pic(self) -> "ActionItemCreate":
        if (self.main_pic_user_id is None) == (self.main_pic_display_name is None):
            raise ValueError("Choose an active PIC or enter a PIC name")
        if self.main_pic_user_id is None and self.main_pic_origin_unit_id is not None:
            raise ValueError("Named PICs cannot have a verified origin unit")
        if self.main_pic_user_id is not None and self.main_pic_origin_unit_id is None:
            raise ValueError("Choose the PIC's active origin unit")
        return self


class ActionItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=20_000)
    output_expected: str | None = Field(default=None, max_length=20_000)
    due_date: date | None = None
    priority: str = Field(min_length=1, max_length=100)

    _strip_title = field_validator("title")(_trim_required)
    _strip_description = field_validator("description")(_trim_required)
    _strip_output = field_validator("output_expected")(_trim_optional)
    _strip_priority = field_validator("priority")(_trim_required)


class ActionItemAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_user_id: UUID | None = None
    assignee_display_name: str | None = Field(default=None, max_length=200)
    pic_origin_unit_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=4_000)
    assignment_role: AssignmentRole
    expected_version: int = Field(ge=1)
    _strip_assignee_display_name = field_validator("assignee_display_name")(_trim_optional)
    _strip_reason = field_validator("reason")(_trim_optional)

    @model_validator(mode="after")
    def require_assignee(self) -> "ActionItemAssignmentCreate":
        if (self.assignee_user_id is None) == (self.assignee_display_name is None):
            raise ValueError("Choose an active PIC or enter a PIC name")
        if self.assignee_user_id is None and self.pic_origin_unit_id is not None:
            raise ValueError("Named PICs cannot have a verified origin unit")
        if self.assignee_user_id is not None and self.pic_origin_unit_id is None:
            raise ValueError("Choose the PIC's active origin unit")
        return self


class ActionItemAssignmentEnd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=4_000)

    _strip_reason = field_validator("reason")(_trim_optional)


class AssignablePicDirectoryUser(BaseModel):
    id: UUID
    full_name: str
    job_title: str | None
    active_units: list[OrganizationUnitReference]


class AssignablePicDirectoryResponse(BaseModel):
    query: str
    pics: list[AssignablePicDirectoryUser]
    units: list[OrganizationUnitReference]
    more_pics: bool


class OrganizationUnitDirectoryResponse(BaseModel):
    units: list[OrganizationUnitReference]


class ProgressUpdateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment_id: UUID | None = None
    report_text: str | None = Field(default=None, max_length=20_000)
    blocker_text: str | None = Field(default=None, max_length=20_000)
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    completion_requested: bool = False

    _strip_report = field_validator("report_text")(_trim_optional)
    _strip_blocker = field_validator("blocker_text")(_trim_optional)

    @model_validator(mode="after")
    def require_update_content(self) -> "ProgressUpdateCreate":
        if (
            self.report_text is None
            and self.blocker_text is None
            and self.progress_percent is None
            and not self.completion_requested
        ):
            raise ValueError("Progress update must contain a report, blocker, progress, or request")
        return self


class ActionItemStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    to_status: ActionItemStatus
    note: str | None = Field(default=None, max_length=4_000)

    _strip_note = field_validator("note")(_trim_optional)


class CompletionReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    progress_update_id: UUID
    outcome: CompletionReviewOutcome
    review_note: str | None = Field(default=None, max_length=4_000)

    _strip_review_note = field_validator("review_note")(_trim_optional)

    @model_validator(mode="after")
    def require_revision_note(self) -> "CompletionReviewCreate":
        if self.outcome is CompletionReviewOutcome.NEEDS_REVISION and not self.review_note:
            raise ValueError("A review note is required when revision is needed")
        return self


class ActionItemAssignmentResponse(BaseModel):
    id: UUID
    action_item_id: UUID
    assignee_user_id: UUID | None
    assignee_display_name: str | None
    assignee_name: str | None
    pic_origin_unit: OrganizationUnitReference | None
    assigned_by_user_id: UUID
    assignment_role: AssignmentRole
    started_at: datetime
    ended_at: datetime | None
    ended_by_user_id: UUID | None
    end_reason: str | None


class ActionItemEvidenceResponse(BaseModel):
    id: UUID
    progress_update_id: UUID
    evidence_kind: ActionItemEvidenceKind
    original_filename: str | None
    content_type: str | None
    size_bytes: int | None
    sha256: str | None
    external_url: str | None
    link_label: str | None
    download_url: str | None
    scan_status: ActionItemEvidenceScanStatus | None
    uploaded_by_user_id: UUID
    created_at: datetime


class ProgressUpdateResponse(BaseModel):
    id: UUID
    action_item_id: UUID
    assignment_id: UUID | None
    actor_user_id: UUID
    submitted_as: ProgressSubmitterKind
    report_text: str | None
    blocker_text: str | None
    progress_percent: int | None
    completion_requested: bool
    submitted_at: datetime
    evidence: list[ActionItemEvidenceResponse] = Field(default_factory=list)


class ActionItemEvidenceLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: AnyUrl = Field(max_length=2_048)
    label: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("url")
    @classmethod
    def require_https(cls, value: AnyUrl) -> AnyUrl:
        if value.scheme != "https" or value.username is not None or value.password is not None:
            raise ValueError("Evidence links must use HTTPS and must not include credentials")
        return value

    _strip_label = field_validator("label")(_trim_optional)


class ActionItemStatusHistoryResponse(BaseModel):
    id: UUID
    event_number: int
    old_status: ActionItemStatus | None
    new_status: ActionItemStatus
    changed_by_id: UUID
    verification_id: UUID | None
    change_note: str | None
    changed_at: datetime


class CompletionVerificationResponse(BaseModel):
    id: UUID
    action_item_id: UUID
    progress_update_id: UUID
    reviewer_user_id: UUID
    outcome: CompletionReviewOutcome
    review_note: str | None
    reviewed_at: datetime


class ActionItemResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    source_minutes_revision_id: UUID
    source_decision_id: UUID
    disposition_id: UUID | None
    responsible_unit: OrganizationUnitReference | None
    source_revision_is_stale: bool
    title: str
    description: str
    output_expected: str | None
    due_date: date | None
    priority: str
    official_status: ActionItemStatus
    version: int
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    deleted_at: datetime | None
    active_assignments: list[ActionItemAssignmentResponse]


class ActionItemDetailResponse(ActionItemResponse):
    assignment_history: list[ActionItemAssignmentResponse]
    progress_updates: list[ProgressUpdateResponse]
    status_history: list[ActionItemStatusHistoryResponse]
    completion_verifications: list[CompletionVerificationResponse]
