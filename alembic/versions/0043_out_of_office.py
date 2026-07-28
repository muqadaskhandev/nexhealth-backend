"""Out-of-office reply settings for Messages

Revision ID: 0043_out_of_office
Revises: 0042_saved_responses
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_out_of_office"
down_revision: Union[str, None] = "0042_saved_responses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_MSG = (
    "Thank you for your text message. Our staff is unavailable and will reach out as soon as possible."
)


def upgrade() -> None:
    op.create_table(
        "out_of_office_settings",
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
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("auto_reply_message", sa.String(320), nullable=False, server_default=DEFAULT_MSG),
        sa.Column(
            "service_hours",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "custom_dates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "shared_location_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("location_id", name="uq_ooo_settings_location"),
    )
    op.create_index("ix_out_of_office_settings_practice_id", "out_of_office_settings", ["practice_id"])
    op.create_index("ix_out_of_office_settings_location_id", "out_of_office_settings", ["location_id"])

    op.add_column(
        "message_threads",
        sa.Column("last_ooo_reply_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("message_threads", "last_ooo_reply_at")
    op.drop_index("ix_out_of_office_settings_location_id", table_name="out_of_office_settings")
    op.drop_index("ix_out_of_office_settings_practice_id", table_name="out_of_office_settings")
    op.drop_table("out_of_office_settings")
