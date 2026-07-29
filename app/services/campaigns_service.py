"""Campaigns service — favorites, copy, audience, build, send/schedule."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.staff_context import StaffContext
from app.models.campaigns import Campaign, CampaignSendLog, CampaignStatus
from app.models.staff import Appointment, Patient, WaitlistEntry, WaitlistStatus
from app.schemas.campaigns import (
    CampaignCopyRequest,
    CampaignCreateBlank,
    CampaignGenerateAiRequest,
    CampaignScheduleRequest,
    CampaignUpdate,
)

FAVORITE_TEMPLATES: list[dict[str, Any]] = [
    {
        "title": "🎃 TEMPLATE: Halloween",
        "email_subject": "🎃 Halloween",
        "email_preview_text": "Spooktacular smiles await!",
        "email_body": (
            "Hi {{PATIENT_FIRST_NAME}},\n\n"
            "Wishing you a safe and happy Halloween from all of us!\n\n"
            "Don't forget to brush after those treats. Book your next visit anytime.\n\n"
            "Thanks,\n{{LOCATION_NAME}}"
        ),
        "sms_body": (
            "Hi {{PATIENT_FIRST_NAME}}! Happy Halloween from {{LOCATION_NAME}}. "
            "Brush after treats & book anytime: {{LOCATION_BOOKING_APPOINTMENT}}"
        ),
    },
    {
        "title": "🇺🇸 TEMPLATE: Labor Day",
        "email_subject": "🇺🇸 Labor Day",
        "email_preview_text": "Enjoy the long weekend",
        "email_body": (
            "Hi {{PATIENT_FIRST_NAME}},\n\n"
            "Happy Labor Day! Our office hours may change this weekend—call "
            "{{LOCATION_PHONE}} if you need us.\n\n"
            "Thanks,\n{{LOCATION_NAME}}"
        ),
        "sms_body": (
            "Happy Labor Day from {{LOCATION_NAME}}! Hours may vary—call "
            "{{LOCATION_PHONE}} with questions."
        ),
    },
    {
        "title": "🏢 TEMPLATE: Office closure",
        "email_subject": "Office closure notice",
        "email_preview_text": "Important update about our hours",
        "email_body": (
            "Hi {{PATIENT_FIRST_NAME}},\n\n"
            "{{LOCATION_NAME}} will be closed due to weather. Please call us at "
            "{{LOCATION_PHONE}} to reschedule, or click below to book online.\n\n"
            "{{LOCATION_BOOKING_APPOINTMENT}}\n\n"
            "Thanks,\n{{LOCATION_NAME}}"
        ),
        "sms_body": (
            "{{LOCATION_NAME}} is closed due to weather. Call {{LOCATION_PHONE}} "
            "to reschedule or book: {{LOCATION_BOOKING_APPOINTMENT}}"
        ),
    },
    {
        "title": "🎁 TEMPLATE: Winter Holiday Special Offer",
        "email_subject": "Winter Holiday Special Offer",
        "email_preview_text": "A special offer for you",
        "email_body": (
            "Hi {{PATIENT_FIRST_NAME}},\n\n"
            "This season, enjoy a special offer on select treatments. Reply or book "
            "online to learn more.\n\nThanks,\n{{LOCATION_NAME}}"
        ),
        "sms_body": (
            "Hi {{PATIENT_FIRST_NAME}}, enjoy our winter special at {{LOCATION_NAME}}. "
            "Book: {{LOCATION_BOOKING_APPOINTMENT}}"
        ),
    },
    {
        "title": "📋 TEMPLATE: End of Year Insurance Benefits Reminder",
        "email_subject": "Use your remaining insurance benefits",
        "email_preview_text": "Don't lose unused benefits",
        "email_body": (
            "Hi {{PATIENT_FIRST_NAME}},\n\n"
            "Your dental benefits reset soon. Schedule care before year-end so you "
            "don't lose unused coverage.\n\nBook: {{LOCATION_BOOKING_APPOINTMENT}}\n\n"
            "Thanks,\n{{LOCATION_NAME}}"
        ),
        "sms_body": (
            "Hi {{PATIENT_FIRST_NAME}}, use remaining insurance benefits before they "
            "reset. Book with {{LOCATION_NAME}}: {{LOCATION_BOOKING_APPOINTMENT}}"
        ),
    },
]


def _parse_uuids(raw: list | None) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for item in raw or []:
        try:
            out.append(uuid.UUID(str(item)))
        except ValueError:
            continue
    return out


def _creator_name(ctx: StaffContext) -> str:
    name = (ctx.user.full_name or "").strip()
    return name or (ctx.user.email or "Staff")


async def _seed_favorites(db: AsyncSession, ctx: StaffContext) -> None:
    existing = await db.scalar(
        select(Campaign.id).where(
            Campaign.practice_id == ctx.practice_id,
            Campaign.is_favorite_template.is_(True),
        ).limit(1)
    )
    if existing is not None:
        return
    for spec in FAVORITE_TEMPLATES:
        db.add(
            Campaign(
                practice_id=ctx.practice_id,
                location_ids=[],
                title=spec["title"],
                status=CampaignStatus.FAVORITE.value,
                is_favorite_template=True,
                wizard_step="build",
                has_email=True,
                has_sms=True,
                email_subject=spec["email_subject"],
                email_preview_text=spec["email_preview_text"],
                email_body=spec["email_body"],
                sms_body=spec["sms_body"][:425],
                created_by_name="NexHealth",
            )
        )
    await db.commit()


async def list_campaigns(
    db: AsyncSession, ctx: StaffContext, *, tab: str = "all", q: str | None = None
) -> list[Campaign]:
    await _seed_favorites(db, ctx)
    rows = list(
        await db.scalars(
            select(Campaign)
            .where(Campaign.practice_id == ctx.practice_id)
            .order_by(Campaign.updated_at.desc())
        )
    )
    if tab == "drafts":
        rows = [r for r in rows if r.status == CampaignStatus.DRAFT.value and not r.is_favorite_template]
    elif tab == "scheduled":
        rows = [r for r in rows if r.status == CampaignStatus.SCHEDULED.value]
    elif tab == "sent":
        rows = [r for r in rows if r.status == CampaignStatus.SENT.value]
    elif tab == "favorites":
        rows = [r for r in rows if r.is_favorite_template or r.status == CampaignStatus.FAVORITE.value]
    # all = everything including favorites

    if q and q.strip():
        needle = q.strip().lower()
        rows = [r for r in rows if needle in (r.title or "").lower()]
    return rows


async def get_campaign(db: AsyncSession, ctx: StaffContext, campaign_id: uuid.UUID) -> Campaign:
    row = await db.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.practice_id == ctx.practice_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    return row


async def create_blank_campaign(
    db: AsyncSession, ctx: StaffContext, data: CampaignCreateBlank
) -> Campaign:
    locs = data.location_ids or [ctx.location_id]
    row = Campaign(
        practice_id=ctx.practice_id,
        location_ids=[str(x) for x in locs],
        title=(data.title or "Untitled campaign").strip(),
        status=CampaignStatus.DRAFT.value,
        is_favorite_template=False,
        wizard_step="audience",
        has_email=True,
        has_sms=False,
        email_subject="",
        email_body="Hi {{PATIENT_FIRST_NAME}},\n\n\n\nThanks,\n{{LOCATION_NAME}}",
        created_by_user_id=ctx.user.id,
        created_by_name=_creator_name(ctx),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def copy_campaign(
    db: AsyncSession, ctx: StaffContext, source_id: uuid.UUID, data: CampaignCopyRequest
) -> Campaign:
    source = await get_campaign(db, ctx, source_id)
    locs = data.location_ids or [ctx.location_id]
    if not locs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Select at least one location"
        )
    row = Campaign(
        practice_id=ctx.practice_id,
        location_ids=[str(x) for x in locs],
        title=data.title.strip(),
        status=CampaignStatus.DRAFT.value,
        is_favorite_template=False,
        source_campaign_id=source.id,
        wizard_step="audience",
        audience_filters={},
        has_email=True,
        has_sms=bool(source.sms_body),
        email_subject=source.email_subject or "",
        email_preview_text=source.email_preview_text or "",
        email_body=source.email_body or "",
        email_images=list(source.email_images or []),
        sms_body=(source.sms_body or "")[:425],
        created_by_user_id=ctx.user.id,
        created_by_name=_creator_name(ctx),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_campaign(
    db: AsyncSession, ctx: StaffContext, campaign_id: uuid.UUID, data: CampaignUpdate
) -> Campaign:
    row = await get_campaign(db, ctx, campaign_id)
    if row.is_favorite_template:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Favorite templates are read-only — make a copy first",
        )
    if row.status == CampaignStatus.SENT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Sent campaigns cannot be edited"
        )

    payload = data.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"] is not None:
        row.title = payload["title"].strip()
    if "location_ids" in payload and payload["location_ids"] is not None:
        row.location_ids = [str(x) for x in payload["location_ids"]]
    if "wizard_step" in payload and payload["wizard_step"] is not None:
        step = payload["wizard_step"]
        if step not in ("audience", "verify", "build"):
            raise HTTPException(status_code=400, detail="Invalid wizard step")
        row.wizard_step = step
    if "audience_filters" in payload and payload["audience_filters"] is not None:
        row.audience_filters = payload["audience_filters"]
    if "selected_patient_ids" in payload and payload["selected_patient_ids"] is not None:
        row.selected_patient_ids = [str(x) for x in payload["selected_patient_ids"]]
    if "excluded_patient_ids" in payload and payload["excluded_patient_ids"] is not None:
        row.excluded_patient_ids = [str(x) for x in payload["excluded_patient_ids"]]
    if "has_email" in payload and payload["has_email"] is not None:
        row.has_email = bool(payload["has_email"])
    if "email_subject" in payload and payload["email_subject"] is not None:
        row.email_subject = payload["email_subject"]
    if "email_preview_text" in payload and payload["email_preview_text"] is not None:
        row.email_preview_text = payload["email_preview_text"]
    if "email_body" in payload and payload["email_body"] is not None:
        row.email_body = payload["email_body"]
    if "email_images" in payload and payload["email_images"] is not None:
        row.email_images = [
            img if isinstance(img, dict) else img.model_dump()  # type: ignore[union-attr]
            for img in payload["email_images"]
        ]
    if "has_sms" in payload and payload["has_sms"] is not None:
        row.has_sms = bool(payload["has_sms"])
    if "sms_body" in payload and payload["sms_body"] is not None:
        row.sms_body = (payload["sms_body"] or "")[:425]
    if "ai_prompt" in payload and payload["ai_prompt"] is not None:
        row.ai_prompt = payload["ai_prompt"]

    await db.commit()
    await db.refresh(row)
    return row


async def delete_campaign(db: AsyncSession, ctx: StaffContext, campaign_id: uuid.UUID) -> None:
    row = await get_campaign(db, ctx, campaign_id)
    if row.is_favorite_template:
        raise HTTPException(status_code=400, detail="Cannot delete favorite templates")
    await db.delete(row)
    await db.commit()


def _age_years(dob: date | None, today: date) -> int | None:
    if dob is None:
        return None
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


async def resolve_audience_patients(
    db: AsyncSession, ctx: StaffContext, campaign: Campaign
) -> list[Patient]:
    """Active patients at campaign locations, narrowed by filters."""
    filters = campaign.audience_filters or {}
    loc_ids = _parse_uuids(campaign.location_ids)
    if not loc_ids:
        loc_ids = [ctx.location_id]

    stmt = select(Patient).where(
        Patient.practice_id == ctx.practice_id,
        Patient.archived.is_(False),
        Patient.location_id.in_(loc_ids),
    )
    patients = list(await db.scalars(stmt))
    today = date.today()

    age_mode = (filters.get("age") or "all").lower()
    age_min = filters.get("age_min")
    age_max = filters.get("age_max")
    gender = (filters.get("gender") or "all").lower()
    appt = (filters.get("appointment") or "all").lower()
    insurance_name = (filters.get("insurance_name") or "").strip().lower()
    waitlist = (filters.get("waitlist") or "all").lower()
    continuing = bool(filters.get("continuing_care_due"))
    search_names: list[str] = [str(x).strip().lower() for x in (filters.get("search_names") or []) if str(x).strip()]

    # Appointment presence
    patient_ids = [p.id for p in patients]
    past_ids: set[uuid.UUID] = set()
    future_ids: set[uuid.UUID] = set()
    if patient_ids and appt != "all":
        now = datetime.now(timezone.utc)
        appts = list(
            await db.scalars(
                select(Appointment).where(
                    Appointment.practice_id == ctx.practice_id,
                    Appointment.patient_id.in_(patient_ids),
                )
            )
        )
        for a in appts:
            starts = a.starts_at
            if starts.tzinfo is None:
                starts = starts.replace(tzinfo=timezone.utc)
            if starts < now:
                past_ids.add(a.patient_id)
            else:
                future_ids.add(a.patient_id)

    waitlist_ids: set[uuid.UUID] = set()
    if patient_ids and waitlist != "all":
        entries = list(
            await db.scalars(
                select(WaitlistEntry).where(
                    WaitlistEntry.practice_id == ctx.practice_id,
                    WaitlistEntry.patient_id.in_(patient_ids),
                    WaitlistEntry.status == WaitlistStatus.WAITING,
                )
            )
        )
        waitlist_ids = {e.patient_id for e in entries}

    result: list[Patient] = []
    for p in patients:
        age = _age_years(p.dob, today)
        if age_mode == "over_18" and (age is None or age < 18):
            continue
        if age_mode == "under_18" and (age is None or age >= 18):
            continue
        if age_mode == "custom":
            if age is None:
                continue
            if age_min is not None and age < int(age_min):
                continue
            if age_max is not None and age > int(age_max):
                continue

        g = (p.gender or "").strip().lower()
        if gender != "all":
            if gender == "female" and g not in ("f", "female", "woman"):
                continue
            if gender == "male" and g not in ("m", "male", "man"):
                continue
            if gender == "other" and g in ("f", "female", "woman", "m", "male", "man", ""):
                continue

        if appt == "has_past" and p.id not in past_ids:
            continue
        if appt == "has_future" and p.id not in future_ids:
            continue
        if appt == "none" and (p.id in past_ids or p.id in future_ids):
            continue

        if insurance_name:
            data = p.insurance_data or {}
            name = str(data.get("name") or data.get("plan") or "").lower()
            employer = str(data.get("employer") or "").lower()
            group = str(data.get("group_number") or data.get("groupNumber") or "").lower()
            if insurance_name not in name and insurance_name not in employer and insurance_name not in group:
                continue

        if waitlist == "on_asap" or waitlist == "on_sooner":
            if p.id not in waitlist_ids:
                continue

        # Demo: continuing care due ≈ has past appointment and no future
        if continuing and not (p.id in past_ids and p.id not in future_ids):
            continue

        if search_names:
            full = f"{p.first_name} {p.last_name}".strip().lower()
            if not any(n in full or n in (p.first_name or "").lower() or n in (p.last_name or "").lower() for n in search_names):
                continue

        result.append(p)

    # Manual CSV inclusions (matched by email/phone or appended as synthetic selection via selected ids)
    excluded = {str(x) for x in (campaign.excluded_patient_ids or [])}
    result = [p for p in result if str(p.id) not in excluded]

    selected = _parse_uuids(campaign.selected_patient_ids)
    if selected:
        selected_set = set(selected)
        # If explicit selection set after verify, intersect
        if campaign.wizard_step in ("verify", "build") and selected:
            by_id = {p.id: p for p in result}
            # Also load any selected not already in result
            missing = [sid for sid in selected if sid not in by_id]
            if missing:
                extra = list(
                    await db.scalars(
                        select(Patient).where(
                            Patient.practice_id == ctx.practice_id,
                            Patient.id.in_(missing),
                        )
                    )
                )
                for p in extra:
                    by_id[p.id] = p
            result = [by_id[sid] for sid in selected if sid in by_id]

    return result


async def preview_audience(
    db: AsyncSession, ctx: StaffContext, campaign_id: uuid.UUID
) -> tuple[list[Patient], int]:
    campaign = await get_campaign(db, ctx, campaign_id)
    patients = await resolve_audience_patients(db, ctx, campaign)
    return patients, len(patients)


def generate_ai_copy(data: CampaignGenerateAiRequest) -> dict[str, str]:
    """Demo AI writer — produces campaign copy from a short outline."""
    prompt = data.prompt.strip()
    if data.channel == "sms":
        body = (
            f"Hi {{{{PATIENT_FIRST_NAME}}}}, {prompt.rstrip('.')}. "
            f"Questions? Call {{{{LOCATION_PHONE}}}}. – {{{{LOCATION_NAME}}}}"
        )[:425]
        return {"subject": "", "preview_text": "", "body": body}

    subject = prompt[:60] if len(prompt) <= 60 else prompt[:57] + "…"
    body = (
        f"Hi {{{{PATIENT_FIRST_NAME}}}},\n\n"
        f"{prompt.rstrip('.')}.\n\n"
        f"We're here if you need anything—call {{{{LOCATION_PHONE}}}} or book online:\n"
        f"{{{{LOCATION_BOOKING_APPOINTMENT}}}}\n\n"
        f"Thanks,\n{{{{LOCATION_NAME}}}}"
    )
    return {
        "subject": subject,
        "preview_text": prompt[:120],
        "body": body,
    }


async def send_campaign_now(
    db: AsyncSession, ctx: StaffContext, campaign_id: uuid.UUID
) -> Campaign:
    campaign = await get_campaign(db, ctx, campaign_id)
    if campaign.is_favorite_template:
        raise HTTPException(status_code=400, detail="Make a copy before sending")
    if not campaign.has_email and not campaign.has_sms:
        raise HTTPException(status_code=400, detail="Add an email or SMS message first")
    if campaign.has_email and not (campaign.email_body or "").strip():
        raise HTTPException(status_code=400, detail="Email body is empty")
    if campaign.has_sms and not (campaign.sms_body or "").strip():
        raise HTTPException(status_code=400, detail="SMS body is empty")

    patients = await resolve_audience_patients(db, ctx, campaign)
    if not patients:
        raise HTTPException(status_code=400, detail="No patients in the audience")

    # SMS registration gate for SMS channel
    if campaign.has_sms:
        from app.services import communications_service as comm_svc

        approved = await comm_svc.is_sms_registration_approved(
            db, ctx.practice_id, ctx.location_id
        )
        if not approved:
            raise HTTPException(
                status_code=400,
                detail="SMS registration incomplete — register your business before sending SMS campaigns",
            )

    now = datetime.now(timezone.utc)
    for p in patients:
        name = f"{p.first_name} {p.last_name}".strip()
        if campaign.has_email:
            db.add(
                CampaignSendLog(
                    campaign_id=campaign.id,
                    practice_id=ctx.practice_id,
                    patient_id=p.id,
                    patient_name=name,
                    channel="email",
                    status="sent" if (p.email or "").strip() else "failed",
                    failure_reason="" if (p.email or "").strip() else "Missing email",
                    sent_at=now,
                )
            )
        if campaign.has_sms:
            prefs = p.notification_prefs or {}
            ok = bool((p.phone or "").strip()) and prefs.get("sms") is not False
            db.add(
                CampaignSendLog(
                    campaign_id=campaign.id,
                    practice_id=ctx.practice_id,
                    patient_id=p.id,
                    patient_name=name,
                    channel="sms",
                    status="sent" if ok else "failed",
                    failure_reason="" if ok else "Missing phone or unsubscribed",
                    sent_at=now,
                )
            )

    campaign.status = CampaignStatus.SENT.value
    campaign.sent_at = now
    campaign.scheduled_at = None
    campaign.recipient_count = len(patients)
    campaign.wizard_step = "build"
    campaign.created_by_name = campaign.created_by_name or _creator_name(ctx)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def schedule_campaign(
    db: AsyncSession, ctx: StaffContext, campaign_id: uuid.UUID, data: CampaignScheduleRequest
) -> Campaign:
    campaign = await get_campaign(db, ctx, campaign_id)
    if campaign.is_favorite_template:
        raise HTTPException(status_code=400, detail="Make a copy before scheduling")
    when = data.scheduled_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Schedule time must be in the future")

    patients = await resolve_audience_patients(db, ctx, campaign)
    campaign.status = CampaignStatus.SCHEDULED.value
    campaign.scheduled_at = when
    campaign.recipient_count = len(patients)
    campaign.wizard_step = "build"
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def send_test(
    db: AsyncSession, ctx: StaffContext, campaign_id: uuid.UUID, channel: str
) -> dict[str, str]:
    campaign = await get_campaign(db, ctx, campaign_id)
    if channel == "email" and not (campaign.email_body or "").strip():
        raise HTTPException(status_code=400, detail="Email body is empty")
    if channel == "sms" and not (campaign.sms_body or "").strip():
        raise HTTPException(status_code=400, detail="SMS body is empty")
    return {
        "message": f"Test {channel} sent to your staff account ({ctx.user.email})",
    }
