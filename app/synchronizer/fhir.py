"""FHIR-based EHR adapter (Epic, athena, eClinicalWorks)."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.models.practice import EhrSystem
from app.synchronizer._helpers import require_fields
from app.synchronizer.fetch import (
    fetch_fhir_access_token,
    http_get_json,
    http_ping,
    parse_fhir_patients,
    parse_generic_patients,
)
from app.synchronizer.types import ConnectionTestResult, EhrPatientRecord


class FhirAdapter:
    def __init__(self, ehr_system: EhrSystem) -> None:
        self.ehr_system = ehr_system

    def required_fields(self, connection_mode: str) -> list[dict[str, str]]:
        if connection_mode == "on_prem":
            return [
                {"key": "agent_host", "label": "FHIR connector URL", "type": "url"},
                {"key": "agent_token", "label": "Connector token", "type": "password"},
            ]
        return [
            {"key": "fhir_base_url", "label": "FHIR base URL", "type": "url"},
            {"key": "client_id", "label": "Client ID", "type": "text"},
            {"key": "client_secret", "label": "Client secret", "type": "password"},
            {"key": "access_token", "label": "Access token (optional)", "type": "password"},
        ]

    def validate_credentials(self, credentials: dict[str, Any], connection_mode: str) -> list[str]:
        if connection_mode == "on_prem":
            return require_fields(credentials, ["agent_host", "agent_token"])
        errors = require_fields(credentials, ["fhir_base_url"])
        if not str(credentials.get("access_token", "")).strip():
            errors.extend(require_fields(credentials, ["client_id", "client_secret"]))
        return errors

    async def _auth_headers(self, credentials: dict[str, Any], connection_mode: str) -> dict[str, str]:
        if connection_mode == "on_prem":
            return {"Authorization": f"Bearer {credentials['agent_token']}"}
        token = await fetch_fhir_access_token(credentials)
        if not token:
            raise ValueError("Could not obtain FHIR access token — check client ID/secret or provide access_token")
        return {"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"}

    async def test_connection(
        self, credentials: dict[str, Any], connection_mode: str
    ) -> ConnectionTestResult:
        errors = self.validate_credentials(credentials, connection_mode)
        if errors:
            return ConnectionTestResult(ok=False, message=errors[0])
        if connection_mode == "on_prem":
            host = str(credentials["agent_host"]).rstrip("/")
            return await http_ping(f"{host}/health", headers={"Authorization": f"Bearer {credentials['agent_token']}"})
        base = str(credentials["fhir_base_url"]).rstrip("/")
        try:
            headers = await self._auth_headers(credentials, connection_mode)
        except ValueError as exc:
            return ConnectionTestResult(ok=False, message=str(exc))
        return await http_ping(f"{base}/metadata", headers=headers)

    async def pull_patients(
        self,
        credentials: dict[str, Any],
        connection_mode: str,
        *,
        ehr_site_id: str,
        limit: int = 50,
    ) -> list[EhrPatientRecord]:
        headers = await self._auth_headers(credentials, connection_mode)
        if connection_mode == "on_prem":
            host = str(credentials["agent_host"]).rstrip("/")
            query = urlencode({"site_id": ehr_site_id, "limit": limit})
            status, payload = await http_get_json(f"{host}/api/patients?{query}", headers=headers)
        else:
            base = str(credentials["fhir_base_url"]).rstrip("/")
            query = urlencode({"_count": limit})
            status, payload = await http_get_json(f"{base}/Patient?{query}", headers=headers)

        if status == 0 or status >= 400 or payload is None:
            raise ValueError(f"FHIR patient fetch failed (HTTP {status})")

        patients = parse_fhir_patients(payload)
        if not patients:
            patients = parse_generic_patients(payload)
        return [p for p in patients if p.first_name or p.last_name][:limit]
