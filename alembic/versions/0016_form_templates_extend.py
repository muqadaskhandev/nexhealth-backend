"""Form templates: location scoping, builder fields, digitize support

Revision ID: 0016_form_templates_extend
Revises: 0015_waitlist_slot_cancel
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_form_templates_extend"
down_revision: Union[str, None] = "0015_waitlist_slot_cancel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_templates",
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=True),
    )
    # Backfill any pre-existing rows (created before forms were location-scoped) to
    # their practice's first location, then lock the column down.
    op.execute(
        """
        UPDATE form_templates
        SET location_id = (
            SELECT id FROM locations
            WHERE locations.practice_id = form_templates.practice_id
            ORDER BY id LIMIT 1
        )
        WHERE location_id IS NULL
        """
    )
    op.alter_column("form_templates", "location_id", nullable=False)
    op.create_index("ix_form_templates_location_id", "form_templates", ["location_id"])
    op.alter_column("form_templates", "form_type", server_default="")
    op.add_column("form_templates", sa.Column("source", sa.String(20), nullable=False, server_default="build"))
    op.add_column("form_templates", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
    op.add_column("form_templates", sa.Column("display_type", sa.String(20), nullable=False, server_default="wizard"))
    op.add_column("form_templates", sa.Column("fields", postgresql.JSONB, nullable=False, server_default="[]"))
    op.add_column("form_templates", sa.Column("page_count", sa.Integer, nullable=False, server_default="1"))
    op.add_column("form_templates", sa.Column("uploaded_file_url", sa.String, nullable=True))
    op.add_column("form_templates", sa.Column("digitize_notes", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("form_templates", "digitize_notes")
    op.drop_column("form_templates", "uploaded_file_url")
    op.drop_column("form_templates", "page_count")
    op.drop_column("form_templates", "fields")
    op.drop_column("form_templates", "display_type")
    op.drop_column("form_templates", "status")
    op.drop_column("form_templates", "source")
    op.drop_index("ix_form_templates_location_id", table_name="form_templates")
    op.drop_column("form_templates", "location_id")
