"""Staff workflow API — patients, scheduling, forms, comms, payments, verification."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_admin
from app.core.staff_context import StaffContext, get_staff_context
from app.database import get_db
from app.models.user import User
from app.schemas.staff import (
    ActivityOut,
    AppointmentCreate,
    AppointmentOut,
    AppointmentUpdate,
    DashboardStats,
    LocationActivityOut,
    FormSubmissionOut,
    CopyFormTemplatesRequest,
    FormPacketCreate,
    FormPacketOut,
    FormPacketUpdate,
    FormRequestBatchOut,
    FormSubmissionDetailOut,
    FormTemplateCreate,
    FormTemplateOut,
    FormTemplateUpdate,
    MedicalAlertCreate,
    MedicalAlertOut,
    MedicalAlertUpdate,
    MessageOut,
    MessageThreadOut,
    MessageThreadUpdate,
    MoveMedicalAlertRequest,
    PatientCreate,
    PatientOut,
    PatientUpdate,
    PaymentLinkCreate,
    PaymentLinkOut,
    ArchiveFormRequestsRequest,
    AssignPublicPacketSubmissionRequest,
    PublicPacketSubmissionOut,
    ReactivateFormRequestsRequest,
    SendFormRequest,
    SendMessageRequest,
    SyncFormRequestsRequest,
    VerifyInsuranceRequest,
    AsapListCreate,
    AsapListOut,
    WaitlistCreate,
    WaitlistOut,
)
from app.services import asap_list_service, staff_service

router = APIRouter(tags=["staff"])


def _patient_out(p) -> PatientOut:
    out = PatientOut.model_validate(p)
    fi = p.first_name[:1].upper() if p.first_name else ""
    li = p.last_name[:1].upper() if p.last_name else ""
    return out.model_copy(
        update={
            "initials": (fi + li) or "??",
            "full_name": f"{p.first_name} {p.last_name}".strip(),
        }
    )


async def _form_template_out(db: AsyncSession, tpl) -> FormTemplateOut:
    locked = await staff_service.is_form_template_locked(db, tpl)
    return FormTemplateOut.model_validate(tpl).model_copy(update={"is_locked": locked})


def _appt_out(appt, patient) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        patient_id=appt.patient_id,
        provider_name=appt.provider_name,
        appointment_type=appt.appointment_type,
        appointment_type_def_id=appt.appointment_type_def_id,
        starts_at=appt.starts_at,
        duration_minutes=appt.duration_minutes,
        status=appt.status.value,
        insurance_status=appt.insurance_status.value,
        forms_status=appt.forms_status.value,
        meta=appt.meta or {},
        patient_name=f"{patient.first_name} {patient.last_name}",
        patient_initials=f"{patient.first_name[:1]}{patient.last_name[:1]}".upper(),
        patient_dob=patient.dob.isoformat() if patient.dob else None,
        patient_email=patient.email,
        patient_phone=patient.phone,
    )


# ── Dashboard ────────────────────────────────────────────────────────────────
@router.get("/api/dashboard/stats", response_model=DashboardStats)
async def stats(
    start_date: str | None = Query(default=None, description="YYYY-MM-DD range start"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD range end"),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    start_day = end_day = None
    if start_date or end_date:
        start = datetime.fromisoformat(start_date) if start_date else datetime.fromisoformat(end_date)  # type: ignore[arg-type]
        end = datetime.fromisoformat(end_date) if end_date else start
        start_day, end_day = start, end
    return DashboardStats(**await staff_service.dashboard_stats(db, ctx, start_day=start_day, end_day=end_day))


@router.get("/api/activity", response_model=list[LocationActivityOut])
async def location_activity(
    limit: int = 75,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    """Recent activity for patients at the active location."""
    rows = await staff_service.list_location_activity(db, ctx, limit=min(max(limit, 1), 200))
    return [
        LocationActivityOut(
            id=activity.id,
            patient_id=patient.id,
            patient_name=f"{patient.first_name} {patient.last_name}".strip(),
            activity_type=activity.activity_type.value
            if hasattr(activity.activity_type, "value")
            else str(activity.activity_type),
            title=activity.title,
            body=activity.body or "",
            created_at=activity.created_at,
        )
        for activity, patient in rows
    ]


# ── Patients ─────────────────────────────────────────────────────────────────
@router.get("/api/patients", response_model=list[PatientOut])
async def list_patients(
    q: str = "",
    archived: bool = False,
    all_locations: bool = False,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await staff_service.list_patients(db, ctx, q=q, archived=archived, all_locations=all_locations)
    return [_patient_out(p) for p in rows]


@router.get("/api/patients/duplicates")
async def duplicate_patients(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    groups = await staff_service.find_duplicate_patients(db, ctx)
    return [[_patient_out(p) for p in g] for g in groups]


@router.get("/api/patients/{patient_id}", response_model=PatientOut)
async def get_patient(
    patient_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    p = await staff_service.get_patient(db, ctx, patient_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return _patient_out(p)


@router.get("/api/patients/{patient_id}/activity", response_model=list[ActivityOut])
async def patient_activity(
    patient_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    p = await staff_service.get_patient(db, ctx, patient_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    rows = await staff_service.list_patient_activity(db, patient_id)
    return [ActivityOut.model_validate(a) for a in rows]


@router.post("/api/patients", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
async def create_patient(
    payload: PatientCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    p = await staff_service.create_patient(db, ctx, payload)
    await db.commit()
    return _patient_out(p)


@router.patch("/api/patients/{patient_id}", response_model=PatientOut)
async def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    p = await staff_service.get_patient(db, ctx, patient_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Patient not found")
    p = await staff_service.update_patient(db, ctx, p, payload)
    await db.commit()
    return _patient_out(p)


@router.post("/api/patients/merge", response_model=PatientOut)
async def merge_patients(
    keep_id: uuid.UUID,
    merge_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        p = await staff_service.merge_patients(db, ctx, keep_id=keep_id, merge_id=merge_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    await db.commit()
    return _patient_out(p)


# ── Scheduling ─────────────────────────────────────────────────────────────────
@router.get("/api/appointments", response_model=list[AppointmentOut])
async def list_appointments(
    date: str | None = Query(default=None, description="YYYY-MM-DD (single day)"),
    start_date: str | None = Query(default=None, description="YYYY-MM-DD range start"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD range end"),
    patient_id: uuid.UUID | None = Query(default=None),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    if patient_id:
        rows = await staff_service.list_appointments(db, ctx, patient_id=patient_id)
    elif start_date or end_date:
        start = datetime.fromisoformat(start_date) if start_date else datetime.fromisoformat(end_date)  # type: ignore[arg-type]
        end = datetime.fromisoformat(end_date) if end_date else start
        rows = await staff_service.list_appointments(db, ctx, start_day=start, end_day=end)
    elif date:
        rows = await staff_service.list_appointments(db, ctx, day=datetime.fromisoformat(date))
    else:
        rows = await staff_service.list_appointments(db, ctx)
    return [_appt_out(a, p) for a, p in rows]


@router.post("/api/appointments", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    payload: AppointmentCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        appt = await staff_service.create_appointment(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    patient = await staff_service.get_patient(db, ctx, appt.patient_id)
    await db.commit()
    return _appt_out(appt, patient)


@router.patch("/api/appointments/{appt_id}", response_model=AppointmentOut)
async def update_appointment(
    appt_id: uuid.UUID,
    payload: AppointmentUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    appt = await staff_service.update_appointment(db, ctx, appt_id, payload)
    if appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    patient = await staff_service.get_patient(db, ctx, appt.patient_id)
    await db.commit()
    return _appt_out(appt, patient)


@router.get("/api/waitlist", response_model=list[WaitlistOut])
async def list_waitlist(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_waitlist(db, ctx)
    return [
        WaitlistOut(
            id=e.id,
            patient_id=e.patient_id,
            provider_name=e.provider_name,
            appointment_type=e.appointment_type,
            notes=e.notes,
            status=e.status.value,
            patient_name=f"{p.first_name} {p.last_name}",
            created_at=e.created_at,
        )
        for e, p in rows
    ]


@router.post("/api/waitlist", response_model=WaitlistOut, status_code=status.HTTP_201_CREATED)
async def add_waitlist(
    payload: WaitlistCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    entry = await staff_service.add_waitlist(db, ctx, payload)
    patient = await staff_service.get_patient(db, ctx, entry.patient_id)
    await db.commit()
    return WaitlistOut(
        id=entry.id,
        patient_id=entry.patient_id,
        provider_name=entry.provider_name,
        appointment_type=entry.appointment_type,
        notes=entry.notes,
        status=entry.status.value,
        patient_name=f"{patient.first_name} {patient.last_name}" if patient else "",
        created_at=entry.created_at,
    )


@router.delete("/api/waitlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_waitlist_entry(
    entry_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    entry = await staff_service.remove_waitlist(db, ctx, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Waitlist entry not found")
    await db.commit()


@router.get("/api/asap-list", response_model=list[AsapListOut])
async def list_asap(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await asap_list_service.list_asap(db, ctx)
    return [
        AsapListOut(
            id=appt.id,
            patient_id=patient.id,
            patient_name=f"{patient.first_name} {patient.last_name}".strip(),
            provider_name=appt.provider_name,
            appointment_type=appt.appointment_type,
            starts_at=appt.starts_at,
            duration_minutes=appt.duration_minutes,
            notes=str((appt.meta or {}).get("asap_notes", "") or ""),
            created_at=appt.created_at,
        )
        for appt, patient in rows
    ]


@router.post("/api/asap-list", response_model=AsapListOut, status_code=status.HTTP_201_CREATED)
async def add_to_asap(
    payload: AsapListCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        appt = await asap_list_service.add_to_asap(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    patient = await staff_service.get_patient(db, ctx, appt.patient_id)
    await db.commit()
    return AsapListOut(
        id=appt.id,
        patient_id=appt.patient_id,
        patient_name=f"{patient.first_name} {patient.last_name}".strip() if patient else "",
        provider_name=appt.provider_name,
        appointment_type=appt.appointment_type,
        starts_at=appt.starts_at,
        duration_minutes=appt.duration_minutes,
        notes=str((appt.meta or {}).get("asap_notes", "") or ""),
        created_at=appt.created_at,
    )


@router.delete("/api/asap-list/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_asap(
    appointment_id: uuid.UUID,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    appt = await asap_list_service.remove_from_asap(db, ctx, appointment_id)
    if appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ASAP entry not found")
    await db.commit()


# ── Medical alerts ───────────────────────────────────────────────────────────
@router.get("/api/medical-alerts", response_model=list[MedicalAlertOut])
async def medical_alerts(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_medical_alerts(db, ctx)
    return [MedicalAlertOut.model_validate(a) for a in rows]


@router.post("/api/medical-alerts", response_model=MedicalAlertOut, status_code=status.HTTP_201_CREATED)
async def create_medical_alert(
    payload: MedicalAlertCreate,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        alert = await staff_service.create_medical_alert(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return MedicalAlertOut.model_validate(alert)


@router.patch("/api/medical-alerts/{alert_id}", response_model=MedicalAlertOut)
async def update_medical_alert(
    alert_id: uuid.UUID,
    payload: MedicalAlertUpdate,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        alert = await staff_service.update_medical_alert(db, ctx, alert_id, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return MedicalAlertOut.model_validate(alert)


@router.delete("/api/medical-alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_medical_alert(
    alert_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await staff_service.delete_medical_alert(db, ctx, alert_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()


@router.post("/api/medical-alerts/{alert_id}/move")
async def move_medical_alert(
    alert_id: uuid.UUID,
    payload: MoveMedicalAlertRequest,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await staff_service.move_medical_alert(db, ctx, alert_id, payload.direction)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"message": "Moved"}


# ── Forms ────────────────────────────────────────────────────────────────────
@router.get("/api/forms/templates", response_model=list[FormTemplateOut])
async def form_templates(
    archived: bool = Query(default=False),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await staff_service.list_form_templates(db, ctx, archived=archived)
    return [await _form_template_out(db, t) for t in rows]


@router.get("/api/forms/templates/frequent", response_model=list[FormTemplateOut])
async def frequent_form_templates(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_frequent_form_templates(db, ctx)
    return [await _form_template_out(db, t) for t in rows]


@router.post("/api/forms/templates", response_model=FormTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_form_template(
    payload: FormTemplateCreate,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        tpl = await staff_service.create_form_template(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return await _form_template_out(db, tpl)


@router.patch("/api/forms/templates/{template_id}", response_model=FormTemplateOut)
async def update_form_template(
    template_id: uuid.UUID,
    payload: FormTemplateUpdate,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    tpl = await staff_service.get_form_template(db, ctx, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Form template not found")
    try:
        tpl = await staff_service.update_form_template(db, tpl, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return await _form_template_out(db, tpl)


@router.post("/api/forms/templates/digitize", response_model=FormTemplateOut, status_code=status.HTTP_201_CREATED)
async def digitize_form_template(
    file: UploadFile = File(...),
    name: str = Form(...),
    notes: str = Form(default=""),
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        tpl = await staff_service.create_digitized_form_template(db, ctx, name, notes, file)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return await _form_template_out(db, tpl)


@router.post("/api/forms/templates/copy", status_code=status.HTTP_200_OK)
async def copy_form_templates(
    payload: CopyFormTemplatesRequest,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await staff_service.copy_form_templates(
            db, ctx, payload.template_ids, payload.packet_ids, payload.location_ids
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return result


@router.post("/api/forms/templates/{template_id}/duplicate", response_model=FormTemplateOut, status_code=status.HTTP_201_CREATED)
async def duplicate_form_template(
    template_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    tpl = await staff_service.get_form_template(db, ctx, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Form template not found")
    copy = await staff_service.duplicate_form_template(db, ctx, tpl)
    await db.commit()
    return await _form_template_out(db, copy)


@router.post("/api/forms/templates/{template_id}/archive", response_model=FormTemplateOut)
async def archive_form_template(
    template_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    tpl = await staff_service.get_form_template(db, ctx, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Form template not found")
    tpl = await staff_service.archive_form_template(db, tpl)
    await db.commit()
    return await _form_template_out(db, tpl)


@router.post("/api/forms/templates/{template_id}/unarchive", response_model=FormTemplateOut)
async def unarchive_form_template(
    template_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    tpl = await staff_service.get_form_template(db, ctx, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Form template not found")
    tpl = await staff_service.unarchive_form_template(db, tpl)
    await db.commit()
    return await _form_template_out(db, tpl)


@router.post("/api/forms/templates/{template_id}/set-default", response_model=FormTemplateOut)
async def set_default_form_template(
    template_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    tpl = await staff_service.get_form_template(db, ctx, template_id)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Form template not found")
    try:
        await staff_service.set_default_form_template(db, ctx, tpl)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return await _form_template_out(db, tpl)


@router.get("/api/forms/packets", response_model=list[FormPacketOut])
async def form_packets(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_form_packets(db, ctx)
    return [FormPacketOut.model_validate(p) for p in rows]


@router.post("/api/forms/packets", response_model=FormPacketOut, status_code=status.HTTP_201_CREATED)
async def create_form_packet(
    payload: FormPacketCreate,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        packet = await staff_service.create_form_packet(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return FormPacketOut.model_validate(packet)


@router.patch("/api/forms/packets/{packet_id}", response_model=FormPacketOut)
async def update_form_packet(
    packet_id: uuid.UUID,
    payload: FormPacketUpdate,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    packet = await staff_service.get_form_packet(db, ctx, packet_id)
    if packet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Packet not found")
    try:
        packet = await staff_service.update_form_packet(db, packet, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return FormPacketOut.model_validate(packet)


@router.delete("/api/forms/packets/{packet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form_packet(
    packet_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    packet = await staff_service.get_form_packet(db, ctx, packet_id)
    if packet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Packet not found")
    await staff_service.delete_form_packet(db, packet)
    await db.commit()


@router.post("/api/forms/packets/{packet_id}/duplicate", response_model=FormPacketOut, status_code=status.HTTP_201_CREATED)
async def duplicate_form_packet(
    packet_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    packet = await staff_service.get_form_packet(db, ctx, packet_id)
    if packet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Packet not found")
    copy = await staff_service.duplicate_form_packet(db, ctx, packet)
    await db.commit()
    return FormPacketOut.model_validate(copy)


@router.post("/api/forms/packets/{packet_id}/public-access", response_model=FormPacketOut)
async def enable_packet_public_access(
    packet_id: uuid.UUID,
    _: User = Depends(require_admin),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    packet = await staff_service.get_form_packet(db, ctx, packet_id)
    if packet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Packet not found")
    packet = await staff_service.enable_packet_public_access(db, packet)
    await db.commit()
    return FormPacketOut.model_validate(packet)


@router.get("/api/forms/public-submissions", response_model=list[PublicPacketSubmissionOut])
async def public_packet_submissions(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_public_packet_submissions(db, ctx)
    return [PublicPacketSubmissionOut(**row) for row in rows]


@router.post("/api/forms/public-submissions/{submission_id}/assign")
async def assign_public_packet_submission(
    submission_id: uuid.UUID,
    payload: AssignPublicPacketSubmissionRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await staff_service.assign_public_packet_submission(db, ctx, submission_id, payload.patient_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"message": "Submission assigned"}


@router.get("/api/forms/submissions", response_model=list[FormSubmissionOut])
async def form_submissions(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_form_submissions(db, ctx)
    return [
        FormSubmissionOut(
            id=s.id,
            patient_id=s.patient_id,
            form_name=s.form_name,
            device=s.device,
            sync_status=s.sync_status,
            submitted_at=s.submitted_at,
            patient_name=f"{p.first_name} {p.last_name}",
            patient_initials=f"{p.first_name[:1]}{p.last_name[:1]}".upper(),
        )
        for s, p in rows
    ]


@router.post("/api/forms/send", status_code=status.HTTP_201_CREATED)
async def send_form(
    payload: SendFormRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        requests = await staff_service.send_form(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"message": "Form(s) sent to patient", "count": len(requests)}


@router.get("/api/forms/requests", response_model=list[FormRequestBatchOut])
async def form_requests(
    tab: str = Query(default="all"),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    if tab not in {"active", "expired", "synced", "deleted", "all"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid tab")
    rows = await staff_service.list_form_request_batches(db, ctx, tab=tab)
    return [FormRequestBatchOut(**r) for r in rows]


@router.post("/api/forms/requests/reactivate")
async def reactivate_form_requests(
    payload: ReactivateFormRequestsRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await staff_service.reactivate_form_requests(db, ctx, payload.request_ids, payload.expires_at)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"message": "Form request moved to active"}


@router.post("/api/forms/requests/archive")
async def archive_form_requests(
    payload: ArchiveFormRequestsRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await staff_service.archive_form_requests(db, ctx, payload.request_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"message": "Form request archived"}


@router.post("/api/forms/requests/sync")
async def sync_form_requests(
    payload: SyncFormRequestsRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await staff_service.sync_form_requests(db, ctx, payload.request_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"message": "Sync attempted"}


@router.post("/api/forms/requests/mark-synced")
async def mark_synced_form_requests(
    payload: SyncFormRequestsRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        await staff_service.mark_synced_form_requests(db, ctx, payload.request_ids)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return {"message": "Marked as synced"}


@router.get("/api/forms/requests/submissions", response_model=list[FormSubmissionDetailOut])
async def form_request_submissions(
    request_ids: list[uuid.UUID] = Query(default=[]),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await staff_service.get_form_request_submissions(db, ctx, request_ids)
    return [FormSubmissionDetailOut(form_name=r.form_name, answers=r.answers, submitted_at=r.submitted_at) for r in rows]


# ── Communications ───────────────────────────────────────────────────────────
def _message_out(m, p, thread) -> MessageOut:
    return MessageOut(
        id=m.id,
        thread_id=m.thread_id,
        direction=m.direction,
        body=m.body,
        channel=m.channel.value if hasattr(m.channel, "value") else m.channel,
        sent_at=m.sent_at,
        patient_id=p.id if p else None,
        patient_name=f"{p.first_name} {p.last_name}".strip() if p else "",
        patient_first_name=(p.first_name or "") if p else "",
        patient_last_name=(p.last_name or "") if p else "",
        patient_phone=(p.phone or "") if p else "",
        delivery_status=getattr(m, "delivery_status", None) or "delivered",
        failure_reason=getattr(m, "failure_reason", None),
        attachment_name=getattr(m, "attachment_name", None),
        thread_unread=bool(getattr(thread, "unread", False)),
        thread_archived=bool(getattr(thread, "archived", False)),
    )


@router.get("/api/messages", response_model=list[MessageOut])
async def list_messages(
    patient_id: uuid.UUID | None = Query(default=None),
    include_archived: bool = Query(default=False),
    archived_only: bool = Query(default=False),
    unread_only: bool = Query(default=False),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await staff_service.list_messages(
        db,
        ctx,
        patient_id=patient_id,
        include_archived=include_archived,
        archived_only=archived_only,
        unread_only=unread_only,
    )
    return [_message_out(m, p, thread) for m, p, thread in rows]


@router.post("/api/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    payload: SendMessageRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    msg = await staff_service.send_message(db, ctx, payload)
    patient = await staff_service.get_patient(db, ctx, payload.patient_id)
    # Reload thread for unread/archived flags
    from sqlalchemy import select
    from app.models.staff import MessageThread

    thread = await db.scalar(select(MessageThread).where(MessageThread.id == msg.thread_id))
    await db.commit()
    return _message_out(msg, patient, thread)


@router.patch("/api/message-threads/{thread_id}", response_model=MessageThreadOut)
async def update_message_thread(
    thread_id: uuid.UUID,
    payload: MessageThreadUpdate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    """Mark a thread unread / archive (or restore)."""
    thread = await staff_service.update_message_thread(db, ctx, thread_id, payload)
    await db.commit()
    return MessageThreadOut(
        id=thread.id,
        patient_id=thread.patient_id,
        unread=thread.unread,
        archived=thread.archived,
    )


# ── Payments ─────────────────────────────────────────────────────────────────
@router.get("/api/payments", response_model=list[PaymentLinkOut])
async def list_payments(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_payments(db, ctx)
    return [
        PaymentLinkOut(
            id=link.id,
            patient_id=link.patient_id,
            amount=link.amount,
            description=link.description,
            status=link.status.value,
            created_at=link.created_at,
            paid_at=link.paid_at,
            patient_name=f"{p.first_name} {p.last_name}",
        )
        for link, p in rows
    ]


@router.post("/api/payments", response_model=PaymentLinkOut, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentLinkCreate,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    link = await staff_service.create_payment_link(db, ctx, payload)
    patient = await staff_service.get_patient(db, ctx, link.patient_id)
    await db.commit()
    return PaymentLinkOut(
        id=link.id,
        patient_id=link.patient_id,
        amount=link.amount,
        description=link.description,
        status=link.status.value,
        created_at=link.created_at,
        paid_at=link.paid_at,
        patient_name=f"{patient.first_name} {patient.last_name}" if patient else "",
    )


# ── Verification ─────────────────────────────────────────────────────────────
@router.post("/api/insurance/verify", response_model=PatientOut)
async def verify_insurance(
    payload: VerifyInsuranceRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        p = await staff_service.verify_insurance(db, ctx, payload.patient_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    await db.commit()
    return _patient_out(p)
