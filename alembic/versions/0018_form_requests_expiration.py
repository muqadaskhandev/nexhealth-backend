"""Form requests: expiration date

Revision ID: 0018_form_requests_expiration
Revises: 0017_form_templates_archive
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_form_requests_expiration"
down_revision: Union[str, None] = "0017_form_templates_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_requests",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill any pre-existing rows (sent before requests had an expiration) to
    # the standard 7-day default measured from when they were sent.
    op.execute("UPDATE form_requests SET expires_at = sent_at + INTERVAL '7 days' WHERE expires_at IS NULL")
    op.alter_column("form_requests", "expires_at", nullable=False)


def downgrade() -> None:
    op.drop_column("form_requests", "expires_at")
