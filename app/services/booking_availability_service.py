"""Compute bookable time slots from provider availability (shared by staff preview + public booking)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment_types import AppointmentTypeDef, PatientTypeRule
from app.models.providers import AvailabilityBlock, AvailabilitySlot, Provider, ProviderStatus, RepeatMode
from app.models.staff import Appointment, AppointmentStatus


def practice_slug(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", name.lower()) or "practice"


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_time(mins: int) -> time:
    return time(hour=mins // 60, minute=mins % 60)


def _provider_offers_type(
    provider: Provider, slot: AvailabilitySlot, appointment_type_id: uuid.UUID
) -> bool:
    type_id = str(appointment_type_id)
    if slot.use_provider_defaults:
        return type_id in [str(x) for x in (provider.default_appointment_type_ids or [])]
    return type_id in [str(x) for x in (slot.appointment_type_ids or [])]


def _block_overlaps(
    block: AvailabilityBlock, date_str: str, start_min: int, end_min: int
) -> bool:
    day_start = datetime.fromisoformat(f"{date_str}T00:00:00").replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    block_start = block.starts_at
    block_end = block.ends_at
    if block_end <= day_start or block_start >= day_end:
        return False
    slot_start = day_start + timedelta(minutes=start_min)
    slot_end = day_start + timedelta(minutes=end_min)
    return block_start < slot_end and block_end > slot_start


def _appointment_overlaps(
    appt: Appointment, date_str: str, start_min: int, end_min: int, provider_name: str
) -> bool:
    if appt.status == AppointmentStatus.CANCELLED:
        return False
    if appt.provider_name != provider_name:
        return False
    day_start = datetime.fromisoformat(f"{date_str}T00:00:00").replace(tzinfo=timezone.utc)
    appt_start = appt.starts_at
    if appt_start.tzinfo is None:
        appt_start = appt_start.replace(tzinfo=timezone.utc)
    appt_end = appt_start + timedelta(minutes=appt.duration_minutes)
    slot_start = day_start + timedelta(minutes=start_min)
    slot_end = day_start + timedelta(minutes=end_min)
    return appt_start < slot_end and appt_end > slot_start


def compute_openings(
    *,
    appointment_type: AppointmentTypeDef,
    providers: list[Provider],
    slots: list[AvailabilitySlot],
    blocks: list[AvailabilityBlock],
    appointments: list[Appointment],
    days_needed: int = 14,
    max_scan: int = 60,
    provider_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Return [{date, times: [{minutes, provider_id, provider_name, iso}]}]."""
    duration = appointment_type.duration_minutes
    eligible = [
        p
        for p in providers
        if p.status == ProviderStatus.ACTIVE
        and str(appointment_type.id) in [str(x) for x in (p.default_appointment_type_ids or [])]
        and (provider_id is None or p.id == provider_id)
    ]
    results: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()

    for d in range(max_scan):
        if len(results) >= days_needed:
            break
        day = today + timedelta(days=d)
        date_str = day.isoformat()
        day_of_week = day.weekday()
        # Python weekday: Mon=0; JS getDay: Sun=0 — availability uses JS convention in frontend
        js_dow = (day.weekday() + 1) % 7

        times: list[dict[str, Any]] = []
        seen: set[tuple[int, str]] = set()

        for provider in eligible:
            provider_slots = [
                s
                for s in slots
                if s.provider_id == provider.id and _provider_offers_type(provider, s, appointment_type.id)
            ]
            provider_blocks = [b for b in blocks if b.provider_id == provider.id]
            provider_appts = appointments

            for slot in provider_slots:
                if slot.repeat_mode == RepeatMode.ONCE:
                    if slot.specific_date != day:
                        continue
                else:
                    if slot.day_of_week != js_dow:
                        continue
                    if slot.starts_on and day < slot.starts_on:
                        continue

                start = _time_to_minutes(slot.start_time)
                end = _time_to_minutes(slot.end_time)
                for t in range(start, end - duration + 1, duration):
                    if any(
                        _block_overlaps(b, date_str, t, t + duration) for b in provider_blocks
                    ):
                        continue
                    if any(
                        _appointment_overlaps(a, date_str, t, t + duration, provider.name)
                        for a in provider_appts
                    ):
                        continue
                    key = (t, str(provider.id))
                    if key in seen:
                        continue
                    seen.add(key)
                    slot_dt = datetime.combine(day, _minutes_to_time(t), tzinfo=timezone.utc)
                    times.append(
                        {
                            "minutes": t,
                            "label": _format_time_label(t),
                            "provider_id": str(provider.id),
                            "provider_name": provider.name,
                            "starts_at": slot_dt.isoformat(),
                        }
                    )

        if times:
            times.sort(key=lambda x: (x["minutes"], x["provider_name"]))
            results.append({"date": date_str, "times": times})

    return results


def _format_time_label(mins: int) -> str:
    h = mins // 60
    m = mins % 60
    period = "PM" if h >= 12 else "AM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {period}"


def filter_types_for_patient(
    types: list[AppointmentTypeDef], patient_kind: str, type_ids: list[uuid.UUID] | None = None
) -> list[AppointmentTypeDef]:
    out: list[AppointmentTypeDef] = []
    for t in types:
        if not t.available_online:
            continue
        if type_ids and t.id not in type_ids:
            continue
        if patient_kind == "new":
            if t.patient_type in (PatientTypeRule.NEW, PatientTypeRule.ALL):
                out.append(t)
        else:
            if t.patient_type in (PatientTypeRule.EXISTING, PatientTypeRule.ALL):
                out.append(t)
    return out


async def load_scheduling_data(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID,
    location_id: uuid.UUID,
    appointment_type_id: uuid.UUID | None = None,
) -> tuple[list[Provider], list[AvailabilitySlot], list[AvailabilityBlock], list[Appointment]]:
    providers = list(
        (
            await db.execute(
                select(Provider).where(
                    Provider.practice_id == practice_id,
                    Provider.location_id == location_id,
                )
            )
        ).scalars().all()
    )
    slots = list(
        (
            await db.execute(
                select(AvailabilitySlot).where(
                    AvailabilitySlot.practice_id == practice_id,
                    AvailabilitySlot.location_id == location_id,
                )
            )
        ).scalars().all()
    )
    blocks = list(
        (
            await db.execute(
                select(AvailabilityBlock).where(
                    AvailabilityBlock.practice_id == practice_id,
                    AvailabilityBlock.location_id == location_id,
                )
            )
        ).scalars().all()
    )
    appt_stmt = select(Appointment).where(
        Appointment.practice_id == practice_id,
        Appointment.location_id == location_id,
        Appointment.status != AppointmentStatus.CANCELLED,
        Appointment.starts_at >= datetime.now(timezone.utc) - timedelta(days=1),
    )
    appointments = list((await db.execute(appt_stmt)).scalars().all())
    return providers, slots, blocks, appointments
