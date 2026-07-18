"""Auth request/response schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import AccountType, AuthProvider, UserRole
from app.schemas.location import LocationOut


def _normalize_login_email(value: str) -> str:
    email = value.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ValueError("invalid email address")
    return email


class LoginRequest(BaseModel):
    # Plain str — dev seed accounts may use reserved TLDs like `.local`.
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_login_email(value)


class TotpRequiredOut(BaseModel):
    totp_required: bool = True
    tx: str


class TotpSetupOut(BaseModel):
    secret: str
    provisioning_uri: str
    qr_message: str = "Scan this URI in Google Authenticator or Authy"


class TotpEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class TotpVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return _normalize_login_email(value)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    initials: str
    role: UserRole
    account_type: AccountType
    auth_provider: AuthProvider
    is_active: bool
    email_verified: bool
    totp_enabled: bool
    practice_id: uuid.UUID | None = None


class SessionOut(BaseModel):
    """The `/me` payload the SPA uses to render the shell."""

    user: UserOut
    active_location: LocationOut | None
    locations: list[LocationOut]


class MessageOut(BaseModel):
    message: str


class ProvidersOut(BaseModel):
    """Which SSO buttons the login page should show."""

    google: bool
    azure: bool
    okta: bool
