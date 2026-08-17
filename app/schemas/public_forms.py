"""Pydantic schemas for the public (unauthenticated) patient forms flow."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class PublicTokenInfoOut(BaseModel):
    practice_name: str
    practice_logo_url: str | None
    location_name: str
    location_address: str
    location_phone: str


class PublicVerifyRequest(BaseModel):
    last_name: str = Field(min_length=1, max_length=120)
    dob: date


class PublicFormFieldOut(BaseModel):
    id: str
    type: str
    label: str
    required: bool
    options: list[str]
    page: int
    min_length: int | None = None
    max_length: int | None = None
    conditional_field_id: str | None = None
    conditional_value: str = ""


class MedicalAlertEntryOut(BaseModel):
    id: str
    label: str


class PublicFormOut(BaseModel):
    request_id: uuid.UUID
    template_id: uuid.UUID
    name: str
    display_type: str
    page_count: int
    fields: list[PublicFormFieldOut]
    completed: bool
    expires_at: datetime
    medical_alerts: dict[str, list[MedicalAlertEntryOut]] | None = None
    prefill_answers: dict[str, Any] = Field(default_factory=dict)


class PublicAppointmentOut(BaseModel):
    id: uuid.UUID
    starts_at: datetime
    provider_name: str
    appointment_type: str
    forms_status: str


class PublicVerifyOut(BaseModel):
    patient_name: str
    practice_name: str
    practice_logo_url: str | None
    location_name: str
    location_address: str
    location_phone: str
    forms: list[PublicFormOut]
    upcoming_appointment: PublicAppointmentOut | None = None


class PublicSubmitRequest(BaseModel):
    last_name: str = Field(min_length=1, max_length=120)
    dob: date
    form_request_id: uuid.UUID
    answers: dict[str, Any] = Field(default_factory=dict)


class PublicSubmitOut(BaseModel):
    remaining: int


class PublicPacketFormOut(BaseModel):
    template_id: uuid.UUID
    name: str
    display_type: str
    page_count: int
    fields: list[PublicFormFieldOut]
    medical_alerts: dict[str, list[MedicalAlertEntryOut]] | None = None


class PublicPacketInfoOut(BaseModel):
    packet_name: str
    practice_name: str
    practice_logo_url: str | None
    location_name: str
    location_address: str
    location_phone: str
    forms: list[PublicPacketFormOut]


class PublicPacketFormAnswers(BaseModel):
    template_id: uuid.UUID
    answers: dict[str, Any] = Field(default_factory=dict)


class PublicPacketSubmitRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    dob: date
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=320)
    submissions: list[PublicPacketFormAnswers] = Field(min_length=1)


class PublicPacketSubmitOut(BaseModel):
    submission_id: uuid.UUID
