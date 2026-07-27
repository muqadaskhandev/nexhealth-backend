"""Locations: default manual form-request expiration settings

Revision ID: 0020_form_expiration_settings
Revises: 0019_form_packets
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_form_expiration_settings"
down_revision: Union[str, None] = "0019_form_packets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("form_expiration_amount", sa.Integer(), nullable=False, server_default="7"))
    op.add_column("locations", sa.Column("form_expiration_unit", sa.String(20), nullable=False, server_default="days"))


def downgrade() -> None:
    op.drop_column("locations", "form_expiration_unit")
    op.drop_column("locations", "form_expiration_amount")
