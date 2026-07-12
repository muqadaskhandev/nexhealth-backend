"""Generic / other EHR adapter — real API calls only."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.models.practice import EhrSystem
from app.synchronizer._helpers import require_fields
from app.synchronizer.fetch import http_get_json, http_ping, parse_generic_patients
from app.synchronizer.types import ConnectionTestResult, EhrPatientRecord


class OtherEhrAdapter:
    ehr_system = EhrSystem.OTHER

    def required_fields(self, connection_mode: str) -> list[dict[str, str]]:
        if connection_mode == "on_prem":
            return [
                {"key": "agent_host", "label": "Connector URL", "type": "url"},
                {"key": "agent_token", "label": "Connector token", "type": "password"},
            ]
        return [
            {"key": "base_url", "label": "API base URL", "type": "url"},
            {"key": "api_key", "label": "API key", "type": "password"},
            {"key": "api_secret", "label": "API secret (optional)", "type": "password"},
        ]

    def validate_credentials(self, credentials: dict[str, Any], connection_mode: str) -> list[str]:
        if connection_mode == "on_prem":
            return require_fields(credentials, ["agent_host", "agent_token"])
        return require_fields(credentials, ["base_url", "api_key"])

    def _base(self, credentials: dict[str, Any], connection_mode: str) -> str:
        key = "agent_host" if connection_mode == "on_prem" else "base_url"
        return str(credentials[key]).rstrip("/")

    def _headers(self, credentials: dict[str, Any], connection_mode: str) -> dict[str, str]:
        if connection_mode == "on_prem":
            return {"Authorization": f"Bearer {credentials['agent_token']}"}
        headers = {"Authorization": f"Bearer {credentials['api_key']}"}
        if credentials.get("api_secret"):
            headers["X-Api-Secret"] = str(credentials["api_secret"])
        return headers

    async def test_connection(
        self, credentials: dict[str, Any], connection_mode: str
    ) -> ConnectionTestResult:
        errors = self.validate_credentials(credentials, connection_mode)
        if errors:
            return ConnectionTestResult(ok=False, message=errors[0])
        base = self._base(credentials, connection_mode)
        path = "/health" if connection_mode == "on_prem" else "/api/health"
        return await http_ping(f"{base}{path}", headers=self._headers(credentials, connection_mode))

    async def pull_patients(
        self,
        credentials: dict[str, Any],
        connection_mode: str,
        *,
        ehr_site_id: str,
        limit: int = 50,
    ) -> list[EhrPatientRecord]:
        base = self._base(credentials, connection_mode)
        headers = self._headers(credentials, connection_mode)
        query = urlencode({"site_id": ehr_site_id, "limit": limit})
        path = "/api/patients" if connection_mode == "on_prem" else "/api/v1/patients"
        status, payload = await http_get_json(f"{base}{path}?{query}", headers=headers)
        if status == 0 or status >= 400 or payload is None:
            raise ValueError(f"EHR patient fetch failed (HTTP {status})")
        patients = parse_generic_patients(payload)
        return [p for p in patients if p.first_name or p.last_name][:limit]
