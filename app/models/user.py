"""User model and related enums."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.location import UserLocation
    from app.models.practice import Practice
    from app.models.token import PasswordResetToken, RefreshToken


class UserRole(str, enum.Enum):
    """Practice-user roles. Admins can manage other users."""

    ADMIN = "admin"
    MEMBER = "member"


class AccountType(str, enum.Enum):
    """Platform vs practice-scoped accounts."""

    SUPER_ADMIN = "super_admin"
    PRACTICE = "practice"


class AuthProvider(str, enum.Enum):
    """How the account authenticates."""

    PASSWORD = "password"
    GOOGLE = "google"
    AZURE = "azure"
    OKTA = "okta"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    # Nullable because SSO-only users have no local password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    first_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    # values_callable makes SQLAlchemy persist the enum *values* (e.g. "admin")
    # rather than the member *names* ("ADMIN"), matching the Postgres enum.
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserRole.MEMBER,
    )
    account_type: Mapped[AccountType] = mapped_column(
        Enum(
            AccountType,
            name="account_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AccountType.PRACTICE,
    )
    practice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("practices.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    auth_provider: Mapped[AuthProvider] = mapped_column(
        Enum(
            AuthProvider,
            name="auth_provider",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AuthProvider.PASSWORD,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # TOTP 2FA (required for practice admins after first login)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Brute-force protection
    failed_login_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    practice: Mapped["Practice | None"] = relationship(back_populates="users")
    memberships: Mapped[list["UserLocation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def initials(self) -> str:
        fi = self.first_name[:1].upper() if self.first_name else ""
        li = self.last_name[:1].upper() if self.last_name else ""
        return (fi + li) or self.email[:2].upper()
