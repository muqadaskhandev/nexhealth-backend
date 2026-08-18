"""Schemas for the public online booking portal."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class PublicBookingLocationOut(BaseModel):
    id: uuid.UUID
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone: str
    logo_url: str | None = None
    separate_by_patient_type: bool = True
    ask_for_insurance: bool = False


class PublicBookingInfoOut(BaseModel):
    practice_name: str
    practice_logo_url: str | None = None
    locations: list[PublicBookingLocationOut]
    separate_by_patient_type: bool = True
    payments_enabled: bool = False
    booking_redirect_url: str = ""


class PublicBookingInsuranceOut(BaseModel):
    id: uuid.UUID
    name: str


class PublicBookingTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    duration_minutes: int
    patient_type: str


class PublicBookingProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    avatar_url: str | None = None


class PublicBookingOpeningOut(BaseModel):
    date: str
    times: list[dict[str, Any]]


class PublicBookingFormFieldOut(BaseModel):
    id: uuid.UUID
    label: str
    field_type: str
    required: bool
    show_to: str
    options: list[str] = Field(default_factory=list)
    help_text: str = ""


class PublicBookRequest(BaseModel):
    location_id: uuid.UUID
    appointment_type_id: uuid.UUID
    provider_id: uuid.UUID
    starts_at: datetime
    patient_kind: str = Field(pattern="^(new|existing)$")
    booking_for: str = Field(default="self", pattern="^(self|child|other)$")
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr | str = ""
    phone: str = ""
    dob: date | None = None
    zip_code: str = ""
    gender: str = ""
    guarantor_first_name: str = ""
    guarantor_last_name: str = ""
    guarantor_email: EmailStr | str = ""
    guarantor_phone: str = ""
    call_text_consent: bool = False
    insurance_id: uuid.UUID | None = None
    utm_source: str = ""
    utm_medium: str = ""
    utm_campaign: str = ""
    form_answers: dict[str, Any] = Field(default_factory=dict)


class PublicBookOut(BaseModel):
    message: str
    appointment_id: uuid.UUID
    confirmation: str
    email_sent: bool = False
    email: str = ""
