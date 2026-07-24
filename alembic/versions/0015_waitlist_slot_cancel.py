"""Waitlist request slots: per-slot cancellation

Revision ID: 0015_waitlist_slot_cancel
Revises: 0014_waitlist_requests
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_waitlist_slot_cancel"
down_revision: Union[str, None] = "0014_waitlist_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "waitlist_request_slots",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("waitlist_request_slots", "cancelled_at")
