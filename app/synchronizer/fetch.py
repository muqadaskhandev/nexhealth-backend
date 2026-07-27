"""HTTP fetch + parsing helpers for real EHR API calls."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import httpx

from app.synchronizer.types import ConnectionTestResult, EhrPatientRecord


async def http_get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[int, str]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers or {})
        return resp.status_code, resp.text
    except httpx.HTTPError as exc:
        return 0, str(exc)


async def http_ping(url: str, headers: dict[str, str] | None = None) -> ConnectionTestResult:
    status, body = await http_get(url, headers=headers)
    if status == 0:
        return ConnectionTestResult(ok=False, message=f"Could not reach EHR: {body}")
    if status < 400:
        return ConnectionTestResult(ok=True, message=f"Connected (HTTP {status})")
    return ConnectionTestResult(ok=False, message=f"EHR returned HTTP {status}: {body[:200]}")


async def http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    status, text = await http_get(url, headers=headers)
    if status == 0 or status >= 400:
        return status, None
    try:
        import json

        return status, json.loads(text)
    except ValueError:
        return status, None


async def http_post_json(
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any, str]:
    """POST JSON; returns (status, parsed_json_or_None, raw_text)."""
    import json

    hdrs = {"Content-Type": "application/json", **(headers or {})}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.post(url, headers=hdrs, json=json_body)
        text = resp.text
        parsed: Any = None
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
        return resp.status_code, parsed, text
    except httpx.HTTPError as exc:
        return 0, None, str(exc)


async def http_put_json(
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any, str]:
    import json

    hdrs = {"Content-Type": "application/json", **(headers or {})}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.put(url, headers=hdrs, json=json_body)
        text = resp.text
        parsed: Any = None
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
        return resp.status_code, parsed, text
    except httpx.HTTPError as exc:
        return 0, None, str(exc)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _first(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_open_dental_patients(payload: Any, *, ehr_site_id: str) -> list[EhrPatientRecord]:
    rows = payload if isinstance(payload, list) else payload.get("patients", payload) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []

    out: list[EhrPatientRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        site = _first(row.get("ClinicNum"), row.get("clinic_num"), row.get("site_id"))
        if site and ehr_site_id and site != ehr_site_id:
            continue
        pat_id = _first(row.get("PatNum"), row.get("pat_num"), row.get("id"))
        if not pat_id:
            continue
        out.append(
            EhrPatientRecord(
                ehr_patient_id=str(pat_id),
                first_name=_first(row.get("FName"), row.get("first_name"), row.get("firstName")),
                last_name=_first(row.get("LName"), row.get("last_name"), row.get("lastName")),
                email=_first(row.get("Email"), row.get("email")),
                phone=_first(row.get("WirelessPhone"), row.get("HmPhone"), row.get("phone")),
                dob=_parse_date(row.get("Birthdate") or row.get("dob") or row.get("birthdate")),
                gender=_first(row.get("Gender"), row.get("gender")),
                address=_first(row.get("Address"), row.get("address")),
            )
        )
    return out


def parse_fhir_patients(payload: Any) -> list[EhrPatientRecord]:
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return []

    out: list[EhrPatientRecord] = []
    for entry in entries:
        resource = entry.get("resource", entry) if isinstance(entry, dict) else {}
        if not isinstance(resource, dict) or resource.get("resourceType") != "Patient":
            continue
        names = resource.get("name") or []
        first_name = last_name = ""
        if names and isinstance(names[0], dict):
            first_name = _first((names[0].get("given") or [""])[0])
            last_name = _first(names[0].get("family"))
        telecom = resource.get("telecom") or []
        email = phone = ""
        for item in telecom:
            if not isinstance(item, dict):
                continue
            if item.get("system") == "email":
                email = _first(item.get("value"))
            if item.get("system") == "phone":
                phone = _first(item.get("value"))
        out.append(
            EhrPatientRecord(
                ehr_patient_id=_first(resource.get("id")),
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                dob=_parse_date(resource.get("birthDate")),
                gender=_first(resource.get("gender")),
            )
        )
    return out


def parse_generic_patients(payload: Any, *, id_field: str = "id") -> list[EhrPatientRecord]:
    rows = payload if isinstance(payload, list) else payload.get("patients", payload.get("data", [])) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []

    out: list[EhrPatientRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pat_id = _first(row.get(id_field), row.get("patient_id"), row.get("PatNum"))
        if not pat_id:
            continue
        out.append(
            EhrPatientRecord(
                ehr_patient_id=str(pat_id),
                first_name=_first(row.get("first_name"), row.get("firstName"), row.get("FName")),
                last_name=_first(row.get("last_name"), row.get("lastName"), row.get("LName")),
                email=_first(row.get("email"), row.get("Email")),
                phone=_first(row.get("phone"), row.get("Phone"), row.get("WirelessPhone")),
                dob=_parse_date(row.get("dob") or row.get("birthdate") or row.get("Birthdate")),
                gender=_first(row.get("gender"), row.get("Gender")),
                address=_first(row.get("address"), row.get("Address")),
            )
        )
    return out


async def fetch_fhir_access_token(credentials: dict[str, Any]) -> str | None:
    if credentials.get("access_token"):
        return str(credentials["access_token"]).strip()
    base = str(credentials.get("fhir_base_url", "")).rstrip("/")
    client_id = credentials.get("client_id", "")
    client_secret = credentials.get("client_secret", "")
    if not base or not client_id or not client_secret:
        return None

    token_urls = [
        f"{base}/oauth2/token",
        f"{base}/Token",
        re.sub(r"/fhir.*$", "", base, flags=re.I) + "/oauth2/token",
    ]
    for token_url in dict.fromkeys(token_urls):
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(
                    token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if resp.status_code < 400:
                data = resp.json()
                token = data.get("access_token")
                if token:
                    return str(token)
        except httpx.HTTPError:
            continue
    return None
