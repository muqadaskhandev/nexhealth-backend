"""Add post-booking redirect URL on practices."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_booking_redirect"
down_revision = "0031_appointment_type_position"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "practices",
        sa.Column("booking_redirect_url", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("practices", "booking_redirect_url")
