"""Public Reviews survey (1–5 rating → Google or internal feedback)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import reviews_service

router = APIRouter(tags=["public-reviews"])


class ReviewSubmitBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    feedback: str = Field(default="", max_length=2000)


@router.get("/api/public/reviews/{appointment_id}")
async def get_review_appointment(
    appointment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await reviews_service.public_review_info(db, appointment_id)


@router.post("/api/public/reviews/{appointment_id}")
async def submit_review(
    appointment_id: uuid.UUID,
    body: ReviewSubmitBody,
    db: AsyncSession = Depends(get_db),
):
    return await reviews_service.public_submit_review(
        db,
        appointment_id,
        rating=body.rating,
        feedback=body.feedback,
    )
