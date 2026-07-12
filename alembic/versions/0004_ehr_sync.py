"""EHR Synchronizer: connections, location mapping, patient external IDs

Revision ID: 0004_ehr_sync
Revises: 0003_staff
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_ehr_sync"
down_revision: Union[str, None] = "0003_staff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

connection_mode = postgresql.ENUM("api", "on_prem", name="connection_mode", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    connection_mode.create(bind, checkfirst=True)

    op.create_table(
        "ehr_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "ehr_system",
            postgresql.ENUM(
                "none",
                "open_dental",
                "dentrix",
                "athena",
                "eclinicalworks",
                "epic",
                "other",
                name="ehr_system",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("connection_mode", connection_mode, nullable=False, server_default="api"),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "credentials_hint",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("connector_installed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "ehr_sync_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "practice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("practices.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("patients_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.add_column("locations", sa.Column("ehr_site_id", sa.String(120), nullable=True))
    op.add_column("locations", sa.Column("ehr_site_name", sa.String(200), nullable=True))

    op.add_column("patients", sa.Column("ehr_patient_id", sa.String(120), nullable=True))
    op.create_index("ix_patients_ehr_patient_id", "patients", ["ehr_patient_id"])
    op.create_index(
        "uq_patients_practice_ehr_id",
        "patients",
        ["practice_id", "ehr_patient_id"],
        unique=True,
        postgresql_where=sa.text("ehr_patient_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_patients_practice_ehr_id", table_name="patients")
    op.drop_index("ix_patients_ehr_patient_id", table_name="patients")
    op.drop_column("patients", "ehr_patient_id")
    op.drop_column("locations", "ehr_site_name")
    op.drop_column("locations", "ehr_site_id")
    op.drop_table("ehr_sync_logs")
    op.drop_table("ehr_connections")
    connection_mode.drop(op.get_bind(), checkfirst=True)
