"""Waitlist requests: slots + candidate patients

Revision ID: 0014_waitlist_requests
Revises: 0013_reserve_with_google
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_waitlist_requests"
down_revision: Union[str, None] = "0013_reserve_with_google"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

waitlist_request_status = postgresql.ENUM(
    "sent", "cancelled", name="waitlist_request_status", create_type=False,
)


def upgrade() -> None:
    waitlist_request_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "waitlist_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", waitlist_request_status, nullable=False, server_default="sent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_waitlist_requests_practice_id", "waitlist_requests", ["practice_id"])
    op.create_index("ix_waitlist_requests_location_id", "waitlist_requests", ["location_id"])

    op.create_table(
        "waitlist_request_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("waitlist_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("waitlist_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operatory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("operatories.id", ondelete="CASCADE"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by_patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_appointment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_waitlist_request_slots_waitlist_request_id", "waitlist_request_slots", ["waitlist_request_id"])

    op.create_table(
        "waitlist_request_patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("waitlist_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("waitlist_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_waitlist_request_patients_waitlist_request_id", "waitlist_request_patients", ["waitlist_request_id"])
    op.create_index("ix_waitlist_request_patients_patient_id", "waitlist_request_patients", ["patient_id"])


def downgrade() -> None:
    op.drop_table("waitlist_request_patients")
    op.drop_table("waitlist_request_slots")
    op.drop_table("waitlist_requests")
    waitlist_request_status.drop(op.get_bind(), checkfirst=True)
