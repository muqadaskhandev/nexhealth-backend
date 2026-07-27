"""Availability blocks for providers

Revision ID: 0010_availability_blocks
Revises: 0009_providers_availability
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_availability_blocks"
down_revision: Union[str, None] = "0009_providers_availability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "availability_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operatory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operatories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_availability_blocks_practice_id", "availability_blocks", ["practice_id"])
    op.create_index("ix_availability_blocks_location_id", "availability_blocks", ["location_id"])
    op.create_index("ix_availability_blocks_provider_id", "availability_blocks", ["provider_id"])


def downgrade() -> None:
    op.drop_table("availability_blocks")
