"""Medical alerts: optional SNOMED CT code

Revision ID: 0028_medical_alert_snomed
Revises: 0027_medical_alert_flash_order
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_medical_alert_snomed"
down_revision: Union[str, None] = "0027_medical_alert_flash_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("medical_alerts", sa.Column("snomed_code", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("medical_alerts", "snomed_code")
