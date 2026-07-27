"""Pydantic schemas for staff workflow APIs."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.appointment_types import MappingFieldsIn


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
    appointment_type_def_id: uuid.UUID | None = None
    starts_at: datetime
    duration_minutes: int
    status: str
    insurance_status: str
    forms_status: str
    meta: dict[str, Any] = Field(default_factory=dict)
    patient_name: str = ""
    patient_initials: str = ""
    patient_dob: str | None = None
    patient_email: str = ""
    patient_phone: str = ""


class AppointmentCreate(BaseModel):
    patient_id: uuid.UUID
    provider_name: str
    appointment_type: str = "OP1"
    appointment_type_id: uuid.UUID | None = None
    mapping_fields: MappingFieldsIn | None = None
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


class AsapListOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    provider_name: str
    appointment_type: str
    starts_at: datetime
    duration_minutes: int
    notes: str = ""
    created_at: datetime


class AsapListCreate(BaseModel):
    patient_id: uuid.UUID
    appointment_id: uuid.UUID | None = None
    provider_name: str = ""
    appointment_type: str = ""
    appointment_type_id: uuid.UUID | None = None
    starts_at: datetime | None = None
    duration_minutes: int = 30
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


class MedicalAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    label: str
    active: bool
    flash: bool
    sort_order: int
    snomed_code: str | None = None


class MedicalAlertCreate(BaseModel):
    category: str
    label: str = Field(min_length=1, max_length=200)
    flash: bool = False
    snomed_code: str | None = Field(default=None, max_length=20)


class MedicalAlertUpdate(BaseModel):
    label: str | None = None
    active: bool | None = None
    flash: bool | None = None
    snomed_code: str | None = None


class MoveMedicalAlertRequest(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


class FormTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    form_type: str = ""
    display_type: str = "wizard"
    fields: list[FormFieldSchema] = Field(min_length=1)
    page_count: int = Field(default=1, ge=1)
    send_automatically: bool = False
    rule_patient_status: str = "any"
    rule_frequency_months: int | None = Field(default=None, ge=1)
    rule_min_age: int | None = Field(default=None, ge=0)
    rule_max_age: int | None = Field(default=None, ge=0)
    rule_appointment_type_ids: list[uuid.UUID] = Field(default_factory=list)


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
    archived_at: datetime | None
    send_automatically: bool
    rule_patient_status: str
    rule_frequency_months: int | None
    rule_min_age: int | None
    rule_max_age: int | None
    rule_appointment_type_ids: list[uuid.UUID]
    is_default: bool
    is_locked: bool = False
    created_at: datetime


class CopyFormTemplatesRequest(BaseModel):
    template_ids: list[uuid.UUID] = Field(min_length=1)
    location_ids: list[uuid.UUID] = Field(min_length=1)


class FormPacketCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    form_template_ids: list[uuid.UUID] = Field(min_length=1)


class FormPacketUpdate(FormPacketCreate):
    pass


class FormPacketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    form_template_ids: list[uuid.UUID]
    public_code: str | None
    created_at: datetime


class PublicPacketSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    form_packet_id: uuid.UUID
    packet_name: str = ""
    first_name: str
    last_name: str
    dob: date | None
    phone: str
    email: str
    form_names: list[str] = Field(default_factory=list)
    created_at: datetime


class AssignPublicPacketSubmissionRequest(BaseModel):
    patient_id: uuid.UUID


class FormRequestFormOut(BaseModel):
    id: uuid.UUID
    name: str


class FormRequestBatchOut(BaseModel):
    patient_id: uuid.UUID
    patient_name: str
    patient_initials: str
    request_ids: list[uuid.UUID]
    sent_at: datetime
    expires_at: datetime
    forms: list[FormRequestFormOut]
    status: str
    completed_status: str
    sync_status: str | None = None


class ReactivateFormRequestsRequest(BaseModel):
    request_ids: list[uuid.UUID] = Field(min_length=1)
    expires_at: datetime


class ArchiveFormRequestsRequest(BaseModel):
    request_ids: list[uuid.UUID] = Field(min_length=1)


class SyncFormRequestsRequest(BaseModel):
    request_ids: list[uuid.UUID] = Field(min_length=1)


class FormSubmissionDetailOut(BaseModel):
    form_name: str
    answers: dict[str, Any]
    submitted_at: datetime


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
    form_template_ids: list[uuid.UUID] = Field(min_length=1)
    expires_at: datetime | None = None
    message: str | None = None
    email_note: str | None = None


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
