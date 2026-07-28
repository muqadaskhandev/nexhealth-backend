"""Public (unauthenticated) conversational intake agent routes."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.practice import Practice
from app.models.staff import FormTemplate
from app.schemas.public_agent import (
    AgentCompleteOut,
    AgentCompleteRequest,
    AgentFieldOut,
    AgentMessageRequest,
    AgentProgressOut,
    AgentSessionOut,
    AgentSessionStartRequest,
    AgentTurnOut,
)
from app.services import agent_service, field_validation_service, public_forms_service
from app.services.agent_field_meta import field_meta, find_field
from app.services.staff_service import form_has_medical_alerts, get_medical_alert_catalog

router = APIRouter(tags=["public-agent"])
limiter = Limiter(key_func=get_remote_address)

SESSION_COOKIE = "nex_agent_session"


def _parse_dob(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid date of birth format.") from exc


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=60 * 60 * 24 * 7,
    )


async def _medical_alerts_for_template(db: AsyncSession, tpl: FormTemplate | None) -> dict | None:
    if tpl is None or not form_has_medical_alerts(tpl):
        return None
    return await get_medical_alert_catalog(db, tpl.practice_id, tpl.location_id)


def _current_field_out(tpl: FormTemplate | None, field_id: str | None) -> AgentFieldOut | None:
    if tpl is None:
        return None
    meta = field_meta(find_field(tpl.fields or [], field_id))
    return AgentFieldOut(**meta) if meta else None


async def _session_response(
    db: AsyncSession,
    *,
    session,
    tpl: FormTemplate | None,
    patient,
    turns: list,
    draft_answers: dict,
    progress: dict,
    done: bool,
    assistant_message: str | None = None,
    validation_status: str | None = None,
    current_field_id: str | None = None,
) -> AgentSessionOut:
    fid = current_field_id if current_field_id is not None else session.current_field_id
    medical = await _medical_alerts_for_template(db, tpl)
    current = _current_field_out(tpl, fid)
    return AgentSessionOut(
        session_id=session.id,
        status=session.status.value,
        form_request_id=session.form_request_id,
        form_name=tpl.name if tpl else "",
        patient_name=f"{patient.first_name} {patient.last_name}".strip(),
        assistant_message=assistant_message,
        turns=[AgentTurnOut(**t) for t in turns],
        draft_answers=draft_answers,
        progress=AgentProgressOut(**progress),
        done=done,
        validation_status=validation_status,
        current_field=current,
        medical_alerts=medical,
    )


@router.post("/api/public/agent/{token}/session", response_model=AgentSessionOut)
@limiter.limit("15/minute")
async def start_session(
    request: Request,
    response: Response,
    token: str,
    payload: AgentSessionStartRequest,
    db: AsyncSession = Depends(get_db),
):
    token_row = await public_forms_service.get_token(db, token)
    if token_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This link is invalid or has expired.")

    dob = _parse_dob(payload.dob)
    patient = await public_forms_service.verify_patient(db, token_row, payload.last_name, dob)
    if patient is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="We couldn't verify your information — check your last name and date of birth.",
        )

    if payload.session_id:
        session = await agent_service.get_session(db, payload.session_id)
        if session is None or session.patient_id != patient.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")
        tpl = await db.get(FormTemplate, session.form_template_id)
    else:
        try:
            session, tpl, _, _ = await agent_service.start_or_resume_session(
                db, token_row, patient, payload.form_request_id
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    practice = await db.get(Practice, token_row.practice_id)
    practice_name = practice.name if practice else "the clinic"

    if payload.session_id is None:
        existing_turns = await agent_service.list_turns(db, session.id)
        if not existing_turns:
            await agent_service.bootstrap_opening(db, session, tpl, patient, practice_name)

    turns = await agent_service.list_turns(db, session.id)
    fields = tpl.fields or [] if tpl else []
    answered, total = field_validation_service.progress_counts(fields, session.draft_answers or {})

    _set_session_cookie(response, str(session.id))
    await db.commit()

    last_agent = next((t for t in reversed(turns) if t["role"] == "agent"), None)
    return await _session_response(
        db,
        session=session,
        tpl=tpl,
        patient=patient,
        turns=turns,
        draft_answers=session.draft_answers or {},
        progress={"answered": answered, "total": total},
        done=answered >= total and total > 0,
        assistant_message=last_agent["content"] if last_agent else None,
    )


@router.post("/api/public/agent/{token}/message", response_model=AgentSessionOut)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    token: str,
    payload: AgentMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    token_row = await public_forms_service.get_token(db, token)
    if token_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This link is invalid or has expired.")

    dob = _parse_dob(payload.dob)
    patient = await public_forms_service.verify_patient(db, token_row, payload.last_name, dob)
    if patient is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Verification failed.")

    session = await agent_service.get_session(db, payload.session_id)
    if session is None or session.patient_id != patient.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")

    practice = await db.get(Practice, token_row.practice_id)
    practice_name = practice.name if practice else "the clinic"

    try:
        result = await agent_service.process_message(
            db,
            session,
            patient,
            practice_name,
            payload.message.strip(),
            structured_value=payload.structured_value,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    tpl = await db.get(FormTemplate, session.form_template_id)
    turns = await agent_service.list_turns(db, session.id)
    await db.commit()

    return await _session_response(
        db,
        session=session,
        tpl=tpl,
        patient=patient,
        turns=turns,
        draft_answers=result.get("draft_answers") or {},
        progress=result.get("progress", {"answered": 0, "total": 0}),
        done=bool(result.get("done")),
        assistant_message=result.get("assistant_message"),
        validation_status=result.get("validation_status"),
        current_field_id=result.get("current_field_id"),
    )


@router.post("/api/public/agent/{token}/complete", response_model=AgentCompleteOut)
@limiter.limit("10/minute")
async def complete_intake(
    request: Request,
    token: str,
    payload: AgentCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    token_row = await public_forms_service.get_token(db, token)
    if token_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This link is invalid or has expired.")

    dob = _parse_dob(payload.dob)
    patient = await public_forms_service.verify_patient(db, token_row, payload.last_name, dob)
    if patient is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Verification failed.")

    session = await agent_service.get_session(db, payload.session_id)
    if session is None or session.patient_id != patient.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found")

    try:
        remaining = await agent_service.complete_session(db, session, patient)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    await db.commit()
    return AgentCompleteOut(remaining=remaining)
