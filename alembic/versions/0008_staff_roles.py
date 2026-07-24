"""Add provider, front_desk, and billing to user_role enum.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op

revision = "0008_staff_roles"
down_revision = "0007_invite_role_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block on some Postgres versions;
    # use IF NOT EXISTS (PG 9.1+/15+) so re-runs are safe.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'provider'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'front_desk'")
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'billing'")


def downgrade() -> None:
    # Postgres cannot remove enum values safely; leave them in place.
    pass
