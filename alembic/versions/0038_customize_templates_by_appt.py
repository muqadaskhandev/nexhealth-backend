"""Customize templates by appointment type

Revision ID: 0038_customize_templates_by_appt
Revises: 0037_communication_templates
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_customize_templates_by_appt"
down_revision: Union[str, None] = "0037_communication_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "template_configurations",
        sa.Column(
            "customize_by_appointment_type",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.add_column(
        "communication_templates",
        sa.Column("appointment_type_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_comm_templates_appointment_type",
        "communication_templates",
        "appointment_type_defs",
        ["appointment_type_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_communication_templates_appointment_type_id",
        "communication_templates",
        ["appointment_type_id"],
    )

    # Replace location+slug uniqueness with default vs variant indexes
    op.drop_constraint("uq_comm_template_location_slug", "communication_templates", type_="unique")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_comm_template_default
        ON communication_templates (location_id, slug)
        WHERE appointment_type_id IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_comm_template_variant
        ON communication_templates (location_id, slug, appointment_type_id)
        WHERE appointment_type_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_comm_template_variant")
    op.execute("DROP INDEX IF EXISTS uq_comm_template_default")
    op.create_unique_constraint(
        "uq_comm_template_location_slug",
        "communication_templates",
        ["location_id", "slug"],
    )
    op.drop_index("ix_communication_templates_appointment_type_id", table_name="communication_templates")
    op.drop_constraint("fk_comm_templates_appointment_type", "communication_templates", type_="foreignkey")
    op.drop_column("communication_templates", "appointment_type_id")
    op.drop_column("template_configurations", "customize_by_appointment_type")
