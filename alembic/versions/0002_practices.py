"""practices, invites, account types, 2FA

Revision ID: 0002_practices
Revises: 0001_initial
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_practices"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

subscription_plan = postgresql.ENUM(
    "starter", "professional", "enterprise", name="subscription_plan", create_type=False
)
ehr_system = postgresql.ENUM(
    "none",
    "open_dental",
    "dentrix",
    "athena",
    "eclinicalworks",
    "epic",
    "other",
    name="ehr_system",
    create_type=False,
)
sync_status = postgresql.ENUM(
    "not_connected", "pending", "connected", "error", name="sync_status", create_type=False
)
account_type = postgresql.ENUM(
    "super_admin", "practice", name="account_type", create_type=False
)
invite_type = postgresql.ENUM(
    "practice_admin", "staff", name="invite_type", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    subscription_plan.create(bind, checkfirst=True)
    ehr_system.create(bind, checkfirst=True)
    sync_status.create(bind, checkfirst=True)
    account_type.create(bind, checkfirst=True)
    invite_type.create(bind, checkfirst=True)

    op.create_table(
        "practices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("address", sa.String(400), nullable=False, server_default=""),
        sa.Column("city", sa.String(120), nullable=False, server_default=""),
        sa.Column("state", sa.String(80), nullable=False, server_default=""),
        sa.Column("zip_code", sa.String(20), nullable=False, server_default=""),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column(
            "subscription_plan",
            subscription_plan,
            nullable=False,
            server_default="starter",
        ),
        sa.Column(
            "enabled_products",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text(
                '\'{"scheduling": true, "forms": true, "communications": true, '
                '"payments": false, "verification": false}\'::jsonb'
            ),
        ),
        sa.Column("ehr_system", ehr_system, nullable=False, server_default="none"),
        sa.Column("sync_status", sync_status, nullable=False, server_default="not_connected"),
        sa.Column("sync_error", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.add_column(
        "users",
        sa.Column(
            "account_type",
            account_type,
            nullable=False,
            server_default="practice",
        ),
    )
    op.add_column(
        "users",
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("totp_secret", sa.String(64), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("totp_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_users_practice_id", "users", "practices", ["practice_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_users_practice_id", "users", ["practice_id"])

    op.add_column(
        "locations",
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_locations_practice_id",
        "locations",
        "practices",
        ["practice_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_locations_practice_id", "locations", ["practice_id"])

    op.create_table(
        "invite_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("first_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("invite_type", invite_type, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_invite_tokens_email", "invite_tokens", ["email"])
    op.create_index("ix_invite_tokens_token_hash", "invite_tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_table("invite_tokens")
    op.drop_index("ix_locations_practice_id", table_name="locations")
    op.drop_constraint("fk_locations_practice_id", "locations", type_="foreignkey")
    op.drop_column("locations", "practice_id")
    op.drop_index("ix_users_practice_id", table_name="users")
    op.drop_constraint("fk_users_practice_id", "users", type_="foreignkey")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "practice_id")
    op.drop_column("users", "account_type")
    op.drop_table("practices")
    invite_type.drop(op.get_bind(), checkfirst=True)
    account_type.drop(op.get_bind(), checkfirst=True)
    sync_status.drop(op.get_bind(), checkfirst=True)
    ehr_system.drop(op.get_bind(), checkfirst=True)
    subscription_plan.drop(op.get_bind(), checkfirst=True)
