"""Reserve with Google location toggle

Revision ID: 0013_reserve_with_google
Revises: 0012_gap_closures
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_reserve_with_google"
down_revision: Union[str, None] = "0012_gap_closures"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "locations",
        sa.Column("reserve_with_google", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("locations", "reserve_with_google")
