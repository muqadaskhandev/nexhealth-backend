"""SMS business registration for A2P compliance

Revision ID: 0044_sms_registration
Revises: 0043_out_of_office
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044_sms_registration"
down_revision: Union[str, None] = "0043_out_of_office"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sms_registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="not_started"),
        sa.Column("legal_business_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("ein", sa.String(20), nullable=False, server_default=""),
        sa.Column("dba_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("business_type", sa.String(100), nullable=False, server_default=""),
        sa.Column("business_address", sa.String(300), nullable=False, server_default=""),
        sa.Column("business_city", sa.String(100), nullable=False, server_default=""),
        sa.Column("business_state", sa.String(50), nullable=False, server_default=""),
        sa.Column("business_zip", sa.String(20), nullable=False, server_default=""),
        sa.Column("business_phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("business_website", sa.String(300), nullable=False, server_default=""),
        sa.Column("auth_rep_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("auth_rep_email", sa.String(200), nullable=False, server_default=""),
        sa.Column("auth_rep_phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("auth_rep_title", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "request_office_number_hosting",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("office_phone_number", sa.String(40), nullable=False, server_default=""),
        sa.Column("failure_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("location_id", name="uq_sms_registration_location"),
    )
    op.create_index("ix_sms_registrations_practice_id", "sms_registrations", ["practice_id"])
    op.create_index("ix_sms_registrations_location_id", "sms_registrations", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_sms_registrations_location_id", table_name="sms_registrations")
    op.drop_index("ix_sms_registrations_practice_id", table_name="sms_registrations")
    op.drop_table("sms_registrations")
