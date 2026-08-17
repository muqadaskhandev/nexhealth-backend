"""Public agent API schemas."""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.public_forms import PublicAppointmentOut


class AgentVerifyRequest(BaseModel):
    last_name: str = Field(min_length=1)
    dob: str  # ISO date YYYY-MM-DD


class AgentSessionStartRequest(BaseModel):
    last_name: str = Field(min_length=1)
    dob: str
    form_request_id: uuid.UUID
    session_id: uuid.UUID | None = None


class AgentMessageRequest(BaseModel):
    last_name: str = Field(min_length=1)
    dob: str
    session_id: uuid.UUID
    message: str = Field(min_length=1, max_length=4000)
    structured_value: Any | None = None


class AgentCompleteRequest(BaseModel):
    last_name: str = Field(min_length=1)
    dob: str
    session_id: uuid.UUID


class AgentTurnOut(BaseModel):
    role: str
    content: str
    field_id: str | None = None
    created_at: str


class AgentFieldOut(BaseModel):
    id: str
    type: str
    label: str
    required: bool = False
    options: list[str] = Field(default_factory=list)
    placeholder: str = ""


class AgentProgressOut(BaseModel):
    answered: int
    total: int


class AgentReviewItemOut(BaseModel):
    field_id: str
    label: str
    type: str = "text"
    value: Any = None


class AgentSessionOut(BaseModel):
    session_id: uuid.UUID
    status: str
    form_request_id: uuid.UUID
    form_name: str
    patient_name: str
    assistant_message: str | None = None
    turns: list[AgentTurnOut] = Field(default_factory=list)
    draft_answers: dict[str, Any] = Field(default_factory=dict)
    progress: AgentProgressOut
    done: bool = False
    validation_status: str | None = None
    current_field: AgentFieldOut | None = None
    medical_alerts: dict[str, list[dict]] | None = None
    upcoming_appointment: PublicAppointmentOut | None = None
    review_items: list[AgentReviewItemOut] = Field(default_factory=list)


class AgentAnswerDetailOut(BaseModel):
    field_id: str
    field_label: str
    raw_patient_text: str
    parsed_value: Any = None
    ai_generated: bool
    status: str
    sync_target: str | None = None


class AgentSessionDetailOut(BaseModel):
    session_id: uuid.UUID
    status: str
    form_request_id: uuid.UUID
    form_name: str = ""
    patient_name: str = ""
    intake_source: str = "agent"
    turns: list[AgentTurnOut] = Field(default_factory=list)
    answers: list[AgentAnswerDetailOut] = Field(default_factory=list)
    draft_answers: dict[str, Any] = Field(default_factory=dict)
    progress: AgentProgressOut | None = None


class AgentCompleteOut(BaseModel):
    remaining: int
    message: str = "Your intake has been submitted. Thank you!"
    upcoming_appointment: PublicAppointmentOut | None = None
    forms_complete_for_visit: bool = False


class AgentUploadOut(BaseModel):
    url: str
    filename: str
