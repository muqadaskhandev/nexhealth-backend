"""Appointment types, insertion rules, mapping rules

Revision ID: 0008_appointment_types
Revises: 0007_invite_role_locations
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_appointment_types"
down_revision: Union[str, None] = "0008_staff_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

patient_type_rule = postgresql.ENUM(
    "new", "existing", "all", name="patient_type_rule", create_type=False,
)


def upgrade() -> None:
    patient_type_rule.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "locations",
        sa.Column("separate_by_patient_type", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "locations",
        sa.Column("allow_cancellations_for_unmapped", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "appointment_type_defs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("available_online", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("patient_type", patient_type_rule, nullable=False, server_default="all"),
        sa.Column("allow_patient_cancel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_appointment_type_defs_practice_id", "appointment_type_defs", ["practice_id"])
    op.create_index("ix_appointment_type_defs_location_id", "appointment_type_defs", ["location_id"])

    op.create_table(
        "insertion_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("appointment_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("appointment_type_defs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_type", sa.String(80), nullable=False, server_default=""),
        sa.Column("codes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_insertion_rules_appointment_type_id", "insertion_rules", ["appointment_type_id"])

    op.create_table(
        "mapping_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_appointment_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("appointment_type_defs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mapping_rules_practice_id", "mapping_rules", ["practice_id"])
    op.create_index("ix_mapping_rules_location_id", "mapping_rules", ["location_id"])


def downgrade() -> None:
    op.drop_table("mapping_rules")
    op.drop_table("insertion_rules")
    op.drop_table("appointment_type_defs")
    op.drop_column("locations", "allow_cancellations_for_unmapped")
    op.drop_column("locations", "separate_by_patient_type")
    patient_type_rule.drop(op.get_bind(), checkfirst=True)
