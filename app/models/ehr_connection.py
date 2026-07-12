"""EHR Synchronizer connection and sync audit models."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.practice import EhrSystem

if TYPE_CHECKING:
    from app.models.practice import Practice


class ConnectionMode(str, enum.Enum):
    API = "api"
    ON_PREM = "on_prem"


class EhrConnection(Base):
    """Per-practice EHR connector credentials and sync metadata."""

    __tablename__ = "ehr_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    ehr_system: Mapped[EhrSystem] = mapped_column(
        Enum(EhrSystem, name="ehr_system", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    connection_mode: Mapped[ConnectionMode] = mapped_column(
        Enum(
            ConnectionMode,
            name="connection_mode",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ConnectionMode.API,
    )
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_hint: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    connector_installed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    practice: Mapped["Practice"] = relationship(back_populates="ehr_connection")


class EhrSyncLog(Base):
    __tablename__ = "ehr_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    patients_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
