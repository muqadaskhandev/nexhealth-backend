"""Add number type to booking_field_type enum

Revision ID: 0036_booking_field_number
Revises: 0035_form_procedure_codes
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0036_booking_field_number"
down_revision: Union[str, None] = "0035_form_procedure_codes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE booking_field_type ADD VALUE IF NOT EXISTS 'number'")


def downgrade() -> None:
    # Postgres does not support removing enum values.
    pass
