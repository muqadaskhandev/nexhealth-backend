"""Campaign analytics engagement fields

Revision ID: 0046_campaign_analytics
Revises: 0045_campaigns
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046_campaign_analytics"
down_revision: Union[str, None] = "0045_campaigns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("is_starred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "campaigns",
        sa.Column("appointments_booked", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "campaign_send_logs",
        sa.Column("patient_email", sa.String(200), nullable=False, server_default=""),
    )
    op.add_column(
        "campaign_send_logs",
        sa.Column("patient_phone", sa.String(40), nullable=False, server_default=""),
    )
    op.add_column(
        "campaign_send_logs",
        sa.Column("opened", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "campaign_send_logs",
        sa.Column("clicked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "campaign_send_logs",
        sa.Column("unsubscribed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "campaign_send_logs",
        sa.Column("responded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("campaign_send_logs", "responded")
    op.drop_column("campaign_send_logs", "unsubscribed")
    op.drop_column("campaign_send_logs", "clicked")
    op.drop_column("campaign_send_logs", "opened")
    op.drop_column("campaign_send_logs", "patient_phone")
    op.drop_column("campaign_send_logs", "patient_email")
    op.drop_column("campaigns", "appointments_booked")
    op.drop_column("campaigns", "is_starred")
