"""Location contact fields + per-location logo

Revision ID: 0006_location_contact_logo
Revises: 0005_sso_totp_transactions
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0006_location_contact_logo"
down_revision: Union[str, None] = "0005_sso_totp_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "locations",
        sa.Column("address_line2", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "locations",
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "locations",
        sa.Column("state", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column(
        "locations",
        sa.Column("zip_code", sa.String(length=20), nullable=False, server_default=""),
    )
    op.add_column(
        "locations",
        sa.Column("phone", sa.String(length=40), nullable=False, server_default=""),
    )
    op.add_column(
        "locations",
        sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "locations",
        sa.Column("logo_url", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("locations", "logo_url")
    op.drop_column("locations", "email")
    op.drop_column("locations", "phone")
    op.drop_column("locations", "zip_code")
    op.drop_column("locations", "state")
    op.drop_column("locations", "city")
    op.drop_column("locations", "address_line2")
