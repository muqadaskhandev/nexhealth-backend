"""Campaign SMS monthly cap and overage settings

Revision ID: 0047_campaign_sms_cap
Revises: 0046_campaign_analytics
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047_campaign_sms_cap"
down_revision: Union[str, None] = "0046_campaign_analytics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaign_send_logs",
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_campaign_send_logs_location_id", "campaign_send_logs", ["location_id"]
    )

    op.create_table(
        "campaign_sms_cap_settings",
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
        sa.Column("allow_overage", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("overage_messages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("location_id", name="uq_campaign_sms_cap_location"),
    )
    op.create_index(
        "ix_campaign_sms_cap_settings_practice_id",
        "campaign_sms_cap_settings",
        ["practice_id"],
    )
    op.create_index(
        "ix_campaign_sms_cap_settings_location_id",
        "campaign_sms_cap_settings",
        ["location_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_sms_cap_settings_location_id", table_name="campaign_sms_cap_settings")
    op.drop_index("ix_campaign_sms_cap_settings_practice_id", table_name="campaign_sms_cap_settings")
    op.drop_table("campaign_sms_cap_settings")
    op.drop_index("ix_campaign_send_logs_location_id", table_name="campaign_send_logs")
    op.drop_column("campaign_send_logs", "location_id")
