"""Google Reserve with Google sync status fields on locations."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_google_reserve_status"
down_revision = "0032_booking_redirect"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "locations",
        sa.Column("google_reserve_status", sa.String(length=20), nullable=False, server_default="inactive"),
    )
    op.add_column(
        "locations",
        sa.Column("google_reserve_message", sa.String(length=500), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("locations", "google_reserve_message")
    op.drop_column("locations", "google_reserve_status")
