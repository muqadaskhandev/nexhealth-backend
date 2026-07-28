"""Message thread unread/archive and delivery status

Revision ID: 0041_message_thread_ux
Revises: 0040_template_send_history
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_message_thread_ux"
down_revision: Union[str, None] = "0040_template_send_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_threads",
        sa.Column("unread", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "message_threads",
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "messages",
        sa.Column("delivery_status", sa.String(20), nullable=False, server_default="delivered"),
    )
    op.add_column(
        "messages",
        sa.Column("failure_reason", sa.String(400), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("attachment_name", sa.String(300), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "attachment_name")
    op.drop_column("messages", "failure_reason")
    op.drop_column("messages", "delivery_status")
    op.drop_column("message_threads", "archived")
    op.drop_column("message_threads", "unread")
