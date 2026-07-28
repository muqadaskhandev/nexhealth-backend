"""Link form requests to the access token from the send batch

Revision ID: 0038_form_request_access_token
Revises: 0037_agent_intake
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_form_request_access_token"
down_revision: Union[str, None] = "0037_agent_intake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "form_requests",
        sa.Column("form_access_token_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_form_requests_form_access_token_id",
        "form_requests",
        "form_access_tokens",
        ["form_access_token_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_form_requests_form_access_token_id", "form_requests", ["form_access_token_id"])


def downgrade() -> None:
    op.drop_index("ix_form_requests_form_access_token_id", table_name="form_requests")
    op.drop_constraint("fk_form_requests_form_access_token_id", "form_requests", type_="foreignkey")
    op.drop_column("form_requests", "form_access_token_id")
