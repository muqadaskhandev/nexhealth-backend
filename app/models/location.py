"""Location and user<->location membership models."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.practice import Practice
    from app.models.user import User


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    practice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    address_line2: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    zip_code: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ehr_site_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ehr_site_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    separate_by_patient_type: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_cancellations_for_unmapped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    set_availability_by_operatory: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ask_for_insurance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reserve_with_google: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    form_expiration_amount: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    form_expiration_unit: Mapped[str] = mapped_column(String(20), default="days", nullable=False)
    form_sync_mode: Mapped[str] = mapped_column(String(20), default="automatic", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    practice: Mapped["Practice | None"] = relationship(back_populates="locations")
    memberships: Mapped[list["UserLocation"]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )


class UserLocation(Base):
    """Join table: which locations a user may access.

    A user only ever sees the locations they are a member of, and can only
    switch their active session into one of these.
    """

    __tablename__ = "user_locations"
    __table_args__ = (
        UniqueConstraint("user_id", "location_id", name="uq_user_location"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    location: Mapped["Location"] = relationship(back_populates="memberships")
