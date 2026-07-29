"""Email/SMS campaigns

Revision ID: 0045_campaigns
Revises: 0044_sms_registration
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045_campaigns"
down_revision: Union[str, None] = "0044_sms_registration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("title", sa.String(300), nullable=False, server_default=""),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column(
            "is_favorite_template",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "source_campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("wizard_step", sa.String(30), nullable=False, server_default="audience"),
        sa.Column(
            "audience_filters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "selected_patient_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "excluded_patient_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("has_email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("email_subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("email_preview_text", sa.String(500), nullable=False, server_default=""),
        sa.Column("email_body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "email_images",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("has_sms", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sms_body", sa.String(425), nullable=False, server_default=""),
        sa.Column("ai_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by_name", sa.String(200), nullable=False, server_default=""),
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
    )
    op.create_index("ix_campaigns_practice_id", "campaigns", ["practice_id"])

    op.create_table(
        "campaign_send_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("patient_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="sent"),
        sa.Column("failure_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "campaign_id", "patient_id", "channel", name="uq_campaign_send_patient_channel"
        ),
    )
    op.create_index("ix_campaign_send_logs_campaign_id", "campaign_send_logs", ["campaign_id"])
    op.create_index("ix_campaign_send_logs_practice_id", "campaign_send_logs", ["practice_id"])


def downgrade() -> None:
    op.drop_index("ix_campaign_send_logs_practice_id", table_name="campaign_send_logs")
    op.drop_index("ix_campaign_send_logs_campaign_id", table_name="campaign_send_logs")
    op.drop_table("campaign_send_logs")
    op.drop_index("ix_campaigns_practice_id", table_name="campaigns")
    op.drop_table("campaigns")
