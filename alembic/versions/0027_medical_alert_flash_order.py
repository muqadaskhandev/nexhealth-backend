"""Medical alerts: Flash Alert flag + manual sort order

Revision ID: 0027_medical_alert_flash_order
Revises: 0026_medical_alerts
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_medical_alert_flash_order"
down_revision: Union[str, None] = "0026_medical_alerts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("medical_alerts", sa.Column("flash", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("medical_alerts", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("medical_alerts", "sort_order")
    op.drop_column("medical_alerts", "flash")
