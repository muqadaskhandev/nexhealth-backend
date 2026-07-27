"""Custom online booking form fields and insurance list

Revision ID: 0011_booking_form
Revises: 0010_availability_blocks
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_booking_form"
down_revision: Union[str, None] = "0010_availability_blocks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

booking_field_type = postgresql.ENUM(
    "text", "note", "single_select", "multi_select", name="booking_field_type", create_type=False,
)


def upgrade() -> None:
    booking_field_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "locations",
        sa.Column("ask_for_insurance", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "booking_form_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_type", booking_field_type, nullable=False, server_default="text"),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("show_to", sa.String(20), nullable=False, server_default="all"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("note_text", sa.String(2000), nullable=False, server_default=""),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_booking_form_fields_practice_id", "booking_form_fields", ["practice_id"])
    op.create_index("ix_booking_form_fields_location_id", "booking_form_fields", ["location_id"])

    op.create_table(
        "booking_insurances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_booking_insurances_practice_id", "booking_insurances", ["practice_id"])
    op.create_index("ix_booking_insurances_location_id", "booking_insurances", ["location_id"])


def downgrade() -> None:
    op.drop_table("booking_insurances")
    op.drop_table("booking_form_fields")
    op.drop_column("locations", "ask_for_insurance")
    booking_field_type.drop(op.get_bind(), checkfirst=True)
