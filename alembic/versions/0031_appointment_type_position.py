"""Add display order to appointment types."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_appointment_type_position"
down_revision = "0030_appointment_type_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "appointment_type_defs",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY location_id ORDER BY created_at, name
            ) - 1 AS pos
            FROM appointment_type_defs
        )
        UPDATE appointment_type_defs AS at
        SET position = ranked.pos
        FROM ranked
        WHERE at.id = ranked.id
        """
    )


def downgrade() -> None:
    op.drop_column("appointment_type_defs", "position")
