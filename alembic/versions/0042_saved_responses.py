"""Saved responses for Messages

Revision ID: 0042_saved_responses
Revises: 0041_message_thread_ux
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_saved_responses"
down_revision: Union[str, None] = "0041_message_thread_ux"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "saved_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "shared_location_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_saved_responses_practice_id", "saved_responses", ["practice_id"])
    op.create_index("ix_saved_responses_location_id", "saved_responses", ["location_id"])


def downgrade() -> None:
    op.drop_index("ix_saved_responses_location_id", table_name="saved_responses")
    op.drop_index("ix_saved_responses_practice_id", table_name="saved_responses")
    op.drop_table("saved_responses")
