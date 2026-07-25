"""Form templates: archive support

Revision ID: 0017_form_templates_archive
Revises: 0016_form_templates_extend
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_form_templates_archive"
down_revision: Union[str, None] = "0016_form_templates_extend"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_templates",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("form_templates", "archived_at")
