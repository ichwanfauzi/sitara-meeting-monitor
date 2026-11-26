from alembic import context
from app.core.config import get_settings
from app.models import (
    action_item,
    audit,
    auth,
    disposition,
    meeting,
    notification,
    organization,
    security,
)
from sqlalchemy import engine_from_config, pool

config = context.config
database_url = get_settings().database_url
if database_url:
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = auth.Base.metadata
assert meeting.Meeting.metadata is target_metadata
assert organization.OrganizationUnit.metadata is target_metadata
assert security.LoginRateLimitBucket.metadata is target_metadata
assert action_item.ActionItem.metadata is target_metadata
assert audit.AuditEvent.metadata is target_metadata
assert disposition.Disposition.metadata is target_metadata
assert notification.Notification.metadata is target_metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("DATABASE_URL must be configured to run migrations")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
