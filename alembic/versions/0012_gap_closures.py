"""Provider avatar/duration overrides + payment booking field type

Revision ID: 0012_gap_closures
Revises: 0011_booking_form
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_gap_closures"
down_revision: Union[str, None] = "0011_booking_form"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "providers",
        sa.Column("appointment_type_durations", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column("providers", sa.Column("avatar_url", sa.String(500), nullable=True))

    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in Postgres.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE booking_field_type ADD VALUE IF NOT EXISTS 'payment'")


def downgrade() -> None:
    op.drop_column("providers", "avatar_url")
    op.drop_column("providers", "appointment_type_durations")
    # Postgres does not support removing an enum value; leaving 'payment' in
    # place on downgrade is intentional (matches how other enum columns in
    # this codebase are downgraded by dropping the whole type only when the
    # migration created it).
