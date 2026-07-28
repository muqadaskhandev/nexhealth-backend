"""Family messaging settings on template configurations

Revision ID: 0039_family_messaging
Revises: 0038_customize_templates_by_appt
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039_family_messaging"
down_revision: Union[str, None] = "0038_customize_templates_by_appt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "template_configurations",
        sa.Column(
            "family_messaging_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "template_configurations",
        sa.Column(
            "use_family_messaging_for_reminders",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "template_configurations",
        sa.Column("family_messaging_age_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("template_configurations", "family_messaging_age_limit")
    op.drop_column("template_configurations", "use_family_messaging_for_reminders")
    op.drop_column("template_configurations", "family_messaging_enabled")
