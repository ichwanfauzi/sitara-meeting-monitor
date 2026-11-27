"""Authentication and server-side session use cases."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.models.auth import User, UserSession


class InvalidPasswordChange(ValueError):
    """Raised when a password change does not prove the current credential."""


class PasswordChangePersistenceError(RuntimeError):
    """Raised when a password change transaction cannot be persisted."""


def authenticate_user(session: Session, email: str, password: str) -> User | None:
    user = session.scalar(select(User).options(selectinload(User.roles)).where(User.email == email))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def create_user_session(session: Session, user: User, ttl_seconds: int) -> tuple[UserSession, str]:
    raw_token = generate_session_token()
    user_session = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )
    session.add(user_session)
    session.commit()
    session.refresh(user_session)
    return user_session, raw_token


def find_active_session(session: Session, raw_token: str) -> tuple[UserSession, User] | None:
    user_session = session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(raw_token))
    )
    if user_session is None or user_session.revoked_at is not None:
        return None

    expires_at = user_session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        return None

    user = session.get(User, user_session.user_id)
    if user is None or not user.is_active:
        return None
    return user_session, user


def revoke_user_session(session: Session, user_session: UserSession) -> None:
    user_session.revoked_at = datetime.now(UTC)
    session.commit()


def change_user_password(
    session: Session,
    *,
    user: User,
    current_session: UserSession,
    current_password: str,
    new_password: str,
) -> None:
    if not verify_password(current_password, user.password_hash) or verify_password(
        new_password, user.password_hash
    ):
        raise InvalidPasswordChange

    now = datetime.now(UTC)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    session.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.id != current_session.id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    try:
        session.commit()
    except SQLAlchemyError as error:
        session.rollback()
        raise PasswordChangePersistenceError from error
