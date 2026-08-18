"""Custom online booking form fields and the practice's insurance list."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BookingFieldType(str, enum.Enum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    NOTE = "note"
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    PAYMENT = "payment"


class BookingFormField(Base):
    __tablename__ = "booking_form_fields"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    field_type: Mapped[BookingFieldType] = mapped_column(
        Enum(BookingFieldType, name="booking_field_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=BookingFieldType.TEXT,
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    show_to: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note_text: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    options: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BookingInsurance(Base):
    __tablename__ = "booking_insurances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
