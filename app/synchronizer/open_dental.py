"""Open Dental EHR adapter — real API calls only.

Auth format (per Open Dental docs):
  Authorization: ODFHIR {DeveloperKey}/{CustomerKey}
  Base URL: https://api.opendental.com/api/v1/
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.config import settings
from app.models.practice import EhrSystem
from app.synchronizer._helpers import require_fields
from app.synchronizer.fetch import (
    http_get_json,
    http_ping,
    parse_generic_patients,
    parse_open_dental_patients,
)
from app.synchronizer.types import ConnectionTestResult, EhrPatientRecord

DEFAULT_BASE_URL = "https://api.opendental.com"


class OpenDentalAdapter:
    ehr_system = EhrSystem.OPEN_DENTAL

    def required_fields(self, connection_mode: str) -> list[dict[str, str]]:
        if connection_mode == "on_prem":
            return [
                {"key": "agent_host", "label": "On-prem agent URL", "type": "url"},
                {"key": "agent_token", "label": "Agent token", "type": "password"},
            ]
        return [
            {"key": "base_url", "label": "API base URL", "type": "url"},
            {"key": "developer_key", "label": "Developer API key (optional if set on server)", "type": "password"},
            {"key": "customer_key", "label": "Customer API key (per clinic)", "type": "password"},
        ]

    def validate_credentials(self, credentials: dict[str, Any], connection_mode: str) -> list[str]:
        if connection_mode == "on_prem":
            return require_fields(credentials, ["agent_host", "agent_token"])
        if not str(credentials.get("developer_key", "")).strip() and settings.open_dental_developer_key:
            credentials["developer_key"] = settings.open_dental_developer_key
        if not str(credentials.get("base_url", "")).strip():
            credentials["base_url"] = settings.open_dental_api_base_url or DEFAULT_BASE_URL
        return require_fields(credentials, ["developer_key", "customer_key"])

    def _headers(self, credentials: dict[str, Any], connection_mode: str) -> dict[str, str]:
        if connection_mode == "on_prem":
            return {"Authorization": f"Bearer {credentials['agent_token']}"}
        dev = str(credentials.get("developer_key") or settings.open_dental_developer_key).strip()
        cust = str(credentials["customer_key"]).strip()
        return {"Authorization": f"ODFHIR {dev}/{cust}"}

    def _base_url(self, credentials: dict[str, Any], connection_mode: str) -> str:
        if connection_mode == "on_prem":
            return str(credentials["agent_host"]).rstrip("/")
        base = str(credentials.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        if base.endswith("/api/v1"):
            return base
        if base.endswith("/api"):
            return f"{base}/v1"
        return f"{base}/api/v1"

    async def test_connection(
        self, credentials: dict[str, Any], connection_mode: str
    ) -> ConnectionTestResult:
        errors = self.validate_credentials(credentials, connection_mode)
        if errors:
            return ConnectionTestResult(ok=False, message=errors[0])
        base = self._base_url(credentials, connection_mode)
        path = "/patients?Limit=1" if connection_mode != "on_prem" else "/health"
        return await http_ping(f"{base}{path}", headers=self._headers(credentials, connection_mode))

    async def pull_patients(
        self,
        credentials: dict[str, Any],
        connection_mode: str,
        *,
        ehr_site_id: str,
        limit: int = 50,
    ) -> list[EhrPatientRecord]:
        base = self._base_url(credentials, connection_mode)
        headers = self._headers(credentials, connection_mode)
        if connection_mode == "on_prem":
            query = urlencode({"site_id": ehr_site_id, "limit": limit})
            status, payload = await http_get_json(f"{base}/api/patients?{query}", headers=headers)
        else:
            params: dict[str, str | int] = {"Limit": limit, "hideInactive": "true"}
            if ehr_site_id and ehr_site_id != "0":
                params["ClinicNum"] = ehr_site_id
            query = urlencode(params)
            status, payload = await http_get_json(f"{base}/patients?{query}", headers=headers)

        if status == 0 or status >= 400 or payload is None:
            raise ValueError(f"Open Dental patient fetch failed (HTTP {status})")

        patients = parse_open_dental_patients(payload, ehr_site_id=ehr_site_id)
        if not patients:
            patients = parse_generic_patients(payload)
        return [p for p in patients if p.first_name or p.last_name][:limit]
