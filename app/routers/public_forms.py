"""Public (unauthenticated) patient forms portal routes.

NOTE: this module intentionally does NOT use `from __future__ import annotations`.
slowapi's @limiter.limit wrapper causes FastAPI to resolve endpoint annotations
against slowapi's module globals; with stringized annotations that resolution
fails and request bodies are misread as query params. Keeping real annotation
objects (read via __wrapped__) avoids that. (Same constraint as app/routers/auth.py.)
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.public_forms import (
    PublicSubmitOut,
    PublicSubmitRequest,
    PublicTokenInfoOut,
    PublicVerifyOut,
    PublicVerifyRequest,
)
from app.services import public_forms_service

router = APIRouter(prefix="/api/public/forms", tags=["public-forms"])
limiter = Limiter(key_func=get_remote_address)


@router.get("/{token}", response_model=PublicTokenInfoOut)
async def get_token_info(token: str, db: AsyncSession = Depends(get_db)):
    token_row = await public_forms_service.get_token(db, token)
    if token_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This link is invalid or has expired.")
    branding = await public_forms_service.get_branding(db, token_row)
    return PublicTokenInfoOut(**branding)


@router.post("/{token}/verify", response_model=PublicVerifyOut)
@limiter.limit("10/minute")
async def verify(
    request: Request,
    token: str,
    payload: PublicVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    token_row = await public_forms_service.get_token(db, token)
    if token_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This link is invalid or has expired.")

    patient = await public_forms_service.verify_patient(db, token_row, payload.last_name, payload.dob)
    if patient is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="We couldn't verify your information — check your last name and date of birth.")

    forms = await public_forms_service.list_pending_forms(db, patient)
    branding = await public_forms_service.get_branding(db, token_row)
    return PublicVerifyOut(
        patient_name=f"{patient.first_name} {patient.last_name}".strip(),
        forms=forms,
        **branding,
    )


@router.post("/{token}/submit", response_model=PublicSubmitOut)
@limiter.limit("20/minute")
async def submit(
    request: Request,
    token: str,
    payload: PublicSubmitRequest,
    db: AsyncSession = Depends(get_db),
):
    token_row = await public_forms_service.get_token(db, token)
    if token_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This link is invalid or has expired.")

    patient = await public_forms_service.verify_patient(db, token_row, payload.last_name, payload.dob)
    if patient is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="We couldn't verify your information — check your last name and date of birth.")

    try:
        remaining = await public_forms_service.submit_form(db, patient, payload.form_request_id, payload.answers)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    await db.commit()
    return PublicSubmitOut(remaining=remaining)
