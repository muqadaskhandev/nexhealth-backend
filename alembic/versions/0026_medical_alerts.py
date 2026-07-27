"""Medical alert catalog for Integrated Medical History forms

Revision ID: 0026_medical_alerts
Revises: 0025_form_sync_status
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_medical_alerts"
down_revision: Union[str, None] = "0025_form_sync_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "medical_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_medical_alerts_location_id", "medical_alerts", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_medical_alerts_location_id", table_name="medical_alerts")
    op.drop_table("medical_alerts")
