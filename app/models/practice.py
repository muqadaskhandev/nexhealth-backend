"""Practice (clinic tenant) model and related enums."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.ehr_connection import EhrConnection
    from app.models.location import Location
    from app.models.user import User


class SubscriptionPlan(str, enum.Enum):
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class EhrSystem(str, enum.Enum):
    NONE = "none"
    OPEN_DENTAL = "open_dental"
    DENTRIX = "dentrix"
    ATHENA = "athena"
    ECLINICALWORKS = "eclinicalworks"
    EPIC = "epic"
    OTHER = "other"


class SyncStatus(str, enum.Enum):
    NOT_CONNECTED = "not_connected"
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"


DEFAULT_PRODUCTS = {
    "scheduling": True,
    "forms": True,
    "communications": True,
    "payments": False,
    "verification": False,
}


class Practice(Base):
    __tablename__ = "practices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    address: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    zip_code: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    subscription_plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(
            SubscriptionPlan,
            name="subscription_plan",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SubscriptionPlan.STARTER,
    )
    enabled_products: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=DEFAULT_PRODUCTS
    )

    ehr_system: Mapped[EhrSystem] = mapped_column(
        Enum(EhrSystem, name="ehr_system", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=EhrSystem.NONE,
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(
            SyncStatus,
            name="sync_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=SyncStatus.NOT_CONNECTED,
    )
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    locations: Mapped[list["Location"]] = relationship(back_populates="practice")
    users: Mapped[list["User"]] = relationship(back_populates="practice")
    ehr_connection: Mapped["EhrConnection | None"] = relationship(
        back_populates="practice", uselist=False
    )
