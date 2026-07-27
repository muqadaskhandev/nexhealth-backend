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
from app.synchronizer._helpers import format_form_answers_text, require_fields
from app.synchronizer.fetch import (
    http_get_json,
    http_ping,
    http_post_json,
    http_put_json,
    parse_generic_patients,
    parse_open_dental_patients,
)
from app.synchronizer.types import ConnectionTestResult, EhrPatientRecord, FormChartPayload, FormPushResult

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

    async def push_form_to_chart(
        self,
        credentials: dict[str, Any],
        connection_mode: str,
        *,
        ehr_patient_id: str,
        payload: FormChartPayload,
    ) -> FormPushResult:
        """Attach completed form as a document; fall back to PatientNotes Medical append."""
        import base64
        from datetime import datetime, timezone

        errors = self.validate_credentials(credentials, connection_mode)
        if errors:
            return FormPushResult(ok=False, message=errors[0])

        pat_num = str(ehr_patient_id).strip()
        if not pat_num:
            return FormPushResult(ok=False, message="Missing EHR patient id (PatNum)")

        base = self._base_url(credentials, connection_mode)
        headers = self._headers(credentials, connection_mode)
        body_text = format_form_answers_text(payload)
        description = f"NexHealth — {payload.form_name}"[:200]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        if connection_mode == "on_prem":
            status, parsed, raw = await http_post_json(
                f"{base}/api/documents/upload",
                json_body={
                    "PatNum": pat_num,
                    "Description": description,
                    "extension": ".txt",
                    "rawBase64": base64.b64encode(body_text.encode("utf-8")).decode("ascii"),
                    "ImgType": "Document",
                    "DateCreated": now,
                },
                headers=headers,
            )
        else:
            status, parsed, raw = await http_post_json(
                f"{base}/documents/Upload",
                json_body={
                    "PatNum": int(pat_num) if pat_num.isdigit() else pat_num,
                    "Description": description,
                    "extension": ".txt",
                    "rawBase64": base64.b64encode(body_text.encode("utf-8")).decode("ascii"),
                    "ImgType": "Document",
                    "DateCreated": now,
                },
                headers=headers,
            )

        if 200 <= status < 300:
            external_id = ""
            if isinstance(parsed, dict):
                external_id = str(parsed.get("DocNum") or parsed.get("id") or "")
            elif parsed is not None:
                external_id = str(parsed)
            return FormPushResult(
                ok=True,
                message="Form uploaded to Open Dental Documents",
                external_id=external_id,
            )

        # Fallback: append to PatientNotes.Medical
        note_block = f"\n\n--- {description} ({now} UTC) ---\n{body_text}"
        existing_medical = ""
        get_status, note_payload = await http_get_json(f"{base}/patientnotes/{pat_num}", headers=headers)
        if get_status < 400 and isinstance(note_payload, dict):
            existing_medical = str(note_payload.get("Medical") or "")

        put_status, _, put_raw = await http_put_json(
            f"{base}/patientnotes/{pat_num}",
            json_body={"Medical": (existing_medical + note_block).strip()},
            headers=headers,
        )
        if 200 <= put_status < 300:
            return FormPushResult(
                ok=True,
                message="Form appended to Open Dental PatientNotes.Medical (document upload unavailable)",
                external_id=pat_num,
            )

        detail = (raw or put_raw or "")[:240]
        return FormPushResult(
            ok=False,
            message=f"Open Dental form push failed (documents HTTP {status}, notes HTTP {put_status}): {detail}",
        )
