"""Link form requests to an appointment for intake/scheduling

Revision ID: 0049_form_request_appointment
Revises: 0048_review_responses
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049_form_request_appointment"
down_revision: Union[str, None] = "0048_review_responses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_requests",
        sa.Column("appointment_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_form_requests_appointment_id",
        "form_requests",
        "appointments",
        ["appointment_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_form_requests_appointment_id", "form_requests", ["appointment_id"])


def downgrade() -> None:
    op.drop_index("ix_form_requests_appointment_id", table_name="form_requests")
    op.drop_constraint("fk_form_requests_appointment_id", "form_requests", type_="foreignkey")
    op.drop_column("form_requests", "appointment_id")
