"""Pydantic schemas for waitlist requests."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class WaitlistRequestSlotIn(BaseModel):
    provider_id: uuid.UUID
    operatory_id: uuid.UUID | None = None
    starts_at: datetime
    ends_at: datetime


class WaitlistRequestCreate(BaseModel):
    slots: list[WaitlistRequestSlotIn] = Field(min_length=1, max_length=10)
    patient_ids: list[uuid.UUID] = Field(min_length=1)
    template_type: str = Field(default="asap", pattern="^(asap|continuing_care)$")


class WaitlistRequestSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    operatory_id: uuid.UUID | None
    provider_name: str = ""
    operatory_name: str | None = None
    starts_at: datetime
    ends_at: datetime
    claimed_by_patient_id: uuid.UUID | None
    claimed_at: datetime | None
    created_appointment_id: uuid.UUID | None
    cancelled_at: datetime | None


class WaitlistPatientOut(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    name: str
    notified_at: datetime | None
    scheduled_notify_at: datetime | None = None


class WaitlistRequestOut(BaseModel):
    id: uuid.UUID
    status: str
    template_type: str = "asap"
    created_at: datetime
    sent_at: datetime
    slots: list[WaitlistRequestSlotOut]
    patients: list[WaitlistPatientOut]


class ClaimSlotRequest(BaseModel):
    patient_id: uuid.UUID


class PatientCandidateOut(BaseModel):
    id: uuid.UUID
    name: str
    reason: str
    appointment_at: datetime | None = None
    recall_type: str | None = None
    recall_due_date: date | None = None
    appointment_notes: str | None = None


class PublicWaitlistSlotOut(BaseModel):
    id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    provider_name: str
    operatory_name: str | None = None
    label: str


class PublicWaitlistOut(BaseModel):
    practice_name: str
    location_name: str
    patient_first_name: str
    slots: list[PublicWaitlistSlotOut]
    booking_redirect_slug: str = ""


class PublicWaitlistClaimOut(BaseModel):
    message: str
    appointment_id: uuid.UUID
    confirmation: str
