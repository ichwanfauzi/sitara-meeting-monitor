"""Add effective-dated organization scope records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_organization_scope"
down_revision: str | None = "0007_decision_brief"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organization_units",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("unit_code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("parent_unit_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "parent_unit_id IS NULL OR parent_unit_id <> id",
            name="ck_organization_units_not_own_parent",
        ),
        sa.ForeignKeyConstraint(
            ["parent_unit_id"],
            ["organization_units.id"],
            name="fk_organization_units_parent_id_organization_units",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("unit_code", name="uq_organization_units_unit_code"),
    )
    op.create_table(
        "user_unit_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_user_unit_memberships_valid_interval",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["organization_units.id"],
            name="fk_user_unit_memberships_unit_id_organization_units",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_unit_memberships_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "unit_id",
            "valid_from",
            name="uq_user_unit_memberships_user_unit_start",
        ),
    )
    op.create_index(
        "ix_user_unit_memberships_user_period",
        "user_unit_memberships",
        ["user_id", "valid_from", "valid_until"],
    )
    op.create_index(
        "ix_user_unit_memberships_unit_period",
        "user_unit_memberships",
        ["unit_id", "valid_from", "valid_until"],
    )
    op.create_table(
        "reporting_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("manager_user_id", sa.Uuid(), nullable=False),
        sa.Column("subordinate_user_id", sa.Uuid(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "manager_user_id <> subordinate_user_id",
            name="ck_reporting_lines_not_self_referential",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_reporting_lines_valid_interval",
        ),
        sa.ForeignKeyConstraint(
            ["manager_user_id"],
            ["users.id"],
            name="fk_reporting_lines_manager_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subordinate_user_id"],
            ["users.id"],
            name="fk_reporting_lines_subordinate_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "manager_user_id",
            "subordinate_user_id",
            "valid_from",
            name="uq_reporting_lines_pair_start",
        ),
    )
    op.create_index(
        "ix_reporting_lines_manager_period",
        "reporting_lines",
        ["manager_user_id", "valid_from", "valid_until"],
    )
    op.create_index(
        "ix_reporting_lines_subordinate_period",
        "reporting_lines",
        ["subordinate_user_id", "valid_from", "valid_until"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    records = {
        # The table name comes only from the fixed migration tuple below.
        # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        table_name: connection.execute(sa.text(f"SELECT count(*) FROM {table_name}")).scalar_one()
        for table_name in ("reporting_lines", "user_unit_memberships", "organization_units")
    }
    populated = [table_name for table_name, count in records.items() if count]
    if populated:
        raise RuntimeError(
            "Cannot downgrade while organization scope contains records: " + ", ".join(populated)
        )

    op.drop_index("ix_reporting_lines_subordinate_period", table_name="reporting_lines")
    op.drop_index("ix_reporting_lines_manager_period", table_name="reporting_lines")
    op.drop_table("reporting_lines")
    op.drop_index("ix_user_unit_memberships_unit_period", table_name="user_unit_memberships")
    op.drop_index("ix_user_unit_memberships_user_period", table_name="user_unit_memberships")
    op.drop_table("user_unit_memberships")
    op.drop_table("organization_units")
