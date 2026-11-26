"""Action items and append-only assignment, progress, status, and review history."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Register the referenced table for ActionItem's composite disposition foreign key.
from app.models import disposition as _disposition_models  # noqa: F401
from app.models.organization import OrganizationUnit

if TYPE_CHECKING:
    from app.models.auth import User


def utc_now() -> datetime:
    return datetime.now(UTC)


class ActionItemStatus(StrEnum):
    BELUM_DIMULAI = "BELUM_DIMULAI"
    BERPROSES = "BERPROSES"
    TERKENDALA = "TERKENDALA"
    MENUNGGU_ACC = "MENUNGGU_ACC"
    SELESAI = "SELESAI"


class AssignmentRole(StrEnum):
    MAIN = "MAIN"
    SUPPORTING = "SUPPORTING"


class CompletionReviewOutcome(StrEnum):
    VERIFIED = "VERIFIED"
    NEEDS_REVISION = "NEEDS_REVISION"


class ProgressSubmitterKind(StrEnum):
    PIC = "PIC"
    LEADERSHIP = "LEADERSHIP"


class ActionItemEvidenceKind(StrEnum):
    FILE = "FILE"
    LINK = "LINK"


class ActionItemEvidenceScanStatus(StrEnum):
    PENDING = "PENDING"
    CLEAN = "CLEAN"
    REJECTED = "REJECTED"


ACTION_ITEM_STATUS_CHECK = (
    "official_status IN ('BELUM_DIMULAI', 'BERPROSES', 'TERKENDALA', 'MENUNGGU_ACC', 'SELESAI')"
)


class ActionItem(Base):
    __tablename__ = "action_items"
    __table_args__ = (
        CheckConstraint(ACTION_ITEM_STATUS_CHECK, name="ck_action_items_official_status"),
        CheckConstraint("version > 0", name="ck_action_items_version_positive"),
        CheckConstraint(
            "(deleted_at IS NULL AND deleted_by_id IS NULL) OR "
            "(deleted_at IS NOT NULL AND deleted_by_id IS NOT NULL)",
            name="ck_action_items_deleted_actor_pair",
        ),
        CheckConstraint(
            "(official_status = 'SELESAI' AND completed_at IS NOT NULL) OR "
            "(official_status <> 'SELESAI' AND completed_at IS NULL)",
            name="ck_action_items_completed_at_status",
        ),
        CheckConstraint(
            "length(trim(title)) > 0 AND length(title) <= 300",
            name="ck_action_items_title",
        ),
        CheckConstraint(
            "length(trim(description)) > 0 AND length(description) <= 20000",
            name="ck_action_items_description",
        ),
        CheckConstraint(
            "output_expected IS NULL OR length(output_expected) <= 20000",
            name="ck_action_items_output_expected",
        ),
        CheckConstraint(
            "length(trim(priority)) > 0 AND length(priority) <= 100",
            name="ck_action_items_priority",
        ),
        ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id", "source_decision_id"],
            [
                "minutes_decisions.meeting_id",
                "minutes_decisions.minutes_revision_id",
                "minutes_decisions.id",
            ],
            name="fk_action_items_exact_source_decision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "disposition_id",
                "meeting_id",
                "source_minutes_revision_id",
                "source_decision_id",
            ],
            [
                "dispositions.id",
                "dispositions.meeting_id",
                "dispositions.source_minutes_revision_id",
                "dispositions.source_decision_id",
            ],
            name="fk_action_items_disposition_source",
            ondelete="RESTRICT",
        ),
        Index("ix_action_items_meeting_status", "meeting_id", "official_status"),
        Index("ix_action_items_source_revision", "meeting_id", "source_minutes_revision_id"),
        Index("ix_action_items_disposition_id", "disposition_id"),
        Index("ix_action_items_responsible_unit_id", "responsible_unit_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    disposition_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    responsible_unit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "organization_units.id",
            name="fk_action_items_responsible_unit",
            ondelete="RESTRICT",
        ),
    )
    meeting_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_minutes_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    output_expected: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(100), nullable=False)
    official_status: Mapped[ActionItemStatus] = mapped_column(
        String(30), default=ActionItemStatus.BELUM_DIMULAI, nullable=False
    )
    created_by_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_action_items_deleted_by_user", ondelete="RESTRICT"),
    )

    assignments: Mapped[list["ActionItemAssignment"]] = relationship(
        back_populates="action_item", order_by=lambda: ActionItemAssignment.started_at
    )
    responsible_unit: Mapped["OrganizationUnit | None"] = relationship(
        "OrganizationUnit", foreign_keys=[responsible_unit_id]
    )
    progress_updates: Mapped[list["ProgressUpdate"]] = relationship(
        back_populates="action_item", order_by=lambda: ProgressUpdate.submitted_at
    )
    status_history: Mapped[list["ActionItemStatusHistory"]] = relationship(
        back_populates="action_item", order_by=lambda: ActionItemStatusHistory.event_number
    )
    completion_verifications: Mapped[list["CompletionVerification"]] = relationship(
        back_populates="action_item", order_by=lambda: CompletionVerification.reviewed_at
    )


class ActionItemAssignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        CheckConstraint(
            "assignment_role IN ('MAIN', 'SUPPORTING')",
            name="ck_assignments_role",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_assignments_end_after_start",
        ),
        CheckConstraint(
            "(ended_at IS NULL AND ended_by_user_id IS NULL AND end_reason IS NULL) OR "
            "(ended_at IS NOT NULL AND ended_by_user_id IS NOT NULL "
            "AND end_reason IS NOT NULL AND length(trim(end_reason)) > 0)",
            name="ck_assignments_end_metadata",
        ),
        CheckConstraint(
            "assignment_reason IS NULL OR length(assignment_reason) <= 4000",
            name="ck_assignments_reason_length",
        ),
        CheckConstraint(
            "(assignee_user_id IS NOT NULL AND assignee_display_name IS NULL) OR "
            "(assignee_user_id IS NULL AND assignee_display_name IS NOT NULL "
            "AND length(trim(assignee_display_name)) > 0)",
            name="ck_assignments_user_or_display_name",
        ),
        CheckConstraint(
            "end_reason IS NULL OR length(end_reason) <= 4000",
            name="ck_assignments_end_reason_length",
        ),
        ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_assignments_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("action_item_id", "id", name="uq_assignments_action_item_id"),
        UniqueConstraint(
            "action_item_id", "id", "assignee_user_id", name="uq_assignments_actor_reference"
        ),
        Index(
            "uq_assignments_one_active_main",
            "action_item_id",
            unique=True,
            postgresql_where=text("assignment_role = 'MAIN' AND ended_at IS NULL"),
            sqlite_where=text("assignment_role = 'MAIN' AND ended_at IS NULL"),
        ),
        Index(
            "uq_assignments_one_active_role_per_user",
            "action_item_id",
            "assignee_user_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
        Index("ix_assignments_assignee_active", "assignee_user_id", "ended_at"),
        Index("ix_assignments_pic_origin_unit_id", "pic_origin_unit_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    action_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assignee_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    assignee_display_name: Mapped[str | None] = mapped_column(String(200))
    assigned_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    pic_origin_unit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "organization_units.id",
            name="fk_assignments_pic_origin_unit",
            ondelete="RESTRICT",
        ),
    )
    assignment_role: Mapped[AssignmentRole] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    assignment_reason: Mapped[str | None] = mapped_column(Text)
    end_reason: Mapped[str | None] = mapped_column(Text)

    action_item: Mapped[ActionItem] = relationship(back_populates="assignments")
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assignee_user_id])
    pic_origin_unit: Mapped["OrganizationUnit | None"] = relationship(
        "OrganizationUnit", foreign_keys=[pic_origin_unit_id]
    )


class ProgressUpdate(Base):
    __tablename__ = "progress_updates"
    __table_args__ = (
        CheckConstraint(
            "progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100",
            name="ck_progress_updates_percent",
        ),
        CheckConstraint(
            "(report_text IS NOT NULL AND length(trim(report_text)) > 0) OR "
            "(blocker_text IS NOT NULL AND length(trim(blocker_text)) > 0) OR "
            "progress_percent IS NOT NULL OR completion_requested",
            name="ck_progress_updates_has_report",
        ),
        CheckConstraint(
            "report_text IS NULL OR length(report_text) <= 20000",
            name="ck_progress_updates_report_length",
        ),
        CheckConstraint(
            "blocker_text IS NULL OR length(blocker_text) <= 20000",
            name="ck_progress_updates_blocker_length",
        ),
        CheckConstraint(
            "(submitted_as = 'PIC' AND assignment_id IS NOT NULL) OR "
            "(submitted_as = 'LEADERSHIP' AND assignment_id IS NULL)",
            name="ck_progress_updates_submission_context",
        ),
        ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_progress_updates_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["action_item_id", "assignment_id"],
            ["assignments.action_item_id", "assignments.id"],
            name="fk_progress_updates_assignment_same_task",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("action_item_id", "id", name="uq_progress_updates_action_item_id"),
        Index("ix_progress_updates_action_item_time", "action_item_id", "submitted_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    action_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assignment_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_as: Mapped[ProgressSubmitterKind] = mapped_column(
        String(20),
        default=ProgressSubmitterKind.PIC,
        server_default=ProgressSubmitterKind.PIC.value,
        nullable=False,
    )
    report_text: Mapped[str | None] = mapped_column(Text)
    blocker_text: Mapped[str | None] = mapped_column(Text)
    progress_percent: Mapped[int | None] = mapped_column(SmallInteger)
    completion_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    action_item: Mapped[ActionItem] = relationship(back_populates="progress_updates")
    evidence: Mapped[list["ActionItemEvidence"]] = relationship(
        back_populates="progress_update", order_by="ActionItemEvidence.created_at"
    )


class ActionItemEvidence(Base):
    __tablename__ = "action_item_evidence"
    __table_args__ = (
        CheckConstraint("evidence_kind IN ('FILE', 'LINK')", name="ck_action_item_evidence_kind"),
        CheckConstraint(
            "(evidence_kind = 'FILE' AND storage_key IS NOT NULL "
            "AND length(storage_key) = 32 "
            "AND original_filename IS NOT NULL AND content_type IS NOT NULL "
            "AND content_type IN ("
            "'application/pdf', 'image/jpeg', 'image/png', 'image/heic', 'image/heif', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', "
            "'application/vnd.openxmlformats-officedocument.presentationml.presentation', "
            "'text/csv', 'text/plain') "
            "AND size_bytes IS NOT NULL AND size_bytes BETWEEN 1 AND 10485760 "
            "AND sha256 IS NOT NULL AND external_url IS NULL) OR "
            "(evidence_kind = 'LINK' AND storage_key IS NULL "
            "AND original_filename IS NULL AND content_type IS NULL "
            "AND size_bytes IS NULL AND sha256 IS NULL AND external_url IS NOT NULL "
            "AND substr(external_url, 1, 8) = 'https://')",
            name="ck_action_item_evidence_payload",
        ),
        CheckConstraint(
            "link_label IS NULL OR length(link_label) BETWEEN 1 AND 200",
            name="ck_action_item_evidence_link_label",
        ),
        CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64", name="ck_action_item_evidence_sha256_length"
        ),
        ForeignKeyConstraint(
            ["action_item_id", "progress_update_id"],
            ["progress_updates.action_item_id", "progress_updates.id"],
            name="fk_action_item_evidence_progress_same_task",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("storage_key", name="uq_action_item_evidence_storage_key"),
        Index("ix_action_item_evidence_progress_time", "progress_update_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    action_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    progress_update_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_kind: Mapped[ActionItemEvidenceKind] = mapped_column(String(10), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(32))
    original_filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    external_url: Mapped[str | None] = mapped_column(Text)
    link_label: Mapped[str | None] = mapped_column(String(200))
    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    progress_update: Mapped[ProgressUpdate] = relationship(back_populates="evidence")
    scan_events: Mapped[list["ActionItemEvidenceScan"]] = relationship(
        back_populates="evidence", order_by="ActionItemEvidenceScan.event_number"
    )


class ActionItemEvidenceScan(Base):
    __tablename__ = "action_item_evidence_scans"
    __table_args__ = (
        CheckConstraint(
            "scan_status IN ('PENDING', 'CLEAN', 'REJECTED')",
            name="ck_action_item_evidence_scans_status",
        ),
        CheckConstraint(
            "event_number > 0",
            name="ck_action_item_evidence_scans_event_number",
        ),
        CheckConstraint(
            "(scan_status = 'PENDING' AND scanner_name IS NULL "
            "AND scanner_version IS NULL AND scanned_sha256 IS NULL) OR "
            "(scan_status IN ('CLEAN', 'REJECTED') AND scanner_name IS NOT NULL "
            "AND length(trim(scanner_name)) > 0 AND scanner_version IS NOT NULL "
            "AND length(trim(scanner_version)) > 0 AND scanned_sha256 IS NOT NULL "
            "AND length(scanned_sha256) = 64)",
            name="ck_action_item_evidence_scans_result",
        ),
        ForeignKeyConstraint(
            ["evidence_id"],
            ["action_item_evidence.id"],
            name="fk_action_item_evidence_scans_evidence_id",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "evidence_id",
            "event_number",
            name="uq_action_item_evidence_scans_event_number",
        ),
        Index(
            "ix_action_item_evidence_scans_latest",
            "evidence_id",
            "event_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    evidence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_status: Mapped[ActionItemEvidenceScanStatus] = mapped_column(String(10), nullable=False)
    scanner_name: Mapped[str | None] = mapped_column(String(100))
    scanner_version: Mapped[str | None] = mapped_column(String(100))
    scanned_sha256: Mapped[str | None] = mapped_column(String(64))
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    evidence: Mapped[ActionItemEvidence] = relationship(back_populates="scan_events")


class CompletionVerification(Base):
    __tablename__ = "completion_verifications"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('VERIFIED', 'NEEDS_REVISION')",
            name="ck_completion_verifications_outcome",
        ),
        CheckConstraint(
            "review_note IS NULL OR length(review_note) <= 4000",
            name="ck_completion_verifications_note_length",
        ),
        CheckConstraint(
            "outcome <> 'NEEDS_REVISION' OR "
            "(review_note IS NOT NULL AND length(trim(review_note)) > 0)",
            name="ck_completion_verifications_revision_note",
        ),
        ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_completion_verifications_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["action_item_id", "progress_update_id"],
            ["progress_updates.action_item_id", "progress_updates.id"],
            name="fk_completion_verifications_progress_same_task",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("action_item_id", "id", name="uq_completion_verifications_action_item_id"),
        UniqueConstraint(
            "action_item_id", "progress_update_id", name="uq_completion_verifications_report"
        ),
        Index("ix_completion_verifications_task_time", "action_item_id", "reviewed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    action_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    progress_update_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewer_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[CompletionReviewOutcome] = mapped_column(String(30), nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    action_item: Mapped[ActionItem] = relationship(back_populates="completion_verifications")


class ActionItemStatusHistory(Base):
    __tablename__ = "status_histories"
    __table_args__ = (
        CheckConstraint("event_number > 0", name="ck_status_histories_event_number_positive"),
        CheckConstraint(
            "old_status IS NULL OR old_status IN "
            "('BELUM_DIMULAI', 'BERPROSES', 'TERKENDALA', 'MENUNGGU_ACC', 'SELESAI')",
            name="ck_status_histories_old_status",
        ),
        CheckConstraint(
            "new_status IN ('BELUM_DIMULAI', 'BERPROSES', 'TERKENDALA', 'MENUNGGU_ACC', 'SELESAI')",
            name="ck_status_histories_new_status",
        ),
        CheckConstraint(
            "old_status IS NULL OR old_status <> new_status",
            name="ck_status_histories_status_changed",
        ),
        CheckConstraint(
            "old_status IS NOT NULL OR new_status = 'BELUM_DIMULAI'",
            name="ck_status_histories_initial_status",
        ),
        CheckConstraint(
            "new_status <> 'SELESAI' OR verification_id IS NOT NULL",
            name="ck_status_histories_completion_verification_required",
        ),
        ForeignKeyConstraint(
            ["action_item_id"],
            ["action_items.id"],
            name="fk_status_histories_action_item_id_action_items",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["action_item_id", "verification_id"],
            ["completion_verifications.action_item_id", "completion_verifications.id"],
            name="fk_status_histories_verification_same_task",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("action_item_id", "event_number", name="uq_status_histories_task_event"),
        Index("ix_status_histories_task_time", "action_item_id", "changed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    action_item_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_number: Mapped[int] = mapped_column(Integer, nullable=False)
    old_status: Mapped[ActionItemStatus | None] = mapped_column(String(30))
    new_status: Mapped[ActionItemStatus] = mapped_column(String(30), nullable=False)
    changed_by_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    verification_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    change_note: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )

    action_item: Mapped[ActionItem] = relationship(back_populates="status_history")
