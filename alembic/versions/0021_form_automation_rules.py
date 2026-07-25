"""Form templates: automatic sending rules

Revision ID: 0021_form_automation_rules
Revises: 0020_form_expiration_settings
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_form_automation_rules"
down_revision: Union[str, None] = "0020_form_expiration_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("form_templates", sa.Column("send_automatically", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("form_templates", sa.Column("rule_patient_status", sa.String(20), nullable=False, server_default="any"))
    op.add_column("form_templates", sa.Column("rule_frequency_months", sa.Integer(), nullable=True))
    op.add_column("form_templates", sa.Column("rule_min_age", sa.Integer(), nullable=True))
    op.add_column("form_templates", sa.Column("rule_max_age", sa.Integer(), nullable=True))
    op.add_column("form_templates", sa.Column("rule_appointment_type_ids", postgresql.JSONB, nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("form_templates", "rule_appointment_type_ids")
    op.drop_column("form_templates", "rule_max_age")
    op.drop_column("form_templates", "rule_min_age")
    op.drop_column("form_templates", "rule_frequency_months")
    op.drop_column("form_templates", "rule_patient_status")
    op.drop_column("form_templates", "send_automatically")
