"""Push completed NexHealth forms into the linked EHR patient chart."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.credential_crypto import decrypt_credentials
from app.models.ehr_connection import EhrConnection, EhrSyncLog
from app.models.location import Location
from app.models.practice import EhrSystem, Practice
from app.models.staff import (
    ActivityType,
    FormRequest,
    FormRequestStatus,
    FormSubmission,
    FormTemplate,
    Patient,
    PatientActivity,
)
from app.synchronizer.registry import get_adapter
from app.synchronizer.types import FormChartPayload


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _log_activity(
    db: AsyncSession,
    *,
    patient_id: uuid.UUID,
    title: str,
    body: str = "",
    meta: dict | None = None,
) -> None:
    db.add(
        PatientActivity(
            patient_id=patient_id,
            activity_type=ActivityType.FORM,
            title=title,
            body=body,
            meta=meta or {},
        )
    )


async def _log_ehr(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    status: str,
    message: str,
) -> None:
    db.add(
        EhrSyncLog(
            practice_id=practice_id,
            action="form_sync",
            status=status,
            message=message[:2000],
            patients_imported=0,
        )
    )


async def _load_connection(db: AsyncSession, practice_id: uuid.UUID) -> EhrConnection | None:
    result = await db.execute(select(EhrConnection).where(EhrConnection.practice_id == practice_id))
    return result.scalar_one_or_none()


async def push_form_request_to_ehr(
    db: AsyncSession,
    req: FormRequest,
    patient: Patient,
    *,
    force: bool = False,
) -> str:
    """Attempt to sync one completed form request to the EHR chart.

    Returns the resulting sync_status: synced | pending | failed.
    """
    if req.status != FormRequestStatus.COMPLETED:
        return req.sync_status or "pending"

    if patient.archived:
        req.sync_status = "failed"
        await _log_activity(
            db,
            patient_id=patient.id,
            title="Form sync failed — patient archived",
            meta={"form_request_id": str(req.id)},
        )
        await db.flush()
        return "failed"

    location = await db.get(Location, req.location_id)
    sync_mode = location.form_sync_mode if location else "automatic"
    if sync_mode == "manual" and not force:
        req.sync_status = "pending"
        await db.flush()
        return "pending"

    if not settings.ehr_sync_enabled:
        req.sync_status = "pending"
        await _log_activity(
            db,
            patient_id=patient.id,
            title="Form sync pending — EHR sync is disabled for this environment",
            meta={"form_request_id": str(req.id)},
        )
        await db.flush()
        return "pending"

    if not patient.ehr_patient_id:
        req.sync_status = "failed"
        await _log_activity(
            db,
            patient_id=patient.id,
            title="Form sync failed — patient is not linked to an EHR chart",
            body="Import or link this patient from your health record, then use Sync now. Or Mark as synced if filed manually.",
            meta={"form_request_id": str(req.id), "reason": "missing_ehr_patient_id"},
        )
        await db.flush()
        return "failed"

    practice = await db.get(Practice, req.practice_id)
    if practice is None or practice.ehr_system == EhrSystem.NONE:
        req.sync_status = "failed"
        await _log_activity(
            db,
            patient_id=patient.id,
            title="Form sync failed — no EHR system configured",
            meta={"form_request_id": str(req.id)},
        )
        await db.flush()
        return "failed"

    conn = await _load_connection(db, req.practice_id)
    if conn is None or not conn.credentials_encrypted:
        req.sync_status = "failed"
        await _log_activity(
            db,
            patient_id=patient.id,
            title="Form sync failed — EHR credentials not configured",
            meta={"form_request_id": str(req.id)},
        )
        await db.flush()
        return "failed"

    result = await db.execute(
        select(FormSubmission)
        .where(FormSubmission.form_request_id == req.id)
        .order_by(FormSubmission.submitted_at.desc())
        .limit(1)
    )
    submission = result.scalar_one_or_none()
    tpl = await db.get(FormTemplate, req.form_template_id)
    form_name = (submission.form_name if submission else None) or (tpl.name if tpl else "Form")
    answers = submission.answers if submission else {}
    submitted_at = submission.submitted_at.isoformat() if submission and submission.submitted_at else _now().isoformat()

    payload = FormChartPayload(
        form_name=form_name,
        answers=answers if isinstance(answers, dict) else {},
        submitted_at_iso=submitted_at,
        patient_name=f"{patient.first_name} {patient.last_name}".strip(),
    )

    try:
        credentials = decrypt_credentials(conn.credentials_encrypted)
        adapter = get_adapter(conn.ehr_system or practice.ehr_system)
        push = await adapter.push_form_to_chart(
            credentials,
            conn.connection_mode.value,
            ehr_patient_id=str(patient.ehr_patient_id),
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 — surface any adapter/network failure as failed sync
        req.sync_status = "failed"
        msg = str(exc)[:500]
        await _log_ehr(db, practice_id=req.practice_id, status="error", message=msg)
        await _log_activity(
            db,
            patient_id=patient.id,
            title=f"Form sync failed — {form_name}",
            body=msg,
            meta={"form_request_id": str(req.id)},
        )
        await db.flush()
        return "failed"

    if push.ok:
        req.sync_status = "synced"
        req.synced_at = _now()
        await _log_ehr(
            db,
            practice_id=req.practice_id,
            status="ok",
            message=f"{form_name} → EHR patient {patient.ehr_patient_id}: {push.message}",
        )
        await _log_activity(
            db,
            patient_id=patient.id,
            title=f"Form synced to EHR chart — {form_name}",
            body=push.message,
            meta={
                "form_request_id": str(req.id),
                "ehr_patient_id": patient.ehr_patient_id,
                "external_id": push.external_id,
            },
        )
        await db.flush()
        return "synced"

    req.sync_status = "failed"
    await _log_ehr(db, practice_id=req.practice_id, status="error", message=push.message)
    await _log_activity(
        db,
        patient_id=patient.id,
        title=f"Form sync failed — {form_name}",
        body=push.message,
        meta={"form_request_id": str(req.id)},
    )
    await db.flush()
    return "failed"


async def apply_form_sync_outcome(
    db: AsyncSession,
    req: FormRequest,
    patient: Patient,
    *,
    force: bool = False,
) -> str:
    """Public entry used after form completion or staff Sync now."""
    return await push_form_request_to_ehr(db, req, patient, force=force)
