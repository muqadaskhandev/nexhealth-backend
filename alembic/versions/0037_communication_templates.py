"""Communication templates + sending hours config

Revision ID: 0037_communication_templates
Revises: 0036_booking_field_number
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_communication_templates"
down_revision: Union[str, None] = "0036_booking_field_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

template_category = postgresql.ENUM(
    "appointment_journey",
    "daily",
    "post_appointment",
    "patient_based",
    "manual",
    name="template_category",
    create_type=False,
)
template_step_kind = postgresql.ENUM(
    "trigger",
    "email",
    "sms",
    "condition",
    name="template_step_kind",
    create_type=False,
)


def upgrade() -> None:
    template_category.create(op.get_bind(), checkfirst=True)
    template_step_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "communication_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", template_category, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("total_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("multi_location", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("location_id", "slug", name="uq_comm_template_location_slug"),
    )
    op.create_index("ix_communication_templates_practice_id", "communication_templates", ["practice_id"])
    op.create_index("ix_communication_templates_location_id", "communication_templates", ["location_id"])

    op.create_table(
        "communication_template_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("communication_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", template_step_kind, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("subtitle", sa.String(300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("timing_value", sa.Integer(), nullable=True),
        sa.Column("timing_unit", sa.String(40), nullable=True),
        sa.Column("condition_label", sa.String(200), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_communication_template_steps_template_id", "communication_template_steps", ["template_id"])

    op.create_table(
        "template_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sending_hours_start", sa.Time(), nullable=False, server_default="06:00:00"),
        sa.Column("sending_hours_end", sa.Time(), nullable=False, server_default="22:00:00"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("location_id", name="uq_template_config_location"),
    )
    op.create_index("ix_template_configurations_practice_id", "template_configurations", ["practice_id"])
    op.create_index("ix_template_configurations_location_id", "template_configurations", ["location_id"])


def downgrade() -> None:
    op.drop_table("template_configurations")
    op.drop_table("communication_template_steps")
    op.drop_table("communication_templates")
    template_step_kind.drop(op.get_bind(), checkfirst=True)
    template_category.drop(op.get_bind(), checkfirst=True)
