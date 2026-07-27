"""Providers, operatories, and provider availability slots

Revision ID: 0009_providers_availability
Revises: 0008_appointment_types
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_providers_availability"
down_revision: Union[str, None] = "0008_appointment_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

provider_status = postgresql.ENUM(
    "active", "inactive", name="provider_status", create_type=False,
)
repeat_mode = postgresql.ENUM(
    "once", "weekly", name="repeat_mode", create_type=False,
)


def upgrade() -> None:
    provider_status.create(op.get_bind(), checkfirst=True)
    repeat_mode.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "locations",
        sa.Column("set_availability_by_operatory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", provider_status, nullable=False, server_default="active"),
        sa.Column("default_appointment_type_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("default_insurances", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_providers_practice_id", "providers", ["practice_id"])
    op.create_index("ix_providers_location_id", "providers", ["location_id"])

    op.create_table(
        "operatories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_operatories_practice_id", "operatories", ["practice_id"])
    op.create_index("ix_operatories_location_id", "operatories", ["location_id"])

    op.create_table(
        "availability_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operatory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operatories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("repeat_mode", repeat_mode, nullable=False, server_default="weekly"),
        sa.Column("specific_date", sa.Date(), nullable=True),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("use_provider_defaults", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("appointment_type_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_availability_slots_practice_id", "availability_slots", ["practice_id"])
    op.create_index("ix_availability_slots_location_id", "availability_slots", ["location_id"])
    op.create_index("ix_availability_slots_provider_id", "availability_slots", ["provider_id"])


def downgrade() -> None:
    op.drop_table("availability_slots")
    op.drop_table("operatories")
    op.drop_table("providers")
    op.drop_column("locations", "set_availability_by_operatory")
    repeat_mode.drop(op.get_bind(), checkfirst=True)
    provider_status.drop(op.get_bind(), checkfirst=True)
