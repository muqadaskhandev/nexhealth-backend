"""Invite role + location_ids

Revision ID: 0007_invite_role_locations
Revises: 0006_location_contact_logo
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0007_invite_role_locations"
down_revision: Union[str, None] = "0006_location_contact_logo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invite_tokens",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
    )
    op.add_column(
        "invite_tokens",
        sa.Column(
            "location_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("invite_tokens", "location_ids")
    op.drop_column("invite_tokens", "role")
