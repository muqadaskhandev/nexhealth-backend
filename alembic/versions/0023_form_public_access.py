"""Public patient forms access: access tokens + captured submission answers

Revision ID: 0023_form_public_access
Revises: 0022_form_requests_archive
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_form_public_access"
down_revision: Union[str, None] = "0022_form_requests_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_submissions",
        sa.Column("answers", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_table(
        "form_access_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint("uq_form_access_tokens_token_hash", "form_access_tokens", ["token_hash"])
    op.create_index("ix_form_access_tokens_token_hash", "form_access_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_form_access_tokens_token_hash", table_name="form_access_tokens")
    op.drop_constraint("uq_form_access_tokens_token_hash", "form_access_tokens", type_="unique")
    op.drop_table("form_access_tokens")
    op.drop_column("form_submissions", "answers")
