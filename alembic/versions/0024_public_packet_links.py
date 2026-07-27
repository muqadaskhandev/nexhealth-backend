"""Public packet links: shareable URL/embed + pending Assign & sync submissions

Revision ID: 0024_public_packet_links
Revises: 0023_form_public_access
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_public_packet_links"
down_revision: Union[str, None] = "0023_form_public_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("form_packets", sa.Column("public_code", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_form_packets_public_code", "form_packets", ["public_code"])
    op.create_index("ix_form_packets_public_code", "form_packets", ["public_code"])

    op.create_table(
        "public_packet_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("form_packet_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("form_packets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=False),
        sa.Column("dob", sa.Date(), nullable=True),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("email", sa.String(320), nullable=False, server_default=""),
        sa.Column("submissions", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("assigned_patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("public_packet_submissions")
    op.drop_index("ix_form_packets_public_code", table_name="form_packets")
    op.drop_constraint("uq_form_packets_public_code", "form_packets", type_="unique")
    op.drop_column("form_packets", "public_code")
