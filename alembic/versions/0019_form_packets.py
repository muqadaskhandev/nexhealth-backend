"""Form packets: bundle multiple forms to send together

Revision ID: 0019_form_packets
Revises: 0018_form_requests_expiration
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_form_packets"
down_revision: Union[str, None] = "0018_form_requests_expiration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "form_packets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("form_template_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_form_packets_location_id", "form_packets", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_form_packets_location_id", table_name="form_packets")
    op.drop_table("form_packets")
