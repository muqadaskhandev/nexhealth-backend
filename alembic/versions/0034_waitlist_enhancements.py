"""Waitlist booking tokens, template type, patient meta, scheduled notifications."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0034_waitlist_enhancements"
down_revision = "0033_google_reserve_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("meta", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "waitlist_requests",
        sa.Column("template_type", sa.String(length=40), nullable=False, server_default="asap"),
    )
    op.add_column(
        "waitlist_request_patients",
        sa.Column("booking_token", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "waitlist_request_patients",
        sa.Column("scheduled_notify_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE waitlist_request_patients SET booking_token = gen_random_uuid() WHERE booking_token IS NULL"
    )
    op.alter_column("waitlist_request_patients", "booking_token", nullable=False)
    op.create_index(
        "ix_waitlist_request_patients_booking_token",
        "waitlist_request_patients",
        ["booking_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_waitlist_request_patients_booking_token", table_name="waitlist_request_patients")
    op.drop_column("waitlist_request_patients", "scheduled_notify_at")
    op.drop_column("waitlist_request_patients", "booking_token")
    op.drop_column("waitlist_requests", "template_type")
    op.drop_column("patients", "meta")
