"""Add date type to booking_field_type enum

Revision ID: 0050_booking_field_date
Revises: 0049_form_request_appointment
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0050_booking_field_date"
down_revision: Union[str, None] = "0049_form_request_appointment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE booking_field_type ADD VALUE IF NOT EXISTS 'date'")


def downgrade() -> None:
    # Postgres does not support removing enum values.
    pass
