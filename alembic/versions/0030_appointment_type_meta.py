"""Appointment type linkage and metadata for insertion/mapping rules.

Revision ID: 0030_appointment_type_meta
Revises: 0029_form_template_default
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_appointment_type_meta"
down_revision: Union[str, None] = "0029_form_template_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column(
            "appointment_type_def_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("appointment_type_defs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "appointments",
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_appointments_appointment_type_def_id", "appointments", ["appointment_type_def_id"])


def downgrade() -> None:
    op.drop_index("ix_appointments_appointment_type_def_id", table_name="appointments")
    op.drop_column("appointments", "meta")
    op.drop_column("appointments", "appointment_type_def_id")
