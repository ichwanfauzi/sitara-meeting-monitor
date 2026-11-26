"""Disposition records and their user, organization-unit, or role targets."""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.auth import Role, User
from app.models.organization import OrganizationUnit


class DispositionTargetType(StrEnum):
    USER = "USER"
    UNIT = "UNIT"
    ROLE = "ROLE"


class Disposition(Base):
    __tablename__ = "dispositions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["meeting_id", "source_minutes_revision_id", "source_decision_id"],
            [
                "minutes_decisions.meeting_id",
                "minutes_decisions.minutes_revision_id",
                "minutes_decisions.id",
            ],
            name="fk_dispositions_exact_source_decision",
            ondelete="RESTRICT",
        ),
        Index("ix_dispositions_meeting_created", "meeting_id", "created_at"),
        Index(
            "uq_dispositions_source_binding",
            "id",
            "meeting_id",
            "source_minutes_revision_id",
            "source_decision_id",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    meeting_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_minutes_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source_decision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    issued_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=text("CURRENT_TIMESTAMP"),
    )

    targets: Mapped[list["DispositionTarget"]] = relationship(back_populates="disposition")


class DispositionTarget(Base):
    __tablename__ = "disposition_targets"
    __table_args__ = (
        CheckConstraint(
            "(target_type = 'USER' AND target_user_id IS NOT NULL "
            "AND target_unit_id IS NULL AND target_role_id IS NULL) OR "
            "(target_type = 'UNIT' AND target_user_id IS NULL "
            "AND target_unit_id IS NOT NULL AND target_role_id IS NULL) OR "
            "(target_type = 'ROLE' AND target_user_id IS NULL "
            "AND target_unit_id IS NULL AND target_role_id IS NOT NULL)",
            name="ck_disposition_targets_target_shape",
        ),
        Index(
            "uq_disposition_targets_user",
            "disposition_id",
            "target_user_id",
            unique=True,
            postgresql_where=text("target_user_id IS NOT NULL"),
            sqlite_where=text("target_user_id IS NOT NULL"),
        ),
        Index(
            "uq_disposition_targets_unit",
            "disposition_id",
            "target_unit_id",
            unique=True,
            postgresql_where=text("target_unit_id IS NOT NULL"),
            sqlite_where=text("target_unit_id IS NOT NULL"),
        ),
        Index(
            "uq_disposition_targets_role",
            "disposition_id",
            "target_role_id",
            unique=True,
            postgresql_where=text("target_role_id IS NOT NULL"),
            sqlite_where=text("target_role_id IS NOT NULL"),
        ),
        Index("ix_disposition_targets_user", "target_user_id"),
        Index("ix_disposition_targets_unit", "target_unit_id"),
        Index("ix_disposition_targets_role", "target_role_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    disposition_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("dispositions.id", ondelete="RESTRICT"), nullable=False
    )
    target_type: Mapped[DispositionTargetType] = mapped_column(String(10), nullable=False)
    target_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    target_unit_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organization_units.id", ondelete="RESTRICT")
    )
    target_role_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT")
    )

    disposition: Mapped[Disposition] = relationship(back_populates="targets")
    target_user: Mapped[User | None] = relationship(foreign_keys=[target_user_id])
    target_unit: Mapped[OrganizationUnit | None] = relationship(foreign_keys=[target_unit_id])
    target_role: Mapped[Role | None] = relationship(foreign_keys=[target_role_id])

    @property
    def target_label(self) -> str:
        if self.target_type == DispositionTargetType.USER and self.target_user is not None:
            return self.target_user.full_name
        if self.target_type == DispositionTargetType.UNIT and self.target_unit is not None:
            return f"{self.target_unit.unit_code} · {self.target_unit.name}"
        if self.target_type == DispositionTargetType.ROLE and self.target_role is not None:
            return f"{self.target_role.role_name} ({self.target_role.role_code})"
        return "Target tidak tersedia"
