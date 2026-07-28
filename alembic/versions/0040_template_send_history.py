"""Template automation send history

Revision ID: 0040_template_send_history
Revises: 0039_family_messaging
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_template_send_history"
down_revision: Union[str, None] = "0039_family_messaging"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "communication_template_sends",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("communication_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("patient_name", sa.String(240), nullable=False, server_default=""),
        sa.Column("patient_dob", sa.Date(), nullable=True),
        sa.Column("communication_label", sa.String(200), nullable=False, server_default=""),
        sa.Column("channel", sa.String(20), nullable=False, server_default="sms"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("appointment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_communication_template_sends_practice_id", "communication_template_sends", ["practice_id"])
    op.create_index("ix_communication_template_sends_location_id", "communication_template_sends", ["location_id"])
    op.create_index("ix_communication_template_sends_template_id", "communication_template_sends", ["template_id"])
    op.create_index("ix_communication_template_sends_patient_id", "communication_template_sends", ["patient_id"])
    op.create_index("ix_communication_template_sends_sent_at", "communication_template_sends", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_communication_template_sends_sent_at", table_name="communication_template_sends")
    op.drop_index("ix_communication_template_sends_patient_id", table_name="communication_template_sends")
    op.drop_index("ix_communication_template_sends_template_id", table_name="communication_template_sends")
    op.drop_index("ix_communication_template_sends_location_id", table_name="communication_template_sends")
    op.drop_index("ix_communication_template_sends_practice_id", table_name="communication_template_sends")
    op.drop_table("communication_template_sends")
