"""User, role, and server-side session models."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.meeting import Agenda, Meeting, MeetingParticipant


def utc_now() -> datetime:
    return datetime.now(UTC)


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column(
        "user_id", Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "role_id", Uuid(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True
    ),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    role_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    role_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    users: Mapped[list["User"]] = relationship(secondary=user_roles, back_populates="roles")


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, back_populates="users")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")
    meetings_created: Mapped[list["Meeting"]] = relationship(
        back_populates="creator", foreign_keys="Meeting.created_by_id"
    )
    meetings_chairperson: Mapped[list["Meeting"]] = relationship(
        back_populates="chairperson", foreign_keys="Meeting.chairperson_id"
    )
    meetings_notetaker: Mapped[list["Meeting"]] = relationship(
        back_populates="notetaker", foreign_keys="Meeting.notetaker_id"
    )
    meeting_participations: Mapped[list["MeetingParticipant"]] = relationship(back_populates="user")
    led_agendas: Mapped[list["Agenda"]] = relationship(back_populates="lead_user")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship(back_populates="sessions")
