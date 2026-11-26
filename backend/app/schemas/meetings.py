"""Meeting, agenda, and participant API schemas."""

from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.meeting import MeetingStatus, MinutesReviewResult

DecisionBriefApprovalEventName = Literal["SUBMITTED", "WITHDRAWN", "APPROVED", "REJECTED"]
DecisionBriefApprovalState = Literal[
    "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "WITHDRAWN"
]


class MeetingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_number: str = Field(min_length=1, max_length=150)
    title: str = Field(min_length=1, max_length=300)
    meeting_type: str = Field(default="RAPIM", min_length=1, max_length=100)
    meeting_date: date
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=300)
    notetaker_id: UUID | None = None

    @field_validator("meeting_number", "title", "meeting_type")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value

    @field_validator("location")
    @classmethod
    def strip_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_time_order(self) -> "MeetingCreate":
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class MeetingMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)
    meeting_number: str | None = Field(default=None, max_length=150)
    title: str | None = Field(default=None, max_length=300)
    meeting_type: str | None = Field(default=None, max_length=100)
    meeting_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    location: str | None = Field(default=None, max_length=300)

    @field_validator("meeting_number", "title", "meeting_type")
    @classmethod
    def strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Field cannot be blank")
        return value

    @field_validator("location")
    @classmethod
    def strip_location(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_changes(self) -> "MeetingMetadataUpdate":
        changes = self.model_fields_set - {"expected_version"}
        if not changes:
            raise ValueError("At least one meeting field must be updated")
        if (
            ("meeting_number" in changes and self.meeting_number is None)
            or ("title" in changes and self.title is None)
            or ("meeting_type" in changes and self.meeting_type is None)
            or ("meeting_date" in changes and self.meeting_date is None)
        ):
            raise ValueError("Title, meeting type, and meeting date cannot be null")
        if self.start_time and self.end_time and self.end_time < self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class AgendaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=500)
    agenda_description: str | None = Field(default=None, max_length=10_000)
    pic_suggestion: str | None = Field(default=None, max_length=300)
    supporting_pic_suggestion: str | None = Field(default=None, max_length=2_000)
    duration_minutes: int | None = Field(default=None, gt=0, le=1440)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value


class AgendaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=500)
    agenda_description: str | None = Field(default=None, max_length=10_000)
    pic_suggestion: str | None = Field(default=None, max_length=300)
    supporting_pic_suggestion: str | None = Field(default=None, max_length=2_000)
    duration_minutes: int | None = Field(default=None, gt=0, le=1440)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be blank")
        return value


class MeetingParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, gt=0)
    user_id: UUID


class MeetingExternalParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)
    participant_name: str = Field(min_length=1, max_length=200)

    @field_validator("participant_name")
    @classmethod
    def strip_participant_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("participant_name cannot be blank")
        return value


class NotetakerHandoverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(gt=0)
    new_notetaker_id: UUID


class MeetingTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_status: MeetingStatus


class MinutesReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes_revision_id: UUID
    result: MinutesReviewResult
    review_note: str | None = Field(default=None, max_length=4_000)

    @field_validator("review_note")
    @classmethod
    def strip_review_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class MinutesDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_text: str = Field(min_length=1, max_length=20_000)
    pic_suggestion: str | None = Field(default=None, max_length=300)
    output_expected: str | None = Field(default=None, max_length=20_000)
    target_date: date | None = None
    target_text: str | None = Field(default=None, max_length=500)
    is_action_item: bool = False

    @field_validator("decision_text")
    @classmethod
    def reject_blank_decision(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Decision text cannot be blank")
        return value

    @field_validator("pic_suggestion")
    @classmethod
    def strip_pic_suggestion(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("output_expected")
    @classmethod
    def strip_output_expected(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("target_text")
    @classmethod
    def strip_target_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def allow_one_target_value(self) -> "MinutesDecisionCreate":
        if self.target_date is not None and self.target_text is not None:
            raise ValueError("Choose either a target date or manual target text")
        return self


class MinutesDiscussionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agenda_id: UUID
    subject: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=1, max_length=100_000)
    decisions: list[MinutesDecisionCreate] = Field(default_factory=list, max_length=100)

    @field_validator("subject")
    @classmethod
    def strip_subject(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("content")
    @classmethod
    def reject_blank_discussion(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Discussion content cannot be blank")
        return value


class MinutesRevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal[1, 2] = 1
    content: str | None = Field(default=None, max_length=1_000_000)
    base_revision_id: UUID | None
    discussions: list[MinutesDiscussionCreate] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_representation(self) -> "MinutesRevisionCreate":
        if self.format_version == 1:
            if self.content is None or not self.content.strip():
                raise ValueError("Text minutes content cannot be blank")
            if self.discussions:
                raise ValueError("Text minutes cannot contain structured discussions")
        else:
            if self.content is not None:
                raise ValueError("Structured minutes must not contain legacy text content")
            if not self.discussions:
                raise ValueError("Structured minutes must contain at least one discussion")

        total_text_length = 0
        total_decisions = 0
        for discussion in self.discussions:
            total_text_length += len(discussion.subject or "") + len(discussion.content)
            total_decisions += len(discussion.decisions)
            for decision in discussion.decisions:
                total_text_length += (
                    len(decision.decision_text)
                    + len(decision.output_expected or "")
                    + len(decision.target_text or "")
                )
        if total_text_length > 1_000_000:
            raise ValueError("Minutes snapshot cannot exceed 1,000,000 text characters")
        if total_decisions > 1_000:
            raise ValueError("Minutes snapshot cannot exceed 1,000 decisions")
        return self


class DecisionBriefDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID
    brief_text: str = Field(default="", max_length=20_000)
    priority: str = Field(default="", max_length=100)
    editorial_note: str | None = Field(default=None, max_length=4_000)

    @field_validator("priority")
    @classmethod
    def strip_priority(cls, value: str) -> str:
        return value.strip()

    @field_validator("brief_text")
    @classmethod
    def strip_brief_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("editorial_note")
    @classmethod
    def strip_editorial_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class DecisionBriefVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_minutes_revision_id: UUID
    summary: str = Field(min_length=1, max_length=100_000)
    notes: str | None = Field(default=None, max_length=20_000)
    decisions: list[DecisionBriefDecisionCreate] = Field(min_length=1, max_length=200)

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("summary cannot be blank")
        return value

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def reject_duplicate_source_decisions(self) -> "DecisionBriefVersionCreate":
        decision_ids = [item.decision_id for item in self.decisions]
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("Decision Brief cannot reference the same source decision twice")
        return self


class DecisionBriefRejectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=4_000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("rejection reason cannot be blank")
        return value


class AgendaResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    agenda_number: int
    title: str
    agenda_description: str | None
    pic_suggestion: str | None
    supporting_pic_suggestion: str | None
    duration_minutes: int | None
    sort_order: int


class MeetingParticipantResponse(BaseModel):
    user_id: UUID
    participant_name: str
    participant_title: str | None


class MeetingExternalParticipantResponse(BaseModel):
    id: UUID
    participant_name: str


class MeetingParticipantOptionResponse(BaseModel):
    id: UUID
    full_name: str
    job_title: str | None
    roles: list[str]


class NotetakerHandoverResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    from_notetaker_id: UUID | None
    to_notetaker_id: UUID
    requested_by_user_id: UUID
    requested_at: datetime
    status: Literal["PENDING", "APPROVED"]
    approved_by_user_id: UUID | None
    approved_at: datetime | None


class MeetingResponse(BaseModel):
    id: UUID
    meeting_number: str
    title: str
    meeting_type: str
    meeting_date: date
    start_time: time | None
    end_time: time | None
    location: str | None
    created_by_id: UUID
    notetaker_id: UUID | None
    status: MeetingStatus
    version: int
    created_at: datetime
    updated_at: datetime
    agendas: list[AgendaResponse]
    participants: list[MeetingParticipantResponse]
    external_participants: list[MeetingExternalParticipantResponse]


class MinutesReviewResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    minutes_revision_id: UUID | None
    reviewer_user_id: UUID
    review_number: int
    result: MinutesReviewResult
    review_note: str | None
    reviewed_at: datetime


class MinutesDecisionResponse(BaseModel):
    id: UUID
    discussion_id: UUID
    decision_number: int
    decision_text: str
    pic_suggestion: str | None
    output_expected: str | None
    target_date: date | None
    target_text: str | None
    is_action_item: bool


class MinutesDiscussionResponse(BaseModel):
    id: UUID
    agenda_id: UUID
    discussion_number: int
    subject: str | None
    content: str
    decisions: list[MinutesDecisionResponse]


class MinutesRevisionResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    revision_number: int
    format_version: Literal[1, 2]
    content: str | None
    discussions: list[MinutesDiscussionResponse]
    created_by_id: UUID
    created_at: datetime


class DecisionBriefDecisionResponse(BaseModel):
    decision_id: UUID
    source_decision_text: str
    source_agenda_id: UUID
    source_agenda_title: str
    source_discussion_id: UUID
    source_discussion_subject: str | None
    brief_text: str | None
    priority: str
    editorial_note: str | None
    position: int


class DecisionBriefApprovalEventResponse(BaseModel):
    id: UUID
    event_number: int
    event_type: DecisionBriefApprovalEventName
    actor_user_id: UUID
    actor_roles: list[str]
    reason: str | None
    correlation_id: UUID | None
    occurred_at: datetime


class DecisionBriefVersionResponse(BaseModel):
    id: UUID
    meeting_id: UUID
    source_minutes_revision_id: UUID
    version_number: int
    summary: str
    notes: str | None
    created_by_id: UUID
    created_at: datetime
    is_stale: bool
    approval_state: DecisionBriefApprovalState
    approval_events: list[DecisionBriefApprovalEventResponse]
    decisions: list[DecisionBriefDecisionResponse]
