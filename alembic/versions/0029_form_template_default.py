"""Form templates: Default flag (for Medical History forms with multiple templates)

Revision ID: 0029_form_template_default
Revises: 0028_medical_alert_snomed
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_form_template_default"
down_revision: Union[str, None] = "0028_medical_alert_snomed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("form_templates", sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("form_templates", "is_default")
