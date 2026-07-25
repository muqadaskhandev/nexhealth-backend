"""Pydantic schemas for staff workflow APIs."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    preferred_name: str | None
    dob: date | None
    gender: str
    email: str
    phone: str
    address: str
    language: str
    provider_name: str
    synced: bool
    archived: bool
    insurance_data: dict[str, Any]
    notification_prefs: dict[str, Any]
    initials: str = ""
    full_name: str = ""


class PatientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    preferred_name: str | None = None
    dob: date | None = None
    gender: str = ""
    email: EmailStr | str = ""
    phone: str = ""
    address: str = ""
    language: str = "English"
    provider_name: str = ""
    insurance_data: dict[str, Any] | None = None
    notification_prefs: dict[str, Any] | None = None


class PatientUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    preferred_name: str | None = None
    dob: date | None = None
    gender: str | None = None
    email: EmailStr | str | None = None
    phone: str | None = None
    address: str | None = None
    language: str | None = None
    provider_name: str | None = None
    synced: bool | None = None
    archived: bool | None = None
    insurance_data: dict[str, Any] | None = None
    notification_prefs: dict[str, Any] | None = None


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_type: str
    title: str
    body: str
    meta: dict[str, Any]
    created_at: datetime


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    provider_name: str
    appointment_type: str
    starts_at: datetime
    duration_minutes: int
    status: str
    insurance_status: str
    forms_status: str
    patient_name: str = ""
    patient_initials: str = ""
    patient_dob: str | None = None
    patient_email: str = ""
    patient_phone: str = ""


class AppointmentCreate(BaseModel):
    patient_id: uuid.UUID
    provider_name: str
    appointment_type: str = "OP1"
    starts_at: datetime
    duration_minutes: int = 30
    status: str = "unconfirmed"


class AppointmentUpdate(BaseModel):
    status: str | None = None
    insurance_status: str | None = None
    forms_status: str | None = None
    starts_at: datetime | None = None
    duration_minutes: int | None = None


class WaitlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    provider_name: str
    appointment_type: str
    notes: str
    status: str
    patient_name: str = ""
    created_at: datetime


class WaitlistCreate(BaseModel):
    patient_id: uuid.UUID
    provider_name: str = ""
    appointment_type: str = ""
    notes: str = ""


class FormFieldSchema(BaseModel):
    id: str
    type: str
    label: str
    required: bool = False
    options: list[str] = Field(default_factory=list)
    page: int = 1
    min_length: int | None = None
    max_length: int | None = None
    conditional_field_id: str | None = None
    conditional_value: str = ""


class FormTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    form_type: str = ""
    display_type: str = "wizard"
    fields: list[FormFieldSchema] = Field(min_length=1)
    page_count: int = Field(default=1, ge=1)


class FormTemplateUpdate(FormTemplateCreate):
    pass


class FormTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    form_type: str
    source: str
    status: str
    display_type: str
    fields: list[FormFieldSchema]
    page_count: int
    uploaded_file_url: str | None
    digitize_notes: str
    created_at: datetime


class CopyFormTemplatesRequest(BaseModel):
    template_ids: list[uuid.UUID] = Field(min_length=1)
    location_ids: list[uuid.UUID] = Field(min_length=1)


class FormSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    form_name: str
    device: str
    sync_status: str
    submitted_at: datetime
    patient_name: str = ""
    patient_initials: str = ""


class SendFormRequest(BaseModel):
    patient_id: uuid.UUID
    form_template_id: uuid.UUID


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    direction: str
    body: str
    channel: str
    sent_at: datetime
    patient_id: uuid.UUID | None = None
    patient_name: str = ""


class SendMessageRequest(BaseModel):
    patient_id: uuid.UUID
    body: str = Field(min_length=1, max_length=2000)
    channel: str = "sms"


class PaymentLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    amount: Decimal
    description: str
    status: str
    created_at: datetime
    paid_at: datetime | None
    patient_name: str = ""


class PaymentLinkCreate(BaseModel):
    patient_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    description: str = ""


class VerifyInsuranceRequest(BaseModel):
    patient_id: uuid.UUID


class DashboardStats(BaseModel):
    appointments_today: int
    confirmed_count: int
    waitlist_count: int
    pending_forms: int
    pending_payments: int
