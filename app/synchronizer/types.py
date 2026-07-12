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
