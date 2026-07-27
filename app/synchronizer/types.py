"""EHR adapter types."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from app.models.practice import EhrSystem


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class EhrPatientRecord:
    ehr_patient_id: str
    first_name: str
    last_name: str
    email: str = ""
    phone: str = ""
    dob: date | None = None
    gender: str = ""
    address: str = ""


@dataclass(frozen=True)
class FormChartPayload:
    """Completed form content to attach to the patient chart in the EHR."""

    form_name: str
    answers: dict[str, Any]
    submitted_at_iso: str = ""
    patient_name: str = ""


@dataclass(frozen=True)
class FormPushResult:
    ok: bool
    message: str
    external_id: str = ""


class EhrAdapter(Protocol):
    ehr_system: EhrSystem

    def required_fields(self, connection_mode: str) -> list[dict[str, str]]:
        ...

    def validate_credentials(self, credentials: dict[str, Any], connection_mode: str) -> list[str]:
        ...

    async def test_connection(
        self, credentials: dict[str, Any], connection_mode: str
    ) -> ConnectionTestResult:
        ...

    async def pull_patients(
        self,
        credentials: dict[str, Any],
        connection_mode: str,
        *,
        ehr_site_id: str,
        limit: int = 50,
    ) -> list[EhrPatientRecord]:
        ...

    async def push_form_to_chart(
        self,
        credentials: dict[str, Any],
        connection_mode: str,
        *,
        ehr_patient_id: str,
        payload: FormChartPayload,
    ) -> FormPushResult:
        ...
