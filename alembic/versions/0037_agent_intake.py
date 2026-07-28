"""Conversational intake agent tables (Milestone 3)

Revision ID: 0037_agent_intake
Revises: 0036_booking_field_number
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_agent_intake"
down_revision: Union[str, None] = "0036_booking_field_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

agent_session_status = postgresql.ENUM(
    "in_progress", "completed", "abandoned", "emergency_stopped",
    name="agent_session_status", create_type=False,
)
agent_turn_role = postgresql.ENUM("patient", "agent", "system", name="agent_turn_role", create_type=False)
agent_answer_status = postgresql.ENUM("pending", "valid", "invalid", name="agent_answer_status", create_type=False)
agent_review_status = postgresql.ENUM("pending", "approved", "rejected", name="agent_review_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for e in (agent_session_status, agent_turn_role, agent_answer_status, agent_review_status):
        e.create(bind, checkfirst=True)

    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("practice_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("practices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("form_access_token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("form_access_tokens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("form_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("form_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("form_template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("form_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", agent_session_status, nullable=False, server_default="in_progress"),
        sa.Column("current_field_id", sa.String(80), nullable=True),
        sa.Column("draft_answers", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_sessions_practice_id", "agent_sessions", ["practice_id"])
    op.create_index("ix_agent_sessions_patient_id", "agent_sessions", ["patient_id"])
    op.create_index("ix_agent_sessions_form_request_id", "agent_sessions", ["form_request_id"])

    op.create_table(
        "agent_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", agent_turn_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("field_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_turns_session_id", "agent_turns", ["session_id"])

    op.create_table(
        "agent_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", sa.String(80), nullable=False),
        sa.Column("field_label", sa.String(400), nullable=False, server_default=""),
        sa.Column("sync_target", sa.String(80), nullable=True),
        sa.Column("raw_patient_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("parsed_value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", agent_answer_status, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_answers_session_id", "agent_answers", ["session_id"])

    op.create_table(
        "agent_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("form_submission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("form_submissions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", agent_review_status, nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_reviews_session_id", "agent_reviews", ["session_id"])

    op.create_table(
        "agent_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_agent_audit_logs_session_id", "agent_audit_logs", ["session_id"])

    op.add_column("form_submissions", sa.Column("intake_source", sa.String(20), nullable=False, server_default="web"))
    op.add_column("form_submissions", sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("form_submissions", sa.Column("agent_session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_form_submissions_agent_session_id",
        "form_submissions",
        "agent_sessions",
        ["agent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_form_submissions_agent_session_id", "form_submissions", type_="foreignkey")
    op.drop_column("form_submissions", "agent_session_id")
    op.drop_column("form_submissions", "ai_generated")
    op.drop_column("form_submissions", "intake_source")
    op.drop_table("agent_audit_logs")
    op.drop_table("agent_reviews")
    op.drop_table("agent_answers")
    op.drop_table("agent_turns")
    op.drop_table("agent_sessions")
    bind = op.get_bind()
    for name in ("agent_review_status", "agent_answer_status", "agent_turn_role", "agent_session_status"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
