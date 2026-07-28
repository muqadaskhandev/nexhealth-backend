"""Orchestration for patient-facing conversational intake agent."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import (
    AgentAnswer,
    AgentAnswerStatus,
    AgentAuditLog,
    AgentReview,
    AgentReviewStatus,
    AgentSession,
    AgentSessionStatus,
    AgentTurn,
    AgentTurnRole,
)
from app.models.staff import FormAccessToken, FormRequest, FormRequestStatus, FormSubmission, FormTemplate, Patient
from app.services import agent_llm_service, field_validation_service, public_forms_service
from app.services.agent_field_meta import field_meta, find_field


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _log_audit(db: AsyncSession, session_id: uuid.UUID, event_type: str, detail: dict | None = None) -> None:
    db.add(AgentAuditLog(session_id=session_id, event_type=event_type, detail=detail or {}))


async def _add_turn(
    db: AsyncSession,
    session_id: uuid.UUID,
    role: AgentTurnRole,
    content: str,
    field_id: str | None = None,
) -> None:
    db.add(AgentTurn(session_id=session_id, role=role, content=content, field_id=field_id))


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> AgentSession | None:
    return await db.get(AgentSession, session_id)


async def find_resumable_session(
    db: AsyncSession, token_row: FormAccessToken, form_request_id: uuid.UUID
) -> AgentSession | None:
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.form_access_token_id == token_row.id,
            AgentSession.form_request_id == form_request_id,
            AgentSession.status == AgentSessionStatus.IN_PROGRESS,
        )
    )
    return result.scalar_one_or_none()


async def start_or_resume_session(
    db: AsyncSession,
    token_row: FormAccessToken,
    patient: Patient,
    form_request_id: uuid.UUID,
) -> tuple[AgentSession, FormTemplate, list[dict], str | None]:
    """Create or resume an agent session. Returns (session, template, turns, opening_message)."""
    result = await db.execute(
        select(FormRequest).where(
            FormRequest.id == form_request_id,
            FormRequest.patient_id == patient.id,
            FormRequest.archived_at.is_(None),
        )
    )
    req = result.scalar_one_or_none()
    if req is None:
        raise ValueError("Form request not found")
    if req.status == FormRequestStatus.COMPLETED:
        raise ValueError("This form has already been submitted")

    tpl = await db.get(FormTemplate, req.form_template_id)
    if tpl is None:
        raise ValueError("Form template not found")

    fields = tpl.fields or []
    session = await find_resumable_session(db, token_row, form_request_id)

    if session is None:
        draft: dict[str, Any] = {}
        first = field_validation_service.next_unanswered_field(fields, draft)
        if first is None:
            raise ValueError("This form has no questions to collect")

        session = AgentSession(
            practice_id=token_row.practice_id,
            location_id=token_row.location_id,
            patient_id=patient.id,
            form_access_token_id=token_row.id,
            form_request_id=req.id,
            form_template_id=tpl.id,
            current_field_id=first.get("id"),
            draft_answers={},
        )
        db.add(session)
        await db.flush()
        await _log_audit(db, session.id, "session_started", {"form_request_id": str(req.id)})
        opening = None
    else:
        opening = None

    turns = await list_turns(db, session.id)
    return session, tpl, turns, opening


async def list_turns(db: AsyncSession, session_id: uuid.UUID) -> list[dict]:
    result = await db.execute(
        select(AgentTurn).where(AgentTurn.session_id == session_id).order_by(AgentTurn.created_at.asc())
    )
    return [
        {"role": t.role.value, "content": t.content, "field_id": t.field_id, "created_at": t.created_at.isoformat()}
        for t in result.scalars().all()
    ]


async def list_answers(db: AsyncSession, session_id: uuid.UUID) -> list[dict]:
    result = await db.execute(select(AgentAnswer).where(AgentAnswer.session_id == session_id))
    return [
        {
            "field_id": a.field_id,
            "field_label": a.field_label,
            "raw_patient_text": a.raw_patient_text,
            "parsed_value": a.parsed_value.get("value") if isinstance(a.parsed_value, dict) else a.parsed_value,
            "ai_generated": a.ai_generated,
            "status": a.status.value,
            "sync_target": a.sync_target,
        }
        for a in result.scalars().all()
    ]


async def bootstrap_opening(
    db: AsyncSession,
    session: AgentSession,
    tpl: FormTemplate,
    patient: Patient,
    practice_name: str,
) -> str:
    """Add opening agent turn if session has no turns yet."""
    result = await db.execute(select(AgentTurn).where(AgentTurn.session_id == session.id).limit(1))
    if result.scalar_one_or_none() is not None:
        return ""

    fields = tpl.fields or []
    current_id = session.current_field_id
    current = next((f for f in fields if f.get("id") == current_id), None)
    if current is None:
        current = field_validation_service.next_unanswered_field(fields, session.draft_answers or {})
        if current:
            session.current_field_id = current.get("id")

    patient_name = f"{patient.first_name} {patient.last_name}".strip()
    msg = agent_llm_service.opening_message(patient_name, practice_name, current or {"label": "Let's begin"})
    await _add_turn(db, session.id, AgentTurnRole.AGENT, msg, current.get("id") if current else None)
    await db.flush()
    return msg


async def process_message(
    db: AsyncSession,
    session: AgentSession,
    patient: Patient,
    practice_name: str,
    message: str,
    *,
    structured_value: Any = None,
) -> dict[str, Any]:
    """Process one patient message; returns structured turn result for the client."""
    if session.status != AgentSessionStatus.IN_PROGRESS:
        raise ValueError("This intake session is no longer active")

    tpl = await db.get(FormTemplate, session.form_template_id)
    if tpl is None:
        raise ValueError("Form template not found")

    fields = tpl.fields or []
    draft = dict(session.draft_answers or {})
    current_id = session.current_field_id
    current = next((f for f in fields if f.get("id") == current_id), None)
    if current is None:
        current = field_validation_service.next_unanswered_field(fields, draft)
        if current is None:
            return {"assistant_message": "All questions are answered. Tap Submit to finish.", "done": True, "validation_status": "valid"}
        session.current_field_id = current.get("id")

    await _add_turn(db, session.id, AgentTurnRole.PATIENT, message, current.get("id"))

    skip_tokens = {"skip", "pass", "n/a", "na", "none", "no answer"}
    if structured_value is None and not current.get("required") and message.strip().lower() in skip_tokens:
        fid = current.get("id")
        draft[fid] = ""
        session.draft_answers = draft
        nxt = field_validation_service.next_unanswered_field(fields, draft)
        agent_msg = "No problem — we'll skip that one."
        if nxt is None:
            session.current_field_id = None
            agent_msg += " Please tap Submit to finish."
            llm_result = {"assistant_message": agent_msg, "done": True, "validation_status": "valid"}
        else:
            session.current_field_id = nxt.get("id")
            agent_msg += f" {agent_llm_service.question_for_field(nxt)}"
            llm_result = {"assistant_message": agent_msg, "done": False, "validation_status": "valid"}
        await _add_turn(db, session.id, AgentTurnRole.AGENT, agent_msg, nxt.get("id") if nxt else None)
        await db.flush()
        return _session_state(session, tpl, llm_result)

    if structured_value is not None:
        ok, err, normalized = field_validation_service.validate_field_value(current, message, structured_value)
        if not ok:
            agent_msg = err or "Please check your answer and try again."
            await _add_turn(db, session.id, AgentTurnRole.AGENT, agent_msg, current.get("id"))
            await db.flush()
            return _session_state(
                session,
                tpl,
                {"assistant_message": agent_msg, "done": False, "validation_status": "invalid"},
            )
        llm_result = {
            "assistant_message": "Thanks — got it.",
            "parsed_value": normalized,
            "validation_status": "valid",
        }
    else:
        # Build conversation snippet for LLM (roles mapped to openai format)
        turn_rows = await list_turns(db, session.id)
        snippet = [{"role": "assistant" if t["role"] == "agent" else t["role"], "content": t["content"]} for t in turn_rows[-10:]]

        allowed = field_validation_service.intake_fields(fields, draft)
        patient_name = f"{patient.first_name} {patient.last_name}".strip()

        llm_result = await agent_llm_service.process_turn(
            patient_name=patient_name,
            practice_name=practice_name,
            current_field=current,
            allowed_fields=allowed,
            draft_answers=draft,
            patient_message=message,
            conversation_snippet=snippet,
        )

    validation_status = llm_result.get("validation_status", "needs_clarification")

    if validation_status == "emergency":
        session.status = AgentSessionStatus.EMERGENCY_STOPPED
        agent_msg = llm_result.get("assistant_message", "")
        await _add_turn(db, session.id, AgentTurnRole.AGENT, agent_msg)
        await _log_audit(db, session.id, "emergency_stop", {"field_id": current.get("id")})
        await db.flush()
        return _session_state(session, tpl, llm_result)

    if validation_status == "off_topic":
        agent_msg = llm_result.get(
            "assistant_message",
            "I can only help with your intake form. For medical questions, please contact your clinic directly.",
        )
        await _add_turn(db, session.id, AgentTurnRole.AGENT, agent_msg, current.get("id"))
        await db.flush()
        llm_result["assistant_message"] = agent_msg
        return _session_state(session, tpl, llm_result)

    if validation_status == "valid" and llm_result.get("parsed_value") is not None:
        fid = current.get("id")
        normalized = llm_result["parsed_value"]
        draft[fid] = normalized
        session.draft_answers = draft

        # Upsert agent answer row
        result = await db.execute(
            select(AgentAnswer).where(AgentAnswer.session_id == session.id, AgentAnswer.field_id == fid)
        )
        ans_row = result.scalar_one_or_none()
        if ans_row is None:
            ans_row = AgentAnswer(
                session_id=session.id,
                field_id=fid,
                field_label=current.get("label") or "",
                sync_target=current.get("sync_target"),
                raw_patient_text=message,
                parsed_value={"value": normalized},
                ai_generated=agent_llm_service.openai_configured(),
                status=AgentAnswerStatus.VALID,
            )
            db.add(ans_row)
        else:
            ans_row.raw_patient_text = message
            ans_row.parsed_value = {"value": normalized}
            ans_row.status = AgentAnswerStatus.VALID
            ans_row.ai_generated = agent_llm_service.openai_configured()

        nxt = field_validation_service.next_unanswered_field(fields, draft)
        if nxt is None:
            session.current_field_id = None
            agent_msg = llm_result.get(
                "assistant_message",
                "Thank you! I have everything I need. Please tap Submit to finish.",
            )
            llm_result["done"] = True
        else:
            session.current_field_id = nxt.get("id")
            agent_msg = llm_result.get("assistant_message") or agent_llm_service.question_for_field(nxt)
            if structured_value is not None and not llm_result.get("assistant_message"):
                agent_msg = agent_llm_service.question_for_field(nxt)
            llm_result["done"] = False

        await _add_turn(db, session.id, AgentTurnRole.AGENT, agent_msg, nxt.get("id") if nxt else None)
        await _log_audit(db, session.id, "field_answered", {"field_id": fid})
    else:
        agent_msg = llm_result.get("assistant_message") or llm_result.get("validation_message") or "Could you clarify that?"
        await _add_turn(db, session.id, AgentTurnRole.AGENT, agent_msg, current.get("id"))
        llm_result["done"] = False

    await db.flush()
    return _session_state(session, tpl, llm_result)


def _session_state(session: AgentSession, tpl: FormTemplate, llm_result: dict) -> dict[str, Any]:
    fields = tpl.fields or []
    draft = session.draft_answers or {}
    answered, total = field_validation_service.progress_counts(fields, draft)
    current = find_field(fields, session.current_field_id)
    return {
        "session_id": str(session.id),
        "status": session.status.value,
        "assistant_message": llm_result.get("assistant_message", ""),
        "validation_status": llm_result.get("validation_status"),
        "current_field_id": session.current_field_id,
        "current_field": field_meta(current),
        "draft_answers": draft,
        "progress": {"answered": answered, "total": total},
        "done": llm_result.get("done", False),
    }


async def complete_session(
    db: AsyncSession,
    session: AgentSession,
    patient: Patient,
) -> int:
    """Finalize intake → FormSubmission + sync targets + review row."""
    if session.status == AgentSessionStatus.COMPLETED:
        raise ValueError("Session already completed")
    if session.status == AgentSessionStatus.EMERGENCY_STOPPED:
        raise ValueError("Intake was stopped due to an emergency — contact the clinic")

    tpl = await db.get(FormTemplate, session.form_template_id)
    fields = tpl.fields or [] if tpl else []
    answers = dict(session.draft_answers or {})

    # Ensure required fields present
    for f in field_validation_service.intake_fields(fields, answers):
        if f.get("required") and not field_validation_service.has_value(f, answers.get(f.get("id"))):
            raise ValueError(f"Missing required answer: {f.get('label')}")

    remaining = await public_forms_service.submit_form(
        db,
        patient,
        session.form_request_id,
        answers,
        intake_source="agent",
        ai_generated=True,
        agent_session_id=session.id,
    )

    session.status = AgentSessionStatus.COMPLETED
    session.completed_at = _now()

    # Link submission for review
    result = await db.execute(
        select(FormSubmission).where(
            FormSubmission.form_request_id == session.form_request_id,
            FormSubmission.agent_session_id == session.id,
        )
    )
    sub = result.scalar_one_or_none()
    db.add(
        AgentReview(
            session_id=session.id,
            form_submission_id=sub.id if sub else None,
            status=AgentReviewStatus.PENDING,
        )
    )
    await _log_audit(db, session.id, "session_completed", {"form_request_id": str(session.form_request_id)})
    await _add_turn(db, session.id, AgentTurnRole.SYSTEM, "Intake submitted successfully.")
    await db.flush()
    return remaining


async def get_session_detail(db: AsyncSession, session_id: uuid.UUID) -> dict | None:
    session = await db.get(AgentSession, session_id)
    if session is None:
        return None
    tpl = await db.get(FormTemplate, session.form_template_id)
    patient = await db.get(Patient, session.patient_id)
    turns = await list_turns(db, session.id)
    answers = await list_answers(db, session.id)
    fields = tpl.fields or [] if tpl else []
    answered, total = field_validation_service.progress_counts(fields, session.draft_answers or {})
    return {
        "session_id": str(session.id),
        "status": session.status.value,
        "form_request_id": str(session.form_request_id),
        "form_name": tpl.name if tpl else "",
        "patient_name": f"{patient.first_name} {patient.last_name}".strip() if patient else "",
        "intake_source": "agent",
        "draft_answers": session.draft_answers or {},
        "turns": turns,
        "answers": answers,
        "progress": {"answered": answered, "total": total},
    }
