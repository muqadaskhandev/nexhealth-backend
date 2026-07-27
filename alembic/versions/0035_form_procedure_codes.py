"""Form templates: procedure code automation rules

Revision ID: 0035_form_procedure_codes
Revises: 0034_waitlist_enhancements
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035_form_procedure_codes"
down_revision: Union[str, None] = "0034_waitlist_enhancements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_templates",
        sa.Column("rule_procedure_codes", postgresql.JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("form_templates", "rule_procedure_codes")
