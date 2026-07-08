"""Auth request/response schemas."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import AuthProvider, UserRole
from app.schemas.location import LocationOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    first_name: str
    last_name: str
    full_name: str
    initials: str
    role: UserRole
    auth_provider: AuthProvider
    is_active: bool
    email_verified: bool


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
