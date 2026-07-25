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
    FormSubmissionOut,
    FormTemplateCreate,
    FormTemplateOut,
    FormTemplateUpdate,
    MessageOut,
    PatientCreate,
    PatientOut,
    PatientUpdate,
    PaymentLinkCreate,
    PaymentLinkOut,
    SendFormRequest,
    SendMessageRequest,
    VerifyInsuranceRequest,
    WaitlistCreate,
    WaitlistOut,
)
from app.services import staff_service

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


def _appt_out(appt, patient) -> AppointmentOut:
    return AppointmentOut(
        id=appt.id,
        patient_id=appt.patient_id,
        provider_name=appt.provider_name,
        appointment_type=appt.appointment_type,
        starts_at=appt.starts_at,
        duration_minutes=appt.duration_minutes,
        status=appt.status.value,
        insurance_status=appt.insurance_status.value,
        forms_status=appt.forms_status.value,
        patient_name=f"{patient.first_name} {patient.last_name}",
        patient_initials=f"{patient.first_name[:1]}{patient.last_name[:1]}".upper(),
        patient_dob=patient.dob.isoformat() if patient.dob else None,
        patient_email=patient.email,
        patient_phone=patient.phone,
    )


# ── Dashboard ────────────────────────────────────────────────────────────────
@router.get("/api/dashboard/stats", response_model=DashboardStats)
async def stats(ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)):
    return DashboardStats(**await staff_service.dashboard_stats(db, ctx))


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
    date: str | None = Query(default=None, description="YYYY-MM-DD"),
    patient_id: uuid.UUID | None = Query(default=None),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    if patient_id:
        rows = await staff_service.list_appointments(db, ctx, patient_id=patient_id)
    else:
        day = datetime.fromisoformat(date) if date else datetime.now().astimezone()
        rows = await staff_service.list_appointments(db, ctx, day=day)
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


# ── Forms ────────────────────────────────────────────────────────────────────
@router.get("/api/forms/templates", response_model=list[FormTemplateOut])
async def form_templates(
    ctx: StaffContext = Depends(get_staff_context), db: AsyncSession = Depends(get_db)
):
    rows = await staff_service.list_form_templates(db, ctx)
    return [FormTemplateOut.model_validate(t) for t in rows]


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
    return FormTemplateOut.model_validate(tpl)


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
    return FormTemplateOut.model_validate(tpl)


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
    return FormTemplateOut.model_validate(tpl)


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
        await staff_service.send_form(db, ctx, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    await db.commit()
    return {"message": "Form sent to patient"}


# ── Communications ───────────────────────────────────────────────────────────
@router.get("/api/messages", response_model=list[MessageOut])
async def list_messages(
    patient_id: uuid.UUID | None = Query(default=None),
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    rows = await staff_service.list_messages(db, ctx, patient_id=patient_id)
    return [
        MessageOut(
            id=m.id,
            thread_id=m.thread_id,
            direction=m.direction,
            body=m.body,
            channel=m.channel.value,
            sent_at=m.sent_at,
            patient_id=p.id,
            patient_name=f"{p.first_name} {p.last_name}",
        )
        for m, p in rows
    ]


@router.post("/api/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    payload: SendMessageRequest,
    ctx: StaffContext = Depends(get_staff_context),
    db: AsyncSession = Depends(get_db),
):
    msg = await staff_service.send_message(db, ctx, payload)
    patient = await staff_service.get_patient(db, ctx, payload.patient_id)
    await db.commit()
    return MessageOut(
        id=msg.id,
        thread_id=msg.thread_id,
        direction=msg.direction,
        body=msg.body,
        channel=msg.channel.value,
        sent_at=msg.sent_at,
        patient_id=payload.patient_id,
        patient_name=f"{patient.first_name} {patient.last_name}" if patient else "",
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
