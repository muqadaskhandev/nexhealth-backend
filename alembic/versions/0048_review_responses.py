"""Stub for Render DB revision 0048_review_responses

The production database was stamped at ``0048_review_responses`` (likely from
another branch/deploy), but that migration file is not in this repository.
This no-op revision exists so Alembic can locate the current DB version and
``alembic upgrade head`` succeeds.

Revision ID: 0048_review_responses
Revises: 0038_form_request_access_token
"""
from typing import Sequence, Union

revision: str = "0048_review_responses"
down_revision: Union[str, None] = "0038_form_request_access_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentionally empty — schema was already applied (or never needed here).
    pass


def downgrade() -> None:
    pass
