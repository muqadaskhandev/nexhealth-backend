"""Form requests: viewed/sync tracking + location sync mode

Revision ID: 0025_form_sync_status
Revises: 0024_public_packet_links
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_form_sync_status"
down_revision: Union[str, None] = "0024_public_packet_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("form_requests", sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("form_requests", sa.Column("sync_status", sa.String(20), nullable=True))
    op.add_column("form_requests", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("locations", sa.Column("form_sync_mode", sa.String(20), nullable=False, server_default="automatic"))


def downgrade() -> None:
    op.drop_column("locations", "form_sync_mode")
    op.drop_column("form_requests", "synced_at")
    op.drop_column("form_requests", "sync_status")
    op.drop_column("form_requests", "viewed_at")
