"""Review responses table for Google Reviews survey flow

Revision ID: 0048_review_responses
Revises: 0047_campaign_sms_cap
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048_review_responses"
down_revision: Union[str, None] = "0047_campaign_sms_cap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
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
        sa.Column(
            "appointment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("google_prompted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_review_responses_practice_id", "review_responses", ["practice_id"])
    op.create_index("ix_review_responses_location_id", "review_responses", ["location_id"])
    op.create_index("ix_review_responses_appointment_id", "review_responses", ["appointment_id"])
    op.create_index("ix_review_responses_patient_id", "review_responses", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_review_responses_patient_id", table_name="review_responses")
    op.drop_index("ix_review_responses_appointment_id", table_name="review_responses")
    op.drop_index("ix_review_responses_location_id", table_name="review_responses")
    op.drop_index("ix_review_responses_practice_id", table_name="review_responses")
    op.drop_table("review_responses")
