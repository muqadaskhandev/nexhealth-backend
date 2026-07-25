"""Form requests: archive support (e.g. patient filled out paper forms instead)

Revision ID: 0022_form_requests_archive
Revises: 0021_form_automation_rules
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_form_requests_archive"
down_revision: Union[str, None] = "0021_form_automation_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("form_requests", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("form_requests", "archived_at")
