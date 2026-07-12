"""EHR Synchronizer: credentials, location mapping, test, and patient import."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.credential_crypto import decrypt_credentials, encrypt_credentials, mask_secret
from app.models.ehr_connection import ConnectionMode, EhrConnection, EhrSyncLog
from app.models.location import Location
from app.models.practice import EhrSystem, Practice, SyncStatus
from app.models.staff import Patient
from app.synchronizer.registry import get_adapter
from app.synchronizer.types import ConnectionTestResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_hint(credentials: dict[str, Any]) -> dict[str, str]:
    hint: dict[str, str] = {}
    for key, value in credentials.items():
        text = str(value)
        if "secret" in key or "token" in key or key.endswith("_key"):
            hint[key] = mask_secret(text)
        else:
            hint[key] = text
    return hint


async def get_connection(db: AsyncSession, practice_id: uuid.UUID) -> EhrConnection | None:
    result = await db.execute(
        select(EhrConnection).where(EhrConnection.practice_id == practice_id)
    )
    return result.scalar_one_or_none()


async def get_or_create_connection(
    db: AsyncSession, practice: Practice
) -> EhrConnection:
    conn = await get_connection(db, practice.id)
    if conn is None:
        conn = EhrConnection(
            practice_id=practice.id,
            ehr_system=practice.ehr_system,
        )
        db.add(conn)
        await db.flush()
    return conn


async def reset_connection_for_ehr_change(
    db: AsyncSession, practice: Practice, ehr_system: EhrSystem
) -> EhrConnection:
    conn = await get_or_create_connection(db, practice)
    conn.ehr_system = ehr_system
    conn.credentials_encrypted = None
    conn.credentials_hint = {}
    conn.connector_installed = False
    conn.last_tested_at = None
    conn.last_sync_at = None
    await db.flush()
    return conn


async def save_credentials(
    db: AsyncSession,
    practice: Practice,
    *,
    connection_mode: ConnectionMode,
    credentials: dict[str, str],
) -> EhrConnection:
    if practice.ehr_system == EhrSystem.NONE:
        raise ValueError("Select an EHR system before saving credentials")

    adapter = get_adapter(practice.ehr_system)
    conn = await get_or_create_connection(db, practice)

    merged = dict(credentials)
    if conn.credentials_encrypted:
        existing = decrypt_credentials(conn.credentials_encrypted)
        for key, value in existing.items():
            if not str(merged.get(key, "")).strip():
                merged[key] = value

    cleaned = {k: v.strip() for k, v in merged.items() if v and str(v).strip()}
    errors = adapter.validate_credentials(cleaned, connection_mode.value)
    if errors:
        raise ValueError(errors[0])

    conn.ehr_system = practice.ehr_system
    conn.connection_mode = connection_mode
    conn.credentials_encrypted = encrypt_credentials(cleaned)
    conn.credentials_hint = _build_hint(cleaned)
    conn.connector_installed = connection_mode == ConnectionMode.ON_PREM
    practice.sync_status = SyncStatus.PENDING
    practice.sync_error = None
    await db.flush()
    return conn


def _load_credentials(conn: EhrConnection) -> dict[str, Any]:
    if not conn.credentials_encrypted:
        raise ValueError("EHR credentials are not configured")
    return decrypt_credentials(conn.credentials_encrypted)


async def map_locations(
    db: AsyncSession,
    practice: Practice,
    mappings: list[dict[str, Any]],
) -> list[Location]:
    location_ids = {m["location_id"] for m in mappings}
    result = await db.execute(
        select(Location).where(
            Location.practice_id == practice.id,
            Location.id.in_(location_ids),
        )
    )
    locations = {loc.id: loc for loc in result.scalars().all()}
    if len(locations) != len(location_ids):
        raise ValueError("One or more locations do not belong to this practice")

    for mapping in mappings:
        loc = locations[mapping["location_id"]]
        loc.ehr_site_id = mapping["ehr_site_id"].strip()
        loc.ehr_site_name = (mapping.get("ehr_site_name") or "").strip() or None

    practice.sync_status = SyncStatus.PENDING
    await db.flush()
    return list(locations.values())


def _all_locations_mapped(locations: list[Location]) -> bool:
    return bool(locations) and all(loc.ehr_site_id for loc in locations)


async def _log_sync(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    action: str,
    status: str,
    message: str,
    patients_imported: int = 0,
) -> None:
    db.add(
        EhrSyncLog(
            practice_id=practice_id,
            action=action,
            status=status,
            message=message,
            patients_imported=patients_imported,
        )
    )


async def test_connection(
    db: AsyncSession, practice: Practice, locations: list[Location]
) -> ConnectionTestResult:
    if practice.ehr_system == EhrSystem.NONE:
        return ConnectionTestResult(ok=False, message="No EHR system selected")

    conn = await get_connection(db, practice.id)
    if conn is None or not conn.credentials_encrypted:
        return ConnectionTestResult(ok=False, message="Save EHR credentials first")

    if not _all_locations_mapped(locations):
        return ConnectionTestResult(
            ok=False, message="Map every practice location to an EHR site/office ID"
        )

    adapter = get_adapter(practice.ehr_system)
    credentials = _load_credentials(conn)
    result = await adapter.test_connection(credentials, conn.connection_mode.value)

    conn.last_tested_at = _now()
    if result.ok:
        practice.sync_status = SyncStatus.CONNECTED
        practice.sync_error = None
        conn.connector_installed = True
        status = "success"
    else:
        practice.sync_status = SyncStatus.ERROR
        practice.sync_error = result.message
        status = "error"

    await _log_sync(
        db,
        practice_id=practice.id,
        action="test_connection",
        status=status,
        message=result.message,
    )
    await db.flush()
    return result


async def run_initial_sync(
    db: AsyncSession, practice: Practice, locations: list[Location]
) -> tuple[int, int, str]:
    if practice.sync_status != SyncStatus.CONNECTED:
        raise ValueError("Test the EHR connection before running sync")

    conn = await get_connection(db, practice.id)
    if conn is None or not conn.credentials_encrypted:
        raise ValueError("EHR credentials are not configured")

    adapter = get_adapter(practice.ehr_system)
    credentials = _load_credentials(conn)

    imported = 0
    updated = 0
    errors: list[str] = []
    for location in locations:
        if not location.ehr_site_id:
            continue
        try:
            records = await adapter.pull_patients(
                credentials,
                conn.connection_mode.value,
                ehr_site_id=location.ehr_site_id,
            )
        except ValueError as exc:
            errors.append(f"{location.name}: {exc}")
            continue
        for record in records:
            existing = await db.execute(
                select(Patient).where(
                    Patient.practice_id == practice.id,
                    Patient.ehr_patient_id == record.ehr_patient_id,
                )
            )
            patient = existing.scalar_one_or_none()
            if patient is None:
                patient = Patient(
                    practice_id=practice.id,
                    location_id=location.id,
                    first_name=record.first_name,
                    last_name=record.last_name,
                    email=record.email,
                    phone=record.phone,
                    dob=record.dob,
                    gender=record.gender,
                    address=record.address,
                    ehr_patient_id=record.ehr_patient_id,
                    synced=True,
                    insurance_data={"status": "unverified", "name": "Unknown"},
                )
                db.add(patient)
                imported += 1
            else:
                patient.first_name = record.first_name
                patient.last_name = record.last_name
                patient.email = record.email
                patient.phone = record.phone
                patient.dob = record.dob
                patient.gender = record.gender
                patient.address = record.address
                patient.location_id = location.id
                patient.synced = True
                updated += 1

    if imported == 0 and updated == 0:
        if errors:
            raise ValueError("; ".join(errors))
        raise ValueError("No patients returned from EHR — check credentials, site IDs, and API access")

    conn.last_sync_at = _now()
    message = f"Imported {imported} patients, updated {updated}"
    if errors:
        message += f" (warnings: {'; '.join(errors)})"
    await _log_sync(
        db,
        practice_id=practice.id,
        action="initial_sync",
        status="success",
        message=message,
        patients_imported=imported,
    )
    await db.flush()
    return imported, updated, message


def connection_out(
    practice: Practice, conn: EhrConnection | None, locations: list[Location]
) -> dict[str, Any]:
    required_fields: list[dict[str, str]] = []
    if practice.ehr_system != EhrSystem.NONE:
        adapter = get_adapter(practice.ehr_system)
        mode = conn.connection_mode.value if conn else ConnectionMode.API.value
        required_fields = adapter.required_fields(mode)

    return {
        "ehr_system": practice.ehr_system,
        "connection_mode": conn.connection_mode if conn else ConnectionMode.API,
        "credentials_configured": bool(conn and conn.credentials_encrypted),
        "credentials_hint": conn.credentials_hint if conn else {},
        "connector_installed": bool(conn and conn.connector_installed),
        "last_tested_at": conn.last_tested_at if conn else None,
        "last_sync_at": conn.last_sync_at if conn else None,
        "sync_status": practice.sync_status,
        "sync_error": practice.sync_error,
        "required_fields": required_fields,
        "locations_mapped": sum(1 for loc in locations if loc.ehr_site_id),
        "locations_total": len(locations),
    }
